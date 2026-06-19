# 인파(Inpa) — 개발 문서 마스터 인덱스 & 라우트맵

> 문서 ID: `dev/00-INDEX.md`
> 최종 갱신: 2026-06-19 (이메일/비밀번호 인증 전환 · 가시성 매트릭스 단일화 반영)
> 대상 독자: PM(전체 조망), 디자이너(화면·가시성·모바일), 개발자(라우트·권한·엔티티 매핑)
> 역할: `docs/dev/` 전체의 **진입점**. 어떤 문서가 무엇을 잠그는지, 모든 라우트의 접근권한·가시성·모바일 대응, 그리고 스트림↔문서↔엔티티 매핑을 한 화면에서 본다.
>
> **이 문서는 "지도"다. 실제 결정의 정본은 각 문서다.**
> - 데이터 모델·API 정본: `dev/02-data-model-and-api.md`
> - 가시성 매트릭스 정본: `dev/02 §0` (본 인덱스 §4는 그 요약)
> - 라우트 정본: 각 기능 문서. 본 인덱스 §3은 그 통합 뷰.

---

## 0. 한 문단 요약

인파는 위촉직 보험설계사 1인을 **테넌트**로 삼는 멀티테넌시 영업 OS다. 테넌트 = 설계사 1인. **'공유' 항목을 제외한 모든 데이터는 owner(설계사) 스코프**다. 인증은 **이메일/비밀번호 전용**(카카오 OAuth 전면 제거)이며, 흐름은 회원가입 → 이메일 인증 → 로그인 → 비밀번호 찾기(이메일 토큰 재설정)다. 준법의 핵심 통제점은 `planner_baseline`(설계사가 소유하는 보장 기준)으로, **기준이 없으면 분석을 부족/충분으로 단정하지 않고 neutral을 강제**한다. 인파는 중개·권유하지 않으며, 설계사가 기준을 소유한다.

---

## 1. 읽는 순서 (역할별 추천 경로)

| 독자 | 먼저 읽을 것 | 그다음 |
| --- | --- | --- |
| **PM / 의사결정** | 본 인덱스 → `01-architecture-and-stack` → `09-compliance-broker-line` | `04-build-plan` → `06-mvp-slice-plan` |
| **디자이너** | 본 인덱스 §3 라우트맵 → `04-ia-and-ux`(기획) → `18-mobile-responsive` | `08-screen-specs-A-heatmap` → 각 기능 문서의 "화면/흐름" |
| **개발자(BE)** | `02-data-model-and-api`(정본) → `03-porting-map` → `07-api-data-contracts` | 각 기능 문서의 "데이터/API/권한" |
| **개발자(FE)** | 본 인덱스 §3 → `01 §스택` → `18-mobile-responsive` | 각 기능 문서의 "화면/흐름" |
| **컴플라이언스 검토** | `09-compliance-broker-line` → `14-compliance-copy-rules` → `16-legal-and-consent` | `10-planner-criteria` |

---

## 2. 문서 인덱스 (`docs/dev/` 전체)

> 분류: **[기반]** 아키텍처·계획, **[계약]** 데이터·API, **[기능]** 화면·흐름, **[준법]** 컴플라이언스·법무, **[운영]** 관리자·인프라.

