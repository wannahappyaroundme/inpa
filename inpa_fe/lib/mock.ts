// 첫 슬라이스 데모용 mock (BE 연결 전).
//
// ⚠️ 컴플라이언스: 인파는 보험을 '중개·권유'하지 않는다.
// - 고객 공유뷰(A) = 납입 현황 등 '사실'만. ('부족/충분' 판정 금지)
// - 히트맵/분석(설계사 도구) = 충족 표기는 '설계사가 정한 기준'으로만.

export type CovStatus = "over" | "enough" | "short" | "none";

export interface HeatItem { name: string; status: CovStatus }
export interface HeatCategory { category: string; items: HeatItem[] }

/* ───────── 설계사 대시보드(홈) ───────── */
export const planner = { name: "이설계", org: "든든생명", initial: "이" };

export const kpis = [
  { label: "내 고객", value: "42", unit: "명" },
  { label: "이번 달 만기", value: "5", unit: "건", accent: true },
  { label: "오늘 할 일", value: "3", unit: "건" },
  { label: "이번 달 신규", value: "2", unit: "명" },
  { label: "미열람 공유", value: "4", unit: "건" },
];

export type EventType = "expiry" | "birthday" | "consult" | "task";
export const eventMeta: Record<EventType, { dot: string; label: string }> = {
  expiry: { dot: "bg-cnone", label: "만기" },
  birthday: { dot: "bg-short", label: "생일" },
  consult: { dot: "bg-enough", label: "상담" },
  task: { dot: "bg-over", label: "할 일" },
};

export const calendar = { year: 2026, month: 6, today: 19 };
export const calendarEvents: Record<number, EventType[]> = {
  3: ["consult"], 5: ["expiry", "task"], 9: ["birthday"], 12: ["consult", "task"],
  16: ["expiry"], 18: ["task"], 19: ["consult", "birthday", "task"], 23: ["expiry"],
  26: ["consult"], 30: ["task"],
};

export const todayTasks: { time: string; title: string; type: EventType }[] = [
  { time: "10:00", title: "김보장님 갱신 상담", type: "consult" },
  { time: "14:00", title: "박안심님 종합보험 만기 안내", type: "expiry" },
  { time: "온종일", title: "신규 리드 3명 팔로업 메시지", type: "task" },
];

/* ───────── 고객 관리(CRM) ───────── */
export const customers = [
  { id: "1", name: "김보장", age: 42, gender: "남", policies: 3, premium: "12.4만", lastContact: "3일 전", expirySoon: true },
  { id: "2", name: "박안심", age: 38, gender: "여", policies: 2, premium: "8.9만", lastContact: "1주 전", expirySoon: true },
  { id: "3", name: "이튼튼", age: 51, gender: "남", policies: 5, premium: "23.1만", lastContact: "어제", expirySoon: false },
  { id: "4", name: "최건강", age: 29, gender: "여", policies: 1, premium: "4.2만", lastContact: "2주 전", expirySoon: false },
  { id: "5", name: "정행복", age: 45, gender: "남", policies: 4, premium: "18.7만", lastContact: "5일 전", expirySoon: false },
  { id: "6", name: "한미소", age: 33, gender: "여", policies: 2, premium: "9.5만", lastContact: "오늘", expirySoon: true },
];

/* ───────── 고객 공유뷰(A): 납입 현황(사실)만 ───────── */
export const shareMock = {
  plannerName: "이설계 설계사 · 든든생명",
  customerName: "김보장",
  product: "무)종합건강보험",
  expiryText: "2092.07 보장 만기 · 20년납",
  monthly: "12.4만원",
  paidText: "1,488만원",
  remainingText: "2,187만원",
  payProgress: 40,
  coverages: [
    { name: "암 진단비", amountText: "3,000만원" },
    { name: "뇌혈관 진단비", amountText: "1,000만원" },
    { name: "허혈성심장 진단비", amountText: "1,000만원" },
    { name: "실손 의료비", amountText: "보유" },
    { name: "수술비 (1~5종)", amountText: "30만~300만원" },
    { name: "입원일당", amountText: "3만원/일" },
    { name: "후유장해", amountText: "1억원" },
  ],
};

