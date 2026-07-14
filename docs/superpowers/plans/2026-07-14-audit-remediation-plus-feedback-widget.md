# 실행 계획 — 감사 리메디에이션 38건 + 피드백 위젯/어드민 여백/트래킹

Date: 2026-07-14 · Branch: feat/design-refactor · PM 승인: 38건 전부 수정 + 3기능.
근거 문서: 감사 확정 목록 = 세션 scratchpad `audit-state.json` (아트팩트 보고서) · 위젯 스펙 = `docs/superpowers/specs/2026-07-10-feedback-widget-admin-polish-tracking-fix.md`.
원칙: 배치당 좁은 변경 + 대상 테스트 + 커밋. 공유 브랜치이므로 push 전 `git fetch` + 내 파일만 stage. em-dash 금지, easy-words(§6). 마이그레이션은 additive만.

남은 감사 3관점(copy·dead·deploy)은 Fable 크레딧 회복 시 병행(별도, 이 계획과 독립).

## 배치 순서 (안전·독립 우선 → 위험·교차 나중)

### A. BE 시간대/날짜 (마이그레이션 0, 로직만) — 6건
- billing/models.py:201 `UsageMeter.current_month` → `timezone.localtime().strftime('%Y-%m')` (+회귀테스트: 7/31 15:30 UTC → '2026-08')
- accounts/manager.py:57 `date.today()` → `timezone.localdate()` (this_ym 파생 포함)
- admin_console/views.py:101 `오늘` 카운트 → `timezone.localdate()` (미사용 year_month 정리)
- insurances/churn.py:130 `date.today()` 3곳 → `timezone.localdate()`
- dashboard/aggregation.py:129 도넛·유지율 기본 날짜 → `timezone.localdate()`
- schedule/views.py:58 월 필터에 `| ~Q(anniversary_md='')` 추가(생일 매년 반복) + 회귀테스트

### B. BE 결제 정합 — 4건 (마이그 0)
- credit.py: `resolve_effective_plan(user)` 공통 헬퍼(구독 존재 AND status active/trial AND not past expires_at → sub.plan, else Free). `_consume`·`_build_usage_response`·AdminBilling·402 멤버십에 적용.
- coupons.py:65 redeem: 무기한/상위/타요금제 active 구독은 덮어쓰기 금지(already/no-op), free·expired만 upsert.
- billing/views.py:61 사용량 응답이 위 헬퍼 사용 + 만료 시 status 'expired' 노출.
- (UsageMeter UTC는 배치 A에서 처리)

### C. BE 예약 — 4건 (마이그 0)
- availability.py:119 GET/POST 격자 통일: POST가 GET과 같은 step 사용(또는 step_min_for의 max(15,...) 제거) + booking_default_duration>=15 clamp.
- schedule/serializers.py:41 block+recur_weekday면 recur_start<recur_end 검증.
- booking/views.py:83 accept/decline 원자적 조건부 update(pending→confirmed 실패 시 400).
- booking/views.py:86 대면 미팅 accept 시 profile.booking_location → meeting.location_detail 저장 + FE booking-settings 장소 입력.

### D. BE 알림 — 3건 + 위젯 알림 배선
- notifications/views.py:100 (CRITICAL) NotificationViewSet/ReminderRuleViewSet read_all·destroy·mark_read를 항상 owner 스코프로(어드민 write 우회 차단, analysis/flags owner_only 패턴).
- admin_console/views.py:521 주문상태→PROMOTION_STATUS, 문의답변/리포트→board-bucket 신규 타입(INQUIRY_ANSWERED 등), 플랜변경→bell-only; 제목 em-dash 제거.
- notifications/jobs.py:338 flatline 창을 now 기준 최근 24h로.
- (위젯용 INQUIRY_RECEIVED 신규 타입은 배치 H)

