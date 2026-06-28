// 단계별 화법·문구 라이브러리 — 정적 데이터(컴플라이언스 게이트 무관, 빠름).
// 신입이 "뭐라 말하지"를 해소하는 상황별 대본. {고객명}·{설계사명} 치환.
//
// ★ 정직성/컴플라이언스 레드라인:
//   - 자동발송 없음 → 복사 후 직접 전달(카톡/문자)까지만.
//   - 카톡(개인 1:1) ⟂ 문자(광고규제): (광고) 표기·무료수신거부·야간(21~08시) 발송금지·아는 고객에게만.

export type CopyChannel = "kakao" | "sms";

export interface CopyTemplate {
  id: string;
  title: string;
  body: string; // {고객명}·{설계사명} 치환
  channel: CopyChannel;
}

export interface CopyCategory {
  key: string;
  label: string;
  desc: string;
  templates: CopyTemplate[];
}

/** {고객명}·{설계사명} 치환(booking/templates_text.render 패턴의 FE판). 빈 값은 안전한 일반어로. */
export function renderCopy(
  body: string,
  vars: { customer?: string; planner?: string }
): string {
  return body
    .replace(/\{고객명\}/g, (vars.customer || "").trim() || "고객")
    .replace(/\{설계사명\}/g, (vars.planner || "").trim() || "담당 설계사");
}

export const COPY_CATEGORIES: CopyCategory[] = [
  {
    key: "referral",
    label: "소개 요청",
    desc: "기존 고객에게 부담 없이 소개를 부탁할 때. 발굴의 가장 빠른 길.",
    templates: [
      {
        id: "referral-thanks",
        title: "감사 인사 + 소개 부탁",
        channel: "kakao",
        body: "{고객명}님, 늘 믿고 맡겨주셔서 감사해요 🙏 혹시 주변에 보험 정리나 보장 점검이 필요한 분 계실까요? 부담 드리지 않고 한 번 살펴봐 드릴게요. — {설계사명}",
      },
      {
        id: "referral-trigger",
        title: "점검 계기로 자연스럽게",
        channel: "kakao",
        body: "{고객명}님, 요즘 실손·암보험 갱신으로 점검 문의가 많아요. 가족이나 지인 중 '내 보험 이대로 괜찮나' 궁금해하시는 분 있으면 편하게 연결해 주세요. 제가 깔끔하게 정리해 드릴게요.",
      },
    ],
  },
  {
    key: "objection",
    label: "거절 응대",
    desc: "흔한 거절 3가지에 대한 부드러운 응대. 밀어붙이지 않는 게 핵심.",
    templates: [
      {
        id: "obj-busy",
        title: "“지금 바빠요”",
        channel: "kakao",
        body: "{고객명}님, 바쁘신데 연락드려 죄송해요. 통화 10분이면 충분하고 편하신 시간에 맞출게요. 이번 주 중 언제가 좋으실까요?",
      },
      {
        id: "obj-have-planner",
        title: "“이미 담당 설계사 있어요”",
        channel: "kakao",
        body: "{고객명}님, 담당 설계사가 계시는군요 👍 바꾸시라는 게 아니라 보장이 겹치거나 빈 곳은 없는지 '제3자 점검' 차원으로 봐드릴게요. 결정은 {고객명}님 몫이에요.",
      },
      {
        id: "obj-money",
        title: "“보험료 부담돼요”",
        channel: "kakao",
        body: "{고객명}님, 보험료 부담되시죠. 새로 드시라는 게 아니라 지금 내는 것 중 줄일 수 있는 중복은 없는지부터 봐요. 오히려 보험료를 아낀 분도 많아요.",
      },
    ],
  },
  {
    key: "appointment",
    label: "약속 잡기 (TA)",
    desc: "전화·문자로 첫 접촉해 만날 약속을 잡는 단계. 선택지를 주면 잡기 쉬워요.",
    templates: [
      {
        id: "ta-first",
        title: "첫 약속 제안",
        channel: "kakao",
        body: "{고객명}님, 안녕하세요. {설계사명}입니다. 보장 점검 30분이면 되는데, 이번 주 목요일 오후 / 금요일 오전 중 언제가 편하실까요?",
      },
      {
        id: "ta-remind",
        title: "약속 전날 리마인드",
        channel: "kakao",
        body: "{고객명}님, 내일 약속 잊지 않으셨죠 😊 시간·장소 그대로 뵐게요. 가지고 계신 증권이나 보험 앱 캡처 있으면 가져와 주시면 더 정확히 봐드려요.",
      },
    ],
  },
  {
    key: "needs",
    label: "니즈 환기 (FA)",
    desc: "직접 만나기 전·후, 담보별로 점검 필요성을 가볍게 일깨울 때.",
    templates: [
      {
        id: "fa-silson",
        title: "실손 갱신 안내",
        channel: "kakao",
        body: "{고객명}님, 실손보험 갱신 시기가 다가오는데 보험료가 꽤 오를 수 있어요. 지금 보장과 비교해 유지/조정 어느 쪽이 유리한지 정리해 드릴게요.",
      },
      {
        id: "fa-cancer",
        title: "암 보장 점검",
        channel: "kakao",
        body: "{고객명}님, 요즘 암 진단비·표적항암 같은 보장이 예전 가입 상품엔 약한 경우가 많아요. {고객명}님 증권 기준으로 빈 곳 있는지 한 번 볼까요?",
      },
      {
        id: "fa-gap",
        title: "보장 공백 환기",
        channel: "kakao",
        body: "{고객명}님, 가입은 여러 개인데 정작 큰 병·수술 때 받는 금액은 적은 경우가 있어요. 증권 한 장만 주시면 보장 공백을 한 화면에 정리해 드릴게요.",
      },
    ],
  },
  {
    key: "aftercare",
    label: "안부 · AS",
    desc: "계약 후 관계 유지. 생일·기념일 안부는 환수를 막는 가장 싼 보험.",
    templates: [
      {
        id: "as-birthday",
        title: "생일 축하",
        channel: "kakao",
        body: "{고객명}님, 생일 진심으로 축하드려요 🎉 건강하고 좋은 일 가득한 한 해 되시길 바라요. — {설계사명}",
      },
      {
        id: "as-1year",
        title: "계약 1년 안부",
        channel: "kakao",
        body: "{고객명}님, 가입하신 지 벌써 1년이 됐네요. 그동안 변동(이사·가족·직업) 있으셨으면 보장도 같이 점검해요. 별일 없으셔도 안부차 연락드렸어요 😊",
      },
      {
        id: "as-event-sms",
        title: "이벤트 안내 (광고문자 예시)",
        channel: "sms",
        body: "(광고) {고객명}님, {설계사명}입니다. 무료 보장점검 이벤트 안내드려요. 신청: [링크]\n무료수신거부 080-000-0000",
      },
    ],
  },
];