| # | 파일 | 한 줄 설명 | 분류 | 주 독자 |
| --- | --- | --- | --- | --- |
| 00 | `00-INDEX.md` | (본 문서) 마스터 인덱스 · 라우트맵 · 스트림 매핑 | 기반 | 전원 |
| 01 | `01-architecture-and-stack.md` | 시스템 아키텍처 · 확정 스택 · foliio vendoring 전략 · 공통 척추 라우트 | 기반 | 전원 |
| 02 | `02-data-model-and-api.md` | **데이터 모델 & API 정본** · 가시성 매트릭스(§0) · 전 엔티티 스코프 | 계약 | BE |
| 03 | `03-porting-map.md` | foliio → 인파 포팅 지도 (calculate.py 8케이스 · claude_parser OCR · 네임스페이스 리네임) | 기반 | BE |
| 04 | `04-build-plan.md` | Phase · 스프린트 · 게이트 빌드 계획 | 기반 | PM·개발 |
| 05 | `05-pre-dev-readiness.md` | 개발 착수 전 준비 체크리스트(법무 선결 3종 포함) | 기반 | PM |
| 06 | `06-mvp-slice-plan.md` | 첫 슬라이스(스캐폴딩 + 공유뷰A + 히트맵) 기획 | 기반 | 개발 |
| 07 | `07-api-data-contracts.md` | 첫 슬라이스 API & 데이터 계약 | 계약 | BE·FE |
| 08 | `08-screen-specs-A-heatmap.md` | 화면 스펙: 공유뷰A(삼쩜삼형) + 담보 히트맵 | 기능 | 디자인·FE |
| 09 | `09-compliance-broker-line.md` | **중개·권유 금지 경계** · 역할 분리(설계사가 기준 소유) | 준법 | 전원 |
| 10 | `10-planner-criteria.md` | **planner_baseline** 기준 설정 · neutral 강제 통제점 | 준법·기능 | BE·PM |
| 11 | `11-auth-onboarding.md` | 인증(이메일/비번) & 온보딩 흐름 | 기능 | 개발 |
| 12 | `12-customer-crud-ocr.md` | 고객 CRUD + 증권 OCR + 가족구성 | 기능 | 개발 |
| 13 | `13-share-northstar.md` | 공유링크(`/s/[token]`) & 북극성 지표 계측 | 기능 | PM·개발 |
| 14 | `14-compliance-copy-rules.md` | 컴플라이언스 카피 룰(면책 문구·금지 표현) | 준법 | 디자인·FE |
| 15 | `15-dashboard-worklog.md` | 대시보드 · 캘린더 · 업무기록(KPI·액션큐) | 기능 | 개발 |
| 16 | `16-legal-and-consent.md` | 법무·동의 설계(약관·국외이전·ConsentLog) | 준법 | 전원 |
| 17 | `17-boards-and-community.md` | 게시판 SNS 피드 · 공지 · FAQ · 1:1 문의 | 기능 | 개발 |
| 18 | `18-mobile-responsive.md` | 전 화면 모바일·반응형 명세 | 기능 | 디자인·FE |
| 19 | `19-admin-console.md` | 관리자 콘솔(운영·모더레이션·검수) | 운영 | 개발·운영 |
| 20 | `20-devops-and-deploy.md` | DevOps & 배포 · 환경변수 · 이메일 발송 인프라 | 운영 | 개발 |
| 21 | `21-promotion-orders.md` | 판촉물 샘플 카탈로그 + 주문제작 | 기능 | 개발 |
| 22 | `22-notifications-reminders.md` | 알림 & 리마인더(5종 만기·생일·접촉) | 기능 | 개발 |
| 23 | `23-billing-and-limits.md` | 요금제 & 사용량 한도(Freemium 월 카운터) | 기능·운영 | PM·BE |
| 24 | `24-landing-marketing.md` | 랜딩(메인) 페이지 스펙 — 히어로·7섹션·CTA·푸터·정직성 고지 | 기능 | PM·디자인·FE |

---

## 3. 마스터 라우트맵 / 사이트맵

> **접근권한 표기**: `공개`(AllowAny) · `비인증만`(로그인 시 리다이렉트) · `설계사`(인증 필수, owner 스코프 자동) · `관리자`(is_admin) · `토큰`(공유링크 share_token 검증).
> **가시성 표기**: 공유 / 비공개 / 소유자전용 / 소유자+관리자 / 공개읽기+관리자쓰기 — `dev/02 §0` 매트릭스 기준.
> **라우트 별칭**: 공통 척추(dev/01)는 복수형 친화 별칭(`/customers`, `/community`, `/promotions`)을 쓰고, 각 기능 문서는 단수형 정본(`/customer`, `/board`, `/promotion`)을 쓴다. **정본 = 기능 문서 라우트**, 별칭은 "정본←별칭" 칸에 표기. FE는 별칭→정본 리다이렉트(또는 단일 채택) 1건 필요(§openGaps).

### 3.0 랜딩 (마케팅 · 공개 · 비로그인)

| 정본 라우트 | 화면 | 접근권한 | 가시성 | 모바일 | 정본 문서 |
| --- | --- | --- | --- | --- | --- |
| `/` | 랜딩(마케팅, 공개/비로그인, 히어로 "설계사님은 클로징만 준비하세요") | **공개**(AllowAny) | 공개읽기 | 모바일 우선, 히어로+CTA+기능소개 | **24** |

> 로그인 후 대시보드는 `/home`(§3.2)으로 분리. 랜딩(`/`)은 SSG 정적 생성. 로그인 상태에서 접근 시 클라이언트 사이드 `useEffect` 로 `/home` 리다이렉트. 상세 스펙 `dev/24`.

