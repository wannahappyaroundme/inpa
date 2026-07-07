# Spec: 판촉물 주문 개선 + 설계사 전화번호 필드 (PM 지시 2026-07-07)

> PM: "판촉물 주문에 ①추가 요청사항(있으면) ②회신 받을 이메일 ③인쇄 정보(이름·연락처·소속) 마이페이지 자동 채움 ④완료 문구 '담당자가 빠르게 확인한 뒤 견적과 함께 첨부해주신 메일과 알림으로 회신드리겠습니다' 식으로." + 전화번호 필드 신설 승인(연락처 자동 채움과 /s 전화 버튼 활성용).

## Decisions (locked)

### A. Profile.phone 신설 (마이그레이션 1건 — 이번 스프린트 유일 허용)
1. `accounts.Profile.phone` CharField(max_length=20, blank=True, default='') — PG-safe.
2. ProfileSerializer 노출 + PATCH 허용. 마이페이지(설정 > 계정)에 '전화번호' 입력칸(숫자·하이픈만, 예: 010-1234-5678). 저장은 기존 프로필 저장 플로우 재사용.
3. **/s 공유뷰 자동 활성 확인**: LB#8의 `_planner_phone` 프로브 헬퍼가 후보 필드명(phone 포함)을 탐지하므로 값이 생기면 planner_contact가 자동으로 채워져 '전화하기/문자하기' 버튼이 살아난다 — 회귀 테스트로 고정(phone 설정 → /s payload planner_contact == 그 번호).

### B. 판촉물 주문 폼(FE /promotion/[sampleId] + BE 허용)
1. **회신 이메일 필드(필수)**: 기본값 = 로그인 계정 이메일(수정 가능). answers JSON에 `_reply_email` 키로 저장.
2. **추가 요청사항(선택)**: textarea, 라벨 '추가 요청사항 (선택)', 플레이스홀더 '따로 요청하실 내용이 있으면 적어주세요.' → answers `_extra_request`.
3. **인쇄 정보 자동 채움**: 샘플 form_fields 중 라벨에 '인쇄'가 포함된 text/textarea 필드가 비어 있으면 프로필로 프리필 — `{이름}, {전화번호}, {소속}` (없는 값은 빼고 콤마 정리; 예: 전화번호 미입력이면 '이경석, 삼성생명 비전지사'). 수정 가능.
4. **BE 검증 허용**: PromotionOrder 생성 시 answers의 `_`-prefixed 메타 키(`_reply_email`, `_extra_request`)를 form_fields 정의에 없어도 통과시키도록(현행 검증 로직 확인 후 최소 수정). `_reply_email`은 이메일 형식 검증. 관리자 주문 상세(admin_console 주문 시리얼라이저/FE /admin/orders)가 answers를 그대로 보여준다면 자동 노출 — 아니면 두 키를 명시 표기.
5. **완료 문구 교체**: '신청이 접수됐어요. 담당자가 빠르게 확인한 뒤 견적과 함께 남겨주신 메일과 알림으로 회신드리겠습니다.' (기존 완료 화면 위치 그대로, em-dash·판정어 금지)

## Tests (BE)
1. Profile phone PATCH 왕복 + 형식(숫자·하이픈·+, 20자) 검증.
2. /s payload: phone 설정 전 null → 설정 후 그 번호(회귀).
3. 주문 생성: `_reply_email`(유효/무효)·`_extra_request` 포함 answers 정상 저장, form_fields 검증 비파괴(기존 테스트 불변).
4. 전체 스위트(554+) 그린.

## Verification gates
- BE check + migrate(신규 1건 적용 확인) + 전체 스위트, FE lint:copy + build 실출력.
- 보고: 마이그레이션 파일명, /s planner_contact 실측, 주문 answers 저장 실측 JSON, 프리필 규칙 설명, 새 카피 전문.
