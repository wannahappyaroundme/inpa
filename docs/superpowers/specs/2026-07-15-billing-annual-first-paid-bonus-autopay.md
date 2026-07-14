# 요금제 개편 — 연구독 + 첫 유료 보너스 이벤트 + 자동결제 설계

Date: 2026-07-15 · Branch: feat/design-refactor · PM 확정(대화).
전제: 현재 베타 `FREE_TIER_UNLIMITED=True`(402 미발동), 결제 = 계좌이체 데스크(관리자 수동 구독 부여), KICC PG는 후속. 이 스펙은 그 위에 얹는다.

## PM 확정 결정
1. **첫 유료 결제 보너스**: 사용자당 **첫 유료 구독 1회에만 +1개월**(월·연 모두 적용). 이후 갱신은 정상. **관리자 토글 on/off**(기본 OFF).
2. **연구독**: 12개월을 **10개월 금액**으로 일시 결제 = 2개월 무료. Plus/Manager **199,000**, Super **399,000** (부가세 별도). 첫 유료 보너스가 연구독 첫 결제에도 적용 → 첫 연구독 = **13개월**.
3. **할인 강조**: '2개월 무료 · 약 17% 할인'을 요금표·업그레이드·랜딩에 크게. (17% = 2/12 = 16.7%)
4. **자동결제(정기결제/자동이체)**: 매달 자동 출금 — **설계 먼저(Phase B)**. 라이브는 PG 인증정보+법적 동의 필요.

## Phase A — 지금 구축 (수동 흐름 위, 확정)

### BE (billing, 마이그레이션 additive)
- `Plan.price_annual_krw` PositiveIntegerField null — 연 요금(부가세 별도). seed = `price_krw*10`(free=0). null이면 표시 시 `price_krw*10` 폴백.
- `Subscription` 신규 필드:
  - `billing_cycle` CharField choices `monthly`/`annual`, default `monthly`.
  - `first_paid_bonus_used` Bool default False — 첫 유료 보너스 소진 마커(사용자당 1회 보장).
  - **Phase B 토대(지금 필드만, 로직 후속)**: `auto_renew` Bool default False, `next_billing_at` DateTime null. (`pg_subscription_id`는 이미 존재.)
- `RuntimeConfig.first_paid_bonus_enabled` Bool default False — 이벤트 토글. `solo()` 기본값 env `FIRST_PAID_BONUS_ENABLED`(기본 False).
- **관리자 구독 부여**(`admin_console/views.py::AdminUserSubscriptionView.patch`): 시리얼라이저에 `billing_cycle` optional. 유료 플랜 부여 시:
  - 기준 만료 = now + (월=1개월 / 연=12개월). 월 연산은 `dateutil.relativedelta`(있으면) 또는 30일 근사, 있는지 확인 후 택1.
  - `first_paid_bonus_enabled` AND `not sub.first_paid_bonus_used` AND 유료(plan.code != free) → +1개월, `first_paid_bonus_used=True`.
  - `expires_at` = 계산값, `billing_cycle` 저장. 무료(free)는 expires_at=None 유지.
  - **하위호환**: `billing_cycle` 미지정 + 기존 무기한 유료(expires_at=None)는 그대로(단순 status 변경 시 만료 강제 안 함). cycle 지정 시에만 만료 계산.
- `credit.resolve_effective_plan`은 이미 만료 인지 → 변경 불필요(만료된 유료는 Free 폴백, 기존 로직).
- `billing/plans` 공개 API + admin serializer: `price_annual_krw`, `billing_cycle` 노출.
- 관리자 설정 토글: `GET/PATCH /admin/billing/mode/`에 `first_paid_bonus_enabled` 추가(기존 `free_tier_unlimited` 관례).

