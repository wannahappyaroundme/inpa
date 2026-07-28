// 설계사가 고객과 다음 행동을 구체적으로 정할 때 쓰는 기본 화법 30개.
// 기본값은 운영 원본이다. 사용자는 복사해 개인 템플릿으로 저장할 수 있지만 직접 덮어쓰지 않는다.

export type TalkTemplateChannel = "message" | "call";

export interface CopyTemplate {
  key: string;
  title: string;
  body: string;
  channel: TalkTemplateChannel;
  isAdvertising?: boolean;
  requiresResultCheck?: boolean;
}

export interface CopyCategory {
  key: string;
  label: string;
  desc: string;
  templates: CopyTemplate[];
}

export interface CopyVariables {
  customer?: string;
  planner?: string;
  affiliation?: string;
  title?: string;
  phone?: string;
  optOut?: string;
}

/** 저장된 변수 문구를 새 문자열로 치환한다. 입력 본문은 바꾸지 않는다. */
export function renderCopy(body: string, vars: CopyVariables): string {
  const customer = (vars.customer || "").trim();
  const affiliation = (vars.affiliation || "").trim();
  const title = (vars.title || "").trim();
  const affiliationAndTitle = [affiliation, title].filter(Boolean).join(" ");
  const customerReadyBody = customer
    ? body.replace(/\{고객명\}/g, customer)
    : body
        .replace(/\{고객명\}\s*고객님/g, "고객님")
        .replace(/\{고객명\}님/g, "안녕하세요")
        .replace(/\{고객명\}/g, "고객님");
  const rendered = customerReadyBody
    .replace(/\{설계사명\}/g, (vars.planner || "").trim() || "담당 설계사")
    .replace(
      /\{소속직책\}으로/g,
      affiliationAndTitle
        ? `${affiliationAndTitle}으로`
        : "보험 설계사로",
    )
    .replace(/\{소속직책\}/g, affiliationAndTitle)
    .replace(/\{소속\}/g, affiliation)
    .replace(/\{직책\}/g, title)
    .replace(/\{설계사연락처\}/g, (vars.phone || "").trim())
    .replace(/\{수신거부안내\}/g, (vars.optOut || "").trim());
  return rendered
    .replace(/[ \t]{2,}/g, " ")
    .replace(/^[ \t]+|[ \t]+$/gm, "");
}

