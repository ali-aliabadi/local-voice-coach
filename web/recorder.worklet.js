// Batches the 128-sample blocks the audio thread hands us into ~4096-sample messages,
// so we post ~4 times a second instead of ~125. The AudioContext is already running at
// 16kHz, so these samples go straight to Whisper with no resampling and no decoding.
const BATCH = 4096;

class Recorder extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(BATCH);
    this.filled = 0;
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true;
    for (let i = 0; i < channel.length; i++) {
      this.buffer[this.filled++] = channel[i];
      if (this.filled === BATCH) {
        this.port.postMessage(this.buffer.slice());
        this.filled = 0;
      }
    }
    return true;
  }
}

registerProcessor('recorder', Recorder);
