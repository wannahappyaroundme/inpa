# Spec: 권유 단어 자동 차단(#23) + 팀 초대 링크(#24)

## Part 1 — 권유 단어 블랙리스트 (#23, §97 자동 방어)

1. **CI(FE)**: `check-copy.js` RULES에 **고객 대면 라우트 한정** 단어 규칙 추가 — 적용 범위: `app/s/**, app/b/**, app/c/**, app/d/**, app/p/**` 렌더 문자열만(주석 제외 휴리스틱 기존 재사용, 파일 경로 필터 지원을 RULES 구조에 추가). 금지 패턴: `추천(?!인)`, `갈아타`, `해지하(세요|시는 게|시길)`, `더 유리`, `가입하세요`, `전환하세요`. 추가 후 `lint:copy` 0 위반이어야 함(위반 발견 시 해당 문구를 중립 표현으로 수정).
2. **BE 서버측 가드**: `analytics` 공유 페이로드(`_build_share_payload`)와 셀프진단 응답의 **고정 카피 필드**(disclaimer 등 코드가 넣는 문자열)에 대해 `contains_advice_words()` 유틸 검사 — 발견 시 logger.error(고객 화면은 깨지 않음, 관측만). 데이터 필드(고객 이름·담보명·금액)는 검사 대상 아님(오탐 방지). 유닛 테스트로 유틸 + 현행 페이로드 클린 단언.
3. 문서화: check-copy.js 헤더 주석에 규칙 근거(§97·금소법, dev/14) 1줄.

## Part 2 — 팀 초대 링크 (#24, 동의 침해 없는 방식)

1. **BE**:
   - `POST /api/v1/manager/invite-link/` (인증 설계사 누구나 = 자기 팀을 만들 관리자): TimestampSigner 토큰(payload = manager user pk), TTL 7일. 응답 `{url}` = `FRONTEND_BASE_URL/register?invite=<token>`.
   - `GET /api/v1/manager/invite-info/?token=` (AllowAny, throttled): 유효하면 `{manager_name, affiliation}`, 무효/만료면 404(FE는 칩 없이 일반 가입으로 진행 — 막지 않는다).
   - `RegisterSerializer`에 optional `invite_token`: 유효하면 생성되는 Profile에 `manager` FK + (비어 있으면) `affiliation` 프리셋. **`manager_share_level`은 절대 건드리지 않음(기본 none — 신입이 설정에서 직접 선택, PIPA-clean 합의사항)**. 무효 토큰이 와도 가입은 성공(토큰만 무시 + 로그) — 초대 링크가 만료됐다고 가입까지 막지 않는다.
2. **FE**:
   - `/manager` 페이지에 '팀 초대 링크' 카드: 버튼 → 링크 생성·복사(공유 위젯 패턴 재사용). 안내 1줄: '이 링크로 가입한 설계사는 내 팀으로 연결돼요. 성과 공유 여부는 본인이 설정에서 선택해요.'
   - `/register`: `?invite=` 있으면 invite-info 조회 → 상단 칩 '{소속} {이름}님의 팀 초대로 가입 중' (무효면 칩 미표시, 정상 가입). 가입 payload에 invite_token 동봉.
3. 마이그레이션 0(Profile.manager·affiliation 기존 필드).

## Redlines / Tests
- planner_attested·동의 관련 코드 무접촉. 초대 토큰은 share 동의를 절대 프리셋하지 않음(회귀 테스트 필수).
- 테스트: 토큰 왕복(생성→가입→manager 연결), TTL 만료(404 + 가입은 성공), share_level=none 유지, affiliation 기존값 보존(프리셋은 빈 값일 때만), invite-info 무효 404. BE 전체 스위트 그린 + FE build/lint.
