type CalendarDate = { year: number; month: number; day: number };

const DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

function daysInMonth(year: number, month: number): number {
  if (month === 2) {
    const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
    return leapYear ? 29 : 28;
  }
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
}

function parseCalendarDate(value: string | Date): CalendarDate | null {
  if (value instanceof Date) {
    if (Number.isNaN(value.getTime())) return null;
    return {
      year: value.getUTCFullYear(),
      month: value.getUTCMonth() + 1,
      day: value.getUTCDate(),
    };
  }

  const match = DATE_PATTERN.exec(value);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) return null;
  return { year, month, day };
}

function compareCalendarDate(a: CalendarDate, b: CalendarDate): number {
  if (a.year !== b.year) return a.year - b.year;
  if (a.month !== b.month) return a.month - b.month;
  return a.day - b.day;
}

function addMonthsFromBirth(birthDate: CalendarDate, months: number): CalendarDate {
  const absoluteMonth = birthDate.year * 12 + birthDate.month - 1 + months;
  const year = Math.floor(absoluteMonth / 12);
  const month = absoluteMonth - year * 12 + 1;
  return {
    year,
    month,
    day: Math.min(birthDate.day, daysInMonth(year, month)),
  };
}

/**
 * 만나이에 마지막 생일부터 지난 완전한 달이 6개월 이상이면 1을 더한다.
 * 모든 비교는 달력 날짜로만 수행해 실행 환경의 시간대 영향을 받지 않는다.
 */
export function computeInsuranceAge(birthDate: string, asOf: string | Date): number | null {
  const birth = parseCalendarDate(birthDate);
  const reference = parseCalendarDate(asOf);
  if (!birth || !reference || compareCalendarDate(birth, reference) > 0) return null;

  let fullYears = reference.year - birth.year;
  const anniversary = addMonthsFromBirth(birth, fullYears * 12);
  if (compareCalendarDate(reference, anniversary) < 0) fullYears -= 1;

  const sixMonthAnniversary = addMonthsFromBirth(birth, fullYears * 12 + 6);
  return fullYears + (compareCalendarDate(reference, sixMonthAnniversary) >= 0 ? 1 : 0);
}
