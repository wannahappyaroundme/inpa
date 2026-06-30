// 인파 로고 — iP 모노그램. P의 세로획 = i의 기둥, 위의 빨간 점 = i의 점(신호등).
// (구) 트윈아크 로고 대체. 서버 컴포넌트 안전(훅 없음).
//
// live=true → 빨간 점에서 방사형 '신호(ping)'가 퍼지며 옅어짐(인터랙션·분석·로딩 상태용).
//   keyframes는 globals.css(.inpa-ping)에 정의. prefers-reduced-motion 시 자동 정지.

type Props = {
  size?: number;
  live?: boolean;
  className?: string;
  title?: string;
  /** P 색(기본 파랑) — 어두운 배경에선 "#FFFFFF" */
  pColor?: string;
  /** true → 링을 한 겹 더(3겹) 띄워 신호가 더 촘촘히 퍼짐(로딩 화면 등 강조용). live와 함께 사용. */
  intense?: boolean;
};

export function InpaMark({
  size = 24,
  live = false,
  className = "",
  title = "인파",
  pColor = "#1E40C4",
  intense = false,
}: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      className={className}
      role="img"
      aria-label={title}
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* P = i의 기둥 겸용 (세로획 + 보울) */}
      <path
        d="M16.5 41 V15.5 H25 A7 7 0 0 1 25 29.5 H16.5"
        fill="none"
        stroke={pColor}
        strokeWidth="7.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* 신호(ping) — 점에서 방사형으로 퍼지며 옅어짐(신호등 느낌) */}
      {live && (
        <>
          <circle className="inpa-ping" cx="16.5" cy="5.05" r="3.9" fill="#DC2626" />
          <circle className="inpa-ping inpa-ping-2" cx="16.5" cy="5.05" r="3.9" fill="#DC2626" />
          {intense && (
            <circle className="inpa-ping inpa-ping-3" cx="16.5" cy="5.05" r="3.9" fill="#DC2626" />
          )}
        </>
      )}
      {/* i의 점 (신호등 빨강) */}
      <circle cx="16.5" cy="5.05" r="3.9" fill="#DC2626" />
    </svg>
  );
}
