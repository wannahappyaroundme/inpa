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

  /** 글자 하나 = '탁'. 공백·문장부호는 살짝 낮고 부드럽게. 글자마다 톤을 흔들어 반복감을 없앤다. */
  key(space = false) {
    if (!this.ctx || !this.master || this.muted) return;
    if (this.ctx.state === "suspended") void this.ctx.resume();
    const t = this.ctx.currentTime;
    const dur = 0.05;
    const buf = this.ctx.createBuffer(1, Math.ceil(this.ctx.sampleRate * dur), this.ctx.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < data.length; i++) {
      data[i] = (Math.random() * 2 - 1) * (1 - i / data.length) ** 2;
    }
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    const band = this.ctx.createBiquadFilter();
    band.type = "bandpass";
    band.frequency.value = (space ? 1300 : 2100) + Math.random() * 600;
    band.Q.value = 1.2;
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(space ? 0.22 : 0.4, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    src.connect(band); band.connect(g); g.connect(this.master);
    src.start(t);
    const osc = this.ctx.createOscillator();
    osc.type = "square";
    osc.frequency.value = 140 + Math.random() * 40;
    const og = this.ctx.createGain();
    og.gain.setValueAtTime(0.1, t);
    og.gain.exponentialRampToValueAtTime(0.001, t + 0.03);
    osc.connect(og); og.connect(this.master);
    osc.start(t); osc.stop(t + 0.035);
  }

  /** 장면 완료음: 타자기 줄바꿈 '딩'. */
  ding() {
    if (!this.ctx || !this.master || this.muted) return;
    const t = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    osc.type = "sine";
    osc.frequency.value = 1568; // G6 근처, 옛 타자기 벨 느낌
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.18, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.5);
    osc.connect(g); g.connect(this.master);
    osc.start(t); osc.stop(t + 0.5);
  }
}