### 3.1 인증·온보딩 (공개 / 비인증)

| 정본 라우트 | 화면 | 접근권한 | 가시성 | 모바일 | 정본 문서 |
| --- | --- | --- | --- | --- | --- |
| `/register` | 회원가입(이메일·비번·약관동의·위촉 자기신고 통합) | 비인증만 | — | client, 약관 인라인 체크박스 | 11, 16 |
| `/verify-email?token=` | 이메일 인증 처리(토큰 24h TTL, 완료 시 `is_active=True`) | 공개(토큰 검증) | — | 처리 후 `/login` 리다이렉트 | 11, 16 |
| `/login` | 이메일/비밀번호 로그인(5회 실패 → 10분 잠금) | 비인증만 | — | client, 단일 폼 | 11, 16 |
| `/forgot-password` | 비밀번호 찾기 — 이메일 입력 | 비인증만 | — | client, 단순 폼 | 11, 16 |
| `/reset-password?token=` | 비밀번호 재설정(토큰 1h TTL, 1회용) | 공개(토큰 검증) | — | client, 비번 2회 입력 | 11, 16 |
| `/onboarding` | 온보딩(STEP1 위촉 자기신고 → STEP2 첫 고객 유도, skip 허용) | 설계사 + `onboarding_completed_at IS NULL` | — | client, 진행 도트 2-step | 11 |

> 별칭 정리: 공통 척추의 `/auth/verify-email`·`/password-reset`·`/password-reset/confirm` 및 core-product의 `/auth/register/`·`/auth/login/`·`/auth/verify/`·`/auth/password/reset/` 는 위 정본 라우트의 별칭이다. **FE 라우트 정본은 `/register`·`/verify-email`·`/login`·`/forgot-password`·`/reset-password`** 로 통일.

### 3.2 핵심 제품 — 설계사 전용 (owner 스코프)

| 정본 라우트 | 화면 | 접근권한 | 가시성 | 모바일 | 정본 문서 |
| --- | --- | --- | --- | --- | --- |
| `/home` | 대시보드(KPI 5종 + 액션큐 5종 + 캘린더, 콜드스타트 빈 상태) | 설계사 + 온보딩완료 | 소유자전용 | 단일컬럼: KPI 가로스크롤→액션큐→주간 캘린더 / 데스크톱 2컬럼 | 15 |
| `/customer` | 고객 목록(카드형 + 검색 + 필터칩 + 태그 + 만기배지 D-N) | 설계사 + OwnedQuerySetMixin | 소유자전용 | 1열 리스트, 스와이프 액션 | 12 |
| `/customer/create` | 고객 등록(수기 폼: 이름·생년월일·성별·연락처·메모·태그·가족) | 설계사 | 소유자전용 | 빈칸채우기 폼(OCR 자동채움과 수렴) | 12 |
| `/customer/:id` | 고객 상세(탭: 분석/갈아타기/공백/이력) | 설계사 + IsOwner | 소유자전용 | 탭 overflow-x-auto, 1열 | 12 |
| `/customer/:id/analysis` | 보장 분석 / 히트맵(planner_baseline neutral 통제점) | 설계사 + IsOwner | 소유자전용 | 좌 sticky 카테고리 + 우 가로스크롤, 셀 탭영역 44px | 08, 10, 12 |
| `/customer/:id/compare` (↔ `/customer/:id/switch`) | 갈아타기 비교안내서(§97 하드블록) | 설계사 + IsOwner | 소유자전용 | 세로 누적(기존→제안), md+ 2열 | 12, 14 |
| `/customer/:id/message` | AI 메시지(목적칩·슬라이더·복사 전용) | 설계사 + IsOwner | 소유자전용 | 목적칩 가로스크롤, 복사 전용 | 14 |
| `/customer/:id/family` | 가족구성 CRUD | 설계사 + IsOwner | 소유자전용 | 서브 폼(relation/name/birth/gender) | 12 |
| `/customer/:id/agree` | 국외이전 동의(병력 민감정보 선결) | 설계사 + IsOwner | 소유자전용 | 체크박스 44px, 셀프동의 링크 복사 | 16 |
| `/calendar` | 캘린더(일정·리마인더) | 설계사 + OwnedQuerySetMixin | 소유자전용 | client, 주간 스트립 | 15 |
| `/settings/baseline` | planner_baseline 기준 설정(★준법 통제점) | 설계사 | 소유자전용 | 상품군 탭 × 연령대 × 성별 × 담보 밴드 | 10 |
| `/prospect` | 발굴(FAB 중앙 강조) | 설계사 | 소유자전용 | 발굴 FAB 돌출 강조 | 04, 15 |

