// マイクの音 (1ch 目) をまとめてメインスレッドへ送る AudioWorklet
const CHUNK = 2048;

class VoiceCapture extends AudioWorkletProcessor {
    constructor() {
        super();
        this.buffer = new Float32Array(CHUNK);
        this.length = 0;
    }

    process(inputs) {
        const input = inputs[0][0];
        if (input) {
            let offset = 0;
            while (offset < input.length) {
                const n = Math.min(CHUNK - this.length, input.length - offset);
                this.buffer.set(input.subarray(offset, offset + n), this.length);
                this.length += n;
                offset += n;
                if (this.length === CHUNK) {
                    this.port.postMessage(this.buffer, [this.buffer.buffer]);
                    this.buffer = new Float32Array(CHUNK);
                    this.length = 0;
                }
            }
        }
        return true;
    }
}

registerProcessor('voice-capture', VoiceCapture);
