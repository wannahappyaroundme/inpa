export function formatCalendarDate(value?: string | null): string {
  if (!value) return "-";
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);
  if (!year || !month || !day) return "-";
  return `${year}년 ${month}월 ${day}일`;
}

export function formatWon(value?: number): string {
  return `${Number(value ?? 0).toLocaleString("ko-KR")}원`;
}