### 3.3 공유·커뮤니티 (공유 가시성)

| 정본 라우트 | 화면 | 접근권한 | 가시성 | 모바일 | 정본 문서 |
| --- | --- | --- | --- | --- | --- |
| `/board` (↔ `/community`) | 게시판 SNS 피드 목록 | 설계사(읽기 전원) | **공유**(owner FK 없음) | 단일컬럼 카드 피드, 커서 무한스크롤, 카테고리 칩 | 17 |
| `/board/new` | 게시글 작성 | 설계사 | 공유(작성 시 author 기록) | 제목(선택)/본문/카테고리/첨부 | 17 |
| `/board/:id` | 게시글 상세(좋아요·댓글) | 설계사(숨김 글은 관리자만) | 공유 | 본문+첨부+좋아요+댓글 | 17 |
| `/board/:id/edit` | 게시글 수정 | **본인 작성자만** | 공유(수정권은 작성자) | 작성 폼 재사용 | 17 |
| `/notice` (↔ `/announcements`) | 공지사항 목록 | 설계사 | **공개읽기+관리자쓰기** | 카드 목록, 고정 공지 상단 | 17, 19 |
| `/notice/:id` | 공지사항 상세 | 설계사 | 공개읽기+관리자쓰기 | 본문, 이전/다음 내비 | 17 |
| `/faq` | FAQ 목록/아코디언 | 설계사 | **공개읽기+관리자쓰기** | 카테고리 아코디언, 검색 | 17, 19 |

### 3.4 1:1 문의 (비공개 — 작성자 + 관리자)

| 정본 라우트 | 화면 | 접근권한 | 가시성 | 모바일 | 정본 문서 |
| --- | --- | --- | --- | --- | --- |
| `/inquiry` (↔ `/inquiries`) | 1:1 문의 목록(본인만) | 설계사(본인) | **비공개**(작성자+관리자) | 본인 문의 카드, 상태 배지 | 17 |
| `/inquiry/new` | 1:1 문의 작성 | 설계사 | 비공개 | 카테고리/제목/내용/첨부 | 17 |
| `/inquiry/:id` | 1:1 문의 상세 + 답변 스레드 | **본인 + 관리자** | 비공개 | 문의 본문 + InquiryReply 스레드 | 17 |

### 3.5 판촉물 (카탈로그=공유 / 주문=소유자+관리자)

| 정본 라우트 | 화면 | 접근권한 | 가시성 | 모바일 | 정본 문서 |
| --- | --- | --- | --- | --- | --- |
| `/promotion` (↔ `/promotions`) | 판촉물 샘플 목록 | 설계사 전원 | **공유**(샘플 카탈로그) | 카드 2열 그리드, 카테고리 칩 | 21 |
| `/promotion/:sampleId` | 샘플 상세 + 주문 폼(2열) | 설계사 전원(샘플 공유, 폼 제출=본인 주문 생성) | 공유(샘플) / 소유자전용(주문 생성) | 세로 배치, 폼 vaul 바텀시트 | 21 |
| `/promotion/orders` (↔ `/orders`, `/me/promo`) | 내 주문 목록(본인만, 상태 배지) | 설계사(본인) | **소유자+관리자** | 목록 카드 | 21 |
| `/promotion/orders/:orderId` | 주문 상세 + 상태 타임라인 + 관리자 메모 | 본인 + 관리자 | 소유자+관리자 | 타임라인 세로 스크롤 | 21 |

### 3.6 알림·설정·요금 (소유자 / 소유자+관리자)

| 정본 라우트 | 화면 | 접근권한 | 가시성 | 모바일 | 정본 문서 |
| --- | --- | --- | --- | --- | --- |
| `/notifications` | 알림 센터(읽음/삭제, 날짜 그룹) | 설계사(본인) | 소유자전용 | 단일컬럼 피드, 스와이프 삭제 | 22 |
| `/settings/reminders` | 알림 설정(5종 on/off, N일 전, 이메일 opt-in) | 설계사 | 소유자전용 | 단일컬럼 설정 폼 | 22 |
| `/settings/profile` | 마이페이지(비번 변경·마케팅 동의 철회·탈퇴) | 설계사 | 소유자전용 | client | 11 |
| `/settings/billing` | 사용량 현황(플랜 + action별 월 카운터 진행 바) | 설계사(본인 스코프 자동) | **소유자+관리자** | 모바일 우선, 진행 바 전폭 | 23 |
| `/settings/billing/upgrade` | Plus 업그레이드 안내(계좌이체 수동, MVP) | 설계사 | 소유자+관리자 | 모바일 우선 | 23 |

