/*
 * M4b — Audio subtitle path (basic).
 *
 * Captures a <video>'s audio, streams it to Lemonade's realtime transcription
 * socket, translates each finalised utterance, renders through the overlay.
 *
 * Bridge side. The wire protocol is Lemonade's `WS /realtime` (OpenAI Realtime
 * shaped): connect with `?model=`, configure with `session.update`, send audio
 * as base64 PCM16 at 16 kHz mono, and read transcripts off
 * `conversation.item.input_audio_transcription.completed`. Those constraints
 * come from the server, not from us — 16 kHz mono PCM16 is the only format it
 * accepts.
 */

import { SubtitlePolicy, DEFAULT_SUBTITLE_POLICY, shouldTranslateCue } from '../../../core/subtitles/cue';
import { SubtitleOverlay, createOverlay } from './track';

/** The rate Lemonade's recogniser accepts, and the only one it accepts. */
const ASR_SAMPLE_RATE = 16000;

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

/** `ws(s)://…/v1/realtime?model=…` from the Lemonade base URL. */
export function realtimeUrl(serverUrl: string, model: string): string {
  const url = new URL(serverUrl);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = `${url.pathname.replace(/\/+$/, '')}/realtime`;
  url.searchParams.set('model', model);
  return url.toString();
}

/**
 * Resample one block of mono float samples down to 16 kHz.
 *
 * Averaging across each source window rather than picking one sample out of
 * every N: plain decimation aliases, and aliased speech transcribes badly.
 */
export function downsampleTo16k(input: Float32Array, inputRate: number): Float32Array {
  if (inputRate <= ASR_SAMPLE_RATE) return input;

  const ratio = inputRate / ASR_SAMPLE_RATE;
  const output = new Float32Array(Math.floor(input.length / ratio));

  for (let i = 0; i < output.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(Math.floor((i + 1) * ratio), input.length);
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j];
    output[i] = end > start ? sum / (end - start) : 0;
  }
  return output;
}

/** Float samples in [-1, 1] as base64 little-endian PCM16. */
export function encodePcm16(samples: Float32Array): string {
  const buffer = new ArrayBuffer(samples.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(i * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  }

  const bytes = new Uint8Array(buffer);
  const CHUNK = 0x8000;
  let binary = '';
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
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
  asrModel: string,
  onTranslate: (text: string) => Promise<string>,
  policy: SubtitlePolicy = DEFAULT_SUBTITLE_POLICY,
): () => void {
  const overlay = createOverlay(video);

  // 1. Tap the video's audio without taking it off the speakers
  const { ctx, source } = tapFor(video);

  // 2. Open the transcription socket
  const ws = new WebSocket(realtimeUrl(serverUrl, asrModel));

  ws.onopen = () => {
    ws.send(JSON.stringify({ type: 'session.update', session: { model: asrModel } }));
  };

  // Utterances are translated concurrently; only the newest may paint.
  let issued = 0;
  let rendered = 0;

  ws.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      if (msg.type !== 'conversation.item.input_audio_transcription.completed') return;

      const text = msg.transcript || '';
      if (!shouldTranslateCue(text, policy)) {
        overlay.render(text); // non-speech: pass through untranslated
        return;
      }

      const seq = ++issued;
      onTranslate(text)
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

  // 3. Feed the socket. A ScriptProcessor rather than an AudioWorklet: a
  // worklet module has to be fetched from a web-accessible URL, which is a
  // manifest change for a node this small.
  const processor = ctx.createScriptProcessor(4096, 1, 1);
  processor.onaudioprocess = (event) => {
    if (ws.readyState !== WebSocket.OPEN) return;
    const samples = downsampleTo16k(event.inputBuffer.getChannelData(0), ctx.sampleRate);
    if (samples.length === 0) return;
    ws.send(JSON.stringify({
      type: 'input_audio_buffer.append',
      audio: encodePcm16(samples),
    }));
  };

  // A ScriptProcessor only runs while it is connected to a destination, so it
  // ends at a muted gain node rather than at the speakers — the audible path
  // is the source's own connection, made once in tapFor.
  const mute = ctx.createGain();
  mute.gain.value = 0;
  source.connect(processor);
  processor.connect(mute);
  mute.connect(ctx.destination);

  return () => {
    processor.onaudioprocess = null;
    source.disconnect(processor);
    processor.disconnect();
    mute.disconnect();
    ws.close();
    // Neither the context nor the source is torn down: closing the context
    // would leave the element permanently silent.
    overlay.container.remove();
  };
}
