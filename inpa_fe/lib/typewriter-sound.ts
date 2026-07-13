// WebAudio 타자기 사운드 합성 — 오디오 파일 없이 키 클릭음을 만든다.
// AudioContext는 브라우저 자동재생 정책상 사용자 제스처(입장 게이트 클릭) 안에서 init() 해야 소리가 난다.
export class TypewriterSound {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private muted = false;

  init() {
    if (this.ctx || typeof window === "undefined") return;
    const Ctor = window.AudioContext
      ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return;
    this.ctx = new Ctor();
    this.master = this.ctx.createGain();
    this.master.gain.value = 0.5;
    this.master.connect(this.ctx.destination);
  }

  get isReady() { return this.ctx !== null; }

  setMuted(m: boolean) {
    this.muted = m;
    if (this.master && this.ctx) {
      this.master.gain.setTargetAtTime(m ? 0 : 0.5, this.ctx.currentTime, 0.01);
    }
  }

  private ready(): AudioContext | null {
    if (!this.ctx || !this.master || this.muted) return null;
    if (this.ctx.state === "suspended") void this.ctx.resume();
    return this.ctx;
  }

  /** 대역 필터를 거친 노이즈 버스트 한 조각. */
  private noiseBurst(t: number, dur: number, freq: number, q: number, gain: number) {
    const ctx = this.ctx!;
    const buf = ctx.createBuffer(1, Math.ceil(ctx.sampleRate * dur), ctx.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / data.length) ** 2;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    const band = ctx.createBiquadFilter();
    band.type = "bandpass";
    band.frequency.value = freq;
    band.Q.value = q;
    const g = ctx.createGain();
    g.gain.setValueAtTime(gain, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    src.connect(band); band.connect(g); g.connect(this.master!);
    src.start(t);
  }

  private tone(t: number, dur: number, freq: number, type: OscillatorType, gain: number) {
    const ctx = this.ctx!;
    const osc = ctx.createOscillator();
    osc.type = type;
    osc.frequency.value = freq;
    const g = ctx.createGain();
    g.gain.setValueAtTime(gain, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    osc.connect(g); g.connect(this.master!);
    osc.start(t); osc.stop(t + dur + 0.02);
  }

  /** 글자 하나 = '탁'. 노이즈 버스트 + 낮은 사각파, 글자마다 톤 흔들기. 공백은 낮고 부드럽게. */
  key(space = false) {
    if (!this.ready()) return;
    const t = this.ctx!.currentTime;
    this.noiseBurst(t, 0.05, (space ? 1300 : 2100) + Math.random() * 600, 1.2, space ? 0.22 : 0.4);
    this.tone(t, 0.03, 140 + Math.random() * 40, "square", 0.1);
  }

  /** 문장 완료음 = 타자기 줄바꿈 '딩'. */
  lineEnd() {
    if (!this.ready()) return;
    const t = this.ctx!.currentTime;
    this.tone(t, 0.5, 1568, "sine", 0.18);
  }

  /** 종막 벨 2음(불 켜짐 전환용): E6 → G6. */
  finale() {
    if (!this.ready()) return;
    const t = this.ctx!.currentTime;
    this.tone(t, 0.9, 1318.5, "sine", 0.13);
    this.tone(t + 0.18, 1.1, 1568, "sine", 0.14);
  }
}
