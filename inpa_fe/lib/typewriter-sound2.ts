// WebAudio 타자기 사운드 합성 v2 — 시네마 v2(/version) 전용. 오디오 파일 없음.
// v1(typewriter-sound.ts) 대비: 타건음 3겹 레이어링(노이즈 버스트 + 저역 바디 + 금속 핑) + 글자별 세기 변주,
// 문장 완료 = 딩 + 캐리지 리턴(노이즈 스윕 + 착지 쿵), 종막 벨 2음(finale).
// AudioContext는 자동재생 정책상 사용자 제스처(게이트 클릭) 안에서 init() 해야 한다.
export class TypewriterSound2 {
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

  /** 글자 하나 = '타닥'. 3겹(타격 노이즈 + 바디 저역 + 금속 핑) + 글자별 세기·톤 변주. 공백 = 낮고 부드럽게. */
  key(space = false) {
    if (!this.ready()) return;
    const t = this.ctx!.currentTime;
    const vel = 0.75 + Math.random() * 0.25; // 타건 세기 변주(기계적 반복감 제거)
    if (space) {
      this.noiseBurst(t, 0.05, 850 + Math.random() * 250, 0.9, 0.2 * vel);
      this.tone(t, 0.04, 120 + Math.random() * 25, "sine", 0.09 * vel);
      return;
    }
    this.noiseBurst(t, 0.045, 1800 + Math.random() * 700, 1.0, 0.3 * vel); // 타격
    this.tone(t, 0.035, 150 + Math.random() * 40, "sine", 0.11 * vel);      // 몸통 울림
    this.tone(t, 0.06, 1100 + Math.random() * 300, "triangle", 0.045 * vel); // 금속 잔향 힌트
  }

  /** 문장 완료 = 타자기 서명음: 딩 → 캐리지 리턴 스윕 → 착지. */
  lineEnd() {
    if (!this.ready()) return;
    const ctx = this.ctx!;
    const t = ctx.currentTime;
    this.tone(t, 0.55, 1568, "sine", 0.15); // 딩(G6)
    // 캐리지 리턴: 노이즈의 대역을 1200→400Hz로 미끄러뜨린다
    const dur = 0.2;
    const buf = ctx.createBuffer(1, Math.ceil(ctx.sampleRate * dur), ctx.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / data.length);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    const band = ctx.createBiquadFilter();
    band.type = "bandpass";
    band.Q.value = 1.4;
    band.frequency.setValueAtTime(1200, t + 0.06);
    band.frequency.exponentialRampToValueAtTime(400, t + 0.06 + dur);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.09, t + 0.06);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.06 + dur);
    src.connect(band); band.connect(g); g.connect(this.master!);
    src.start(t + 0.06);
    this.tone(t + 0.27, 0.05, 110, "sine", 0.1); // 착지 쿵
  }

  /** 종막 벨 2음(불 켜짐 전환용): E6 → G6. */
  finale() {
    if (!this.ready()) return;
    const t = this.ctx!.currentTime;
    this.tone(t, 0.9, 1318.5, "sine", 0.13);
    this.tone(t + 0.18, 1.1, 1568, "sine", 0.14);
  }
}