/* ───────── 히트맵(설계사 기준 충족) ───────── */
export const heatmapMock: HeatCategory[] = [
  { category: "사망", items: [{ name: "일반사망", status: "over" }, { name: "재해사망", status: "enough" }, { name: "질병사망", status: "none" }] },
  { category: "암 진단", items: [{ name: "일반암", status: "short" }, { name: "소액암", status: "enough" }, { name: "고액암", status: "none" }, { name: "유사암", status: "enough" }] },
  { category: "뇌혈관", items: [{ name: "뇌졸중", status: "none" }, { name: "뇌출혈", status: "none" }, { name: "뇌경색", status: "short" }] },
  { category: "심장", items: [{ name: "급성심근경색", status: "short" }, { name: "허혈성심장", status: "none" }] },
  { category: "실손", items: [{ name: "급여", status: "over" }, { name: "비급여주사", status: "enough" }, { name: "비급여MRI", status: "short" }] },
  { category: "수술입원", items: [{ name: "수술비", status: "short" }, { name: "입원일당", status: "enough" }, { name: "질병입원", status: "over" }] },
  { category: "운전자", items: [{ name: "교통사고처리", status: "none" }, { name: "변호사선임", status: "none" }] },
  { category: "배상책임", items: [{ name: "일상생활배상", status: "none" }] },
  { category: "후유장해", items: [{ name: "상해후유장해", status: "enough" }, { name: "질병후유장해", status: "short" }] },
  { category: "노후간병", items: [{ name: "치매", status: "none" }, { name: "장기요양", status: "none" }] },
];

/* ───────── 갈아타기 비교(기존 증권 vs 제안 증권) ───────── */
// ⚠️ 데모용 목업. 실제 갈아타기 판정·발행은 §97 컴플라이언스 게이트 통과 후 설계사 책임.
export interface CompareRowMock { coverage: string; current: number; proposed: number }
export const compareMock = {
  customerName: "김보장",
  current: { product: "기존 · 무)종합건강보험 (2014년 가입)", monthly: 124000, total: 14880000 },
  proposed: { product: "제안 · 무)건강보장보험 (2026년)", monthly: 98000, total: 11760000 },
  rows: [
    { coverage: "암 진단비", current: 30000000, proposed: 50000000 },
    { coverage: "뇌혈관 진단비", current: 10000000, proposed: 20000000 },
    { coverage: "허혈성심장 진단비", current: 10000000, proposed: 20000000 },
    { coverage: "수술비 (1~5종)", current: 3000000, proposed: 5000000 },
    { coverage: "입원일당 (1일)", current: 30000, proposed: 50000 },
    { coverage: "운전자 형사합의금", current: 0, proposed: 30000000 },
    { coverage: "일상생활배상책임", current: 0, proposed: 100000000 },
  ] as CompareRowMock[],
  verdict: {
    decision: "SWITCH" as "KEEP" | "SWITCH" | "NEUTRAL",
    reason:
      "암·뇌·심장 진단비가 현재 기준 대비 부족하고 운전자·배상 담보가 공백입니다. 제안 상품은 월 보험료가 26,000원 낮으면서 핵심 진단비를 강화해요.",
    netBenefitYear: 312000, // 1년 추정 순이득(원)
  },
  warnings: [
    { label: "해지 손실", detail: "기존 계약 해지 시 환급금이 납입액보다 적을 수 있어요 (추정 −180만원)." },
    { label: "면책 리셋", detail: "신규 가입 시 암 보장 90일 면책·1년 50% 감액이 다시 적용됩니다." },
    { label: "예정이율 변경", detail: "구상품과 예정이율이 달라 같은 보장도 보험료 구조가 달라질 수 있어요." },
  ],
  disclaimer:
    "본 비교는 AI 초안이며 최종 판단·고객 안내·책임은 담당 설계사에게 있습니다. (부당승환 유의)",
};
