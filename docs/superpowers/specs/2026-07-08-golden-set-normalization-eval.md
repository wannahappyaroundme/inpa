# 골든셋 정규화 정확도 기준선 (프리런치 리뷰 #18) — Spec

> 2026-07-08. Phase 2 로드맵 ③(PM이 #29 대신 선택). Panel scope (#18): "Golden-set normalization eval harness — a CI-run labeled corpus (from prod unmatched logs and concierge sessions, de-identified/provenance-clean, NEVER from carrier documents or samples/) mapping real coverage names to standard-tree leaves, with an accuracy threshold gating dict and matcher changes." Sequenced after LB-1 seed fix(done). 목적: 사전=유일 취득 자산(Seo)의 정확도를 측정·회귀 방지 + #26 커뮤니티 루프의 병합 게이트(Ha-eun).

## 배경 사실 (탐사 결과)
- 정답 데이터 = **`NORMALIZATION_V0`(seed_normalization.py:236, 326개 `(company, raw_name, std_name)` 튜플)**. 인파 자체 큐레이션 사전이라 **출처 깨끗**(보험사 원본 문서·samples/ 아님 — 패널 provenance 조건 충족).
- 결정적 매처(Claude 없이): `claude_parser.py::_match_by_keywords(raw_name)` → 파서 경로('cat->sub->det') → `coverage_bridge.py::resolve_std_detail(cat,sub,det)` → 표준 `AnalysisDetail`(std_name). `ocrparsing.py::_match_coverage`는 동일 로직.
- ★ **중요:** prod의 DB normalizer(`insurances/views.py::_build_normalizer`)는 `source=ADMIN_VERIFIED`만 신뢰. seed 사전(`NORMALIZATION_V0`)은 `source=SEED`라 **매칭 시 dict 조회에 안 쓰이고 키워드 매처로 매칭**됨. → NORMALIZATION_V0 raw_name을 키워드 매처에 돌리는 것은 **비순환·진짜 검증**(키워드 매처가 큐레이션 매핑을 재현하는지).
- 함정 앵커(gotchas §7): 상피내암≠암진단, 질병중환자실입원일당≠일반 중환자실입원일당, 수술 키워드≠진단비 경로, 입원≠실손 경로. 반드시 통과해야 하는 회귀 케이스.
- DB dict 조회는 **exact-match**(substring 아님) → admin 별칭 추가는 그 raw_name에만 영향(타 담보 substring 오라우팅 위험은 dict가 아니라 **COVERAGE_KEYWORDS 코드**에 있음). 따라서 골든셋 게이트의 1차 가치 = **코드(COVERAGE_KEYWORDS/PARSER_TO_STD/STANDARD_TREE) 변경 회귀 차단**.

## 설계 (마이그레이션 0)

### 1. 골든셋 코퍼스
- `inpa_be/inpa/analysis/data/golden_set.json` (또는 golden_set.py 모듈): 엔트리 `[{company, raw_name, expected_std_leaf, source, note?}]`.
- 부트스트랩: `NORMALIZATION_V0` 326개(source='seed_dict') + **함정 앵커 세트**(source='anchor', 반드시 통과) 명시. 앵커는 오답이 아니라 '올바른 매핑'을 못박는 것(상피내암→상피내암진단비, 질병중환자실→해당 표준, 등).
- 파일 상단 provenance 주석: "인파 자체 큐레이션 사전 + 회귀 앵커. 보험사 원본 문서·samples/ 미포함. 신규 항목은 #26 승인 별칭에서 유래(de-identified)."
- **성장 경로:** #26 어드민 승인(accept) 시 그 `(company, raw_name, std_leaf)`를 골든셋에 append 후보로 로그(자동 파일수정은 안 함 — 리뷰 후 수기 반영. 이유: golden_set은 CI 게이트라 무검증 자동증식 금지).

### 2. 채점기
- `inpa_be/inpa/analysis/golden_eval.py::evaluate_golden_set(entries=None) -> dict`:
  - 각 엔트리에 대해 **prod와 동일 파이프라인** 실행: (a) admin_verified dict 조회(있으면) → (b) 없으면 `_match_by_keywords` → `resolve_std_detail` → 표준 leaf name.
  - 반환 `{total, passed, failed, accuracy(0~1), anchor_total, anchor_passed, failures:[{company, raw_name, expected, got}], anchor_failures:[...]}`.
  - 표준 트리 부재(테스트 DB)시 graceful: leaf name 비교는 std_name 문자열 기준(resolve가 None이어도 파서 경로의 최종 det로 비교하는 폴백은 두지 않음 — 실제 매칭 결과만 채점).
- 순수 함수(부작용 0), DB 읽기만.

### 3. CI 게이트 (핵심 산출물)
- `inpa_be/inpa/analysis/tests.py::GoldenSetGateTests`:
  - `test_accuracy_above_ratchet`: `evaluate_golden_set()['accuracy'] >= GOLDEN_SET_MIN_ACCURACY`. **임계값은 구현자가 실측한 baseline으로 고정(ratchet = 회귀 방지선, 임의의 95%가 아님).** 상수는 `analysis/golden_eval.py::GOLDEN_SET_MIN_ACCURACY`.
  - `test_all_anchors_pass`: 함정 앵커 100% 통과(anchor_failures == []).
  - setUp에서 표준 트리+seed dict 최소 시드(seed_normalization 호출 또는 필요한 leaf만). CI는 이미 `test inpa`를 돌리므로 자동 게이트.
- 실측 baseline이 낮으면(키워드 매처가 재현 못 하는 seed 항목 다수) → 임계값을 그 실측치로 두고, 낮은 이유(어떤 항목이 왜 실패하는지)를 스펙 리뷰에 리포트. 개선은 후속(사전을 admin_verified로 승격하거나 키워드 보강).

### 4. 관리자 명령 + 가시성
- `manage.py eval_normalization [--verbose]` → 정확도·실패 목록 출력(운영/PM 확인용). render startCommand에는 **넣지 않음**(게이트는 CI 담당).
- 어드민 API `GET /api/v1/admin/normalization/accuracy/`(IsAdmin) → `{accuracy, total, passed, anchor_passed, anchor_total, sample_failures:[…up to 20]}`. FE `/admin/normalization`에 '사전 정확도 기준선' 카드(정확도 %, 실패 N건 접기). 다크 admin 관례.

### 5. #26 accept 연동 (게이트 격상)
- `admin_console/views.py::AdminCoverageFlagResolveView` accept 응답에 골든셋 관점 추가:
  - 승인한 `(company, raw_name → std_leaf)`가 기존 골든셋 엔트리와 **충돌**(같은 raw_name이 다른 leaf를 기대)하면 응답 warnings에 명시(어드민이 인지). exact-match라 타 담보 오라우팅은 없으나, "이 승인이 골든셋 기대와 다르다"는 신호는 가치.
  - 승인 후 전체 정확도를 재계산해 응답 `golden_accuracy`로 첨부(변화 가시화). 비차단(경고).
- 기존 substring 충돌 경고는 유지(별개 신호).

### 6. 테스트
- `evaluate_golden_set` 유닛: 앵커 통과, 일부러 틀린 엔트리 주입 시 failures 포착, accuracy 계산 정확.
- 게이트 테스트 2종(위 3).
- 관리자 accuracy API: IsAdmin 격리(설계사 403), 응답 shape.
- `eval_normalization` 커맨드: 실행·비영 종료코드(정확도 정상 시 0), 실패 시 리포트.
- #26 accept 충돌 경고: 골든셋과 다른 leaf 승인 시 warning 포함.

### 마이그레이션 / 컴플라이언스
- 마이그레이션 0(골든셋=파일, 채점=코드, 점수=on-demand).
- 고객 대면·PII 무관(담보명은 표준 용어, 개인정보 아님). samples/·보험사 원본 문서 **절대 미참조**(NORMALIZATION_V0만). 카피 규칙: 관리자 카드 문구 §6 준수(em-dash 금지, '정확도 기준선' 등 사실 표현).
- FE build + lint:copy 게이트.