### E. BE OCR/분석 — 3건 (마이그 0)
- analysis/views.py:131 + analytics/views.py:249 `_build_share_payload`/heatmap '보유' 집계를 portfolio_type=1로 필터(다른 집계와 통일). 회귀테스트: pt=2 제외.
- core/ocr/pii_mask.py:31 구조단어(NOT_NAMES) 뒤 이름 재검사되게 수정 + '계약자명'류·띄어쓴 라벨 커버. 회귀테스트 5형식.
- insurances/self_diagnosis.py:283 재제출 시 이미 저장된 (회사,담보,금액) 시그니처 중복 스킵. 회귀테스트.

### F. BE 보안/권한 — 3건 (마이그 0)
- accounts/views.py:239 구글 링크가 미인증 계정이면 is_active=True+email_verified_at 스탬프 + 기존 비번 set_unusable_password. 회귀테스트.
- accounts/invite.py:74 TeamInviteInfoView가 _NoIndexMixin 상속.
- accounts/public.py:57 소개카드 리드 per-refcode 하루 캡(셀프진단 미러).

### G. FE 수정 — 화면동작/상태/연결 (마이그 0)
- app/d/[ref]/page.tsx:187 국외이전 동의를 files>0일 때만 필수 + 라벨 조건부.
- app/customer/[id]/page.tsx: 비교 재계산 순서보호(insReqRef 패턴)+복사버튼 잠금(1369) · InfoTab 성별/생년월일 명시 비움(633) · 비교표 overflow-x-auto+min-w(1632) · 단계/상태 실패 배너(280).
- app/customers/page.tsx:508 ?stage=contract 시 setShowContract(true).
- app/analysis/page.tsx:151 + app/schedule/page.tsx:138 고객 선택 검색형/전체 로드.
- app/schedule/page.tsx:119 로드 실패 배너+다시시도, remove/toggleDone 오류 표시.
- components/ocr-upload.tsx:104 ConsentModal 오류 표시.
- app/home/page.tsx:170 달력 미팅 과거/진행 포함.
- app/notifications/page.tsx:25 + lib/api.ts NotifType 5종 라벨 추가.
- app/boards/[id]/page.tsx:443 댓글 입력창 하단탭바 오프셋.
- app/admin/inquiries/page.tsx:256 답변 작성자 author_email 표시.
- app/s/[token]/page.tsx:107 + analytics: cta_click 이벤트 허용목록 추가(또는 제거).
- lib/api.ts:1307 어드민 공지/FAQ 목록을 어드민 API로(adminListNotices/Faqs).

### H. 기능 — 피드백 위젯 (boards 마이그 1 additive)
스펙대로: Inquiry.category+feedback, owner nullable, rating/meta/contact_email, POST /feedback/(AllowAny+throttle), INQUIRY_RECEIVED 어드민 팬아웃(+기존 문의 생성에도), FE components/feedback-widget.tsx(app-nav + 랜딩 마운트, 고객링크/어드민/인증페이지 제외), 어드민 문의함 category 필터+별점+meta+비회원.

### I. 기능 — 어드민 여백 정리 (표현만)
admin/layout.tsx `<main>` p-4 sm:p-6 + 페이지별 outer padding 제거 + 통계카드/헤더/에러배너/그리드갭 통일 + FAQ 모바일 stack.

### J. 기능 — 트래킹 수정
OCR_UPLOAD/ANALYSIS_VIEW 이벤트 발생 배선, AdminUsageView planner_activity/customer_response 분리, /admin/usage 2그룹+정렬, days=0 '전체' 토글, adminApi AdminLoginResponse {id,email}.

## 검증
배치별 대상 테스트(`python manage.py test inpa.<app>`), 전체는 주요 마디마다. FE는 배치 G/H/I/J 후 `npm run build` + `npm run lint:copy`. 마무리: 브라우저 스모크(위젯 제출→어드민 문의함+알림, 사용량 nonzero) + README/CLAUDE 갱신.
