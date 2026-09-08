/*
 * M4 — Subtitles, attached to whatever the page is playing.
 *
 * Bridge side. Finds the videos on the page, picks the cheap path when it can
 * (the site's own <track> cues) and the expensive one only when asked (capture
 * the audio and translate the transcript), and keeps up with videos the page
 * adds later.
 */

import { attachTrackSubtitle } from './track';
import { attachAudioSubtitle } from './audio';

export interface SubtitleAttachConfig {
  /** Lemonade base URL — the audio path opens its realtime socket here. */
  serverUrl: string;
  /** Whisper model the realtime endpoint should transcribe with. */
  asrModel: string;
  /** Capture audio when a video publishes no subtitle track. Opt-in. */
  audio: boolean;
}

/** Does this video carry cues we can translate without touching its audio? */
function hasSubtitleTrack(video: HTMLVideoElement): boolean {
  return [...video.textTracks].some((track) => track.kind === 'subtitles');
}

/**
 * Translate subtitles on every video on the page.
 *
 * Returns an undo function that detaches from all of them.
 */
export function attachSubtitles(
  config: SubtitleAttachConfig,
  onTranslate: (text: string, signal?: AbortSignal) => Promise<string>,
): () => void {
  const attached = new Map<HTMLVideoElement, () => void>();

  function attach(video: HTMLVideoElement): void {
    if (attached.has(video)) return;

    if (hasSubtitleTrack(video)) {
      attached.set(video, attachTrackSubtitle(video, undefined, onTranslate));
      return;
    }

    if (!config.audio) {
      // No track yet. It may arrive after the player initialises, so ask to be
      // told rather than deciding now that this video has none.
      const onAddTrack = () => {
        video.textTracks.removeEventListener('addtrack', onAddTrack);
        attach(video);
      };
      video.textTracks.addEventListener('addtrack', onAddTrack);
      return;
    }

    try {
      attached.set(video, attachAudioSubtitle(
        video,
        config.serverUrl,
        config.asrModel,
        (text) => onTranslate(text),
      ));
    } catch {
      // Autoplay policy, a cross-origin video, an already-tapped element —
      // none of it should break the page.
    }
  }

  for (const video of document.querySelectorAll('video')) attach(video);

  // Players mount their <video> after the page load, and a feed adds more.
  const observer = new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (!(node instanceof Element)) continue;
        if (node instanceof HTMLVideoElement) attach(node);
        else for (const video of node.querySelectorAll('video')) attach(video);
      }
    }
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });

  return () => {
    observer.disconnect();
    for (const detach of attached.values()) detach();
    attached.clear();
  };
}
