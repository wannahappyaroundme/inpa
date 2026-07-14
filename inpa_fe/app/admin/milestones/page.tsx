"use client";

// 마일스톤 보드 — 2026-06-21 VC·규제·업계 21인 라운드테이블 결론을 실행 카드로 정리.
// 근거 문서: docs/strategy/2026-06-21-vc-regulator-council.md
// 비코드(현장검증·법무·사업자등록)는 PM 액션, 코드 항목은 상태(완료/진행/예정) 표시.
// 현재는 정적 데이터(추후 BE 연동 가능 — 다른 admin 페이지의 fetch 패턴과 동일하게 교체).

import { useAdminGuard } from "@/lib/useAdminGuard";
import { Card } from "@/components/ui";

type Track = "legal" | "product" | "validation" | "invest";
type Priority = "P0" | "P1" | "P2";
type Status = "done" | "doing" | "todo";
type Owner = "PM" | "개발" | "공동";

interface Milestone {
  id: string;
  track: Track;
  priority: Priority;
  status: Status;
  owner: Owner;
  title: string;
  detail: string; // 무엇을 해야 하나
  how: string; // 해결책 / 방법
}

const TRACKS: { key: Track; label: string; icon: string; desc: string }[] = [
  { key: "legal", label: "법무·규제", icon: "🛡️", desc: "배포·실데이터 전 반드시. 회사 존속급 리스크 차단." },
  { key: "product", label: "제품·코드", icon: "⚙️", desc: "안전 게이트와 핵심 동선. 일부는 오늘 코드로 완료." },
  { key: "validation", label: "검증·시장", icon: "🔍", desc: "매출 없이 시드를 설득할 증거. 현장에서 만든다." },
  { key: "invest", label: "투자·전략", icon: "💰", desc: "시드/프리A 준비. 증거 3종 패키징과 투자자 풀." },
];

