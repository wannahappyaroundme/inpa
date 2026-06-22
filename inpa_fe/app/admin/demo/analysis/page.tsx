import { Card, statusMeta } from "@/components/ui";
import { heatmapMock, type CovStatus } from "@/lib/mock";

const LEGEND: CovStatus[] = ["over", "enough", "short", "none"];
const SUMMARY: [string, string][] = [
  ["월 보험료", "12.4만원"],
  ["총 납입 보험료", "1,488만원"],
  ["보험 건수", "3건"],
  ["분석 모드", "기준 적용"],
];

export default function DemoAnalysis() {
  return (
    <div>
      <div className="text-[13px] text-ink3">담보 한눈표 · 설계사 도구</div>
      <h1 className="text-[22px] font-extrabold text-ink">보장 분석 — 김보장님</h1>

      <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
        {SUMMARY.map(([l, v]) => (
          <Card key={l} className="px-4 py-3.5">
            <div className="text-[12px] text-ink3">{l}</div>
            <div className="mt-1 text-[18px] font-extrabold text-ink">{v}</div>
          </Card>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap gap-3 text-[12px] text-ink3">
        {LEGEND.map((s) => {
          const m = statusMeta(s);
          return (
            <span key={s} className="inline-flex items-center gap-1.5">
              <span className={`w-2.5 h-2.5 rounded-full ${m.dot}`} />
              {m.label}
            </span>
          );
        })}
      </div>

      <div className="mt-4 space-y-3">
        {heatmapMock.map((cat) => (
          <Card key={cat.category} className="p-4">
            <div className="text-[13px] font-bold text-ink mb-2">{cat.category}</div>
            <div className="flex flex-wrap gap-2">
              {cat.items.map((it) => {
                const m = statusMeta(it.status);
                return (
                  <span
                    key={it.name}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-[13px] text-ink"
                  >
                    <span className={`w-2 h-2 rounded-full ${m.dot}`} />
                    {it.name}
                    <span className={`text-[11px] font-semibold ${m.text}`}>{m.label}</span>
                  </span>
                );
              })}
            </div>
          </Card>
        ))}
      </div>

      <p className="px-1 py-5 text-[12px] leading-5 text-muted">
        이 자료는 입력된 증권 정보를 정리한 거예요. 보장이 충분한지 등 <b className="font-semibold text-ink3">판단과 권유는
        담당 설계사</b>를 통해 확인하세요. 최종 책임은 설계사에게 있습니다.
      </p>
    </div>
  );
}
