import {
  renderCopy,
  type CopyVariables,
} from "@/lib/copy-library";

export const GUIDED_TALK_VERSION = "2026-07-29.v1";

export interface GuidedTalkVariables extends CopyVariables {
  referrer?: string;
}

export interface GuidedTalkStep {
  key: string;
  title: string;
  goal: string;
  spokenText: string;
  questions: string[];
  checklist: string[];
  coachNote?: string;
  objectionKeys: string[];
  requiresSalesDisclosure?: boolean;
}

export interface GuidedTalkAction {
  key: string;
  label: string;
  description: string;
  target:
    | "schedule"
    | "quick-appointment"
    | "customer-analysis"
    | "quick-result"
    | "end-call";
}

export interface GuidedTalkPlaybook {
  key: string;
  title: string;
  description: string;
  durationLabel: string;
  goal: string;
  startCondition: string;
  steps: GuidedTalkStep[];
  nextActions: GuidedTalkAction[];
}

export interface GuidedTalkObjection {
  key: string;
  label: string;
  responseText: string;
  secondRefusalText: string;
  terminal?: boolean;
}

const respectfulClose =
  "말씀을 존중해 오늘 대화는 여기서 마치겠습니다. 함께 확인하고 싶으실 때 고객님이 먼저 알려 주세요.";

export const GUIDED_TALK_OBJECTIONS: Record<
  string,
  GuidedTalkObjection
> = {
  "busy-now": {
    key: "busy-now",
    label: "지금 시간이 없어요",
    responseText:
      "일정이 바쁘신 점 알겠습니다. 오늘은 통화를 마치고, 다시 연락드릴 날짜만 정할까요? 고객님이 먼저 연락 주시는 방법도 가능합니다.",
    secondRefusalText: respectfulClose,
  },
  "low-interest": {
    key: "low-interest",
    label: "지금은 관심이 적어요",
    responseText:
      "지금 상담을 이어갈 계획이 크지 않으신 점 알겠습니다. 현재 가입 내용을 한 번 정리할지, 오늘 연락을 마칠지 고객님 뜻에 따르겠습니다.",
    secondRefusalText: respectfulClose,
  },
  "existing-planner": {
    key: "existing-planner",
    label: "담당 설계사가 있어요",
    responseText:
      "이미 관리해 주는 설계사가 있다는 점 알겠습니다. 그 관계는 그대로 두고, 등록된 보험료와 보장 항목을 함께 확인하는 범위로 볼 수 있습니다. 확인만 진행할지 오늘 대화를 마칠지 정해 주세요.",
    secondRefusalText: respectfulClose,
  },
  "source-and-privacy": {
    key: "source-and-privacy",
    label: "연락 경로가 궁금해요",
    responseText:
      "연락 경로부터 설명드리겠습니다. 소개받은 범위와 오늘 확인하려는 내용을 먼저 말씀드리고, 고객님이 동의하신 범위에서만 대화하겠습니다. 설명을 들을지 오늘 연락을 마칠지 선택해 주세요.",
    secondRefusalText: respectfulClose,
  },
  "callback-later": {
    key: "callback-later",
    label: "다시 연락해 주세요",
    responseText:
      "알겠습니다. 고객님이 동의하신 날짜와 시간에 한 번 연락드리겠습니다. 이번 주와 다음 주 중 어느 쪽으로 정할까요?",
    secondRefusalText: respectfulClose,
  },
  "no-more-contact": {
    key: "no-more-contact",
    label: "다음 연락을 원치 않아요",
    responseText:
      "알겠습니다. 말씀하신 뜻에 따라 오늘 연락을 마치고, 이후에는 먼저 연락드리지 않겠습니다.",
    secondRefusalText:
      "말씀하신 연락 중단 의사를 존중해 오늘 연락을 마치겠습니다.",
    terminal: true,
  },
  "no-policy": {
    key: "no-policy",
    label: "증권이 없어요",
    responseText:
      "오늘 증권이 없어도 가입한 보험사와 월 보험료처럼 기억나는 범위부터 정리할 수 있습니다. 보험 앱에서 자료를 준비한 뒤 다시 볼지, 오늘은 확인 순서만 정할지 선택해 주세요.",
    secondRefusalText: respectfulClose,
  },
  "document-privacy": {
    key: "document-privacy",
    label: "자료 공유가 걱정돼요",
    responseText:
      "자료를 어디에 쓰는지 먼저 확인하고 싶으신 점 알겠습니다. 필요한 정보와 사용 목적을 설명드린 뒤 고객님이 동의한 자료만 등록합니다. 설명만 들을지 오늘 자료 확인을 마칠지 정해 주세요.",
    secondRefusalText: respectfulClose,
  },
  "premium-concern": {
    key: "premium-concern",
    label: "보험료가 걱정돼요",
    responseText:
      "매달 내는 금액을 먼저 확인하고 싶으신 점 알겠습니다. 상품을 정하기 전에 보험별 월 보험료와 납입기간부터 나란히 볼 수 있습니다. 금액만 먼저 볼지 오늘 확인을 마칠지 정해 주세요.",
    secondRefusalText: respectfulClose,
  },
  "decide-later": {
    key: "decide-later",
    label: "더 생각해 볼게요",
    responseText:
      "살펴본 뒤 정하고 싶으신 뜻 알겠습니다. 오늘 확인한 사실만 짧게 정리하고, 다음 상담 일정을 정할지 고객님이 먼저 연락 주실지 선택해 주세요.",
    secondRefusalText: respectfulClose,
  },
  "no-decision-today": {
    key: "no-decision-today",
    label: "오늘은 결정하지 않을게요",
    responseText:
      "오늘 결정을 미리 정하지 않으셔도 됩니다. 확인한 보험료와 보장 항목만 정리하고, 다음 확인을 이어갈지 여기서 마칠지 고객님 뜻에 따르겠습니다.",
    secondRefusalText: respectfulClose,
  },
};

