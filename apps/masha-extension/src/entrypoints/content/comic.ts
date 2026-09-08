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

  // Find all images on the page that look like comic panels
  const images = document.querySelectorAll<HTMLImageElement>(
    'img[src], img[data-src]'
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
  const observeCount = Math.min(images.length, 5 + DEFAULT_COMIC_CONFIG.lookahead);
  for (let i = 0; i < observeCount; i++) {
    observer.observe(images[i]);
  }

  // Set up scroll handler to observe more as the reader progresses
  function onScroll() {
    if (!observer) return;
    const scrollIndex = Math.floor(window.scrollY / window.innerHeight);
    const newObserve = scrollIndex + 5 + DEFAULT_COMIC_CONFIG.lookahead;
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