const MILESTONES: Milestone[] = [
  // ── 법무·규제 ──
  {
    id: "L1", track: "legal", priority: "P0", status: "todo", owner: "PM",
    title: "개인사업자 등록 → 약관·처리방침 회사정보 기재",
    detail: "현재 예비창업이라 상호·대표자·CPO·연락처가 공란. 미기재 상태로 민감정보를 수집하면 PIPA·전자상거래법 위반.",
    how: "홈택스에서 개인사업자 등록(당일 가능) → terms/privacy에 상호·연락처·CPO 기재. 통신판매업신고는 결제 붙기 전.",
  },
  {
    id: "L2", track: "legal", priority: "P0", status: "todo", owner: "PM",
    title: "법무 의견서 2건 의뢰 (가장 ROI 높은 지출)",
    detail: "①셀프진단 리드 자동생성이 '무등록 모집·중개'에 해당하는지 ②증권기반 국외이전 동의 적법요건(개보법 §28-8).",
    how: "핀테크 전문 변호사에게 전면 자문 말고 '의견서 2건'만 의뢰 → 생사 리스크 8할 정리.",
  },
  {
    id: "L3", track: "legal", priority: "P0", status: "todo", owner: "공동",
    title: "Anthropic 무학습/무보존(DPA) 증빙 확보",
    detail: "처리방침의 '학습 미사용' 단정이 증빙 없으면 동의 자체 하자 + 표시광고법 위반 소지.",
    how: "Anthropic Console에서 학습 미사용·보존 설정 확인·DPA 확보 → 증빙되면 그대로, 안 되면 처리방침 문구를 사실 범위로 수정.",
  },
  {
    id: "L4", track: "legal", priority: "P0", status: "todo", owner: "PM",
    title: "법무 검토 시점 당기기: '첫 외부 실데이터 전'",
    detail: "'유료 출시 전'이 아니라 외부 트래픽이 처음 들어오기 전이 트리거. 결제 연동=전자금융·통신판매·법인설립 동시 발효.",
    how: "베타 오픈 일정에 법무 게이트를 앞단으로 배치. L1·L2 완료 = 이 게이트 통과의 핵심.",
  },
  {
    id: "L5", track: "legal", priority: "P1", status: "todo", owner: "공동",
    title: "§97 프레이밍 전환: '합법화/방패' → '가드레일'",
    detail: "'갈아타기를 합법화'로 팔면 비교표가 검사장에서 '회사가 승환영업을 조장했다'는 정황증거로 뒤집힘.",
    how: "랜딩·제품 카피를 '모집질서 가드레일이 내장된 도구(위반에 안 빠지게 막아줌)'로 변경. 같은 코드, 정반대 평가.",
  },
  {
    id: "L6", track: "legal", priority: "P1", status: "todo", owner: "개발",
    title: "graded(부족/충분) 판정 영구 동결 정책 명문화",
    detail: "기준선 출처 확정 전까지 graded는 OFF 유지(이미 baseline_source=null→neutral로 코드 강제됨). 정책 문서화 필요.",
    how: "dev 문서에 '출처·면책·법무 통과 전 graded·비교안내서·AI문자 fail-safe OFF' 정책을 명문화.",
  },

  // ── 제품·코드 ──
  {
    id: "P1c", track: "product", priority: "P0", status: "done", owner: "개발",
    title: "병력(민감정보) 베타 수집 차단 ✅",
    detail: "ANALYZE_MEDICAL_ENABLED=False(기본)로 병력 등록 API를 403 차단. AI는 증권 텍스트만 쓰므로 병력 미수집과 무관하게 동작.",
    how: "완료(2026-06-21). settings 플래그 + CustomerMedicalHistory create 게이트 + 테스트 2종. 법무 검토 후 True로 flip.",
  },
  {
    id: "P2c", track: "product", priority: "P0", status: "done", owner: "개발",
    title: "동의기록(ConsentLog) 보존: SET_NULL ✅",
    detail: "고객 삭제(파기) 시에도 동의 증거는 보존(처리방침상 5년 보관). 기존 CASCADE는 감사기록을 함께 소멸시켜 append-only와 모순.",
    how: "완료(2026-06-21). on_delete=SET_NULL + 마이그레이션 0003 + 보존 테스트. 고객 null 로그는 관리자 감사용으로만 잔존.",
  },
  {
    id: "P3c", track: "product", priority: "P0", status: "done", owner: "개발",
    title: "국외이전 동의 = 고객 본인 직접 동의 동선 ✅",
    detail: "설계사가 자기 화면에서 체크하는 현 구조는 대리동의 소지. 정식 안전화는 아키텍처 변경이라 플랜 합의 후 진행.",
    how: "완료(2026-07). OCR 업로드가 consent_overseas_at 없으면 412로 차단 + '동의 요청 링크(/c)'로 고객 본인이 직접 동의(토큰 기록). 설계사 대리동의(planner_attested)는 게이트를 열지 못하도록 서버 강제.",
  },
  {
    id: "P4c", track: "product", priority: "P1", status: "done", owner: "개발",
    title: "FE 병력 입력 UI 숨김 (플래그 연동) ✅",
    detail: "BE는 이미 차단(P1c). FE 폼이 남아 있으면 403만 받는 깨진 UX. 플래그 상태를 받아 입력 UI 자체를 숨김.",
    how: "완료(해당 없음). 확인 결과 FE에 병력 입력 UI 자체가 없어 숨길 대상이 없음. BE 403 게이트(ANALYZE_MEDICAL_ENABLED)만 유효. 향후 병력 입력을 도입하면 그때 플래그 연동 렌더 필요.",
  },
  {
    id: "P5c", track: "product", priority: "P1", status: "done", owner: "개발",
    title: "셀프진단 공개링크 noindex + 비용 가드 점검 ✅",
    detail: "익명 잠재고객 자동 리드화 = 무자격 모집 정조준 + Claude API 비용 폭주 위험.",
    how: "완료(2026-07). 공개 토큰 뷰 5종(/s·/b·/c·/d·/p) 전부 noindex 헤더 + refcode 본인해석 게이팅 + ScopedRateThrottle + refcode 일일 30건 상한 + 파일 5MB·이미지PDF 거부. (Claude 호출 사용량 로깅은 선택 잔여.)",
  },
  {
    id: "P6c", track: "product", priority: "P1", status: "todo", owner: "개발",
    title: "정규화 정확도 계측 + 정규형 토큰 전처리 (전처리 일부 완료)",
    detail: "fuzzy 매칭은 이미 구현됨(보고서 오류 정정). 진짜 할 일은 정확도 측정과 표기 정규화.",
    how: "전처리 일부 반영(2026-07: 괄호·갱신형·차수 토큰 제거). 남음: 상위 5개사 실약관 샘플로 precision/recall 측정 후 IR 자산화.",
  },
  {
    id: "P7c", track: "product", priority: "P1", status: "todo", owner: "공동",
    title: "베타 범위 축소: '16개 끄고 1개 루프'",
    detail: "게시판·판촉물·캘린더·KPI·관리직 대시보드는 PMF 신호를 흐리는 노이즈(다수 합의).",
    how: "남길 단일 동선 = 증권 업로드 → 담보 한눈표(정규화) → 셀프진단 인바운드. 나머지는 숨김/비활성.",
  },
  {
    id: "P8c", track: "product", priority: "P2", status: "done", owner: "개발",
    title: "정직성 카피 가드 자동 차단 ✅",
    detail: "'안전/심의완료/추천' 류 금지어가 사람 검수에만 의존하면 언젠가 샌다.",
    how: "완료(2026-07). inpa_fe/scripts/check-copy.js 가 렌더 문자열의 긴 줄표(대시)를 자동 차단 + CI 게이트(npm run lint:copy). 단어 기반 규칙은 정당한 부인문구 오탐이 커서 제외, RULES 배열로 확장 가능.",
  },
  {
    id: "P9c", track: "product", priority: "P2", status: "done", owner: "개발",
    title: "OCR 인식 실패 시 손입력 폴백 UX ✅",
    detail: "현직 설계사: '3번 실패하면 손입력으로 돌아간다.' 폴백 없으면 이탈.",
    how: "완료(2026-07). 인식 실패 배너에 '직접 입력으로 등록' 버튼 추가(기존 직접입력 모달 재사용). 부분 자동채움은 향후 개선 여지.",
  },

  // ── 검증·시장 ──
  {
    id: "V1", track: "validation", priority: "P0", status: "todo", owner: "PM",
    title: "설계사 30명 현장 인터뷰 + 매주 사용 행동로그",
    detail: "21인 전원 공통 지적: '코드는 진짜인데 검증이 0.' 매출 없이 시드를 설득할 최강 증거.",
    how: "본인/지인 증권으로 5분 콜드스타트 데모 → 30명 인터뷰 → 재방문·업로드·셀프진단 발송 행동로그 수집.",
  },
  {
    id: "V2", track: "validation", priority: "P1", status: "todo", owner: "PM",
    title: "유료 의향 LOI 3건 확보",
    detail: "'이거 없으면 일 못 한다'는 정성 + 지불 의사 신호.",
    how: "인터뷰 우호 설계사·소형 GA에서 유료의향 확인서(LOI) 3건.",
  },
  {
    id: "V3", track: "validation", priority: "P1", status: "todo", owner: "공동",
    title: "정규화 정확도 벤치마크 (IR 자산)",
    detail: "'쓸수록 정확해진다'를 말이 아니라 곡선으로. 해자 증거의 핵심.",
    how: "P6c 계측 결과를 매핑 수·커버 보험사·precision/recall 곡선으로 IR 자료화.",
  },

  // ── 투자·전략 ──
  {
    id: "I1", track: "invest", priority: "P1", status: "todo", owner: "PM",
    title: "시드/프리A 자료: 증거 3종 패키징",
    detail: "실제 고객지표 없이 설득할 3종: ①정규화 정확도 ②법무 의견서(규제 디리스킹) ③행동 로그.",
    how: "밸류 스토리 = '규제를 코드로 강제한 첫 진입자 + 중립 정규화 데이터 자산 + 영업 워크플로우 락인.'",
  },
  {
    id: "I2", track: "invest", priority: "P2", status: "todo", owner: "PM",
    title: "투자자 타겟 리스트",
    detail: "현 TAM·1인팀 단계에 맞는 풀. 거대시장형(알토스·a16z)은 시장 재정의 전엔 미스핏.",
    how: "보험사 CVC·인슈어테크 전략투자(이해도 높음·제휴 경로), 앤틀러·프라이머(공동창업자 매칭).",
  },
  {
    id: "I3", track: "invest", priority: "P2", status: "todo", owner: "PM",
    title: "공동창업자(개발/도메인) 영입 검토",
    detail: "bus factor 1 + 비개발 + 법무 겸임은 규제 산업에서 거의 결격(다수 지적).",
    how: "앤틀러식 팀빌딩 또는 보험 도메인 공동창업자 영입으로 단일 의존 리스크 해소.",
  },
];