### 3.7 공유뷰 (고객 비로그인 열람)

| 정본 라우트 | 화면 | 접근권한 | 가시성 | 모바일 | 정본 문서 |
| --- | --- | --- | --- | --- | --- |
| `/s/:token` | 고객 공유뷰(헤더·탭 숨김, 보장 열람) | **토큰**(AllowAny + share_token 검증) | 공유링크(판정 prop 물리 부재) | 단일컬럼 480~720px, SSR, **noindex** | 08, 13 |

### 3.8 법무 공개 페이지 (공개읽기)

| 정본 라우트 | 화면 | 접근권한 | 가시성 | 모바일 | 정본 문서 |
| --- | --- | --- | --- | --- | --- |
| `/legal/terms` | 서비스 이용약관 | 공개 | 공개읽기+관리자쓰기 | 스크롤 텍스트 | 16 |
| `/legal/privacy` | 개인정보처리방침 | 공개 | 공개읽기+관리자쓰기 | 스크롤 텍스트 | 16 |
| `/legal/terms/history` | 약관 개정 이력(삭제 금지) | 공개 | 공개읽기+관리자쓰기(append-only) | 목록 | 16 |

### 3.9 관리자 콘솔 (관리자 전용 · 데스크톱)

> 관리자 콘솔은 **모바일 미지원**(데스크톱 전용). 별도 진입점 `/admin-login`.

| 정본 라우트 | 화면 | 접근권한 | 가시성 | 모바일 | 정본 문서 |
| --- | --- | --- | --- | --- | --- |
| `/admin-login` | Admin 이메일/비밀번호 로그인 | 비인증(admin 진입점) | — | 미지원 | 19 |
| `/admin` | Admin 대시보드(운영 지표·미처리 항목) | 관리자 | 전체(운영) | 미지원 | 19 |
| `/admin/users` | 설계사 목록·검색·필터 | 관리자 | 전체 | 미지원 | 19 |
| `/admin/users/:id` | 설계사 상세(프로필·크레딧·요금제·유령행 재배정) | 관리자 | 전체 | 미지원 | 19, 23 |
| `/admin/board` | 게시판 신고 큐 모더레이션 | 관리자 | 전체(공유 콘텐츠 운영) | 미지원 | 19, 17 |
| `/admin/announcements` | 공지사항 작성·수정·삭제 | 관리자 | 공개읽기+관리자쓰기 | 미지원 | 19, 17 |
| `/admin/faq` | FAQ 작성·순서 관리 | 관리자 | 공개읽기+관리자쓰기 | 미지원 | 19, 17 |
| `/admin/inquiries` | 1:1 문의 목록·응답 처리 | 관리자 | 비공개(관리자 측) | 미지원 | 19, 17 |
| `/admin/orders` (↔ `/admin/promotion/orders`) | 판촉물 주문 목록·상태 변경·운송장 | 관리자 | 소유자+관리자(관리자 측) | 미지원 | 19, 21 |
| `/admin/promotion/samples` | 판촉물 샘플 CRUD + 폼 필드 빌더 | 관리자 | 공유(카탈로그 관리) | 미지원 | 21 |
| `/admin/consent-logs` | ConsentLog READ-ONLY 열람(PII 마스킹) | 관리자 | 소유자전용(관리자 감사 열람) | 미지원 | 19, 16 |
| `/admin/normalization` | UnmatchedLog 검수 큐 + NormalizationDict 1탭 매핑 | 관리자 | 공유(전역) + 관리자 검수 | 미지원 | 19, 12 |
| `/admin/settings` | 운영 설정(요금제 Plan·한도, 약관 PolicyVersion, 기능 플래그·`FREE_TIER_UNLIMITED`) | 관리자 | 공개읽기+관리자쓰기(Plan/PolicyVersion) | 미지원 | 19, 23, 16 |

### 3.10 라우트 정합 메모 (별칭·중복 정리)

