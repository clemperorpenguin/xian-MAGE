/*
 * M5 — Comic/manga page translation.
 *
 * Bridge side.  Uses IntersectionObserver to translate images as the reader
 * scrolls, with a two-image lookahead.
 */

import { translateImage, ImageTranslateConfig, DEFAULT_IMAGE_CONFIG } from './images';

export interface ComicPageConfig {
  /** Per-site RTL override for manga vs Western comics. */
  rtl: boolean;
  /** Number of images to prefetch ahead. */
  lookahead: number;
}

export const DEFAULT_COMIC_CONFIG: ComicPageConfig = {
  rtl: true,    // manga default
  lookahead: 2,
};

/**
 * Observe comic page images and translate them as the reader scrolls.
 *
 * Returns an undo function.
 */
export function attachComicReader(
  config: ComicPageConfig = DEFAULT_COMIC_CONFIG,
  imageConfig: ImageTranslateConfig = DEFAULT_IMAGE_CONFIG,
): () => void {
  const translated = new Set<string>();
  let observer: IntersectionObserver | null = null;

  // Find all images on the page that look like comic panels, in reading order
  const images = readingOrder(
    Array.from(document.querySelectorAll<HTMLImageElement>('img[src], img[data-src]')),
    config.rtl,
  );

  if (images.length === 0) return () => {};

  observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const img = entry.target as HTMLImageElement;
      const src = img.currentSrc || img.src || img.dataset.src || '';
      if (!src || translated.has(src)) continue;
      translated.add(src);

      translateImage(src, imageConfig).catch(() => {
        // Silent — a failed image translation shouldn't break the page
      });
    }
  }, { rootMargin: '200px' });

  // Observe images, with lookahead for the next N
  const observeCount = Math.min(images.length, 5 + config.lookahead);
  for (let i = 0; i < observeCount; i++) {
    observer.observe(images[i]);
  }

  // Set up scroll handler to observe more as the reader progresses
  function onScroll() {
    if (!observer) return;
    const scrollIndex = Math.floor(window.scrollY / window.innerHeight);
    const newObserve = scrollIndex + 5 + config.lookahead;
    for (let i = 0; i < Math.min(newObserve, images.length); i++) {
      if (!observer || images[i].dataset.mashaObserved) continue;
      images[i].dataset.mashaObserved = 'true';
      observer.observe(images[i]);
    }
  }

  window.addEventListener('scroll', onScroll, { passive: true });

  return () => {
    observer?.disconnect();
    window.removeEventListener('scroll', onScroll);
  };
}

/**
 * Sort panels the way the page is read: down the page, then across.
 *
 * Document order is not reading order for a two-up manga spread, where the
 * right-hand page comes first — and the lookahead prefetches in this order,
 * so getting it wrong translates the page the reader reaches second.
 */
function readingOrder(images: HTMLImageElement[], rtl: boolean): HTMLImageElement[] {
  const boxes = new Map<HTMLImageElement, DOMRect>(
    images.map((img) => [img, img.getBoundingClientRect()]),
  );

  return [...images].sort((a, b) => {
    const ra = boxes.get(a)!;
    const rb = boxes.get(b)!;
    // Same row when the vertical spans overlap by more than half a panel.
    const sameRow = Math.abs(ra.top - rb.top) < Math.min(ra.height, rb.height) / 2;
    if (!sameRow) return ra.top - rb.top;
    return rtl ? rb.left - ra.left : ra.left - rb.left;
  });
}