### FE
- **업그레이드 모달**(`components/upgrade-modal.tsx`): 월/연 토글. 연 선택 시 연 금액 + **'2개월 무료 · 약 17% 할인'** 배지 + 부가세 병기(연 199,000 → VAT 10% → 218,900 입금액 식, 기존 VAT 분해 규칙 재사용). 이벤트 ON이면 '첫 결제 시 한 달 더' 안내. 계좌이체 데스크 문구 유지.
- **랜딩 요금표**: www `app/page.tsx`(+ `components/landing-sections.tsx`) **와** new.inpa.kr `components/brand-story-sections.tsx`:
  - 기존 **'가입 시 무료 쿠폰/모바일 명함 쿠폰' 미보장 문구 제거** → **'첫 유료 결제 시 한 달 더(2개월 이용)'** 이벤트 문구 + **연구독 '2개월 무료·약 17% 할인'** 강조.
  - ⚠️ new.inpa.kr 파일은 다른 세션과 공유 → 편집+커밋 원자적, 다른 세션 파일(cinema-landing 등)은 미접촉.
- `lib/api.ts`/`adminApi.ts` 타입에 `price_annual_krw`·`billing_cycle` 추가. 관리자 구독 부여 UI(설계사 상세)에서 월/연 선택.

### 카피 정직성(§6)
- 이제 문구가 **실제 기능으로 뒷받침**됨(보너스=관리자 부여 시 자동 +1개월, 연구독=관리자 12개월 부여). 미보장 표현 제거. 부가세 별도 병기(전사 규칙). 조작 할인율 금지 — 17%는 2/12 실계산.

## Phase B — 자동결제(정기결제/자동이체) 설계 (라이브 전 준비물 필요)

**라이브 불가 사유**: PG 정기결제 계약·인증정보(빌링키/API 키), 법적 자동출금 동의가 있어야 함. 이 스펙은 설계만.

### 준비물(PM/외부)
- PG 정기결제 계약 + 빌링키 발급 권한 (기존 계획 = KICC 이지페이). 테스트/운영 API 키.
- 법적 **'정기결제 자동출금 동의'** 문구·화면(전자상거래법 정기과금 고지: 금액·주기·해지방법·다음 결제일). consent 버전 모듈에 편입.

### 설계 개요
- **빌링키 등록**: 고객이 카드/계좌 등록 → PG가 **빌링키** 발급 → 서버는 **빌링키 참조만 저장**(`pg_subscription_id`/`billing_key_ref`). **카드번호·계좌번호·CVC 절대 미저장**(PG 볼트만, 보안 레드라인).
- **정기 청구 잡**: 매일 KST 새벽, `auto_renew=True` AND `next_billing_at <= now` 구독을 PG 빌링키로 청구 → 성공 시 `expires_at`·`next_billing_at` 연장, 실패 시 dunning(재시도 3회+유예 → 실패 시 Free 강등, `resolve_effective_plan`이 자동 처리).
- **웹훅**: 결제 성공/실패/취소 수신 → 상태 갱신(멱등, 서명검증).
- **해지/환불**: 사용자 해지 → auto_renew=False, 만료일까지 유지. 환불 정책 별도.
- **계측**: 결제 이벤트 로그(금액·성공/실패 enum, 카드정보 미로그 — PII 레드라인).
- **모델**: Phase A에서 깐 `auto_renew`/`next_billing_at`/`pg_subscription_id` 재사용 + `billing_key_ref`·결제이력 테이블 신설.

### 산출물
Phase B는 별도 승인 후: 페르소나 카운슬(결제·법무·보안·PG 도메인) → Phase 0 계획 → PG 샌드박스 연동 → 법적 동의 → 라이브. **이 스펙 = Phase A 실행 + Phase B 설계 기록.**

## 검증(Phase A)
BE 전체 스위트 + 신규 테스트(연/월 만료 계산·첫 보너스 1회성·토글 OFF 시 미적용·연구독+보너스=13개월). FE build + lint:copy. 마무리: README/CLAUDE 갱신, 배포는 PM 승인.
