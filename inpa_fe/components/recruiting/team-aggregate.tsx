import { Card } from "@/components/ui";
import type { TeamRecruitingSummary } from "@/lib/api";

export function TeamAggregate({
  data,
  planMessage,
  errorMessage,
  onRetry,
}: {
  data: TeamRecruitingSummary | null;
  planMessage: string | null;
  errorMessage: string | null;
  onRetry: () => void;
}) {
  if (planMessage) {
    return (
      <Card className="p-5 text-center">
        <h2 className="text-[16px] font-extrabold text-ink">팀 영입 흐름도 함께 보기</h2>
        <p className="mt-2 text-[13px] leading-6 text-ink2">{planMessage}</p>
      </Card>
    );
  }
  if (errorMessage) {
    return (
      <Card className="p-5 text-center">
        <h2 className="text-[16px] font-extrabold text-ink">팀 영입 흐름</h2>
        <p role="alert" className="mt-2 text-[13px] leading-6 text-ink2">{errorMessage}</p>
        <button type="button" onClick={onRetry} className="mt-3 min-h-11 rounded-xl bg-brand px-4 text-[13px] font-bold text-white">팀 합계 다시 불러오기</button>
      </Card>
    );
  }
  if (!data) return null;

  return (
    <section aria-labelledby="team-recruiting-title" className="space-y-3">
      <div>
        <h2 id="team-recruiting-title" className="text-[17px] font-extrabold text-ink">팀 영입 흐름</h2>
        <p className="mt-1 text-[12px] text-ink3">공유에 동의한 팀원의 합계만 보여요.</p>
      </div>
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: "진행 중", value: data.team_totals.active_recruiting },
          { label: "이번 달 합류", value: data.team_totals.joined_this_month },
          { label: "정착 확인", value: data.team_totals.settlement_due },
        ].map((item) => (
          <Card key={item.label} className="p-3 text-center sm:p-4">
            <p className="text-[10px] font-semibold text-ink3 sm:text-[11px]">{item.label}</p>
            <p className="mt-2 text-[20px] font-extrabold tabular-nums text-ink sm:text-[24px]">{item.value}</p>
          </Card>
        ))}
      </div>
      <Card className="overflow-hidden">
        <div className="divide-y divide-line">
          {data.members.map((member) => (
            <div key={member.user_id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-4 py-3">
              <p className="truncate text-[13px] font-bold text-ink">{member.display_name}</p>
              <p className="text-right text-[11px] text-ink3">
                진행 {member.active_recruiting} · 합류 {member.joined_this_month} · 확인 {member.settlement_due}
              </p>
            </div>
          ))}
          {data.members.length === 0 && <p className="px-4 py-8 text-center text-[12px] text-ink3">팀원이 공유를 선택하면 합계에 바로 반영돼요.</p>}
        </div>
        {data.not_shared_count > 0 && <p className="border-t border-line bg-surface2 px-4 py-3 text-[11px] text-ink3">공유하지 않은 팀원 {data.not_shared_count}명</p>}
      </Card>
    </section>
  );
}
