# 인파 디자인 리팩토리 — 계획 + 분석 (Phase 0)

> 브랜치: `feat/design-refactor` (기존 작업 브랜치 `feat/benchmark-ui-revamp`와 분리)
> 목표: 기능·데이터·라우팅은 그대로 두고, `docs/ui-redesign-spec.md`가 추구하는 시각 언어
> (큰 숫자 · 컬러 아이콘 뱃지 · 컬러 파이프라인 · 넉넉한 여백/라운드)를 대시보드 + 앱 전반에 적용.

## 0. PM이 잠든 사이 내가 내린 2가지 결정 (지시 우선)

1. **색은 절대 안 바꿈.** PM 지시("파랑·빨강·노랑·초록 절대 바꾸지 마")가 스펙 문서보다 우선.
   스펙은 brand `#2E50F0` 등 *다른* 헥스를 제안했지만 **전부 무시**하고 우리 4색을 유지:

   | 색 | 유지값(우리 것) | 토큰 |
   |---|---|---|
   | 파랑 | `#2F58DC` | `--brand` |
   | 초록 | `#6AAC72` | `--success` |
   | 노랑 | `#E7B23E` | `--warning` |
   | 빨강 | `#C73E38` | `--danger` |

   스펙의 "보조 토큰"(canvas, ink, soft 틴트, 단계색)만 **우리 4색에서 다시 유도**해 적용.

2. **상단 네비 유지(사이드바 전환 안 함).** 첨부 이미지는 사이드바지만, 스펙의 1번 규칙이 "상단 유지"이고
   사이드바는 §8 *선택* 항목(별도 플랜 권장). 27개 페이지 레이아웃을 무인 상태로 갈아엎는 건 리스크가 커서
   **상단 네비를 리스타일(액티브 pill·sticky)** 하고, 사이드바는 아침 보고서에서 "원하면 yes" 옵션으로 제시.

## 1. 현재 구조 분석 (스펙 Phase 0 질문 답)

- **대시보드 라우트:** `inpa_fe/app/home/page.tsx` (`"use client"`, 614줄). 인증 가드 `useAuthGuard`.
- **컴포넌트 트리:**
  - `components/app-nav.tsx` (상단 sticky 네비 + 알림벨 + 아바타) → 내부에서 `components/bottom-nav.tsx`(모바일 하단탭).
  - `components/ui.tsx` → `Card`, `StatCard`(KPI 5개), `ReminderCard`, `CustomerAvatar`.
  - `components/charts.tsx` → `BarChart`(월별추이), `DonutChart`(유지현황), `CompareBarChart`, `LineCompareChart`.
  - `components/self-diagnosis-share.tsx` → 무료 보장점검 링크 카드.
  - 나머지(인사·파이프라인·유지율·목표·환수레이더·캘린더·오늘일정)는 `page.tsx` 인라인 JSX.
- **섹션 매핑:** 상단네비=app-nav.tsx · 인사+날짜=page 258-264 · 통계카드5=ui.tsx StatCard(page 273-280) ·
  영업단계=page 283-304 · 월별추이=charts BarChart(page 307-334) · 유지현황도넛=charts DonutChart(page 335-358) ·
  계약유지율=page 363-391 · 이번달목표=page 394-462 · 환수레이더=page 466-491 · 캘린더=page 518-579 ·
  오늘일정=page 581-609.
- **색/폰트/간격/라운드:** 전부 **Tailwind v4 + `app/globals.css`**. `tailwind.config.ts` 없음.
  토큰은 `:root` CSS 변수 → `@theme inline`로 Tailwind 유틸 생성(`bg-brand`, `text-success`…).
  폰트 = Pretendard(CDN link, layout.tsx). 라운드/그림자는 유틸 클래스(rounded-2xl/shadow-sm) 사용.
  다크모드는 어드민(`.theme-system`)만 — 서비스 페이지엔 `dark:` 금지(가드레일).
- **데이터 패칭:** 서버컴포넌트 아님. 클라이언트 `useEffect` + `lib/api.ts`의 plain `fetch`. React Query/SWR 미사용.
  대시보드: `getDashboard()`→`/dashboard/`, `getDashboardInsights()`→`/dashboard/insights/`, `getChurnRadar()`,
  `listCustomers()`, `listMeetings()`, `listScheduleItems()`. 증감률(delta)은 현재 **FE에서** trend로 계산(momDelta).

## 2. 작업 순서 (스펙 권장 = 토큰→네비→카드→파이프라인→차트→나머지)

1. **토큰 중앙화**(globals.css): canvas, soft 틴트 별칭(brand-soft/pos/neg/warn), `shadow-card` 유틸. 4색 유지.
2. **공통 프리미티브**(ui.tsx): Card(shadow-card), `SectionTitle` 신설, `StatCard` 리스타일(아이콘 뱃지+큰 숫자+델타 화살표).
3. **상단 네비**(app-nav.tsx): 액티브 pill(`bg-brand-soft text-brand rounded-full`).
4. **대시보드**(home/page.tsx): 인사 강조, 통계카드 아이콘, 컬러 파이프라인+화살표, 하단 퀵액션 바, 목표/환수/캘린더 정돈.
5. **차트**(charts.tsx): 하드코딩 `#3b82f6`(평균선) → 토큰.
6. **BE 보조**(dashboard 시리얼라이저): `delta_pct`/`delta_dir` 추가(가산만, FE 폴백 유지).
7. **앱 전반 전파**: Card/StatCard/Nav 변경이 55개 import처로 자동 캐스케이드 + 주요 페이지 개별 정돈.
8. **빌드/타입체크 → 스크린샷 → 보고서.**

## 3. 안전장치
- 기존 컴포넌트 수정만(신규 생성 최소화: SectionTitle 1개만 추가).
- StatCard는 `icon`/`tone` **옵셔널** → 다른 곳 사용 없음(홈 전용)이라 안전, 그래도 하위호환.
- 각 단계 후 `npm run build`(타입체크 겸함)로 게이트.
- 머지·배포 안 함(프로덕션은 명시 승인 필요). 아침 검수용으로 브랜치에만 둠.