function PriorityBadge({ p }: { p: Priority }) {
  const map: Record<Priority, string> = {
    P0: "bg-danger text-white",
    P1: "bg-warning text-white",
    P2: "bg-surface2 text-ink3",
  };
  return <span className={`text-[10px] font-extrabold rounded-md px-1.5 py-0.5 ${map[p]}`}>{p}</span>;
}

function StatusBadge({ s }: { s: Status }) {
  const map: Record<Status, { cls: string; label: string }> = {
    done: { cls: "bg-success text-white", label: "완료" },
    doing: { cls: "bg-brand text-white", label: "진행" },
    todo: { cls: "bg-surface2 text-ink3", label: "예정" },
  };
  const m = map[s];
  return <span className={`text-[10px] font-bold rounded-full px-2 py-0.5 ${m.cls}`}>{m.label}</span>;
}

function OwnerChip({ o }: { o: Owner }) {
  return (
    <span className="text-[10px] font-semibold rounded-md px-1.5 py-0.5 bg-brand-soft text-brand">
      {o === "개발" ? "개발(코드)" : o}
    </span>
  );
}

export default function AdminMilestonesPage() {
  const ready = useAdminGuard();
  if (!ready) return null;

  const total = MILESTONES.length;
  const done = MILESTONES.filter((m) => m.status === "done").length;
  const p0open = MILESTONES.filter((m) => m.priority === "P0" && m.status !== "done").length;
  const p1open = MILESTONES.filter((m) => m.priority === "P1" && m.status !== "done").length;

  const STAT = [
    { label: "전체 항목", value: total, unit: "개" },
    { label: "완료", value: done, unit: "개" },
    { label: "P0 남음", value: p0open, unit: "개", warn: true },
    { label: "P1 남음", value: p1open, unit: "개" },
  ];

  return (
    <div className="max-w-5xl">
      <div className="mb-6">
        <h1 className="text-[22px] font-extrabold text-ink">마일스톤</h1>
        <p className="text-[13px] text-ink3 mt-1">
          2026-06-21 VC·규제·업계 21인 라운드테이블 결론을 실행 카드로 정리.{" "}
          <span className="text-ink2">근거: <code className="text-[12px]">docs/strategy/2026-06-21-vc-regulator-council.md</code></span>
        </p>
      </div>

      {/* 요약 스트립 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-7">
        {STAT.map((s) => (
          <Card key={s.label} className="px-4 py-3.5">
            <div className="text-[12px] text-ink3">{s.label}</div>
            <div className="mt-1 flex items-baseline gap-1">
              <span className={`text-[26px] font-extrabold tnum ${s.warn && s.value > 0 ? "text-danger" : "text-ink"}`}>
                {s.value}
              </span>
              <span className="text-[13px] text-ink3">{s.unit}</span>
            </div>
          </Card>
        ))}
      </div>

      {/* 트랙별 카드 */}
      <div className="space-y-8">
        {TRACKS.map((t) => {
          const items = MILESTONES.filter((m) => m.track === t.key);
          return (
            <section key={t.key}>
              <div className="flex items-baseline gap-2 mb-3">
                <h2 className="text-[16px] font-bold text-ink">
                  <span className="mr-1.5">{t.icon}</span>{t.label}
                </h2>
                <span className="text-[12px] text-ink3">{t.desc}</span>
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {items.map((m) => (
                  <Card key={m.id} className={`p-4 ${m.status === "done" ? "opacity-80" : ""}`}>
                    <div className="flex items-center gap-1.5 mb-2 flex-wrap">
                      <PriorityBadge p={m.priority} />
                      <StatusBadge s={m.status} />
                      <OwnerChip o={m.owner} />
                      <span className="text-[11px] text-muted ml-auto tnum">{m.id}</span>
                    </div>
                    <h3 className="text-[14px] font-bold text-ink leading-snug">{m.title}</h3>
                    <p className="text-[12.5px] text-ink2 mt-1.5 leading-relaxed">{m.detail}</p>
                    <div className="mt-2.5 rounded-xl bg-surface2 px-3 py-2">
                      <span className="text-[11px] font-bold text-brand">해결책 </span>
                      <span className="text-[12px] text-ink2 leading-relaxed">{m.how}</span>
                    </div>
                  </Card>
                ))}
              </div>
            </section>
          );
        })}
      </div>

      <p className="mt-8 text-[12px] text-muted leading-5">
        ※ 본 보드는 토론 결론 기반 권고이며, 규제·법무 항목은 정식 법무 검토로 확정해야 합니다.
        코드 완료 항목(✅)은 2026-06-21 적용, 나머지는 우선순위(P0→P1→P2) 순으로 진행하세요.
      </p>
    </div>
  );
}
