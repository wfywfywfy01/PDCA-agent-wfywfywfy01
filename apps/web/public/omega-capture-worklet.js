// Continuous 16 kHz mono PCM16, 20 ms per WebSocket frame.
class OmegaCapture extends AudioWorkletProcessor {
  constructor() {
    super()
    this.frame = new Int16Array(320)
    this.offset = 0
    this.phase = 0
  }

  process(inputs) {
    const channel = inputs[0]?.[0]
    if (!channel) return true
    const ratio = 16000 / sampleRate
    for (const sample of channel) {
      this.phase += ratio
      if (this.phase < 1) continue
      this.phase -= 1
      this.frame[this.offset++] = Math.max(-32768, Math.min(32767, Math.round(sample * 32767)))
      if (this.offset === 320) {
        this.port.postMessage(this.frame.buffer, [this.frame.buffer])
        this.frame = new Int16Array(320)
        this.offset = 0
      }
    }
    return true
  }
}

registerProcessor('omega-capture', OmegaCapture)
