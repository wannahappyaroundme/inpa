# Spec: FE 도달·신뢰 묶음 — 카톡 미리보기(#20) + SEO 기본(#22) + 화면 상태 정리(#21) + 감사 low 정리

## A. 카톡/OG 링크 미리보기 (#20 — 정적 우선, per-token 없음)
1. 공개 토큰 라우트 5종(b/d/p/c/s)의 `layout.tsx`에 라우트별 **정적** metadata: title/description을 고객 대면 문구로(예: /b '상담 시간 고르기 · 인파', desc '편한 시간을 직접 골라 주세요.'; /d '내 보험, 지금 상황에 맞을까요?', desc '1분이면 무료로 확인할 수 있어요.'). OG 이미지는 기존 전역 `opengraph-image.jpg` 재사용(새 에셋 0). 기존 s/b/c/d layout의 robots noindex 유지.
2. **/p에 robots noindex meta 추가**(다른 4종과 동일 — 감사 low 픽스; layout.tsx 신설).

## B. SEO 기본기 (#22)
1. `app/robots.ts`: 허용 = 랜딩·legal·data-policy, 차단 = /s /b /c /d /p /admin /api. `app/sitemap.ts`: 랜딩+legal 3페이지만.
2. 죽은 도메인 정리: `app/layout.tsx` SITE_URL 폴백 → `https://www.inpa.kr`; `components/booking-settings.tsx` 예시 링크 → `https://www.inpa.kr/b/…`.

## C. 화면 상태 정리 (#21 — 무음 실패 제거)
1. `/home`: 로더들의 `.catch(() => null/[])` 무음 처리 → 실패 플래그 수집, 하나라도 실패 시 대시보드 상단에 컴팩트 배너 1개("일부 정보를 못 불러왔어요.") + '다시 시도' 버튼(전체 로더 재실행). 카드별 개별 배너 금지(§6 소음 방지).
2. 히트맵 제로 상태 구분: 보험이 1건 이상인데 모든 담보 held=0이면 "등록된 보험에서 담보를 아직 읽지 못했어요. 증권을 다시 올리거나 직접 입력으로 채울 수 있어요." 안내(보험 0건의 기존 빈 상태와 구분). 판정어 0.
3. 401 우회 픽스(감사 low): `lib/api.ts`의 수제 fetch 3곳(uploadBusinessCard·deleteCustomer·uploadInsuranceOcr)이 request()와 동일한 401 처리(토큰 제거+/login?session=expired)를 타도록 공통 헬퍼로 통일.
4. 바텀내비 더보기 시트 배지: 정의만 되고 렌더 안 되던 `l.badge`를 시트 링크에 표시(PR#47 문서 약속 이행).

## Redlines / Tests
- FE 전용(BE 무변경, 마이그레이션 0). 카피 레드라인 전부 적용. `npm run build` + `lint:copy` 그린. robots/sitemap은 build 산출 확인. /home 재시도 동작은 코드 리뷰로 검증(런타임 테스트 러너 없음 — 리뷰어가 상태 흐름 추적).