| 사안 | 정본 채택 | 별칭(리다이렉트 또는 폐기 대상) |
| --- | --- | --- |
| 고객 | `/customer*` (단수, 기능문서 12) | `/customers*`(공통 척추 dev/01) |
| 게시판 | `/board*` (기능문서 17) | `/community`(공통 척추 dev/01) |
| 공지 | `/notice*` (기능문서 17) | `/announcements`(admin·설계사용 dev/19) |
| 판촉물 | `/promotion*` (기능문서 21) | `/promotions`(척추), `/orders`, `/me/promo`(모바일 dev/18) |
| 1:1 문의 | `/inquiry*` (기능문서 17) | `/inquiries`(admin dev/19) |
| 갈아타기 | `/customer/:id/compare` (척추 dev/01) | `/customer/:id/switch`(모바일 dev/18) |
| 비밀번호 재설정 | `/forgot-password` + `/reset-password` | `/password-reset` + `/password-reset/confirm`(devops dev/20), `/auth/password/reset/`(core dev/12) |
| 이메일 인증 | `/verify-email` | `/auth/verify-email`(account dev/11), `/auth/verify/`(core dev/12) |

> **결정 필요(openGap)**: 위 별칭 8쌍은 **각 1개 정본으로 단일화**하거나 **별칭→정본 308 리다이렉트**를 둘 것. 라우트 정본 단일화 PR 1건 필요. 본 인덱스는 정본을 위와 같이 확정 제안한다.

---

## 4. 가시성 매트릭스 요약 (정본: `dev/02 §0`)

> 테넌트 = 설계사 1인. **'공유'를 제외한 모든 것은 owner 스코프.** 분류별 기준과 대표 엔티티.

| 가시성 클래스 | 누가 보나 | 모델 패턴 | 대표 엔티티 |
| --- | --- | --- | --- |
| **공유** | 모든 설계사 | owner FK 없음 | 게시판 글·댓글·좋아요, 판촉물 샘플 카탈로그, 담보 표준 마스터(AnalysisCategory 등), NormalizationDict, UnmatchedLog, JobRiskCode, ChartDetail |
| **공개읽기 + 관리자쓰기** | 모든 설계사 읽기 / 관리자만 쓰기 | published 플래그 | 공지사항(Notice), FAQ(Faq), 약관(PolicyVersion) |
| **비공개** | 작성자 + 관리자 | author FK + 관리자 우회 | 1:1 문의(Inquiry) + InquiryReply |
| **소유자전용** | 본인만 | owner FK + OwnedQuerySetMixin + IsOwner | 고객·고객동의·보험정보·분석·비교·캘린더·KPI/대시보드·알림/리마인더·**planner_baseline** |
| **소유자 + 관리자** | 설계사 본인 / 관리자 전체 | owner FK + 관리자 우회 | 판촉물 주문(PromotionOrder), 요금제·사용량(billing) |

> **owner 경유(`customer__owner`) 패턴**: FamilyMember·CustomerMedicalHistory·ConsentLog·CustomerInsurance(+Detail)는 자체 owner FK 없이 Customer를 통해 소유자전용으로 스코프된다(`dev/02` 참조).

---

## 5. 스트림 ↔ 문서 ↔ 주요 엔티티 매핑

> 병렬 작업 스트림 10개가 어떤 문서를 정본으로 쓰고, 어떤 엔티티를 책임지는가. 데이터 모델 정본은 항상 `dev/02`이며, 아래 엔티티 컬럼은 "이 스트림이 주로 다루는 엔티티"다.

