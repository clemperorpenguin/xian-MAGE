/*
 * M4a — Subtitle track path.
 *
 * Bridge side.  Reads `<track>` elements, translates cues, renders overlay.
 */

import { Cue, shouldTranslateCue, mergeCues, DEFAULT_SUBTITLE_POLICY, SubtitlePolicy } from '../../../core/subtitles/cue';

export interface SubtitleOverlay {
  container: HTMLDivElement;
  render: (text: string) => void;
  clear: () => void;
}

/**
 * Create a subtitle overlay positioned over the video element.
 */
export function createOverlay(video: HTMLVideoElement): SubtitleOverlay {
  const container = document.createElement('div');
  container.id = 'masha-subtitles';
  container.style.cssText = `
    position: absolute; bottom: 10%; left: 10%; right: 10%;
    text-align: center; z-index: 9999;
    font-size: 1.5em; color: white;
    text-shadow: 2px 2px 4px rgba(0,0,0,0.8);
    background: transparent; pointer-events: none;
  `;
  video.style.position = 'relative';
  video.parentElement!.appendChild(container);

  return {
    container,
    render: (text: string) => {
      container.textContent = text;
    },
    clear: () => {
      container.textContent = '';
    },
  };
}

/**
 * Attach subtitle translation to a video element.
 *
 * Returns an undo function.
 */
export function attachTrackSubtitle(
  video: HTMLVideoElement,
  policy: SubtitlePolicy = DEFAULT_SUBTITLE_POLICY,
  onTranslate: (text: string, signal?: AbortSignal) => Promise<string>,
): () => void {
  const overlay = createOverlay(video);
  let currentCueId: string | null = null;
  let abortController: AbortController | null = null;

  // Find the first text track
  const track = video.textTracks[0];
  if (!track || track.kind !== 'subtitles') {
    return () => { overlay.container.remove(); };
  }

  // Set to 'hidden' so cues fire but the browser doesn't render them
  track.mode = 'hidden';

  function onCueChange() {
    const activeCues = track.activeCues;
    if (!activeCues || activeCues.length === 0) {
      overlay.clear();
      currentCueId = null;
      return;
    }

    const cue = activeCues[0] as any;
    const text = (cue as any).text || '';

    if (!shouldTranslateCue(text, policy)) {
      overlay.render(text); // pass through non-speech cues untranslated
      return;
    }

    // Avoid re-translating the same cue
    const cueId = `${cue.startTime}-${cue.endTime}-${text}`;
    if (cueId === currentCueId) return;
    currentCueId = cueId;

    // Cancel any in-flight translation. The signal has to reach `onTranslate`
    // to actually stop the request, and the id check below is what keeps a
    // slow cue that ignores it from painting over a newer one.
    abortController?.abort();
    abortController = new AbortController();

    onTranslate(text, abortController.signal)
      .then(translated => {
        if (cueId !== currentCueId) return;
        overlay.render(translated);
      })
      .catch(() => {
        if (cueId !== currentCueId) return;
        overlay.render(text); // fall back to original
      });
  }

  track.addEventListener('cuechange', onCueChange);

  return () => {
    track.removeEventListener('cuechange', onCueChange);
    overlay.container.remove();
    abortController?.abort();
  };
}
