// AudioWorklet: 마이크 입력(모노, 컨텍스트 샘플레이트 16kHz)의 128샘플 프레임을 메인 스레드로 전달한다.
// 변환·청크 분할·전송은 메인 스레드(features/interview/pcm.ts)에서 한다.
class PcmCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel && channel.length) this.port.postMessage(channel.slice(0));
    return true;
  }
}
registerProcessor("pcm-capture", PcmCaptureProcessor);
