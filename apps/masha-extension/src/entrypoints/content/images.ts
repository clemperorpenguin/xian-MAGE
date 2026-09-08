/*
 * M5 — Image and comic translation.
 *
 * Bridge side.  Captures images from the page, sends them to the Xian bridge
 * for OCR, translates detected text, and renders via overlay or inpainting.
 *
 * Every network hop goes through the background worker. An MV3 content script
 * has no cross-origin privileges of its own — a `fetch` from here is judged by
 * the *page's* CORS policy, so calls to Lemonade and to the bridge would fail
 * on most of the web.
 */

/** One round trip to the background worker, unwrapped. */
async function ask<T>(message: object, field: string): Promise<T> {
  const response = await chrome.runtime.sendMessage(message);
  if (!response?.success) throw new Error(response?.error || 'Background request failed');
  return response[field] as T;
}

export interface ImageTranslateConfig {
  /** Mode: 'text' for standard images, 'comic' for manga/comics. */
  mode: 'text' | 'comic';
  /** Overlay mode (instant) vs render mode (inpaint). */
  overlay: boolean;
  /** Source language hint. */
  sourceLang: string;
  targetLang: string;
}

export const DEFAULT_IMAGE_CONFIG: ImageTranslateConfig = {
  mode: 'text',
  overlay: true,
  sourceLang: 'Auto',
  targetLang: 'English',
};

/**
 * Translate text found in an image via OCR + LLM.
 *
 * 1. Fetch image as base64 blob (or ask background for cross-origin).
 * 2. POST /ocr → blocks with quads.
 * 3. Translate block texts through Lemonade (batched).
 * 4. If overlay mode: draw translated text in a positioned canvas layer.
 *    If render mode: POST /ocr/render and swap the image src.
 */
export async function translateImage(
  imgSrc: string,
  config: ImageTranslateConfig,
  onProgress?: (blockIdx: number, total: number) => void,
): Promise<void> {
  // 1. Get image bytes
  const imageData = await fetchImageAsBase64(imgSrc);
  if (!imageData) return;

  // 2. OCR via bridge
  const ocrResult = await ask<{ blocks: Array<{ quad: any; text: string; confidence: number }> }>(
    {
      type: 'MASHA_OCR',
      image: imageData,
      sourceLang: config.sourceLang,
      mode: config.mode,
    },
    'result',
  );

  // 3. Translate block texts (batched through Lemonade)
  const blocks = ocrResult.blocks;
  const translations: string[] = [];

  for (let i = 0; i < blocks.length; i++) {
    const block = blocks[i];
    if (block.text.trim().length < 3) {
      translations.push(block.text); // pass through
      continue;
    }

    // Call translation (reuses core pipeline)
    const trans = await translateText(block.text, config.targetLang);
    translations.push(trans);

    onProgress?.(i + 1, blocks.length);
  }

  // 4. Render
  if (config.overlay) {
    renderOverlay(imgSrc, blocks, translations);
  } else {
    await renderInpaint(imgSrc, imageData, blocks, translations);
  }
}

async function fetchImageAsBase64(src: string): Promise<string | null> {
  // The background holds the host permissions, so it fetches the bytes even
  // when the image is served from a different origin than the page.
  try {
    return await ask<string | null>({ type: 'MASHA_FETCH_IMAGE', src }, 'dataUrl');
  } catch {
    return null;
  }
}

async function translateText(text: string, targetLang: string): Promise<string> {
  try {
    return await ask<string>({ type: 'MASHA_TRANSLATE_TEXT', text, targetLang }, 'translation');
  } catch {
    return text; // one unreadable balloon should not abandon the page
  }
}

/**
 * Every <img> currently showing `src`.
 *
 * Matching is on the *resolved* URL, not on the `src` attribute: callers pass
 * `img.currentSrc || img.src`, so an attribute selector would miss every page
 * whose markup is relative or protocol-relative (and would throw outright on a
 * URL containing a quote).
 */
function imagesShowing(src: string): HTMLImageElement[] {
  return Array.from(document.images).filter(
    (img) => (img.currentSrc || img.src) === src,
  );
}

/** One overlay canvas per image, so a re-translate replaces rather than stacks. */
const overlays = new WeakMap<HTMLImageElement, HTMLCanvasElement>();

function renderOverlay(imgSrc: string, blocks: Array<{ quad: any; text: string }>, translations: string[]): void {
  for (const img of imagesShowing(imgSrc)) {
    const parent = img.parentElement;
    if (!parent) continue;

    overlays.get(img)?.remove();

    // The canvas is absolutely positioned against the image's offset parent,
    // so that parent has to be a containing block — setting `position` on the
    // image itself does nothing for a sibling.
    if (getComputedStyle(parent).position === 'static') {
      parent.style.position = 'relative';
    }

    const canvas = document.createElement('canvas');
    canvas.style.cssText = `
      position: absolute; pointer-events: none; z-index: 9999;
      left: ${img.offsetLeft}px; top: ${img.offsetTop}px;
      width: ${img.offsetWidth}px; height: ${img.offsetHeight}px;
    `;
    // Backing store in source pixels; CSS box in rendered pixels. That is what
    // lets the OCR quads be drawn verbatim on a scaled-down image.
    canvas.width = img.naturalWidth || img.width;
    canvas.height = img.naturalHeight || img.height;
    parent.appendChild(canvas);
    overlays.set(img, canvas);

    const ctx = canvas.getContext('2d');
    if (!ctx) continue;

    // Draw translations
    for (let i = 0; i < blocks.length; i++) {
      const q = blocks[i].quad;
      const trans = translations[i];

      // A quad is four corners and may be rotated; cover its bounding box.
      const xs = [q.x1, q.x2, q.x3, q.x4];
      const ys = [q.y1, q.y2, q.y3, q.y4];
      const left = Math.min(...xs);
      const top = Math.min(...ys);
      const width = Math.max(...xs) - left;
      const height = Math.max(...ys) - top;

      // Sample background color from the image
      ctx.fillStyle = 'rgba(255, 255, 255, 0.7)';
      ctx.fillRect(left, top, width, height);

      ctx.fillStyle = '#000';
      ctx.font = '14px sans-serif';
      ctx.textBaseline = 'top';
      ctx.fillText(trans, left + 2, top + 2);
    }
  }
}

async function renderInpaint(
  imgSrc: string,
  imageData: string,
  blocks: Array<{ quad: any; text: string }>,
  translations: string[],
): Promise<void> {
  const rendered = await ask<string>(
    {
      type: 'MASHA_OCR_RENDER',
      image: imageData,
      blocks: blocks.map((b, i) => ({ quad: b.quad, translated: translations[i] })),
    },
    'image',
  );

  // Swap image src with rendered version
  for (const img of imagesShowing(imgSrc)) {
    img.src = rendered;
  }
}