export const GUIDED_TALK_PLAYBOOKS: GuidedTalkPlaybook[] = [
  {
    key: "referred-customer-first-call",
    title: "소개받은 고객 첫 통화",
    description:
      "연락 경위와 상담 목적을 분명히 밝히고, 고객이 원하는 방식으로 다음 약속을 정해요.",
    durationLabel: "약 5분",
    goal: "상담 방식과 다음 일정을 고객과 함께 정하기",
    startCondition: "소개 경위를 사실대로 설명할 수 있을 때 시작해요.",
    steps: [
      {
        key: "call-disclosure",
        title: "신분과 연락 목적 밝히기",
        goal: "누가 왜 연락했는지 먼저 알리고 통화 허락을 구합니다.",
        spokenText:
          "{고객명} 고객님, 안녕하세요. {소속직책} {설계사명}입니다. 가입하신 보험을 함께 확인하고, 필요하시면 보험 상품을 안내드리는 상담 때문에 연락드렸습니다. 지금 2분 정도 통화해도 될까요?",
        questions: ["지금 짧게 통화해도 될까요?"],
        checklist: ["성명·소속", "보험 상담·안내 목적", "통화 허락"],
        coachNote:
          "고객의 대답을 기다린 뒤 다음 단계로 이동합니다. 통화가 어렵다면 바로 고객 반응에서 일정을 정합니다.",
        objectionKeys: ["busy-now", "callback-later", "no-more-contact"],
        requiresSalesDisclosure: true,
      },
      {
        key: "call-referral-context",
        title: "소개 경위 설명하기",
        goal: "소개자가 동의하거나 보증한 범위를 넘겨 말하지 않습니다.",
        spokenText:
          "{소개자명} 님 소개로 연락드렸습니다. 소개 경위만 먼저 말씀드리고, 구체적으로 무엇을 확인할지는 고객님께 직접 여쭙겠습니다.",
        questions: ["연락 경위부터 더 설명드릴까요?"],
        checklist: ["실제 소개 경위와 일치하는지 확인"],
        coachNote:
          "소개자가 고객의 가입 의사나 상담 의사를 보증한 것처럼 말하지 않습니다.",
        objectionKeys: ["source-and-privacy", "no-more-contact"],
      },
      {
        key: "call-customer-priority",
        title: "먼저 궁금한 점 듣기",
        goal: "설명보다 고객이 확인하고 싶은 항목을 먼저 듣습니다.",
        spokenText:
          "이번 상담에서 고객님이 먼저 확인하고 싶은 내용을 한 가지만 여쭤봐도 될까요? 현재 가입 내용, 월 보험료, 최근 받은 안내 중 어디부터 보고 싶으세요?",
        questions: [
          "현재 가입 내용과 월 보험료 중 무엇이 먼저 궁금하세요?",
          "최근 보험사에서 받은 안내가 있나요?",
        ],
        checklist: ["고객이 말한 우선순위를 그대로 기록"],
        objectionKeys: ["low-interest", "existing-planner", "no-more-contact"],
      },
      {
        key: "call-review-method",
        title: "확인 방법 설명하기",
        goal: "상품 결론보다 실제 자료를 먼저 본다는 원칙을 알립니다.",
        spokenText:
          "상담에서는 증권에 적힌 보험료, 납입기간, 보장 항목을 실제 자료 기준으로 함께 확인합니다. 변경이나 가입 여부는 먼저 정하지 않고 현재 내용을 한눈에 정리합니다.",
        questions: ["전화와 대면 중 어떤 방식으로 함께 볼까요?"],
        checklist: ["사실 확인과 상품 판단을 구분"],
        objectionKeys: ["existing-planner", "premium-concern", "low-interest"],
      },
      {
        key: "call-schedule-choice",
        title: "상담 방식과 일정 정하기",
        goal: "고객이 방식과 시기를 직접 고르게 합니다.",
        spokenText:
          "한 번 확인해 보신다면 전화 상담과 대면 상담 중 어떤 방식으로 정할까요? 일정은 이번 주와 다음 주 중 어느 쪽이 맞으세요? 오늘은 여기서 통화를 마치셔도 됩니다.",
        questions: [
          "전화 상담과 대면 상담 중 어떤 방식이 맞으세요?",
          "이번 주와 다음 주 중 어느 쪽으로 정할까요?",
        ],
        checklist: ["방식", "날짜", "시간", "장소 또는 통화 방법"],
        objectionKeys: [
          "busy-now",
          "callback-later",
          "low-interest",
          "no-more-contact",
        ],
      },
      {
        key: "call-confirmation",
        title: "약속 확인하고 마치기",
        goal: "정한 일정과 준비할 자료를 짧게 확인합니다.",
        spokenText:
          "정한 날짜와 시간에 말씀드린 방식으로 뵙겠습니다. 준비 가능한 증권이나 보험 앱 화면이 있으면 함께 확인하고, 일정이 달라지면 이 번호로 알려 주세요. 오늘 통화 감사합니다.",
        questions: ["정한 날짜·시간·방식이 모두 맞나요?"],
        checklist: ["일정 재확인", "준비물은 가능한 범위로 안내"],
        objectionKeys: ["no-policy", "document-privacy", "no-more-contact"],
      },
    ],
    nextActions: [
      {
        key: "open-schedule",
        label: "일정 열기",
        description: "정한 약속을 일정에서 확인해요.",
        target: "schedule",
      },
      {
        key: "open-booking-copy",
        label: "예약 안내 문구 열기",
        description: "고객에게 보낼 짧은 예약 문구를 골라요.",
        target: "quick-appointment",
      },
      {
        key: "end-call",
        label: "연락 종료",
        description: "고객 상태와 연락 결과를 상세 화면에서 정리해요.",
        target: "end-call",
      },
    ],
  },
  {
    key: "first-coverage-review",
    title: "첫 대면 보장 점검",
    description:
      "고객이 궁금한 항목부터 실제 증권으로 확인하고, 자료 등록과 다음 상담을 정해요.",
    durationLabel: "약 20분",
    goal: "확인할 자료와 다음 상담 행동을 고객과 함께 정하기",
    startCondition: "상담 목적과 예상 시간을 먼저 설명하고 시작해요.",
    steps: [
      {
        key: "meeting-disclosure",
        title: "신분과 상담 목적 다시 밝히기",
        goal: "첫 만남에서 신분과 보험 상담 목적을 다시 확인합니다.",
        spokenText:
          "{고객명} 고객님, 처음 뵙겠습니다. {소속직책} {설계사명}입니다. 오늘은 가입하신 보험을 함께 확인하고, 필요하시면 보험 상품을 안내드리는 상담을 위해 뵈었습니다. 상담을 시작해도 될까요?",
        questions: ["지금 상담을 시작해도 될까요?"],
        checklist: ["성명·소속", "보험 상담·안내 목적", "상담 시작 허락"],
        objectionKeys: ["low-interest", "existing-planner", "no-more-contact"],
        requiresSalesDisclosure: true,
      },
      {
        key: "meeting-scope",
        title: "오늘 범위와 시간 맞추기",
        goal: "상담 시간과 오늘 확인할 범위를 함께 정합니다.",
        spokenText:
          "오늘은 약 20분 동안 고객님이 궁금한 부분을 듣고, 실제 증권에서 확인할 순서를 정하겠습니다. 먼저 궁금한 점을 보고, 시간이 더 필요하면 다음 일정을 따로 정해도 괜찮을까요?",
        questions: ["오늘 꼭 확인하고 싶은 한 가지가 있나요?"],
        checklist: ["예상 시간", "오늘 확인 범위", "연장하지 않고 다음 일정 선택"],
        objectionKeys: ["busy-now", "no-decision-today"],
      },
      {
        key: "meeting-priority",
        title: "고객의 궁금증부터 듣기",
        goal: "준비한 설명보다 고객의 질문을 먼저 둡니다.",
        spokenText:
          "가입하신 보험을 생각할 때 가장 먼저 확인하고 싶은 부분은 무엇인가요? 월 보험료, 보장 내용, 갱신 안내 중 하나부터 말씀해 주셔도 됩니다.",
        questions: [
          "월 보험료와 보장 내용 중 무엇이 먼저 궁금하세요?",
          "최근 받은 갱신이나 계약 안내가 있나요?",
        ],
        checklist: ["고객의 표현을 바꾸지 않고 우선순위 기록"],
        objectionKeys: ["premium-concern", "low-interest"],
      },
      {
        key: "meeting-life-context",
        title: "필요한 범위만 상황 확인하기",
        goal: "질문 이유를 설명하고 고객이 답할 범위를 고르게 합니다.",
        spokenText:
          "가입 내용을 보는 데 필요한 범위에서 직업이나 가족 구성처럼 최근 달라진 점을 확인해도 될까요? 답하고 싶은 항목만 말씀해 주시면 됩니다.",
        questions: [
          "보험 가입 뒤 직업이나 가족 구성에 달라진 점이 있나요?",
          "이번 점검에서 빼고 싶은 질문이 있나요?",
        ],
        checklist: ["질문 이유 설명", "선택 가능성 안내", "필요한 항목만 확인"],
        coachNote:
          "주소, 결혼, 자녀를 친분 질문처럼 연달아 묻지 않습니다. 상담에 필요한 이유가 있는 항목만 선택합니다.",
        objectionKeys: ["source-and-privacy", "document-privacy"],
      },
      {
        key: "meeting-current-policies",
        title: "현재 보험과 납입 내용 확인하기",
        goal: "기억과 실제 자료를 구분해 현재 상태를 정리합니다.",
        spokenText:
          "먼저 가입한 보험사와 월 보험료, 납입기간을 기억나는 범위에서 적어보겠습니다. 정확한 내용은 증권이나 보험 앱 화면에서 다시 확인하겠습니다.",
        questions: [
          "현재 기억나는 월 보험료는 어느 정도인가요?",
          "납입기간이나 갱신 안내를 받은 보험이 있나요?",
        ],
        checklist: ["고객 기억은 임시 메모", "정확한 값은 실제 자료에서 재확인"],
        objectionKeys: ["no-policy", "premium-concern", "existing-planner"],
      },
      {
        key: "meeting-fact-review",
        title: "실제 증권에서 사실 확인하기",
        goal: "보장 이름과 금액뿐 아니라 지급 조건과 제한도 함께 봅니다.",
        spokenText:
          "이제 증권에 적힌 보험료, 납입기간, 보장 항목과 금액을 차례로 보겠습니다. 같은 이름처럼 보여도 지급 조건이나 제한이 다를 수 있어 실제 자료의 문구를 함께 확인하겠습니다.",
        questions: [
          "보험료와 보장 항목 중 어느 표부터 볼까요?",
          "설명이 더 필요한 용어가 있나요?",
        ],
        checklist: ["보험료", "납입기간", "보장 항목·금액", "지급 조건·제한"],
        objectionKeys: ["premium-concern", "decide-later"],
      },
      {
        key: "meeting-consent",
        title: "동의받고 자료 등록 안내하기",
        goal: "자료의 목적과 범위를 먼저 설명하고 고객이 직접 동의하게 합니다.",
        spokenText:
          "인파에서 증권 내용을 정리하려면 먼저 고객님께 자료 사용 목적과 항목을 안내하고 동의를 받아야 합니다. 안내 링크를 직접 확인한 뒤 동의하신 자료만 등록하겠습니다. 링크를 지금 볼까요, 다음 일정 전에 보내드릴까요? 오늘은 여기서 마치셔도 됩니다.",
        questions: [
          "동의 안내 링크를 지금 확인할까요?",
          "자료는 직접 등록할지 함께 볼지 어떤 방식이 맞으세요?",
        ],
        checklist: ["고객 본인 동의", "동의한 범위만 등록", "자료 전달 방법 확인"],
        objectionKeys: ["document-privacy", "no-policy", "decide-later"],
      },
      {
        key: "meeting-summary",
        title: "확인한 내용과 다음 일정 정하기",
        goal: "오늘 확인한 사실과 남은 항목을 나누고 다음 행동을 하나 정합니다.",
        spokenText:
          "오늘은 현재 보험료와 확인할 보장 항목을 여기까지 정리했습니다. 다음에는 등록된 증권을 함께 볼지, 필요한 질문부터 더 확인할지 정할 수 있습니다. 일정에서 다음 상담을 잡을까요, 정리한 내용을 먼저 받아보실까요, 오늘은 여기서 마칠까요?",
        questions: [
          "다음에는 증권 확인과 질문 정리 중 무엇부터 할까요?",
          "다음 일정을 지금 정할까요?",
        ],
        checklist: ["확인한 사실", "남은 항목", "다음 행동 하나"],
        objectionKeys: ["decide-later", "no-decision-today", "no-more-contact"],
      },
    ],
    nextActions: [
      {
        key: "open-customer-analysis",
        label: "고객 분석 열기",
        description: "선택한 고객의 증권 등록과 분석을 이어가요.",
        target: "customer-analysis",
      },
      {
        key: "open-followup-schedule",
        label: "다음 일정 열기",
        description: "다음 상담 일정을 정해요.",
        target: "schedule",
      },
      {
        key: "open-result-copy",
        label: "정리 문구 열기",
        description: "오늘 확인한 내용을 보낼 빠른 문구를 골라요.",
        target: "quick-result",
      },
    ],
  },
];

export function renderGuidedTalk(
  body: string,
  variables: GuidedTalkVariables,
): string {
  const referrer = (variables.referrer || "").trim();
  const withReferrer = body
    .replace(
      /\{소개자명\}\s*님 소개로/g,
      referrer ? `${referrer} 님 소개로` : "소개를 받아",
    )
    .replace(
      /\{소개자명\}\s*님께서/g,
      referrer ? `${referrer} 님께서` : "소개해 주신 분께서",
    )
    .replace(
      /\{소개자명\}\s*님/g,
      referrer ? `${referrer} 님` : "소개해 주신 분",
    )
    .replace(/\{소개자명\}/g, referrer || "소개해 주신 분");
  return renderCopy(withReferrer, variables);
}

export function talkScriptsHref(
  customerId: number,
  options: {
    mode?: "guided" | "quick";
    playbook:
      | "referred-customer-first-call"
      | "first-coverage-review";
  },
): string {
  const params = new URLSearchParams({ customerId: String(customerId) });
  if (options.mode === "quick") params.set("mode", "quick");
  params.set("playbook", options.playbook);
  return `/scripts?${params.toString()}`;
}