| 스트림 | 정본 문서 | 주 라우트 영역 | 주요 엔티티 | 가시성 클래스 |
| --- | --- | --- | --- | --- |
| **공통척추** | `01-architecture-and-stack` | 전역 셸·네비·`/home`·`/s/:token` | (앱 셸·라우팅·디자인 토큰) | — |
| **account** | `11-auth-onboarding` | `/register`·`/login`·`/verify-email`·`/forgot-password`·`/reset-password`·`/onboarding`·`/settings/profile` | User, Profile, Token(DRF authtoken) | 소유자전용(본인+관리자) |
| **legal-consent** | `16-legal-and-consent` | `/legal/*`·`/customer/:id/agree`·약관 동의 | ConsentLog, PolicyVersion, CustomerMedicalHistory | 공개읽기+관리자쓰기 / 소유자전용 |
| **core-product** | `12-customer-crud-ocr` (+08,10,13) | `/customer*`·`/settings/baseline`·`/s/:token` | Customer, CustomerTag, FamilyMember, CustomerInsurance(+Detail), **PlannerBaseline**, NormalizationDict, UnmatchedLog, AnalysisCategory/SubCategory/Detail, ChartDetail, JobRiskCode | 소유자전용 / 공유(마스터) |
| **notifications** | `22-notifications-reminders` | `/notifications`·`/settings/reminders` | Notification, ReminderRule | 소유자전용 |
| **boards** | `17-boards-and-community` | `/board*`·`/notice*`·`/faq`·`/inquiry*` | Post, Comment, Like, Notice, Faq, Inquiry, InquiryReply, Report | 공유 / 공개읽기+관리자쓰기 / 비공개 |
| **판촉물** | `21-promotion-orders` | `/promotion*` | PromotionSample, PromotionOrder, PromotionOrderStatusLog | 공유(카탈로그) / 소유자+관리자(주문) |
| **billing** | `23-billing-and-limits` | `/settings/billing*` | Plan, Subscription, UsageMeter | 소유자+관리자(Plan은 공개읽기) |
| **admin** | `19-admin-console` | `/admin*` | (위 엔티티의 관리자 운영 뷰: 신고 모더레이션·검수·동의 감사) | 전체(관리자 운영) |
| **devops** | `20-devops-and-deploy` | (배포·환경변수·이메일 인프라) | (앱 외 인프라) | — |
| **mobile** | `18-mobile-responsive` | 전 라우트의 모바일 명세 | (화면 단면 — 자체 엔티티 없음) | — |

> 참고: `dataModelDelta`/`iaDelta`의 직렬 통합 정본은 `dev/02`(데이터)와 본 `dev/00-INDEX`(IA·라우트)다. 두 문서는 서로 교차 참조한다.

---

## 6. 횡단 결정 핀(전 라우트 적용)

이 결정들은 특정 화면이 아니라 **모든 라우트에 일관 적용**된다.

1. **인증 = 이메일/비밀번호 전용.** 카카오 OAuth 전면 제거. 토큰은 Django `PasswordResetTokenGenerator` 상속(별도 DB 테이블 없음, stateless, 이메일 인증 24h / 비번 재설정 1h, 1회용). 정본 `dev/11`, `dev/16`.
2. **멀티테넌시 = 설계사 1인 테넌트.** '공유' 외 전부 owner 스코프(`OwnedQuerySetMixin` + `IsOwner`). 정본 매트릭스 `dev/02 §0`.
3. **★준법 통제점 planner_baseline.** `baseline_source == null`이면 분석 히트맵 status를 **neutral 강제**(부족/충분 단정 금지). 정본 `dev/10`, `dev/02`.
4. **정직성 레드라인.** "심의완료/안전" 배지 금지. AI 생성물에 "AI 초안 · 최종책임 설계사" 면책 고정. **원탭 자동발송 없음**(클립보드 복사/카톡 열기까지만). 정본 `dev/14`.
5. **컴플라이언스 게이트.** 병력(민감정보)을 Claude API로 보내려면 **국외이전 동의가 AI 분석의 선결조건**(detect API 412 게이트). 정본 `dev/16`.
6. **갈아타기 §97.** 비교안내서는 부당승환 방지 하드블록 포함. 정본 `dev/12`, `dev/14`.
7. **관리자 페이지 필수 · 데스크톱 전용.** `/admin*` 전 라우트 모바일 미지원. 정본 `dev/19`.
8. **공유뷰 noindex.** `/s/:token`은 SSR + `noindex`(검색 비노출). 정본 `dev/13`.

---

## 7. 미결(openGaps) — 후속 직렬 통합/결정 필요

| # | 항목 | 제안 기본값 | 정본 문서 |
| --- | --- | --- | --- |
| G1 | 라우트 별칭 8쌍 단일화(§3.10) | 본 인덱스 §3 정본 라우트로 통일 + 별칭 308 리다이렉트 | 01, 11, 12, 17, 18, 19, 20 |
| G2 | ~~공지/FAQ 비인증 공개 허용 여부~~ | 해소: Notice·Faq=공개읽기(AllowAny GET)+관리자쓰기 확정(결정 17) | 17 |
| G3 | 데이터 모델 정본(`dev/02`)과 본 인덱스 라우트 정합 재검증(엔티티명 1:1) | `dev/02` 재작성 직후 본 인덱스 §5 동기화 | 02 |
| G4 | `EmailVerificationToken` 서술 동기화(별도 테이블 폐기 → Generator 상속) | `dev/11` 서술을 `dev/02` 정본에 맞춰 갱신 | 11 |
| G5 | 모바일 미지원 관리자 콘솔의 운영자 모바일 긴급 열람 경로 | v2까지 미지원 유지, 긴급 시 데스크톱 접속 | 19 |

