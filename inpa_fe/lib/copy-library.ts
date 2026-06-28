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
      {
        id: "obj-think",
        title: "“생각해 볼게요”",
        channel: "kakao",
        body: "{고객명}님, 천천히 생각하셔도 돼요 😊 결정하시라는 게 아니라, 우선 지금 보장이 어떤 상태인지만 한 화면으로 정리해서 보내드릴게요. 보고 나서 편하실 때 말씀 주세요.",
      },
      {
        id: "obj-dont-know",
        title: "“보험 잘 몰라요”",
        channel: "kakao",
        body: "{고객명}님, 모르시는 게 당연해요. 그래서 제가 있는 거고요 🙂 어려운 용어 빼고 '지금 받을 수 있는 돈 / 빈 곳'만 쉽게 짚어드릴게요. 증권 한 장이면 충분해요.",
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
      {
        id: "ta-phone",
        title: "비대면(전화) 약속",
        channel: "kakao",
        body: "{고객명}님, 직접 뵙기 어려우시면 전화로도 충분해요. 미리 증권만 캡처해서 보내주시면, 통화하면서 화면 보며 같이 짚어드릴게요. 오늘 저녁 / 내일 점심 중 언제가 편하세요?",
      },
      {
        id: "ta-noshow",
        title: "약속 미루어진 뒤 재제안",
        channel: "kakao",
        body: "{고객명}님, 지난번엔 바쁘셨죠 😊 부담 없이 다시 한번만 잡아볼게요. 이번 주 안 되시면 다음 주도 괜찮아요. 편하신 요일만 알려주세요.",
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
        id: "as-holiday",
        title: "명절 안부",
        channel: "kakao",
        body: "{고객명}님, 풍성한 명절 보내고 계신가요 🙂 가족과 좋은 시간 보내시고, 늘 건강하시길 바라요. 필요하신 일 있으면 언제든 편하게 연락 주세요. — {설계사명}",
      },
      {
        id: "as-life-event",
        title: "경사(출산·결혼·이직) 계기",
        channel: "kakao",
        body: "{고객명}님, 좋은 소식 진심으로 축하드려요 🎉 가족이 늘거나 환경이 바뀌면 필요한 보장도 달라질 수 있어요. 바쁘신 거 정리되시면 가볍게 한 번 점검해 드릴게요.",
      },
      {
        id: "as-event-sms",
        title: "이벤트 안내 (광고문자 예시)",
        channel: "sms",
        body: "(광고) {고객명}님, {설계사명}입니다. 무료 보장점검 이벤트 안내드려요. 신청: [링크]\n무료수신거부 080-000-0000",
      },
    ],
  },
  {
    key: "prospecting",
    label: "신규 발굴 (지인 첫 접촉)",
    desc: "아는 사람에게 부담 없이 첫 말을 꺼낼 때. 영업 티 안 나게, 도움 주는 톤으로.",
    templates: [
      {
        id: "prospect-acquaintance",
        title: "지인에게 첫 알림",
        channel: "kakao",
        body: "{고객명}님, 저 요즘 보험 일 하고 있어요 🙂 뭘 권하려는 건 아니고, 혹시 '내 보험 이대로 괜찮나' 궁금하실 때 편하게 물어보시라고요. 점검은 무료고 결정은 {고객명}님 몫이에요.",
      },
      {
        id: "prospect-longtime",
        title: "오랜만에 연락하는 지인",
        channel: "kakao",
        body: "{고객명}님, 오랜만이에요! 잘 지내시죠 😊 다름 아니라 제가 보장 점검을 도와드리는 일을 하고 있어서요. 부담 갖지 마시고, 필요하실 때 증권 한 장만 보여주시면 깔끔히 정리해 드릴게요.",
      },
      {
        id: "prospect-card",
        title: "명함 받은 분께 첫 인사",
        channel: "kakao",
        body: "{고객명}님, 어제 인사드린 {설계사명}입니다. 만나뵙게 되어 반가웠어요 🙂 언제든 보험 관련해 궁금한 점 생기면 편하게 연락 주세요. 답만 드려도 좋습니다.",
      },
    ],
  },
  {
    key: "reengage",
    label: "재접촉 (오래 연락 못 한 고객)",
    desc: "연락 끊긴 기간이 길어진 고객에게 자연스럽게 다시 다가갈 때. 안부가 먼저.",
    templates: [
      {
        id: "reengage-checkup",
        title: "안부 + 가벼운 점검 제안",
        channel: "kakao",
        body: "{고객명}님, 한동안 연락 못 드렸네요. 잘 지내셨죠 😊 별일 없으셔도 안부차 연락드렸어요. 그동안 가족이나 직업에 변동 있으셨으면, 보장도 한 번 같이 살펴볼까요?",
      },
      {
        id: "reengage-system",
        title: "제도·상품 변경 계기",
        channel: "kakao",
        body: "{고객명}님, 잘 지내시죠. 최근 실손·암보장 관련 제도가 좀 바뀌어서요. {고객명}님 가입 상품에 영향 있는지만 빠르게 확인해 드리려고 연락드렸어요. 부담 갖지 마세요 🙂",
      },
    ],
  },
  {
    key: "result",
    label: "점검 결과 공유",
    desc: "분석을 마친 뒤 결과를 전달할 때. 갈아타기를 권하지 않고 사실만 — 결정은 고객 몫.",
    templates: [
      {
        id: "result-share",
        title: "보장 한눈표 링크 전달",
        channel: "kakao",
        body: "{고객명}님, 말씀드린 보장 점검표 정리했어요. 아래 링크에서 지금 보장 상태를 한 화면으로 보실 수 있어요. 보시고 궁금한 점 있으면 편하게 물어봐 주세요. [링크]",
      },
      {
        id: "result-gap",
        title: "공백 요약 (중립 안내)",
        channel: "kakao",
        body: "{고객명}님, 점검해 보니 잘 갖춰진 부분도 있고, 큰 병·수술 쪽은 조금 얇은 곳이 보였어요. 어떻게 할지는 천천히 정하시면 되고, 저는 선택지만 객관적으로 정리해 드릴게요.",
      },
      {
        id: "result-keep",
        title: "지금 유지가 나을 때 (정직 안내)",
        channel: "kakao",
        body: "{고객명}님, 점검 결과 지금 보험을 굳이 바꾸실 필요는 없어 보여요. 잘 들어두셨어요 👍 무리해서 바꾸기보다 이대로 유지하시고, 변동 생기면 그때 다시 봐드릴게요.",
      },
    ],
  },
  {
    key: "closing",
    label: "청약 · 마무리",
    desc: "고객이 마음을 정한 뒤 청약을 차분히 마무리할 때. 재촉하지 않고 안내 위주로.",
    templates: [
      {
        id: "closing-confirm",
        title: "청약 직전 확인",
        channel: "kakao",
        body: "{고객명}님, 지난번 말씀 주신 방향으로 준비해 두었어요. 진행 전에 한 번 더 확인만 드릴게요 — 궁금하거나 마음에 걸리는 부분 있으면 지금 편하게 말씀 주세요 🙂",
      },
      {
        id: "closing-docs",
        title: "필요 서류 안내",
        channel: "kakao",
        body: "{고객명}님, 청약에 필요한 건 신분증과 본인 명의 계좌 정도예요. 준비되시면 알려주세요. 작성은 제가 옆에서 같이 도와드릴게요. 오래 안 걸려요 😊",
      },
      {
        id: "closing-thanks",
        title: "청약 후 감사 + 다음 단계",
        channel: "kakao",
        body: "{고객명}님, 믿고 맡겨주셔서 감사해요 🙏 증권 나오면 바로 전달드리고, 이후에도 갱신·변동 챙겨서 먼저 연락드릴게요. 늘 편하게 연락 주세요. — {설계사명}",
      },
    ],
  },
];
