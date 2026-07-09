# 활성화 퍼널 계측 + UTM 캡처 + 인증 멈춤 알람 (프리런치 리뷰 #16) — Spec

> 2026-07-08. Phase 2 마지막 후보(PM 지시). Panel scope (#16): "Define activation (first policy analyzed + first customer-facing link sent within 7 days of signup); instrument signup → first customer → first analysis → first shared link as a cohort funnel in admin console on the analytics app; capture UTM/source at signup; alert when signups occur but email verifications flatline." partially built(NorthStarEvent 기반 존재).

## 핵심 설계 판단 (탐사 결과)
- **퍼널 4단계는 새 이벤트 배선 없이 기존 DB 타임스탬프로 전부 계산 가능**(이벤트는 누락 위험 → 타임스탬프가 더 견고):
  - 가입 = `User.date_joined`
  - 이메일 인증 = `Profile.email_verified_at`(이미 존재, 인증 시점 스탬프)
  - 첫 고객 = `MIN(Customer.created_at)` per owner
  - 첫 분석("first policy analyzed") = `MIN(CustomerInsurance.created_at)` per owner(`customer__owner`) — 증권 등록/OCR 결과가 곧 분석
  - 첫 공유 링크 = `MIN(Customer.share_sent_at)` per owner(공유 발급 시 스탬프됨)
- 따라서 `NorthStarEvent`에 SIGNUP/OCR 이벤트를 **새로 emit 하지 않는다**(OCR_UPLOAD/ANALYSIS_VIEW 죽은 상수는 그대로 둠). 온디맨드 집계(코드베이스 관례: AdminDashboardView·compute_funnel·AdminClaudeCostView 전부 실시간 계산).
- **활성화 정의**: (첫 분석) AND (첫 공유 링크)가 **가입 후 7일 이내**. `ACTIVATION_WINDOW_DAYS=7`(env).
- UTM/유입은 **없어서 신설 필요**(Profile 필드 + serializer + FE 캡처).
- 인증 멈춤 알람: `email_verified_at` vs `date_joined` 비교 job만 신설(데이터는 이미 있음).
- ★ 이름 충돌 주의: `dashboard/aggregation.py::compute_funnel`(설계사 영업단계 퍼널)과 다름 → `AdminActivationFunnelView`로 명명.

## 설계

### 1. BE — 활성화 퍼널 API (admin_console, IsAdmin)
`GET /api/v1/admin/activation-funnel/?days=30` (AdminClaudeCostView 패턴 복제, @inpa.local 제외):
- 창(days) 내 가입 코호트 대상 퍼널 단계별 인원 + 전환율:
  - `signup`(코호트 총원) → `verified`(email_verified_at not null) → `first_customer`(고객 1+) → `first_analysis`(보험 1+) → `first_share`(share_sent_at 있는 고객 1+) → `activated`(첫분석 AND 첫공유 모두 가입+7일 이내).
  - 각 단계 인원 + 직전 단계 대비 전환율(%). 사실 수치만(§6 판정어 금지).
- **UTM/유입 소스 분해**: `utm_source`(없으면 'direct') 별 가입·활성화 수.
- **활성화까지 평균 일수**(activated 코호트의 date_joined→활성화 시점 평균).
- 온디맨드 aggregation(저장 플래그 없음). 성능: 코호트 크기 작음(초기), N+1 회피 위해 per-owner MIN을 `.values('owner').annotate(Min(...))` 서브쿼리로.

### 2. BE — UTM/유입 캡처 (accounts 마이그레이션, additive)
- `Profile` 필드 3개: `utm_source`/`utm_medium`/`utm_campaign` CharField(max 60, blank, default ''). (단일 소스면 utm_source만 채워짐.)
- `RegisterSerializer`: optional `utm_source/utm_medium/utm_campaign` 수용(기존 affiliation/title 처럼), `create()`가 Profile에 저장. 미전달 = 빈 값(direct).
- 검증: 값 max 60 절단, 위험문자 제거(영숫자·`-_.` 만; 로그/표시 안전). PII 아님(캠페인 태그).

### 3. FE — UTM 첫터치 캡처 (라이트 고정, 시각 변화 0)
- `app/page.tsx`(www 랜딩) + 공개 진입점에 첫터치 캡처: `utm_source/medium/campaign` 쿼리파라미터가 있으면 `sessionStorage`('inpa_utm')에 **최초 1회만** 저장(덮어쓰기 안 함 = first-touch).
- `app/register/page.tsx`: 제출 시 sessionStorage('inpa_utm') + 현재 URL 쿼리파라미터를 읽어 register payload에 실어 보냄(기존 invite_token 스레딩과 동일 패턴). `RegisterPayload` 타입 확장.
- 시각적 변화 없음(순수 캡처). §6 무관(사용자 노출 문구 없음).

### 4. BE — 인증 멈춤 데드맨 알람 (notifications)
- 신규 `NotifType.SIGNUP_VERIFY_FLATLINE`(마이그레이션 AlterField choices) + `ADMIN_NOTIF_TYPES` 등록.
- `notifications/jobs.py::check_signup_verification_flatline(today)`: **최근 창(기본 1일, 노이즈 방지 위해 env `ACTIVATION_FLATLINE_LOOKBACK_DAYS` 검토)** 신규 가입 수 ≥ `ACTIVATION_FLATLINE_MIN_SIGNUPS`(env 기본 3) 인데 같은 창 인증 수가 0이면 관리자 전원 알림(`_notify_admins`). 멱등(하루 1회, dedup unique constraint 활용 or target_date로).
- `run_daily_jobs`에 정리/체크 단계로 추가(cleanup_* 나란히, try/except 격리). 성공 시 하트비트 유지.
- `_notify_admins` 중복(promotion/views.py·analysis/flags.py) → 공용 헬퍼로 뽑아 재사용(선택, 3중복 방지).

### 5. FE — 관리자 활성화 퍼널 화면 (admin, 시스템 테마)
- `app/admin/activation-funnel/page.tsx`: days 토글(7/30/90) + 퍼널 막대(단계별 인원, 전환율) + 활성화율 StatCard + UTM 소스별 표(가입·활성화) + 활성화 평균 일수. charts.tsx `BarChart` 재사용. 판정어 없음.
- `app/admin/layout.tsx` nav 항목 추가. `lib/adminApi.ts` `adminGetActivationFunnel(days)` + 타입.

### 테스트 (BE)
- 퍼널 집계: 코호트 백데이팅(`.update(date_joined=...)`)으로 단계별 인원·전환율·활성화(7일 창 경계) 정확. @inpa.local 제외. IsAdmin 격리(설계사 403).
- 활성화 7일 창: 8일째 첫분석은 미활성, 6일째는 활성.
- UTM: register가 utm_source 저장, 미전달 시 direct 집계, 위험문자 절단.
- 데드맨: 가입≥임계+인증0 → 관리자 알림, 인증>0 또는 가입<임계 → 무알림, 멱등(재실행 중복 0).
- run_daily_jobs에 체크 단계 탑재 + 하트비트 유지.

### 마이그레이션
2건(accounts: Profile utm 3필드 / notifications: NotifType choices AlterField). 전부 additive.

### 컴플라이언스
- UTM = 캠페인 태그(PII 아님), 위험문자 제거. 활성화 퍼널은 집계 수치만(개별 고객 정보 0, §6 판정어 0). 고객 대면 무변경(랜딩 캡처는 비가시). 관리자 전용(IsAdmin).
