# Spec: 오늘 전화 리스트 (MVP #19, 채점 1위 8.31)

> 아침에 열면 "오늘 누구에게 전화할지"가 이미 정해져 있는 pull 방식 큐. 알림과 달리 화면을 열 때 계산하므로 배치가 죽어도 항상 동작. PM 배치 승인: 홈 대시보드 카드.

## Decisions (locked)

### BE — `GET /api/v1/customers/call-list/` (CustomerViewSet @action, list route, owner-scoped)
1. 대상: 본인 소유 + `status='active'` 고객만(보류/휴면/종료 제외). 최대 10명 + `total_candidates` 수.
2. 랭킹(결정적, 투명): score =
   - 생일 임박(D-day ≤ 7): `100 - dday*10`
   - 만기 임박(보유계약 중 최근접 만기 D-day 0~30): `80 - dday*2`
   - 무접촉: `min(무접촉일수, 60)` (앵커 = last_contacted_at 없으면 created_at, KST)
   - 단계 보정: sales_stage가 contact(TA)/meeting(FA)이면 +10 (진행 모멘텀)
   score 0인 고객(사유 없음)은 제외. 동점은 무접촉일수 desc.
3. 날짜 파싱: 생일·만기 CharField는 `inpa.notifications.jobs`의 `_parse_date`/`_next_birthday` 재사용(순환 import 없음: customers.views → notifications.jobs → customers.models 는 단방향). 만기 후보는 알림 생산자와 동일 필터(portfolio_type=1, is_cancelled=False).
4. 응답 행: `{id, name, mobile_phone_number, sales_stage, score, reasons: ["생일 D-3", "만기 D-12", "무접촉 21일"], last_contacted_at}` — reasons 는 그대로 칩으로 렌더 가능한 한글 라벨.
5. 성능: 고객·보험 각 1쿼리 수준(파이썬 계산 OK, 규모 작음). 마이그레이션 0.

### FE — 홈 대시보드 카드 (app/home)
1. 배치: 좌측 8칸 컬럼, 영업 파이프라인 카드 바로 아래.
2. 행 UI: 이름(고객 상세 링크) + 사유 칩(최대 3) + 우측 원탭 3버튼: 전화(`tel:`)·문자(`sms:`)·화법(`/scripts?customer=<id>` 링크, 기존 프리필 재사용).
3. 상태: 로딩 스켈레톤 / 오류 시 재시도 버튼 / 빈 상태 "오늘은 챙길 고객을 다 챙겼어요. 새 고객 발굴에 시간을 써보세요." (긍정 프레임).
4. 하단 '고객 전체 보기' → /customers.
5. lib/api.ts에 타입+fetch 추가.

## Redlines
- 판정어 금지(리스트는 '연락 우선순위'일 뿐, 보장 판단 아님). 쉬운말·긍정·em-dash 금지·'준비 중' 금지(린트).
- owner 격리 절대(액션도 OwnedQuerySetMixin 큐리셋 기반).

## Tests (BE)
1. 랭킹: 생일 D-1 > 만기 D-5 > 무접촉 30일 순서 검증. 2. active만(보류·휴면 제외). 3. 타 설계사 고객 미노출. 4. score 0 제외 + 10명 캡 + total_candidates. 5. 잘못된 날짜 문자열 안전. 전체 스위트(524+) 그린, FE build+lint 통과.

## Verification
- BE check + full suite 실출력, FE build/lint 실출력. 보고: 랭킹 예시 3건의 실제 응답 JSON.
