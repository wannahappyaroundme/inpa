# Spec: 신뢰 대청소 + PII 로그 정리 (LB#7 + LB#9 코드 부분)

> LB#7(launch trust sweep) 중 코드로 해결되는 조각 + LB#9(PII log scrub). 이미 해결된 조각: 랜딩 '월 N건'(카피 커밋 18c6a89), /settings/reminders 숨김 불필요(알림 엔진 822a3b9로 실동작). 법정 표시사항 기재는 PM의 사업자 정보 대기(별도).

## Decisions (locked)

### A. `cleanup_demo` 관리 명령 (신규, seed_demo 옆 inpa/analysis/management/commands/)
1. 프로드의 [DEMO] 잔재를 안전하게 제거하는 1회성 명령(멱등, Render Shell에서 실행 예정):
   - `@inpa.local` 이메일 사용자 전부 삭제(CASCADE로 소유 데이터 정리) — 단 `is_admin` 프로필은 절대 삭제 금지(안전 가드).
   - `code`가 `demo_`로 시작하는 Plan: 남은 Subscription 참조가 없으면 삭제, 있으면 `is_active=False` (공개 /billing/plans/ 노출 즉시 차단).
   - 결과 카운트 출력(사용자/플랜 삭제·비활성 수). `--dry-run` 기본 아님(명시적 명령이므로) but print what it does.
2. seed_demo 자체는 수정하지 않는다(로컬 데모 용도 유지).

### B. '준비 중' 카피 정리 (§6c 레드라인 위반 3곳)
1. `inpa_fe/app/settings/account/page.tsx` 카카오·네이버 로그인 행: **행 자체 삭제**(없는 연동을 광고하지 않는다). Google 행은 유지하되 env 미설정 시 문구를 '관리자 설정 후 연결할 수 있어요'로(positive).
2. `inpa_fe/app/customer/[id]/page.tsx:~881` 명함 자동 인식 문구 → '명함 정보는 위 칸에 직접 입력해 주세요.' (기능 약속 없음, 다음 행동만).
3. `inpa_fe/scripts/check-copy.js` RULES에 '준비 중' 금지 규칙 추가(렌더 문자열 한정, 주석 제외 — 기존 em-dash 규칙과 같은 방식). 추가 후 `npm run lint:copy`가 0 위반이어야 함(위반이 새로 잡히면 그 문구도 같은 원칙으로 정리).

### C. 판촉물 카탈로그 빈 이미지 → 브랜드 플레이스홀더
`inpa_fe/app/promotion/page.tsx`(및 같은 폴백을 쓰는 상세)의 '이미지 없음' 폴백을 **의도된 디자인**으로 교체: 브랜드 그라디언트 배경 + 카테고리/샘플명 타이포 카드(부정 문구 0). 메뉴 숨김은 하지 않는다(판촉물 페이지 상단의 내 소개 카드 위젯 접근 유지 — 패널의 hide 결정 대신 완성도 보정으로 해석, 근거: 소개 카드 동선 보존).

### D. PII 로그 정리 (LB#9 코드 부분)
1. `inpa_be/inpa/core/ocr/claude_parser.py`: `:616` 파싱 실패 시 `response_text[:200]` print(고객 증권 내용 유출) → 내용 없이 길이·예외만 logger.warning. `:631` 성공 print(회사/상품명) → logger.info로 회사 코드·건수 수준만. `:832/:863` 오류 객체 print → logger.exception/워닝(내용 미포함). print → logging 전환.
2. `inpa_be/inpa/insurances/views.py:~138` pdf 추출 오류 print → logger.warning(예외 타입·메시지만, 파일 내용 금지).
3. `config/settings/base.py`에 LOGGING 설정 추가: console 핸들러, root INFO, `inpa` 로거 INFO — 요청 본문/PII를 찍는 포매터 없음. prod에서 gunicorn stdout으로 흐르는 현행 동작 유지(단순·표준형).

## Redlines
- 렌더 문자열: 쉬운말·긍정 프레임·em-dash 금지·'준비 중' 금지(이번에 규칙화).
- cleanup_demo는 demo 패턴 밖 데이터를 절대 못 건드리게 필터를 이메일 도메인/코드 프리픽스로만.
- 기존 테스트 549? (현재 496) 전체 그린 유지.

## Tests
1. cleanup_demo: 데모 사용자+플랜+구독 픽스처 → 실행 → 데모만 사라지고 실사용자/free·plus 플랜 무손상; 재실행 멱등; admin @inpa.local 가드.
2. claude_parser 로깅: 파싱 실패 경로에서 응답 내용이 로그 문자열에 포함되지 않음(assertLogs로 검증 가능한 형태면 추가, 어려우면 코드 리뷰로 갈음하고 노트에 기록).
3. FE: `npm run lint:copy`(새 규칙 포함) + `npm run build` 그린.

## Verification gates
- BE: `python manage.py check` + 전체 스위트(현재 496) 그린, 마이그레이션 0.
- FE: lint:copy 0 위반 + build 성공.
- grep '준비 중' → 렌더 문자열 0(주석 제외).
- 보고: 파일 목록, cleanup_demo 실행 시 프로드 예상 동작 요약(런북 한 줄), 로그에 남는 정보 수준 요약.
