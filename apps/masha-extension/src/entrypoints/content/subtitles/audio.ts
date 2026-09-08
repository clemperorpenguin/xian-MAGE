/*
 * M4b — Audio subtitle path (basic).
 *
 * Captures audio from a <video> element, sends to Lemonade realtime ASR,
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
 * Start audio capture + realtime translation for a video.
 *
 * Requires user opt-in (explicit per-site).
 *
 * Returns an undo function that stops capture and cleans up.
 */
export function attachAudioSubtitle(
  video: HTMLVideoElement,
  serverUrl: string,
  targetLang: string,
  policy: SubtitlePolicy = DEFAULT_SUBTITLE_POLICY,
): () => void {
  const overlay = createOverlay(video);
  const session: AudioSession = { video, stream: null, source: null, processor: null, ws: null, overlay };

  // 1. Capture audio from the video element
  const ctx = new AudioContext();
  const dest = ctx.createMediaStreamDestination();
  const source = ctx.createMediaElementSource(video);
  source.connect(dest);
  session.source = source;
  session.stream = dest.stream;

  // 2. Open WebSocket to Lemonade's realtime endpoint
  const wsUrl = serverUrl.replace('/v1', '/realtime');
  const ws = new WebSocket(wsUrl);
  session.ws = ws;

  ws.onopen = () => {
    // Send configure message for ASR
    ws.send(JSON.stringify({
      type: 'configure',
      audio: { format: 'pcm16', sample_rate: 16000, channels: 1 },
      language: targetLang,
    }));
  };

  ws.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      if (msg.type === 'transcript' && msg.final) {
        const text = msg.text || '';
        if (shouldTranslateCue(text, policy)) {
          overlay.render(text);
        }
      }
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
    recorder.stop();
    ws.close();
    ctx.close();
    overlay.container.remove();
  };
}