export const COPY_CATEGORIES: CopyCategory[] = [
  {
    key: "referral",
    label: "소개 요청",
    desc: "관리 경험을 떠올릴 수 있는 고객에게 구체적인 연결 방법을 제안해요.",
    templates: [
      {
        key: "referral-thanks",
        title: "관리 후 소개 부탁",
        channel: "message",
        body: "{고객명} 고객님, 함께 보험 내용을 정리해 주셔서 감사합니다. 주변에도 가입한 내용을 한눈에 정리하고 싶은 분이 있다면 같은 방식으로 도와드릴 수 있어요. 떠오르는 한 분께 제 연락처를 보내 주실까요, 세 사람이 함께 있는 대화방을 열어 주실까요? {설계사명} 드림",
      },
      {
        key: "referral-trigger",
        title: "가족 점검으로 연결",
        channel: "call",
        body: "{고객명} 고객님, 가족 보험은 서로 다른 시기에 가입해 한 번에 보기 어려운 경우가 있습니다. 등록된 보험료와 보장 항목을 함께 펼쳐 보면 가족이 각자 확인할 부분을 나눌 수 있어요. 먼저 확인해 볼 가족 한 분을 정할까요, 가족이 함께 가능한 시간을 예약할까요?",
      },
    ],
  },
  {
    key: "objection",
    label: "망설임 응대",
    desc: "고객의 상황을 먼저 인정하고, 작게 시작할 수 있는 선택지를 제시해요.",
    templates: [
      {
        key: "obj-busy",
        title: "지금 시간이 없을 때",
        channel: "message",
        body: "{고객명} 고객님, 지금 일정이 바쁘신 점 확인했습니다. 필요한 자료와 먼저 볼 항목을 짧게 나누면 다음 대화를 준비하기 쉬워요. 메시지로 준비물을 먼저 확인할까요, 짧은 통화를 예약할까요?",
      },
      {
        key: "obj-have-planner",
        title: "담당 설계사가 있을 때",
        channel: "call",
        body: "{고객명} 고객님, 이미 관리해 주는 설계사가 있다는 점 확인했습니다. 담당 관계는 그대로 두고 등록된 보험료와 보장 항목을 한 표에서 확인할 수 있어요. 표만 받아볼까요, 담당 설계사와 함께 볼 시간을 정할까요?",
      },
      {
        key: "obj-money",
        title: "보험료가 걱정될 때",
        channel: "call",
        body: "{고객명} 고객님, 매달 내는 금액을 먼저 살펴보는 게 중요하다는 말씀 확인했습니다. 판단에 앞서 보험별 보험료와 납입기간을 나란히 보면 현재 부담을 분명히 알 수 있어요. 월 보험료부터 확인할까요, 납입기간까지 함께 볼까요?",
      },
      {
        key: "obj-think",
        title: "조금 더 생각하고 싶을 때",
        channel: "message",
        body: "{고객명} 고객님, 더 살펴본 뒤 정하고 싶다는 말씀 확인했습니다. 검토할 내용을 짧게 나누면 다음 대화에서 같은 설명을 반복하지 않아도 돼요. 보험료와 보장 내용 중 어느 항목을 먼저 확인해 보내드릴까요?",
      },
      {
        key: "obj-dont-know",
        title: "보험 용어가 어려울 때",
        channel: "call",
        body: "{고객명} 고객님, 보험 용어부터 쉽게 설명해 달라는 말씀 확인했습니다. 증권에 적힌 항목을 일상적인 말로 하나씩 풀어보면 현재 가입 내용을 직접 확인할 수 있어요. 증권 사진을 먼저 보내 주실까요, 화면을 보며 통화할까요?",
      },
    ],
  },
  {
    key: "appointment",
    label: "약속 잡기",
    desc: "시간과 준비물을 분명히 제시해 고객이 바로 선택할 수 있게 해요.",
    templates: [
      {
        key: "ta-first",
        title: "첫 점검 약속",
        channel: "message",
        body: "{고객명} 고객님, 안녕하세요. {소속직책} {설계사명}입니다. 첫 만남에서는 가입한 보험과 궁금한 항목을 함께 정리하겠습니다. 평일 낮과 평일 저녁 중 어느 시간대로 예약할까요?",
      },
      {
        key: "ta-remind",
        title: "약속 전날 확인",
        channel: "message",
        body: "{고객명} 고객님, 내일 약속 시간을 다시 확인드립니다. 보험 증권이나 보험 앱 화면이 있으면 등록된 내용을 함께 살펴볼 수 있어요. 약속대로 진행할지, 시간을 조정할지 답장으로 알려 주실까요?",
      },
      {
        key: "ta-phone",
        title: "전화로 점검 예약",
        channel: "message",
        body: "{고객명} 고객님, 이동이 어려우시면 전화로 가입 내용을 함께 확인할 수 있어요. 통화 전에 증권 사진을 보내 주시면 같은 화면을 보며 설명드리겠습니다. 평일 낮과 평일 저녁 중 어느 시간대로 예약할까요?",
      },
      {
        key: "ta-noshow",
        title: "놓친 약속 다시 잡기",
        channel: "message",
        body: "{고객명} 고객님, 지난 약속은 일정이 맞지 않아 만나지 못했습니다. 필요한 시간을 다시 정해 두면 확인하려던 내용을 이어갈 수 있어요. 이번 주와 다음 주 중 어느 주로 예약할까요?",
      },
    ],
  },
  {
    key: "needs",
    label: "확인할 항목 찾기",
    desc: "결과를 미리 단정하지 않고 실제 증권에서 볼 항목을 정해요.",
    templates: [
      {
        key: "fa-silson",
        title: "실손 갱신 내용 확인",
        channel: "message",
        body: "{고객명} 고객님, 실손 갱신 안내를 받으셨다면 바뀐 보험료와 보장 내용을 실제 안내서에서 확인해야 합니다. 현재 내용과 갱신 뒤 내용을 나란히 적으면 달라지는 항목을 놓치지 않을 수 있어요. 안내서 사진을 먼저 보내 주실까요, 통화로 함께 확인할까요?",
      },
      {
        key: "fa-cancer",
        title: "암 관련 보장 확인",
        channel: "call",
        body: "{고객명} 고객님, 암 관련 보장은 상품마다 항목 이름과 지급 범위가 다를 수 있어 실제 증권 확인이 먼저입니다. 진단비와 치료비 항목을 나눠 보면 가입 내용을 이해하기 쉬워요. 진단비부터 확인할까요, 치료비부터 확인할까요?",
      },
      {
        key: "fa-gap",
        title: "전체 보장 항목 펼쳐 보기",
        channel: "call",
        body: "{고객명} 고객님, 여러 보험을 따로 보면 같은 종류의 보장도 한 번에 파악하기 어렵습니다. 등록된 보험을 한 표에 모으면 가지고 있는 항목과 금액을 차례로 확인할 수 있어요. 큰 질병 항목부터 볼까요, 수술·입원 항목부터 볼까요?",
      },
    ],
  },
  {
    key: "aftercare",
    label: "안부와 관리",
    desc: "생활 변화가 있었는지 자연스럽게 묻고 다음 관리 시점을 정해요.",
    templates: [
      {
        key: "as-birthday",
        title: "생일 축하와 관리 일정",
        channel: "message",
        body: "{고객명} 고객님, 생일을 진심으로 축하드립니다. 건강하고 좋은 일이 가득한 한 해 보내세요. 생일이 지난 뒤 등록된 연락처와 직업 정보를 짧게 확인할까요, 다음 정기 연락 때 함께 볼까요? {설계사명} 드림",
      },
      {
        key: "as-1year",
        title: "가입 1년 뒤 안부",
        channel: "call",
        body: "{고객명} 고객님, 가입 후 1년이 되어 관리 연락드립니다. 그동안 가족, 직업, 주소가 달라졌다면 등록된 정보도 같이 확인할 수 있어요. 이번 주에 확인할까요, 다음 주로 예약할까요?",
      },
      {
        key: "as-holiday",
        title: "명절 안부와 다음 연락",
        channel: "message",
        body: "{고객명} 고객님, 가족과 편안한 명절 보내시길 바랍니다. 연휴 뒤 바뀐 연락처나 가족 정보가 있는지 확인하면 다음 관리 때 바로 반영할 수 있어요. 연휴 다음 주에 확인할까요, 이번에는 안부만 나눌까요? {설계사명} 드림",
      },
      {
        key: "as-life-event",
        title: "결혼·출산·이직 뒤 확인",
        channel: "call",
        body: "{고객명} 고객님, 새로운 시작을 진심으로 축하드립니다. 가족이나 직업 정보가 달라졌다면 현재 등록 내용도 함께 맞춰볼 수 있어요. 바뀐 정보만 먼저 확인할까요, 전체 가입 내용을 보는 약속을 잡을까요?",
      },
      {
        key: "as-event-sms",
        title: "보장 정리 안내 문자",
        channel: "message",
        isAdvertising: true,
        body: "(광고) {고객명} 고객님, {소속직책} {설계사명}입니다. 문의: {설계사연락처}\n등록된 보험의 보험료와 보장 항목을 한 화면에 정리해 드립니다. 안내를 받아볼지, 다음 연락을 원치 않는지 답장으로 선택해 주세요.\n수신거부: {수신거부안내}",
      },
    ],
  },
  {
    key: "prospecting",
    label: "첫 연락",
    desc: "관계의 맥락을 밝히고 고객이 원하는 대화 범위를 직접 고르게 해요.",
    templates: [
      {
        key: "prospect-acquaintance",
        title: "지인에게 근황 알리기",
        channel: "message",
        body: "{고객명}님, 오랜만이에요. 저는 요즘 보험 설계사로 일하며 가입한 보험료와 보장 항목을 정리하는 일을 돕고 있어요. 궁금한 보험 하나를 먼저 확인해 볼까요, 제 연락처만 저장해 둘까요?",
      },
      {
        key: "prospect-longtime",
        title: "오랜만인 지인에게 연락",
        channel: "call",
        body: "{고객명}님, 오랜만에 안부 전합니다. 저는 현재 {소속직책}으로 일하며 보험 증권을 이해하기 쉽게 정리해 드리고 있어요. 먼저 근황만 나눌까요, 가입한 보험 중 궁금한 한 가지를 함께 확인할까요?",
      },
      {
        key: "prospect-card",
        title: "명함을 나눈 뒤 첫 인사",
        channel: "message",
        body: "안녕하세요, {고객명} 고객님. 명함을 나눈 {소속직책} {설계사명}입니다. 만나 뵙게 되어 반가웠습니다. 보험료, 납입기간, 보장 항목 중 궁금한 내용이 생기면 확인을 도와드릴게요. 제 연락처를 저장해 둘까요, 짧은 전화 약속을 잡을까요?",
      },
    ],
  },
  {
    key: "reengage",
    label: "다시 연락하기",
    desc: "지난 연락 이후 달라진 정보를 확인하며 대화를 다시 시작해요.",
    templates: [
      {
        key: "reengage-checkup",
        title: "오랜만에 안부와 정보 확인",
        channel: "message",
        body: "{고객명} 고객님, 오랜만에 안부 전합니다. 지난 연락 뒤 가족, 직업, 연락처가 달라졌다면 등록된 정보도 함께 맞춰둘 수 있어요. 바뀐 정보만 답장으로 확인할까요, 통화 시간을 예약할까요?",
      },
      {
        key: "reengage-system",
        title: "등록된 보험 다시 펼쳐 보기",
        channel: "call",
        body: "{고객명} 고객님, 한동안 따로 보지 않았던 보험은 현재 보험료와 납입기간부터 다시 확인하면 이해하기 쉽습니다. 실제 증권에 적힌 내용을 기준으로 차례로 정리하겠습니다. 보험료부터 확인할까요, 만기와 납입기간부터 확인할까요?",
      },
    ],
  },
  {
    key: "result",
    label: "정리 내용 공유",
    desc: "실제 화면과 같은지 설계사가 먼저 확인한 뒤 고객과 볼 순서를 정해요.",
    templates: [
      {
        key: "result-share",
        title: "정리한 보험 내용 안내",
        channel: "message",
        requiresResultCheck: true,
        body: "{고객명} 고객님, 등록해 주신 보험의 보험료와 보장 항목을 한 화면에 정리했습니다. 정리한 화면에서 보험료를 먼저 확인할까요, 보장 내용을 먼저 확인할까요?",
      },
      {
        key: "result-gap",
        title: "표에서 볼 항목 정하기",
        channel: "call",
        requiresResultCheck: true,
        body: "{고객명} 고객님, 표에 표시된 금액은 등록된 보험 내용을 기준으로 정리한 값입니다. 실제 증권과 같은지 함께 확인한 뒤 자세히 볼 항목을 정하겠습니다. 질병 관련 항목부터 확인할까요, 상해 관련 항목부터 확인할까요?",
      },
      {
        key: "result-keep",
        title: "현재 등록 내용 다시 확인",
        channel: "message",
        requiresResultCheck: true,
        body: "{고객명} 고객님, 현재 등록된 보험료와 보장 항목을 다시 정리해 두었습니다. 실제 증권과 같은지 확인하면 다음 관리 때 같은 자료를 이어서 볼 수 있어요. 등록 내용을 먼저 확인할까요, 달라진 정보부터 반영할까요?",
      },
    ],
  },
  {
    key: "closing",
    label: "신청과 마무리",
    desc: "고객이 확인할 내용을 한 번 더 짚고 다음 절차를 구체적으로 정해요.",
    templates: [
      {
        key: "closing-confirm",
        title: "신청 직전 최종 확인",
        channel: "call",
        body: "{고객명} 고객님, 오늘 확인한 보험료와 보장 내용을 한 번 더 점검한 뒤 신청 절차를 이어가겠습니다. 지금 진행할까요, 조정할 항목부터 함께 확인할까요?",
      },
      {
        key: "closing-docs",
        title: "필요 서류와 진행 방법",
        channel: "message",
        body: "{고객명} 고객님, 필요한 서류는 신청할 상품과 상황에 따라 달라질 수 있어 확인한 준비 목록을 먼저 보내드리겠습니다. 목록을 받은 뒤 모바일로 진행할까요, 만나서 진행할까요?",
      },
      {
        key: "closing-thanks",
        title: "신청 후 다음 절차 안내",
        channel: "message",
        body: "{고객명} 고객님, 오늘 신청한 내용과 다음 절차를 다시 정리해 보내드리겠습니다. 증권이 발급되면 신청 내용과 같은지 함께 확인할 수 있어요. 증권을 받은 날 확인할까요, 다음 날 통화로 확인할까요? {설계사명} 드림",
      },
    ],
  },
];

const ADVERTISING_VARIABLES = [
  "{설계사연락처}",
  "{수신거부안내}",
] as const;

export function getAdvertisingVariableGuidance(
  sourceKey: string | null,
  body: string,
): string | null {
  const source = COPY_CATEGORIES
    .flatMap((category) => category.templates)
    .find((template) => template.key === sourceKey);
  if (!source?.isAdvertising) return null;
  const missing = ADVERTISING_VARIABLES.filter(
    (variable) => !body.includes(variable),
  );
  if (missing.length === 0) return null;
  return `광고 화법 본문에 ${missing.join(", ")} 변수를 다시 넣어 주세요.`;
}