---

## 부록 A. 라우트 빠른 색인 (알파벳/경로순)

```
/                              공개    랜딩(마케팅·비로그인) dev/24
/admin                         관리자  대시보드            dev/19
/admin-login                   비인증  Admin 로그인        dev/19
/admin/announcements           관리자  공지 관리           dev/19,17
/admin/board                   관리자  신고 모더레이션      dev/19,17
/admin/consent-logs            관리자  동의 감사(RO)       dev/19,16
/admin/faq                     관리자  FAQ 관리            dev/19,17
/admin/inquiries               관리자  문의 처리           dev/19,17
/admin/normalization           관리자  정규화 검수 큐       dev/19,12
/admin/orders                  관리자  주문 처리           dev/19,21
/admin/promotion/samples       관리자  샘플 CRUD          dev/21
/admin/settings                관리자  운영 설정(요금제·약관) dev/19,23,16
/admin/users                   관리자  설계사 목록         dev/19
/admin/users/:id               관리자  설계사 상세         dev/19,23
/board                         설계사  게시판 피드(공유)    dev/17
/board/:id                     설계사  게시글 상세         dev/17
/board/:id/edit                본인    게시글 수정         dev/17
/board/new                     설계사  게시글 작성         dev/17
/calendar                      설계사  캘린더(소유자)       dev/15
/customer                      설계사  고객 목록(소유자)    dev/12
/customer/:id                  설계사  고객 상세           dev/12
/customer/:id/agree            설계사  국외이전 동의        dev/16
/customer/:id/analysis         설계사  히트맵 분석         dev/08,10,12
/customer/:id/compare          설계사  갈아타기 비교        dev/12,14
/customer/:id/family           설계사  가족구성 CRUD       dev/12
/customer/:id/message          설계사  AI 메시지           dev/14
/customer/create               설계사  고객 등록           dev/12
/faq                           설계사  FAQ(공개읽기)       dev/17
/forgot-password               비인증  비번 찾기           dev/11,16
/home                          설계사  대시보드(소유자)     dev/15
/inquiry                       본인    1:1 문의 목록       dev/17
/inquiry/:id                   본인+관리자  문의 상세      dev/17
/inquiry/new                   설계사  문의 작성           dev/17
/legal/privacy                 공개    개인정보처리방침      dev/16
/legal/terms                   공개    이용약관            dev/16
/legal/terms/history           공개    약관 개정 이력       dev/16
/login                         비인증  로그인              dev/11,16
/notice                        설계사  공지(공개읽기)       dev/17,19
/notice/:id                    설계사  공지 상세           dev/17
/notifications                 설계사  알림 센터(소유자)     dev/22
/onboarding                    설계사  온보딩              dev/11
/promotion                     설계사  판촉물 목록(공유)     dev/21
/promotion/:sampleId           설계사  샘플 상세+주문       dev/21
/promotion/orders              본인    내 주문(소유자+관리)  dev/21
/promotion/orders/:orderId     본인+관리자  주문 상세      dev/21
/prospect                      설계사  발굴                dev/04,15
/register                      비인증  회원가입            dev/11,16
/reset-password                공개    비번 재설정(토큰)     dev/11,16
/s/:token                      토큰    고객 공유뷰(noindex) dev/08,13
/settings/baseline             설계사  기준 설정(준법통제)   dev/10
/settings/billing              설계사  사용량(소유자+관리)   dev/23
/settings/billing/upgrade      설계사  업그레이드 안내      dev/23
/settings/profile              설계사  마이페이지(소유자)    dev/11
/settings/reminders            설계사  알림 설정(소유자)     dev/22
/verify-email                  공개    이메일 인증(토큰)     dev/11,16
```

---

> **유지보수 규칙**: 새 라우트/문서를 추가하면 본 인덱스 §2(문서 인덱스)·§3(라우트맵)·부록 A를 함께 갱신한다. 데이터 모델 변경은 항상 `dev/02`가 정본이며, 본 인덱스 §5는 그 요약을 따라간다.
