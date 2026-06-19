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
