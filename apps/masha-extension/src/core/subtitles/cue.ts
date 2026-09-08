/*
 * M4 — Subtitle cue processing.
 *
 * Browser-free core.  Cue merging, skip detection, lookahead window.
 */

export interface Cue {
  id: string;
  text: string;
  startMs: number;
  endMs: number;
}

export interface MergedCue {
  id: string;            // first cue's id
  text: string;
  startMs: number;
  endMs: number;
}

export interface SubtitlePolicy {
  /** Skip cues that are only punctuation, music indicators, etc. */
  skipPattern: RegExp;         // /^[\s\[\(♫♪]*([Music|Applause|Cheers|♪|♫])[\s\]\)♫♪]*$/i
  /** Merge cues split at sentence boundaries when the gap ≤ this. */
  mergeGapMs: number;          // 100
  /** Number of cues to prefetch. */
  prefetchCount: number;       // 5
}

export const DEFAULT_SUBTITLE_POLICY: SubtitlePolicy = {
  skipPattern: /^[\s\[\(♫♪🎵]*(\[Music\]|\[Applause\]|\[Cheers\]|♪|♫|🎵)[\s\]\)♫♪🎵]*$/i,
  mergeGapMs: 100,
  prefetchCount: 5,
};

/**
 * Should this cue be translated?  Skips non-speech indicators and
 * very short cues.
 */
export function shouldTranslateCue(text: string, policy: SubtitlePolicy = DEFAULT_SUBTITLE_POLICY): boolean {
  if (text.trim().length < 3) return false;
  if (policy.skipPattern.test(text.trim())) return false;
  return true;
}

/**
 * Merge cues that are part of the same sentence.
 *
 * If two consecutive cues have a gap ≤ `mergeGapMs` and the first does not
 * end with terminal punctuation, they are merged into one translation unit.
 */
export function mergeCues(
  cues: Cue[],
  policy: SubtitlePolicy = DEFAULT_SUBTITLE_POLICY,
): MergedCue[] {
  if (cues.length === 0) return [];

  const merged: MergedCue[] = [];
  let current: Cue = cues[0];

  for (let i = 1; i < cues.length; i++) {
    const next = cues[i];
    const gap = next.startMs - current.endMs;

    if (gap <= policy.mergeGapMs && !sentenceEnds(current.text)) {
      // Merge: extend the current cue
      current = {
        id: current.id,
        text: current.text + ' ' + next.text,
        startMs: current.startMs,
        endMs: next.endMs,
      };
    } else {
      merged.push({
        id: current.id,
        text: current.text,
        startMs: current.startMs,
        endMs: current.endMs,
      });
      current = next;
    }
  }

  merged.push({
    id: current.id,
    text: current.text,
    startMs: current.startMs,
    endMs: current.endMs,
  });

  return merged;
}

/**
 * Does `text` end with terminal punctuation that suggests a sentence boundary?
 */
function sentenceEnds(text: string): boolean {
  const last = text.trim().slice(-1);
  return /[\.\!\?\:。！？]/.test(last);
}

/**
 * Compute the lookahead window: cues that should be translated in advance.
 *
 * Returns the indices of cues up to `prefetchCount` ahead of the current cue.
 */
export function lookaheadWindow(
  currentIndex: number,
  cueCount: number,
  policy: SubtitlePolicy = DEFAULT_SUBTITLE_POLICY,
): number[] {
  const end = Math.min(currentIndex + policy.prefetchCount, cueCount);
  const window: number[] = [];
  for (let i = currentIndex; i < end; i++) {
    window.push(i);
  }
  return window;
}
