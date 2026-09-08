/*
 * M5 — Image and comic translation.
 *
 * Bridge side.  Captures images from the page, sends them to the Xian bridge
 * for OCR, translates detected text, and renders via overlay or inpainting.
 */

export interface ImageTranslateConfig {
  /** Bridge base URL (e.g. http://127.0.0.1:13306). */
  bridgeUrl: string;
  /** Mode: 'text' for standard images, 'comic' for manga/comics. */
  mode: 'text' | 'comic';
  /** Overlay mode (instant) vs render mode (inpaint). */
  overlay: boolean;
  /** Source language hint. */
  sourceLang: string;
  targetLang: string;
}

export const DEFAULT_IMAGE_CONFIG: ImageTranslateConfig = {
  bridgeUrl: 'http://127.0.0.1:13306',
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
  const ocrResp = await fetch(`${config.bridgeUrl}/ocr`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      image: imageData,
      source_lang: config.sourceLang,
      mode: config.mode,
    }),
  });

  if (!ocrResp.ok) throw new Error(`OCR failed: ${ocrResp.status}`);
  const ocrResult = await ocrResp.json();

  // 3. Translate block texts (batched through Lemonade)
  const blocks = ocrResult.blocks as Array<{ quad: any; text: string; confidence: number }>;
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
    await renderInpaint(imgSrc, imageData, blocks, translations, config);
  }
}

async function fetchImageAsBase64(src: string): Promise<string | null> {
  try {
    const resp = await fetch(src, { credentials: 'omit' });
    const blob = await resp.blob();
    const reader = new FileReader();
    return new Promise<string>((resolve) => {
      reader.onloadend = () => resolve(reader.result as string);
      reader.readAsDataURL(blob);
    });
  } catch {
    // Cross-origin: ask background to fetch with host permissions
    return new Promise((resolve) => {
      chrome.runtime.sendMessage(
        { type: 'MASHA_FETCH_IMAGE', src },
        (response) => resolve(response?.dataUrl || null),
      );
    });
  }
}

async function translateText(text: string, targetLang: string): Promise<string> {
  // Reuse the existing Lemonade translation call
  // (simplified: direct fetch to /v1/chat/completions)
  const resp = await fetch('http://127.0.0.1:13305/v1/chat/completions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: 'Xian-Ultra',
      messages: [
        { role: 'system', content: `Translate to ${targetLang}.` },
        { role: 'user', content: text },
      ],
      max_tokens: 512,
      temperature: 0.3,
    }),
  });
  const data = await resp.json();
  return data.choices?.[0]?.message?.content || text;
}

function renderOverlay(imgSrc: string, blocks: Array<{ quad: any; text: string }>, translations: string[]): void {
  // Find the image element
  const imgs = document.querySelectorAll(`img[src="${imgSrc}"]`);
  if (imgs.length === 0) return;
  const img = imgs[0] as HTMLImageElement;

  // Create overlay canvas
  const canvas = document.createElement('canvas');
  canvas.style.cssText = `
    position: absolute; top: 0; left: 0; width: 100%; height: 100%;
    pointer-events: none; z-index: 9999;
  `;
  canvas.width = img.naturalWidth || img.width;
  canvas.height = img.naturalHeight || img.height;
  img.style.position = 'relative';
  img.parentElement!.appendChild(canvas);

  const ctx = canvas.getContext('2d')!;

  // Draw translations
  for (let i = 0; i < blocks.length; i++) {
    const q = blocks[i].quad;
    const trans = translations[i];

    // Sample background color from the image
    ctx.fillStyle = 'rgba(255, 255, 255, 0.7)';
    ctx.fillRect(q.x1, q.y1, q.x2 - q.x1, q.y4 - q.y1);

    ctx.fillStyle = '#000';
    ctx.font = '14px sans-serif';
    ctx.textBaseline = 'top';
    ctx.fillText(trans, q.x1 + 2, q.y1 + 2);
  }
}

async function renderInpaint(
  imgSrc: string,
  imageData: string,
  blocks: Array<{ quad: any; text: string }>,
  translations: string[],
  config: ImageTranslateConfig,
): Promise<void> {
  const renderResp = await fetch(`${config.bridgeUrl}/ocr/render`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      image: imageData,
      blocks: blocks.map((b, i) => ({
        quad: b.quad,
        translated: translations[i],
      })),
    }),
  });

  if (!renderResp.ok) throw new Error(`Render failed: ${renderResp.status}`);
  const result = await renderResp.json();

  // Swap image src with rendered version
  const imgs = document.querySelectorAll(`img[src="${imgSrc}"]`);
  for (const img of imgs) {
    (img as HTMLImageElement).src = result.image;
  }
}
