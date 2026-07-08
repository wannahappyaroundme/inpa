# 담보 사전 피드백 루프 (프리런치 리뷰 #26) — Spec

> 2026-07-08. Phase 2 roadmap ①. Panel scope (features.md #26): "In-heatmap 'this 담보 looks wrong' flag routed into the existing admin unmatched-log/normalization review queue; contributor-credit gamification cut." Unblocked by LB-1 identity-true seed upsert (2026-07-04).

## 목적

설계사가 보장 한눈표에서 잘못 잡힌(또는 이상한) 담보를 한 번에 알리면, 어드민이 검수해서 정규화 사전(`NormalizationDict`, `SOURCE_ADMIN_VERIFIED`)에 반영한다. 반영된 별칭은 다음 분석부터 자동 적용(기존 `_build_normalizer` 훅이 admin_verified만 신뢰) → 데이터 복리 효과.

## 현재 상태 (탐사 결과 요약)

- 이미 있음: `UnmatchedLog`(미매칭 큐) + admin_console `admin/normalization/*` 4개 API + FE `/admin/normalization` 페이지 + `_build_normalizer` DB 사전 훅 + `seed_normalization` upsert가 admin_verified 행 보호.
- **버그(같이 수정):** FE `adminMapNormalization`이 `{unmatched_id, standard_name}`을 보내는데 BE는 `{unmatched_log_id, std_detail_id, confidence}`를 기대 — 기존 매핑 등록이 동작하지 않음. 타입 필드명도 드리프트(`insurer/count/standard_name` vs `company/occurrence/std_detail_name`).
- **갭 A:** 매칭에 성공한 담보의 원문(raw OCR name)이 저장되지 않음 → 오매칭 신고를 별칭으로 바꿀 원문이 없음.
- **갭 B:** '오매칭 신고' 모델 부재(UnmatchedLog는 미매칭 전용).

## 설계

### BE

1. **`CustomerInsuranceDetail.raw_name`** CharField(200, default '') 추가 (insurances 마이그레이션, additive). `_persist_ocr`에서 원문 저장(이후 업로드부터; 레거시 행은 빈 값 → FE는 `detail.name` 폴백). 직접 입력 경로는 빈 값 유지.
2. **`CoverageFlag` 모델** (analysis 앱, 마이그레이션): `owner` FK(User, CASCADE), `customer` FK(SET_NULL null), `analysis_detail` FK(AnalysisDetail, SET_NULL null), `case` FK(CustomerInsuranceDetail, SET_NULL null), `raw_name_snapshot` CharField(200, ''), `company` SmallInt null, `note` CharField(300, ''), `status` (open/accepted/rejected, default open), `resolved_by` FK(SET_NULL), `resolution_memo` CharField(200,''), timestamps. 인덱스: status.
3. **설계사 API:** `POST /api/v1/customers/<id>/coverage-flags/` (owner-scoped, IsOwner 패턴): `{analysis_detail_id, case_id?, note?}` → 서버가 raw_name_snapshot/company를 case에서 스냅샷. 생성 시 admin fan-out 알림(신규 `NotifType.COVERAGE_FLAG_REQUESTED`, `ADMIN_NOTIF_TYPES` 등록, `_notify_admins` 패턴 복제). 응답은 긍정 프레이밍용 최소 정보. Rate: 기존 ScopedRateThrottle 관례 따름.
4. **케이스 조회 API:** `GET /api/v1/customers/<id>/coverage-cases/?detail_id=` (owner-scoped) → 그 고객·그 표준담보에 연결된 케이스 목록 `[{case_id, insurance_id, insurance_title, name(detail_name), raw_name, assurance_amount}]`. 플래그 모달용.
5. **어드민 API:** `GET /admin/normalization/flags/?status=` (목록) · `POST /admin/normalization/flags/<id>/resolve/` `{action: 'accept'|'reject', std_detail_id?, raw_name?, memo?}`.
   - accept: `NormalizationDict.get_or_create(company, raw_name → std_detail, source=ADMIN_VERIFIED, verified_by)` + **연결 정정**: 플래그된 case의 `InsuranceDetail.analysis_detail` M2M을 새 leaf로 교체(카탈로그 행 공유 특성상 같은 이름 전체에 적용 — 사전 철학과 동일: 잘못은 전역으로 고침). 응답에 교정된 연결 수 + **substring 충돌 경고**(신규 raw_name이 기존 dict raw_name의 부분문자열이거나 그 반대면 warning 목록, 차단은 안 함).
   - reject: status만 변경 + memo.
   - 어드민 대시보드 `unresolved_unmatched` 옆에 open flag 수 추가.
6. **골든셋 게이트(#18)는 후속** — v1은 substring 충돌 경고로 대체(사전 룩업은 exact-match라 실위험 낮음).

### FE

1. **한눈표(HeatCell):** 각 leaf 행에 조용한 액션(호버/탭 시 깃발 아이콘) → 모달: 케이스 목록(coverage-cases) 중 선택(1건이면 자동) + 한 줄 메모 → 전송. 카피는 §6 준수 — 라벨 "담보 위치가 이상해요" / 완료 "알려주셔서 감사해요. 확인 후 다음 분석부터 자동으로 바로잡을게요." (부정어·'신고' 지양). 서비스 화면 light 고정.
2. **/admin/normalization:** 탭 추가 "이상 신고"(open 목록: 원문·회사·설계사 메모·현재 매핑) → 표준담보 선택 + 승인/반려. 승인 응답의 충돌 경고·교정 수 표시.
3. **계약 정합 버그픽스:** `adminMapNormalization` payload를 `{unmatched_log_id, std_detail_id, confidence}`로, 타입 필드 `company/occurrence/std_detail_name`으로 정정(BE가 SSOT).
4. `lib/api.ts`(설계사용 2개) + `lib/adminApi.ts`(어드민 2개) 확장.

### 테스트

- flag 생성: owner-scoping(타인 고객 404), case 스냅샷, 알림 fan-out, 중복 생성 허용(동일 leaf 재신고는 새 행).
- resolve accept: dict 행 생성(admin_verified) + M2M 교체 수 + 충돌 경고 케이스, reject 경로.
- coverage-cases: 소유 격리, raw_name 폴백.
- `_persist_ocr` raw_name 저장 회귀.
- 기존 계약 버그픽스: admin map 정상 동작 회귀(BE 테스트 이미 있음 → FE는 build 게이트).

### 마이그레이션

2건 (insurances: raw_name 추가 / analysis: CoverageFlag). 모두 additive, 데이터 마이그레이션 없음.

### 컴플라이언스/카피 가드

- 고객 대면 화면(/s /d /c /b) 변화 없음. 신고 UI는 설계사 내부 화면 전용.
- 판정어·등급 무관(매핑 위치만 다룸). 허위 문구 없음. em-dash 금지, 긍정 프레이밍.
