/**
 * Mic capture → 16 kHz mono int16 PCM → base64.
 *
 * Uses an AudioWorklet to downsample in real time. We send batches every
 * ~250 ms to keep the IPC chatter low; the sidecar VAD doesn't need
 * shorter chunks to detect utterance boundaries.
 *
 * The base64 encoding is wasteful (33% overhead) but keeps the wire
 * protocol readable and trivial. At 16 kHz mono int16 = 32 KB/s ×
 * 1.33 = ~43 KB/s of base64. Negligible at IPC scale.
 */

import { sendCommand } from "./sidecar";

const TARGET_SR = 16000;
const SEND_INTERVAL_MS = 250;

export type AudioCapture = {
  stop: () => Promise<void>;
};

/** Inline AudioWorklet source. We register it via a Blob URL so we don't
 * need a separate static file. */
const WORKLET_SRC = `
class CaptureProcessor extends AudioWorkletProcessor {
  constructor(opts) {
    super();
    this.targetSr = opts.processorOptions.targetSr;
    this.batchMs = opts.processorOptions.batchMs;
    this.batchSize = Math.floor(this.targetSr * this.batchMs / 1000);
    this.buf = new Int16Array(this.batchSize);
    this.bufWritten = 0;
    this.ratio = sampleRate / this.targetSr;
    this.acc = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    // Naive linear-decimation downsampler. Adequate for ASR; fancier
    // resampling lives behind a flag if we ever need it.
    let i = 0;
    while (i < ch.length) {
      const f = ch[i];
      const s = Math.max(-1, Math.min(1, f));
      this.buf[this.bufWritten] = s < 0 ? s * 0x8000 : s * 0x7fff;
      this.bufWritten++;
      this.acc += this.ratio;
      const step = Math.max(1, Math.round(this.acc));
      i += step;
      this.acc -= step;
      if (this.bufWritten >= this.batchSize) {
        this.port.postMessage(this.buf.buffer.slice(0));
        this.bufWritten = 0;
      }
    }
    return true;
  }
}
registerProcessor("sarathi-capture", CaptureProcessor);
`;

function int16ToBase64(int16: ArrayBuffer): string {
  const bytes = new Uint8Array(int16);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(
      null,
      Array.from(bytes.subarray(i, i + chunk)),
    );
  }
  return btoa(binary);
}

export async function startMicCapture(): Promise<AudioCapture> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
    video: false,
  });

  // AudioContext defaults to the device's hardware rate; we resample in the worklet.
  const ctx = new AudioContext();
  const blob = new Blob([WORKLET_SRC], { type: "application/javascript" });
  const url = URL.createObjectURL(blob);
  await ctx.audioWorklet.addModule(url);
  URL.revokeObjectURL(url);

  const src = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, "sarathi-capture", {
    processorOptions: { targetSr: TARGET_SR, batchMs: SEND_INTERVAL_MS },
    numberOfInputs: 1,
    numberOfOutputs: 0,
  });
  src.connect(node);

  // Worklet posts ArrayBuffers of int16 PCM; we forward them as base64.
  node.port.onmessage = (ev) => {
    const buf = ev.data as ArrayBuffer;
    if (!buf || buf.byteLength === 0) return;
    void sendCommand({ type: "audio", pcm_b64: int16ToBase64(buf) });
  };

  return {
    async stop() {
      try {
        node.port.onmessage = null;
        node.disconnect();
        src.disconnect();
        stream.getTracks().forEach((t) => t.stop());
        await ctx.close();
      } catch {
        /* ignore */
      }
    },
  };
}
