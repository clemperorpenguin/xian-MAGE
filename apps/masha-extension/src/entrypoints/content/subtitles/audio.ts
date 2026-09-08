/*
 * M4b — Audio subtitle path (basic).
 *
 * Captures audio from a <video> element, sends it to Lemonade's realtime ASR,
 * translates each finalised utterance, renders through the overlay.
 *
 * Bridge side.  Audio capture uses Web Audio API.
 */

import { SubtitlePolicy, DEFAULT_SUBTITLE_POLICY, shouldTranslateCue } from '../../../core/subtitles/cue';
import { SubtitleOverlay, createOverlay } from './track';

export interface AudioSession {
  video: HTMLVideoElement;
  stream: MediaStream | null;
  source: MediaElementAudioSourceNode | MediaStreamAudioSourceNode | null;
  processor: AudioWorkletNode | null;
  ws: WebSocket | null;
  overlay: SubtitleOverlay;
}

/**
 * The audio graph built for a given <video>.
 *
 * `createMediaElementSource` may be called only once per element — a second
 * call throws — and the element's audio is rerouted into the graph for good,
 * so the context and source outlive any one capture session and are reused.
 */
interface VideoTap {
  ctx: AudioContext;
  source: MediaElementAudioSourceNode;
}

const taps = new WeakMap<HTMLVideoElement, VideoTap>();

function tapFor(video: HTMLVideoElement): VideoTap {
  let tap = taps.get(video);
  if (!tap) {
    const ctx = new AudioContext();
    const source = ctx.createMediaElementSource(video);
    // Without this the element is silent for as long as the tap exists:
    // routing it into the graph takes it off the default output.
    source.connect(ctx.destination);
    tap = { ctx, source };
    taps.set(video, tap);
  }
  return tap;
}

/**
 * Start audio capture + realtime translation for a video.
 *
 * Requires user opt-in (explicit per-site).
 *
 * `onTranslate` receives each finalised utterance and returns its translation;
 * results that arrive out of order are dropped rather than shown late.
 *
 * Returns an undo function that stops capture and cleans up.
 */
export function attachAudioSubtitle(
  video: HTMLVideoElement,
  serverUrl: string,
  sourceLang: string,
  targetLang: string,
  onTranslate: (text: string, targetLang: string) => Promise<string>,
  policy: SubtitlePolicy = DEFAULT_SUBTITLE_POLICY,
): () => void {
  const overlay = createOverlay(video);
  const session: AudioSession = { video, stream: null, source: null, processor: null, ws: null, overlay };

  // 1. Capture audio from the video element, leaving playback audible
  const { ctx, source } = tapFor(video);
  const dest = ctx.createMediaStreamDestination();
  source.connect(dest);
  session.source = source;
  session.stream = dest.stream;

  // 2. Open WebSocket to Lemonade's realtime endpoint
  const wsUrl = serverUrl.replace('/v1', '/realtime');
  const ws = new WebSocket(wsUrl);
  session.ws = ws;

  ws.onopen = () => {
    // Configure ASR. `language` is what is being *spoken*, not what we
    // translate into, and the format has to describe what step 3 actually
    // puts on the wire.
    ws.send(JSON.stringify({
      type: 'configure',
      audio: { format: 'webm-opus', sample_rate: ctx.sampleRate, channels: 1 },
      language: sourceLang,
    }));
  };

  // Utterances are translated concurrently; only the newest may paint.
  let issued = 0;
  let rendered = 0;

  ws.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      if (msg.type !== 'transcript' || !msg.final) return;

      const text = msg.text || '';
      if (!shouldTranslateCue(text, policy)) {
        overlay.render(text); // non-speech: pass through untranslated
        return;
      }

      const seq = ++issued;
      onTranslate(text, targetLang)
        .then(translated => {
          if (seq < rendered) return; // a later utterance already painted
          rendered = seq;
          overlay.render(translated);
        })
        .catch(() => {
          if (seq < rendered) return;
          rendered = seq;
          overlay.render(text); // fall back to the transcript
        });
    } catch { /* ignore parse errors */ }
  };

  ws.onerror = () => {
    overlay.render('[audio error]');
  };

  // 3. Pipe audio data through the WebSocket
  // (Simplified: MediaStream → MediaRecorder → WS for this basic version)
  const recorder = new MediaRecorder(dest.stream, {
    mimeType: 'audio/webm;codecs=opus',
  });
  recorder.ondataavailable = (blobEvt) => {
    if (blobEvt.data.size > 0 && ws.readyState === WebSocket.OPEN) {
      ws.send(blobEvt.data);
    }
  };
  recorder.start(200); // chunk every 200ms

  return () => {
    if (recorder.state !== 'inactive') recorder.stop();
    ws.close();
    // Drop only the capture branch. Closing the context, or disconnecting the
    // source outright, would leave the element permanently silent.
    source.disconnect(dest);
    overlay.container.remove();
  };
}
