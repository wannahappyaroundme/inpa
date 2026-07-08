# 공유(/s) 스냅샷 보관 (프리런치 리뷰 #27) — Spec

> 2026-07-08. Phase 2 로드맵 ②. Panel scope (#27): "Immutable comparison snapshot archive — point-in-time denormalized JSON on the share record (literal coverage names/figures, consent state, dict+matcher version stamp, timestamp), zero FKs to the standard tree, PII-minimized mirroring the /s payload, retention TTL, inclusion in withdrawal/deletion automation." Sequenced after backups(H-3, done) + seed fix(LB-1, done).

## PM 확정 결정 (2026-07-08)
- **보존기간 = 180일(6개월)**, 리드 파기(`LEAD_RETENTION_DAYS`)와 동일. 경과 시 자동 삭제.
- **스코프 = 공유(/s) 스냅샷.** 비교(갈아타기) 공유 기능은 §97로 막혀 있어 존재하지 않음 → 고객이 실제로 받는 유일한 화면 = 한눈표 공유(/s). 그 시점 /s 페이로드를 박제. 목적(승환 분쟁 시 "그때 무엇을 보여줬는가" 증거)은 동일 달성.

## 핵심 사실 (탐사 결과)
- 공유 레코드 모델 부재. 공유는 `Customer`의 4필드(`share_token`/`share_expires_at`/`share_sent_at`/`user_view_at`)뿐이고 `/s`는 매 요청 `_build_share_payload(customer)`로 즉석 계산(`analytics/views.py:238`).
- 공유 생성 = `CustomerShareCreateView.post`(`analytics/views.py:395`, 토큰 회전 + `SHARE_TTL_DAYS=90` + `NorthStarEvent.SHARE_CREATED` 로그). FE `ShareLinkButton`→`createShareLink`.
- `/s` 페이로드는 이미 PII 최소화: 이름 마스킹(`홍**`)·birth_year만·전화/메모/병력 없음·판정(verdict/switch_warnings) 절대 미포함(회귀테스트 `test_share_view_excludes_planner_verdict`). 스냅샷은 이 shape을 **그대로** 복제(추가 PII 금지).
- 동의 현재상태 = `has_current_overseas_consent(customer)` + `CONSENT_TEXTS_VERSION='v2-2026-07-04'`. `ConsentLog`는 append-only, customer SET_NULL.
- 사전 버전 = `SeedMarker(key='seed_normalization').version`(live) fallback 코드 `SEED_VERSION`. 매처는 코드 버전만.
- 파기 자동화 = `notifications/jobs.py::cleanup_expired_leads` + `run_daily_jobs`(08:00 KST cron). 동의 철회 = `customers/public_consent.py::_apply_revocations`(현재 revoked_at 스탬프만, 삭제 없음).
- 불변 복제 선례 = `CoverageFlag.raw_name_snapshot`(생성 시 원본에서 값 복제). append-only 선례 = `ConsentLog`/`NorthStarEvent`(JSONField `payload`).

## 설계

### BE — 모델 (analytics 앱, 마이그레이션)
`ShareSnapshot` (append-only, 생성 후 수정 없음):
- `owner` FK(User, CASCADE) — 소유 스코프
- `customer` FK(Customer, **CASCADE**) — 고객 삭제 시 PII 동반 삭제(ConsentLog의 SET_NULL과 다름: 스냅샷은 비정규화 PII를 들고 있으므로 고객과 함께 파기)
- `share_token` UUIDField(null) — 캡처 시점 토큰(상관용, unique 아님)
- `payload` JSONField(default dict) — `_build_share_payload(customer)` 결과 통째 박제(담보명·held_amount·summary·tree·mode·disclaimer). **표준트리 FK 없음 = 불변.**
- `consent_overseas` Bool — 캡처 시점 `has_current_overseas_consent`
- `consent_doc_version` CharField — 캡처 시점 `CONSENT_TEXTS_VERSION`
- `consent_scopes` JSONField(default list) — 캡처 시점 유효(미철회) customer_self 동의 scope 목록
- `dict_version` CharField — `SeedMarker seed_normalization` version(live) fallback 코드 `SEED_VERSION`
- `insurance_count` SmallInt — 캡처 시점 보유 보험 수(요약 편의)
- `captured_at` DateTimeField(auto_now_add) — 불변 타임스탬프
- `retention_expires_at` DateTimeField(db_index) — `captured_at + SHARE_SNAPSHOT_RETENTION_DAYS`
- Meta: ordering `-captured_at`, index (owner, customer), index (retention_expires_at).

`settings/base.py`: `SHARE_SNAPSHOT_RETENTION_DAYS = env.int(default=180)`.

### BE — 캡처
`CustomerShareCreateView.post`(analytics/views.py): 토큰 회전·저장 후, `payload = _build_share_payload(customer)` 재사용(이미 계산되면 재사용, 아니면 호출) → `ShareSnapshot.objects.create(...)`. 동의/사전 버전은 헬퍼로 계산. **캡처 실패가 공유 링크 발급을 막지 않도록** try/except로 격리(로그만; 링크는 정상 발급). `retention_expires_at`은 `timezone.now() + timedelta(days=SHARE_SNAPSHOT_RETENTION_DAYS)`.

### BE — 조회 API (설계사, owner-scoped)
- `GET /api/v1/customers/<id>/share-snapshots/` → 그 고객의 스냅샷 목록(최신순): `[{id, captured_at, retention_expires_at, insurance_count, consent_overseas, consent_doc_version, dict_version}]`(payload 미포함 = 목록 경량).
- `GET /api/v1/customers/<id>/share-snapshots/<snap_id>/` → 단건 상세(payload 포함, 소유 격리 404). 프론트가 그 시점 화면을 재구성.
- 소유 격리는 heatmap/flags 뷰 패턴(`_get_customer` owner 스코프) 복제. 어드민 read 우회는 기존 관례 따름(쓰기 없음 = 캡처는 서버 자동).

### BE — 파기 자동화 (2경로 + FK)
1. **TTL 파기:** `notifications/jobs.py`에 `cleanup_expired_share_snapshots(now)` 신설 → `ShareSnapshot.objects.filter(retention_expires_at__lte=now).delete()`, `run_daily_jobs`에 `cleanup_expired_leads`와 나란히 단계 추가(요약 로그). KST 앵커(`timezone.now()` UTC 비교는 안전 — retention_expires_at도 aware).
2. **동의 철회 파기:** `public_consent.py::_apply_revocations`에서 **personal_info** scope 철회 시 그 고객의 `ShareSnapshot` 전량 삭제(고객이 "내 정보 보관 중단" 요청 = 공유 기록도 파기). 다른 scope 철회는 스냅샷 유지(overseas는 Claude 전송용이라 무관).
3. **고객 삭제:** FK CASCADE로 자동(별도 코드 불필요; `cleanup_expired_leads`의 고객 삭제도 함께 파기됨).

### FE (설계사 내부 화면)
- 고객 상세에 **'공유 기록'** 섹션/모달: 스냅샷 목록(공유한 날짜·보험 수·동의 상태·자동삭제 예정일) → 항목 클릭 시 그 시점 화면 재구성(payload의 tree를 기존 공유뷰 렌더러 재사용해 읽기전용 표시). 카피 §6 준수(긍정·쉬운 말; '박제/스냅샷' 같은 기술어 대신 "공유 기록", "그때 보여드린 화면"). em-dash 금지. **설계사 내부 화면 = light 고정.**
- 목적 안내 1줄(내부용, 담담한 사실): "고객에게 공유한 시점의 화면을 기록으로 남깁니다. 6개월 후 자동 삭제됩니다."
- `lib/api.ts`: `listShareSnapshots`, `getShareSnapshot` + 타입.

### 테스트 (BE)
- 캡처: 공유 생성 시 스냅샷 1건 생성, payload가 `_build_share_payload`와 일치, 동의/사전 버전 스탬프 정확, `retention_expires_at = captured_at + 180d`.
- 불변/무FK: payload에 표준트리 id가 있어도 이후 트리 변경이 스냅샷 payload에 영향 없음(값 복제 확인).
- PII 레드라인: 스냅샷 payload에 verdict/switch_warnings/전화/메모/병력 없음 + 이름 마스킹·birth_year만(공유뷰와 동일 회귀).
- 소유 격리: 타 설계사 고객 스냅샷 목록/상세 404.
- 캡처 실패 격리: `_build_share_payload` 예외 시에도 공유 링크는 201(스냅샷만 스킵).
- TTL 파기: 180일 초과 스냅샷 삭제, 미만 보존(`@override_settings` days 조정).
- 동의 철회 파기: personal_info 철회 시 그 고객 스냅샷 삭제, 타 고객·타 scope는 보존.
- 고객 삭제 CASCADE: 고객 delete 시 스냅샷 삭제.
- `run_daily_jobs` 멱등: 재실행 시 중복 삭제 없음(이미 삭제됨), 하트비트 유지.

### 마이그레이션
1건(analytics: ShareSnapshot). additive.

### 컴플라이언스 레드라인
- 스냅샷은 `/s` 페이로드 미러 = 이미 PII 최소화. **추가 PII 절대 금지.** verdict/switch_warnings 유입 차단(공유뷰가 애초에 미포함이므로 payload 복제만으로 안전, 회귀테스트로 고정).
- 보존기간 유한(180일) + 파기 자동화 = "증권 원본 미보관" PIPA 자산 유지(Seo/Dr. Im 조건). 개인정보처리방침에 보관 항목/기간 1줄 추가 필요(문서 갱신 단계, 후속).
- 고객 대면 화면(/s·/d·/c·/b) 무변경. 조회 UI는 설계사 내부 전용.
- 문서: privacy 페이지에 "공유 기록(담보명·금액·동의 상태) 6개월 보관 후 파기" 고지 추가(구현에 포함).
