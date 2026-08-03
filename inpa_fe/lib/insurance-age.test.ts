import { describe, expect, it } from "vitest";

import { computeInsuranceAge } from "@/lib/insurance-age";

describe("보험나이 공용 계산", () => {
  it.each([
    ["2000-01-31", "2026-07-30", 26, "6개월 하루 전"],
    ["2000-01-31", "2026-07-31", 27, "정확히 6개월"],
    ["2000-08-31", "2026-02-27", 25, "월말 상령일 하루 전"],
    ["2000-08-31", "2026-02-28", 26, "짧은 달의 월말 상령일"],
    ["2000-02-29", "2025-08-28", 25, "윤년 생일 상령일 하루 전"],
    ["2000-02-29", "2025-08-29", 26, "윤년 생일 상령일"],
    ["2000-08-04", "2026-08-04", 26, "오늘이 생일"],
  ] as const)("%s → %s는 %s세다 (%s)", (birthDate, asOf, expected, _label) => {
    expect(computeInsuranceAge(birthDate, asOf)).toBe(expected);
  });

  it.each([
    ["", "2026-08-04"],
    ["2000-2-03", "2026-08-04"],
    ["2000-02-30", "2026-08-04"],
    ["2026-08-05", "2026-08-04"],
    ["2027-01-01", "2026-08-04"],
    ["2000-08-04", "not-a-date"],
  ] as const)("잘못된 날짜나 미래 생일 %s / %s는 계산하지 않는다", (birthDate, asOf) => {
    expect(computeInsuranceAge(birthDate, asOf)).toBeNull();
  });

  it("Date 기준일은 UTC 달력 날짜로 고정해 환경 시간대에 흔들리지 않는다", () => {
    expect(computeInsuranceAge("2000-01-31", new Date("2026-07-31T00:00:00.000Z"))).toBe(27);
  });
});
