# 공개 토큰 페이지 브랜드 로딩 스켈레톤 (프리런치 리뷰 #14) — Spec

> 2026-07-08. Phase 2 로드맵 ⑤(PM 지시 병행). Panel scope (#14): "Ordinary branded loading/skeleton states on /b, /d, /c, /s for a 2-5 second residual wait after the warm path lands. The 30-60s wake screen and auto-retry are EXPLICITLY KILLED." FE-only, presentation, 마이그레이션 0.

## 범위 (엄수)
- **하지 말 것:** 30~60초 웨이크 화면·자동 재시도(패널 kill). Render 콜드스타트 대응은 Starter 상시가동으로 이미 해결됨. 이건 **웜패스 도착 후 2~5초 잔여 대기**용 평범한 브랜드 스켈레톤일 뿐.
- **할 것:** /s·/b·/c 초기 로딩을 형태 일치 브랜드 스켈레톤으로 통일. /d는 폼이 즉시 렌더(fetch 블로킹 없음)라 초기 스켈레톤 불필요 — 제출 후 분석 화면은 이미 브랜드 처리 완료(레퍼런스).

## 현재 상태 (탐사)
- 4 페이지 전부 `"use client"` + `useEffect` fetch → `loading.tsx`(서버 Suspense)는 이 대기를 못 덮음. **client 스켈레톤이 정답.**
- `/s`(app/s/[token]/page.tsx:28 `ShareSkeleton`): 형태 일치 회색 `animate-pulse` 블록 있음(브랜드 없음).
- `/b`(app/b/[token]/page.tsx:106) · `/c`(app/c/[token]/page.tsx:141): 가운데 "불러오는 중…" 텍스트만(형태·브랜드 0).
- `/d`(app/d/[ref]/page.tsx:219): 제출 후 `analyzing` 화면 = **골드 스탠다드**(`InpaMark live intense` 펄스 + `LOADING_MSGS` 1.6s 회전). 초기 폼은 즉시 렌더.
- `InpaMark`(components/inpa-logo.tsx): 재사용 브랜드 로딩 컴포넌트. props `live`(핑 애니), `intense`(3번째 링), `size`, `pColor`, `dotColor`. `@keyframes inpaPing`(globals.css:36) + `prefers-reduced-motion` 이미 처리.
- 공유 `<Skeleton>` 컴포넌트 없음(페이지마다 로컬 중복). 토큰: `bg-surface2`(페이지) / `bg-surface`+`border-line`+`shadow-card`(카드) / `bg-line`(스켈레톤 블록) / `bg-accent-tint`(헤더). 라이트 고정.

## 설계 (FE only)

### 1. 공유 스켈레톤 프리미티브 `components/token-skeleton.tsx`
- `SkeletonBar({w,h,className})` · `SkeletonCard({className, children})` · `SkeletonRow` — `animate-pulse bg-line rounded` 기반 형태 블록.
- `TokenLoadingShell({children, brandMark=true})` — 공통 셸: `mx-auto max-w-md min-h-dvh bg-surface2` + `bg-accent-tint` 헤더 바 + (옵션) 상단/중앙에 **`InpaMark live` 작은 브랜드 마크** + 자식 스켈레톤. 은은한 브랜드감(과하지 않게 — /d analyzing의 intense 대형은 '분석 중' 전용, 여기선 작은 live 마크로 절제).
- 로딩 카피(선택, 절제): §6 톤 "불러오고 있어요"(현재 "불러오는 중…" 대체). em-dash 금지, 긍정 톤. `/d` `LOADING_MSGS` 레지스터 맞춤.

### 2. 페이지별 스켈레톤 조립(실제 레이아웃 미러)
- **`/s`**: 기존 `ShareSkeleton`을 공유 프리미티브로 리팩토링 + 작은 `InpaMark live` 브랜드 마크 추가 + sticky CTA 자리 블록 보강. 헤더·히어로·2열 요약·5행 담보 리스트 유지. **ContentProtect/Watermark는 스켈레톤에 미적용**(민감 내용 없음, 현행 유지).
- **`/b`**: "불러오는 중…" → 헤더 + 제목 2줄 + 상담방식 3열 pill + 빈시간 4~5행 블록 + CTA 바 블록.
- **`/c`**: "불러오는 중…" → 헤더 + 제목 2줄 + 동의 카드 3~4개(체크박스 행 + 2줄) + CTA 블록.
- **`/d`**: 초기 폼은 즉시 렌더라 **변경 없음**. (analyzing 화면 이미 브랜드 완료. 원하면 그 InpaMark+회전메시지 패턴을 프리미티브로 추출해 공유하되, 동작 불변.)

### 3. 배선
- 각 페이지의 기존 `loading`/`!info`/`!disclosure` 분기에서 새 스켈레톤 컴포넌트 반환(라우팅·Suspense 변경 0). getShareView/getBookingInfo/getConsentDisclosure 흐름 무변경.

### 검증
- FE `npm run build`(타입체크) + `npm run lint:copy`(em-dash·권유단어·준비중). BE 무변경.
- 4 페이지 라이트 고정 유지(dark: 금지). 고객 대면 카피 §6.
- reduced-motion 존중(InpaMark 이미 처리, animate-pulse는 OS 설정이 알아서 약화).
- 시각 확인: 로컬에서 각 페이지 로딩 분기가 브랜드 스켈레톤을 그리는지(테스트 러너 없음 → build + 코드 리뷰로 대체, 스켈레톤은 순수 프레젠테이션).

### 컴플라이언스
- 마이그레이션 0. BE 0. 고객 대면 4면 라이트·긍정·쉬운 말. 웨이크 화면/자동 재시도 절대 추가 안 함(패널 kill 준수).
