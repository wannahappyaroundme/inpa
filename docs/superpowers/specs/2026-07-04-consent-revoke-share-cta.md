# Spec: 동의 철회 + /s 상담 연결 버튼 (LB#10 + LB#8)

> LB#10(consent withdrawal, H-7): UI가 이미 "언제든 수신을 거부할 수 있어요"라고 약속하는데 철회 수단이 없다(PIPA 철회권). `ConsentLog.revoked_at/revoke_ip` 필드는 존재.
> LB#8(/s never-dead CTA): 설계사가 업무시간(WorkHour)을 안 정했으면 고객 화면의 '담당 설계사에게 물어보기'가 이벤트만 남기고 아무 반응이 없다(고객이 손에 쥔 화면의 죽은 버튼).

## Part 1 — 동의 철회 (LB#10)

### Decisions (locked)
1. **철회 입구 = /c 토큰 페이지** (동의와 같은 채널 = "동의만큼 쉽게"): GET 응답의 각 항목에 `already` 외 `revocable`(이미 동의된 scope) 표시. FE /c는 이미 동의된 항목에 '동의 철회' 버튼을 노출.
2. **POST /c** 가 `agreed` 와 별개로 `revoked: [scope]` 배열을 받는다. 철회 = 해당 customer+scope의 **모든 unrevoked ConsentLog**(subject 불문)에 `revoked_at=now, revoke_ip` 스탬프. 토큰 scope 밖 철회는 무시(위조 가드, agreed와 동일 원칙).
3. **효과 정합(구현 전 실필드 추적 필수):**
   - overseas 철회 → `has_current_overseas_consent`가 자동 False(revoked 필터 기존 존재) → 새 분석 412. 저장된 분석은 유지(정직 안내: "이후 새 분석에만 적용돼요").
   - marketing/third_party 철회 → 고객 상세 '동의 완료' 배지/상태 표시가 읽는 실제 필드·시리얼라이저를 추적해 일관되게 반영(Customer에 미러 필드가 있으면 함께 정리 — 마이그레이션은 0 유지, 기존 필드만 사용).
4. **고객 대면 카피(§6):** 철회 확인 문구는 사실+다음 행동만. 예: overseas '철회하면 새 증권 분석부터 적용돼요. 이미 정리된 자료는 그대로 볼 수 있어요.' 부정·법률 용어 금지, em-dash 금지.
5. **리드 보존기간 자동 파기 — PM 확정: 6개월(180일).** daily runner(`notifications/jobs.py::run_daily_jobs`)에 알림 생산자와 별개의 정리 단계로 탑재:
   - 대상: `lead_source`가 인바운드(셀프진단·소개카드 실제 값 확인)인 Customer 중, 활동 앵커(last_contacted_at 있으면 그것, 없으면 created_at)가 180일 초과 AND sales_stage='db' AND 보유 보험 0 AND ContactLog 0 AND Meeting 0 (= 상담 미전환). 설계사가 직접 등록한 고객은 절대 대상 아님.
   - 처리: Customer 하드 삭제(ConsentLog는 SET_NULL로 감사 로그 잔존 = 기존 문서화된 설계). 삭제 후 설계사에게 요약 알림 1건('오래 연락이 닿지 않은 잠재고객 N명의 개인정보를 정리했어요. 개인정보 보호를 위한 자동 정리예요.' — 긍정 프레임, 타입은 기존 재사용).
   - 설정: `LEAD_RETENTION_DAYS` env(기본 180). 0/미설정 음수면 스킵(안전).
   - 공개 고지: `legal/privacy` 보유기간 절에 한 줄 추가('상담으로 이어지지 않은 보장점검·상담 신청 정보는 마지막 활동일부터 6개월 후 파기'). 동의 문구(consent_texts) 버전은 올리지 않는다(고지 강화일 뿐 동의 내용 변경 아님 — v3 재동의 연쇄 방지).
   - 테스트: 180일 경계(179일=보존, 181일=삭제), 전환 흔적(보험/연락기록/미팅/단계) 있으면 보존, 직접 등록 고객 보존, 멱등.

### Tests
- GET: 동의된 scope에 revocable=true. POST revoked → 모든 unrevoked 로그 revoked_at 스탬프, 재철회 멱등.
- overseas 철회 후 OCR 게이트 412(reason=missing 또는 reconsent — 기존 로그 상태에 따라; 실동작 확인해 단언).
- 토큰 scope 밖 철회 무시. planner_attested 로그도 함께 철회됨.
- /c 재동의(철회 후 다시 agree) → 새 v2 로그 생성, 게이트 다시 열림(왕복 테스트).

## Part 2 — /s 상담 연결 버튼 (LB#8)

### Decisions (locked)
1. **BE `analytics/views.py::_build_share_payload`**: `planner_contact` 추가 — 설계사 전화번호(Profile/User의 실필드 추적; 없으면 null). booking_url 로직은 기존 그대로.
2. **FE `/s`**: '담당 설계사에게 물어보기' 클릭 시:
   - booking_url 있으면 기존처럼 예약 이동(불변).
   - 없으면 **인라인 연락 레이어** 오픈: [전화하기(tel:)] [문자하기(sms:)] (planner_contact 있을 때) + [연락 요청 남기기] 버튼. 전부 카카오톡 인앱 웹뷰에서 동작하는 표준 스킴만.
3. **연락 요청(콜백)**: 기존 `ShareEventView` 이벤트 타입에 `callback_request` 추가(스키마 화이트리스트 갱신) → 설계사에게 Notification 생성. **새 NotifType 추가 금지**(메뉴 배지 파티션 유지) — `SELF_DIAGNOSIS_LEAD` 재사용, 제목 '고객 연락 요청', 본문 '{고객명}님이 보장 안내 화면에서 연락을 요청했어요.' 같은 공유건은 하루 1회만 알림(중복 방지).
4. **고객 대면 카피**: 혜택+다음 행동만. 콜백 완료 화면 '요청을 전달했어요. 곧 연락드릴 거예요.'
5. FE `/s`는 공개 화면 — 콘텐츠 보호(워터마크 등) 기존 래핑 불변.

### Tests
- payload에 planner_contact(있음/없음 두 경우). callback_request 이벤트 → 알림 1건(owner 정확), 같은 날 재요청 → 알림 중복 0, 이벤트 로그는 기록.
- 이벤트 화이트리스트에 잘못된 타입은 기존처럼 거부.

## 공통 Verification gates
- BE check + 전체 스위트(496+) 그린, 마이그레이션 0. FE lint:copy + build 그린.
- 보고: /c 철회 UI 문구 전문, /s 레이어 문구 전문, 알림 재사용 타입, 리드 보존기간 질문(PM 결정 대기) 명시.
