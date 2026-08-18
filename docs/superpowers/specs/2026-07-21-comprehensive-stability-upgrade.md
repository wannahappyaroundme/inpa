# 인파 종합 안정화·신뢰성 업그레이드 설계

> 날짜: 2026-07-21  
> 상태: PM 상세 명세 최종 승인, 구현 계획 확정 단계  
> 우선순위: 새 기능보다 운영 안정성·실제 버그·산출물 사실성  
> 배포 원칙: Preview 검증 후 Production은 PM의 별도 명시 승인 필요

## 1. 결론

이번 작업은 전면 재작성이나 기능 확장이 아니다. 운영 중인 서비스에서 확인된 계산 오류, 개인정보 수명주기 결함, 예약 상태 불일치, 오류를 정상 데이터처럼 보이는 화면, 사실과 다른 카피를 위험 순서대로 고치는 안정화 프로그램이다.

채택한 방식은 **위험 우선 단계형 안정화**다.

1. Release 1: 핵심 판정·동의·공유·산출물 사실성
2. Release 2: 데이터 손실·오류 상태·시간대·입력 계약
3. Release 3: 예약 상태기계·Google Calendar 동기화
4. Release 4: 품질 게이트·운영 선언·계측·의존성

각 Release는 독립 테스트와 롤백 경계를 가진다. 큰 리팩터링과 기능 추가를 한 번에 섞지 않는다.

## 2. 범위

### 포함

- 보장 기준선의 금액 단위, 상품군, 연령대, 성별 판정 계약
- 셀프진단의 외부 AI 호출 전 동의 증적
- 공유 링크 발급·만료·철회·과거 링크 호환 수명주기
- 여러 증권 비교, 공유 스냅샷, 영업 문구의 사실성
- 예약 설정 로드 실패와 부분 저장
- 소개카드 상담 신청의 연락 수단 계약
- API 오류와 실제 빈 데이터 상태 분리
- 공개 링크의 만료 오류와 일시 장애 분리
- 고객 검색·캘린더의 요청 경합
- KST 벽시계 변환과 실제 날짜 검증
- 미팅 수락·거절·취소 상태기계와 Google Calendar 생성·삭제·재시도
- 업무시간 중복·겹침과 공개 예약 기간 계약
- Render Blueprint 드리프트, 평가 명령 테스트 독립성, 의존성 업데이트 정책
- 베타 사용량 측정과 한도 차단 분리
- 접근성·오류 경계·E2E 회귀 게이트

### 제외

- 현재 다른 작업에서 수정 중인 랜딩, 게시판 시드, Manager 3단 요금제 파일
- 보험 검토형 파이프라인 운영 게이트 개방
- 의료정보 수집, 비교안내서 발행, 유료 quota 운영 개방
- 새로운 모바일 앱, 신규 판매 기능, 대규모 기술 스택 교체
- Production 배포와 유료 인프라 변경

동시 작업 파일은 그대로 보존한다. 이번 구현에서 필요한 내용이 겹치면 해당 작업이 정리된 뒤 최신 기준으로 재검토한다.

## 3. 확인된 기준 상태

### 통과

- Frontend 단위 테스트: 101개
- Frontend 카피 검사: 221개 파일, 0건
- Next.js Production build: 69개 라우트
- 공개 페이지 모바일 390px: 가로 넘침과 콘솔 오류 없음
- Django system check
- Django migration dry-run: 새 변경 없음
- Boards 대상 테스트: 96개
- `git diff --check`

### 미통과·관찰

- Backend 전체 테스트는 1,676개 진행 시 평가 명령 테스트 1개가 `E_DATASET_PATH`로 오류, 17개 skip
- 단일 오류는 제품 API 실패가 아니라 삭제된 임시 Git worktree가 `prunable` 상태로 등록된 로컬 환경에서 평가 명령이 모든 경로 검사를 중단하는 문제
- 동일 테스트 단독 재현 완료
- 유효한 현재 worktree만 주입하면 테스트용 private dataset 100건 검증 성공
- npm 의존성은 `postcss` 계열 transitive moderate 5건. 강제 수정은 Next.js 대규모 다운그레이드를 제안하므로 적용 금지
- 프로젝트 Python runtime 의존성에는 알려진 취약점이 없었고, 임시 감사 환경의 pip/setuptools 경고만 확인

현재 통과 결과는 기존 코드의 모든 의미가 올바르다는 뜻이 아니다. 보장 기준선처럼 잘못된 계약을 그대로 기대하는 테스트도 있어, 아래 골든 회귀 테스트가 새로 필요하다.

## 4. 페르소나 협의체

### 구성

세 개의 독립 협의체로 나누어 같은 코드를 서로 다른 기준으로 검토했다.

- 제품·사업·성장: 대표, 기획자, 브랜드·PR 마케터, 퍼포먼스 마케터, 그로스·분석, CS, 보험 도메인
- 화면·경험·품질: UI/UX 전문 프런트 개발자, UI/UX 디자이너, 브랜드 디자이너, 접근성, QA
- 서버·데이터·위험: 백엔드·데이터 개발자, 보안·인프라, 법무·컴플라이언스, QA

### Round 1: 독립 감사

- 제품 협의체는 결정론 비교의 AI 오표시, 초록·빨강 우열 암시, 과거 스냅샷의 현재형 표현, 고객 화면의 설계사용 문구, 영업 문구의 가짜 번호와 검증 불가 주장을 우선 제기했다.
- 화면 협의체는 예약 설정 덮어쓰기, 연락처 없는 상담 신청, 오류를 빈 상태로 표현하는 분석 화면, 검색·캘린더 요청 경합, 브라우저 시간대 의존, 공개 링크의 재시도 부재를 제기했다.
- 서버 협의체는 보장 기준선의 단위·범위 오류, 미발급 공유 토큰 fallback, 외부 AI 호출 후 동의 기록, 예약 accept/cancel 경합, Google 일정 잔존, Render 선언 드리프트를 제기했다.

### Round 2: 공격·방어

- 320px 랜딩 오버플로는 운영 HEAD가 아니라 현재 미커밋 동시 작업 위험으로 판정해 구현 범위에서 제외했다.
- robots, 키보드 접근성, 전역 오류 경계는 실제 결함이지만 데이터 진실성보다 낮은 P2 품질 게이트로 내렸다.
- 공유 fallback은 UUID 열거가 사실상 불가능하고 legacy 호환 의도가 테스트로 고정된 점을 반영해 Critical에서 High로 내렸다.
- 셀프진단은 checkbox를 AI 호출 전에 확인하므로 “무동의 전송” 주장은 기각했다. 다만 호출 후 DB 장애 시 동의 증적이 사라지는 감사 결함은 High로 유지했다.
- 예약 생성 자체의 동일 시간 이중 예약 방어는 정상으로 확인했다. 결함 범위는 수락·취소 이후와 외부 캘린더 동기화로 한정했다.

### Round 3: 최종 조정

- 보장 기준선은 화면의 기본 단위가 만원, preset도 만원, 실제 held amount는 원인데 숫자를 그대로 비교한다는 직접 증거로 Critical에 만장일치했다.
- 여러 증권 비교의 결정론 계산 자체와 신규 v2 공유의 불변 스냅샷·회수·만료·소유자 격리는 정상으로 확인했다.
- 운영 신뢰를 우선해 P0 7개, 최우선 P1 3개, Release 3 동반 보강과 후속 품질 P2로 확정했다.

## 5. 점수 기반 종합

점수는 코드 경로와 사용자 노출을 기준으로 한 상대 우선순위다. 실제 운영 발생률 통계가 없는 항목은 보수적으로 추정했다.

`총점 = 피해 심각도 40% + 노출 가능성 25% + 신뢰·사업 영향 20% + 수정 레버리지 15%`

각 항목은 1~5점, 총점은 100점 환산이다.

| 순위 | 항목 | 총점 | 등급 | 결정 |
|---:|---|---:|---|---|
| 1 | 보장 기준선 단위·상품군·연령·성별 오류 | 100 | Critical | P0, 자동 판정 fail-closed |
| 2 | 비교·공유·영업 문구 사실성 | 92 | High | P0, 고객 노출 즉시 정정 |
| 3 | 연락처 없는 소개카드 상담 신청 | 87 | High | P0, 휴대폰 FE·BE 필수 |
| 4 | 외부 AI 호출 후 동의 증적 저장 | 86 | High | P0, 동의 receipt 선커밋 |
| 5 | 예약 설정 로드 실패 후 덮어쓰기 | 82 | High | P0, 로드 전 저장 차단 |
| 6 | 예약 상태·Google Calendar 불일치 | 77 | High | P0, DB 상태기계+outbox |
| 7 | 분석 오류를 실제 빈 고객으로 표현 | 75 | High | P0, 오류·빈 상태 분리 |
| 8 | 미발급 Customer 공유 token fallback | 74 | High | P1, 감사 후 종료 |
| 9 | Render Blueprint Starter/free 드리프트 | 73 | High 운영위험 | P1, 실제 설정 대조 후 정합 |
| 10 | 캘린더 요청 경합·브라우저 시간대 | 70 | Medium-High | P1, latest-wins+KST |
| 11 | WorkHour 오류·중복·겹침 | 68 | Medium-High | Release 3 동반 보강 |
| 12 | 평가 명령의 stale worktree 의존 | 52 | Medium 개발도구 | P2, hermetic test |

P0와 P1은 발생 순서가 아니라 릴리스 차단 순서다. 각 항목의 실제 구현은 파일 충돌과 마이그레이션 의존성을 고려해 작은 배치로 나눈다.

## 6. 대안과 채택 이유

| 대안 | 장점 | 단점 | 판정 |
|---|---|---|---|
| P0 긴급 패치만 | 가장 빠른 핵심 위험 차단 | UX·예약·운영 부채가 남음 | 일부만 채택, Release 1 |
| 위험 우선 단계형 안정화 | 회귀와 배포 위험을 릴리스별로 통제 | 여러 검증 마디 필요 | 채택 |
| 전면 일괄 개편 | 중복 구조를 한 번에 정리 | 운영 서비스와 동시 작업에서 회귀 반경이 큼 | 기각 |

## 7. Release 1 설계: 핵심 안전성과 사실성

### 7.1 보장 기준선

#### 안전 장치

- `HEATMAP_GRADING_ENABLED`를 새 운영 게이트로 둔다.
- 기본값과 Production 초기값은 `False`다.
- 게이트가 닫히면 모든 담보 상태는 `neutral`이며, 보유금액 사실만 표시한다.
- 코드 수정과 테스트 통과만으로 게이트를 열지 않는다. 신뢰할 수 있는 비식별 gold set과 보험 도메인 검토를 별도 통과해야 한다.

#### 금액 단위

- 판정 내부 표준은 정수 원 단위다.
- `unit=1(만원)`: Decimal 값에 10,000을 곱해 원으로 변환한다.
- `unit=2(원)`: 그대로 사용한다.
- `unit=3(구좌)`: 자동 금액 판정에서 제외하고 `neutral`로 둔다.
- float 비교를 금지하고 Decimal 또는 정수로 판정한다.
- 설정 화면은 사용자가 입력한 단위를 보존하되, 히트맵 API의 판정용 값은 서버가 정규화한다. FE가 재계산하지 않는다.

#### 적용 범위

- `coverage_key`, 상품군, 연령대, 성별을 모두 판정 키로 사용한다.
- 연령대가 정확히 일치해야 한다. 생년월일이 없거나 실제 날짜가 아니면 `neutral`이다.
- 성별은 `고객 성별 exact → gender=null 공통` 순서만 허용한다. 다른 성별을 사용하지 않는다.
- 현재 분석 트리는 생명/손해 2분류만 명확하다.
  - 생명 카테고리는 생명 기준만 사용한다.
  - 손해 카테고리는 손해 기준만 사용한다.
  - 실손·연금저축처럼 4분류를 명확히 식별할 수 없는 기준은 트리 계약이 확장되기 전까지 `neutral`이다.
- 후보가 두 개 이상이거나 적용 범위가 모호하면 임의 최고점 선택 대신 `neutral`이다.

#### 화면 상태

- 기준이 없을 때: `기준 설정하기`
- 기준은 있으나 판정 게이트가 닫혔을 때: `설정한 기준 확인하기`
- 기준이 적용되지 않는 구좌·불명확 상품군: 보유금액만 표시하고 판단 색·라벨을 표시하지 않는다.
- 내부 위험 용어와 운영 게이트 표현은 설계사 화면에도 노출하지 않는다.

#### 필수 골든 테스트

- 5,000만원 기준과 50,000,000원 보유액이 같은 값
- 3,000만원 기준에 20,000,000원은 부족
- 원 단위 기준은 추가 변환 없음
- 구좌는 neutral
- 30대 남 기준이 60대 여성에게 적용되지 않음
- 30대 성별 공통은 30대 남·여에게 fallback
- 생명 기준이 손해 카테고리에 적용되지 않음
- 실재하지 않는 생년월일은 neutral

### 7.2 셀프진단 동의 증적

처리 순서를 두 트랜잭션으로 분리한다.

1. 요청 형식, 실제 날짜, 전화번호, 파일 크기·형식, 일일 한도, provider 설정을 먼저 검증한다.
2. 첫 DB 트랜잭션에서 고객을 idempotent하게 생성·재사용하고 개인정보·국외이전 동의 로그를 저장한다.
3. 첫 트랜잭션 커밋 후에만 외부 AI를 호출한다.
4. 두 번째 DB 트랜잭션에서 성공한 보험·담보 결과와 처리 상태를 저장한다.

정책:

- AI 파싱이 실패해도 고객이 직접 제출한 동의 receipt는 기존 보존 정책에 따라 남긴다.
- provider 실패는 원문·응답 내용을 로그에 남기지 않고 결과 enum, token count, 비용, 오류 유형만 남긴다.
- 동일 요청의 재시도는 기존 고객을 재사용하고 보험 지문 중복 방지를 유지한다.
- 일부 파일 실패는 요청 전체를 실패시키지 않는다. 성공한 파일은 저장하고 실패 파일은 다음 행동을 안내한다.

### 7.3 공유 링크 수명주기

- 신규 공유의 유일한 공개 권위는 `ShareSnapshot.share_token`이다.
- `INSURANCE_REVIEW_GATE_ENABLED`와 legacy 공유 호환을 분리한다.
- `LEGACY_SHARE_FALLBACK_ENABLED`를 별도 게이트로 두고 기본값은 `False`다.
- Customer 생성 시 자동 UUID가 있더라도 `ShareSnapshot` 또는 검증된 과거 발급 기록이 없으면 공개 API는 404를 반환한다.
- `share_token`, `share_sent_at`, `share_expires_at`, 철회 관련 필드는 일반 Customer PATCH에서 모두 읽기 전용이다.
- 철회된 링크는 다른 필드 PATCH로 다시 열 수 없다.

전환 순서:

1. Production에서 기존 감사 명령을 dry-run으로 실행해 실제 발급 링크, v1 snapshot, 미발급 token 수만 확인한다.
2. 결과에는 고객명·전화번호·토큰 원문을 출력하지 않는다.
3. 실제 과거 발급분에 필요한 한시 정책을 확정한다.
4. 미발급 token은 즉시 fail-closed한다.
5. fallback을 종료한 뒤 신규 v2 발급·열람·철회·만료를 실제 API로 확인한다.

Production 감사 명령 실행과 fallback 종료는 별도 운영 승인 대상이다.

### 7.4 비교·공유·영업 문구 사실성

#### 여러 증권 비교

- 숫자와 delta는 결정론 계산 결과다.
- AI가 실제 생성한 `guide_draft`가 있을 때만 AI 참고자료 문구를 노출한다.
- API는 산출 출처를 명시적으로 구분한다. 예: `comparison_source=deterministic`, `guide_source=ai|null`.
- 증감·추가·삭제는 회색 계열과 텍스트·아이콘으로 구분한다. 초록·빨강으로 좋고 나쁨을 암시하지 않는다.
- malformed ID, 현재 고객에게 없는 ID, 삭제된 ID와 명시적인 빈 선택을 구분한다.
- 기본 제품 계약은 A/B 각 1건 이상이다. 잘못된 선택은 400 또는 409로 반환하며 0건 사실 데이터처럼 렌더하지 않는다.

#### 공유 스냅샷

- `지금 보장 현황`을 `공유 당시 보장 현황`으로 바꾼다.
- 공개 응답에 `captured_at`을 포함하고 서비스 기준인 KST 날짜로 표시한다.
- 고객용 공식 짧은 고지는 한 번만 표시한다.
- 설계사 책임·업무 지시 문구는 고객용 `/s`에서 제거하고 설계사 내부 분석 화면에만 유지한다.

#### 영업 문구

- 가짜 `080-000-0000` 템플릿은 삭제한다. 실제 수신거부 번호 설정이 생기기 전에는 해당 완성문을 제공하지 않는다.
- 검증 불가능한 사회적 증거, 절감 효과, 특정 보장 공백 단정, 유지·조정 권고를 제거한다.
- 사실 확인 질문, 고객이 확인할 항목, 다음 행동 중심으로 다시 쓴다.
- `lib/copy-library.ts`와 실제 복사 가능한 문자열을 copy lint 대상에 포함한다.
- 자동 금지어 검사와 사람이 읽는 골든 카피 리뷰를 함께 사용한다.

## 8. Release 2 설계: 데이터 무결성과 복구 가능한 화면

### 8.1 예약 설정

- Profile과 WorkHour를 독립 상태로 로드한다.
- Profile GET 성공 전 이름·소속·직책·예약 설정 저장을 비활성화한다.
- WorkHour GET 실패 시 `업무시간 없음`으로 바꾸지 않고 재시도 상태를 보여준다.
- 로드에 실패한 영역의 추가·삭제·저장을 차단한다.
- 전체 Profile을 덮는 PATCH 대신 성공적으로 읽은 원본과 비교한 변경 필드만 PATCH한다.
- 저장 실패 시 사용자가 입력한 값을 유지하고 재시도할 수 있어야 한다.

### 8.2 소개카드 `/p`

- 현재 제품에는 인앱 답장 수단이 없으므로 휴대폰 번호를 필수로 한다.
- FE와 BE가 같은 정규식·길이 계약을 사용한다.
- 이름·동의·검증된 전화번호가 모두 있어야 고객, 알림, 전환 이벤트를 생성한다.
- 잘못된 번호는 4xx이며 성공 이벤트를 남기지 않는다.
- 같은 설계사·전화번호의 중복 방지 계약을 유지한다.

### 8.3 오류와 빈 상태

- 성공한 `[]`만 진짜 빈 상태다.
- 401은 인증 복구, 403은 권한 안내, 404/410은 무효·만료, 409는 최신 상태 재조회, 429는 재시도 시점, 5xx·network는 일시 오류로 구분한다.
- 분석 고객 목록 실패 시 기존 성공 데이터가 있으면 유지하고 상단에 재시도 안내를 표시한다.
- 공개 `/b`, `/c`, `/p`는 404/410과 일시 오류를 분리하고 일시 오류에는 `다시 확인하기`를 제공한다.
- 관리자 설정·사용자 상세의 부분 실패도 카드별 오류·재시도를 제공한다.
- best-effort telemetry 실패와 사용자 데이터 저장 실패를 같은 방식으로 다루지 않는다.

### 8.4 요청 경합

- 고객 검색은 초기 중복 호출을 제거하고 request sequence 또는 AbortController로 최신 요청만 반영한다.
- 일정·홈 달력은 월별 요청 키를 사용해 이전 달의 늦은 응답이 현재 달을 덮지 못하게 한다.
- 비교 재계산과 공개 목록도 같은 latest-wins 패턴을 사용한다.
- 로딩 중 이전 성공 데이터를 지우지 않는다.

### 8.5 KST와 실제 날짜

- 서비스의 일정·오늘·이번 달은 기기 위치와 무관하게 `Asia/Seoul` 기준이다.
- `datetime-local` 문자열을 브라우저 로컬 시간으로 `Date` 생성하지 않는다.
- 공용 KST 벽시계 파서와 UTC 변환 함수를 한 곳에 둔다.
- 단일 일정은 KST 입력을 UTC로 저장하고 KST로 표시한다.
- 반복 업무시간은 KST wall-clock을 그대로 저장한다.
- all-day·timeless todo의 기존 KST 정오 규칙을 공용 함수로 고정한다.
- 생년월일은 정규식뿐 아니라 실제 calendar date인지 FE와 BE 모두 검증한다.

## 9. Release 3 설계: 예약 상태기계와 외부 캘린더

### 9.1 DB 상태기계

앱 DB가 최종 진실이다.

- `pending → confirmed`
- `pending → declined`
- `confirmed → canceled`
- 그 외 전환은 409 또는 명확한 4xx

수락·거절·취소는 행 잠금 또는 조건부 UPDATE를 사용해 한 요청만 성공하게 한다.

수락 트랜잭션에는 다음을 함께 포함한다.

- Meeting 상태 확정
- 대면 장소 스냅샷
- 고객의 FA 단계 승급
- `fa_reached_at` 최초 도달 보존
- `last_contacted_at` 갱신
- Google Calendar upsert outbox 생성

취소 트랜잭션에는 다음을 함께 포함한다.

- confirmed 상태 검증
- Meeting canceled 전환
- Google Calendar delete outbox 생성

### 9.2 Google Calendar outbox

외부 API를 DB 트랜잭션 안에서 호출하지 않는다.

Additive 모델 예시:

- meeting FK
- operation: `upsert|delete`
- status: `pending|processing|succeeded|failed`
- dedupe_key unique
- attempts
- next_attempt_at
- last_error_code
- created_at, updated_at

규칙:

- DB 커밋 후 Celery 작업으로 처리한다.
- 같은 dedupe key는 한 번만 실행한다.
- network·timeout·429·5xx는 최대 3회, 1초→2초→4초 backoff 후 운영 재시도 상태로 남긴다.
- 400·403은 재시도하지 않는다.
- 401은 연결 갱신 안내 상태로 남긴다.
- delete 404는 이미 삭제된 것으로 보고 성공 처리한다.
- 외부 삭제 실패가 앱 예약 취소를 막지 않는다.
- `google_event_id`는 삭제 성공 전 지우지 않는다.
- 로그에는 고객명·메모·전화번호를 남기지 않는다.

화면은 동기화 실패를 빨간 거절 상태로 표현하지 않는다. `앱에서는 취소됐어요. 연결된 캘린더를 다시 확인하고 있어요.`처럼 현재 상태와 다음 행동을 제공한다.

### 9.3 WorkHour와 예약 기간

- 같은 요일에 여러 구간을 허용한다.
- 인접 구간은 허용한다. 예: 09:00-12:00, 12:00-18:00.
- 일부 겹침, 완전 포함, 정확 중복은 거절한다.
- 기존 잘못된 데이터가 있어도 availability 생성기는 구간 union 또는 슬롯 dedupe로 동일 슬롯을 한 번만 반환한다.
- DB에는 정확 중복을 막는 additive unique constraint를 검토한다.
- 공개 GET과 POST는 하나의 `BOOKING_HORIZON_DAYS` 계약을 사용한다. 기본은 현행 노출 기준 14일이다.
- POST는 보이지 않은 15~60일 슬롯을 받지 않는다.
- KST 자정과 마지막 날 포함 여부를 테스트로 고정한다.

## 10. Release 4 설계: 품질·운영·계측

### 10.1 공통 화면 품질

- root `error.tsx`, `global-error.tsx`, `not-found.tsx`를 서비스 톤으로 제공한다.
- 고객 카드 등 클릭 가능한 요소를 button/link 의미 구조와 키보드 조작으로 바꾼다.
- modal은 focus trap, Escape, focus return, 제목 연결을 갖춘다.
- 내부 인증 라우트는 noindex를 명시한다. robots는 접근제어 수단으로 취급하지 않는다.
- 320px·390px·데스크톱에서 가로 넘침, 긴 한국어, 빈 상태, 오류 상태를 확인한다.

### 10.2 사용량 계측

- `measure_usage`와 `enforce_limit`을 분리한다.
- 베타 무제한은 차단만 생략하고 UsageMeter는 증가시킨다.
- API마다 한 요청당 한 번만 측정한다.
- 동시 요청과 KST 월 경계 테스트를 추가한다.
- 기존 NorthStarEvent와 ClaudeApiLog를 중복 과금 근거로 사용하지 않는다.

### 10.3 Render Blueprint

- 실제 Render 대시보드의 web, worker, queue, cron 플랜을 읽기 전용으로 대조한다.
- 현재 문서의 Starter 운영 상태가 맞으면 `render.yaml`도 같은 desired state로 고친다.
- Blueprint를 배포 SSOT로 사용한다.
- 플랜 변경으로 비용이 달라지는 실제 sync·deploy는 PM의 별도 승인 없이는 실행하지 않는다.
- rollback 대상 플랜과 이전 설정을 기록한다.

### 10.4 평가 명령 테스트

- `git worktree list --porcelain`에서 `prunable`로 표시되고 실제 경로가 없는 항목은 현재 유효 worktree로 취급하지 않는다.
- 살아 있는 worktree 경로의 strict 검증과 dataset-worktree 겹침 차단은 유지한다.
- 단위 테스트는 개발자 로컬 Git 메타데이터에 의존하지 않도록 명시적 `worktree_roots` 또는 discovery mock을 사용한다.
- stale worktree, malformed live worktree, dataset inside worktree, safe sibling temp directory 네 경우를 고정한다.

### 10.5 의존성

- `npm audit fix --force`를 사용하지 않는다.
- Next.js·Sentry·Vercel의 호환 가능한 공식 릴리스에서 postcss 수정 버전이 들어오는 경로를 우선한다.
- override를 사용할 경우 Next build, Vitest, production start를 모두 검증한다.
- Python 감사는 project requirements와 감사 도구 자체를 분리해 보고한다.

## 11. 데이터·마이그레이션

예상 additive 변경:

- Google Calendar outbox 모델과 인덱스
- WorkHour 정확 중복 constraint 또는 정규화 보조 필드, 최종 구현 탐사 후 확정
- 필요한 경우 Calendar sync 상태의 최소 표시 필드

원칙:

- 파괴적 마이그레이션 없음
- 기존 Meeting, Customer, ShareSnapshot 삭제 없음
- 기존 PlannerBaseline 입력값을 일괄 원 단위로 다시 쓰지 않는다. unit을 보존하고 판정 시 정규화한다.
- 데이터 보정 명령은 기본 dry-run, `--apply` 명시, PII 미출력
- 배포 순서는 migration → 구버전 호환 코드 → backfill/audit → 새 계약 활성화
- rollback은 feature flag와 이전 코드가 새 additive schema를 무시할 수 있게 설계한다.

## 12. 오류·보안·개인정보

- 공개 token은 scope별 rate throttle을 유지한다.
- 민감 API는 owner 격리를 중앙 mixin·permission에서 유지한다.
- 외부 AI와 Google 로그에는 원문, 이름, 전화번호, 고객 메모를 남기지 않는다.
- side-effect 실패가 primary DB 요청을 실패시키지 않는 경우, 성공 응답에는 side-effect 상태를 별도 필드로 제공한다.
- 사용자에게 404와 권한 여부를 구분해 타인 데이터 존재를 노출하지 않는다.
- share·consent·calendar outbox의 운영 계측은 enum, count, id만 저장한다.

## 13. 테스트 전략

구현은 각 결함마다 실패하는 테스트를 먼저 추가하는 TDD 순서로 진행한다.

### Backend

- 보장 기준 골든 세트
- 공유 미발급·발급·만료·철회·fallback cutoff
- 셀프진단 provider 호출보다 ConsentLog INSERT가 먼저인지 순서 검증
- `/p` 전화번호 누락·형식·중복
- 예약 accept/cancel 동시성
- outbox 멱등·재시도·delete 404·401
- WorkHour 인접·겹침·포함·중복
- GET/POST 14일 horizon과 KST 자정
- UsageMeter 무제한 측정·동시성·KST 월 경계
- PostgreSQL 전용 경합 테스트

### Frontend

- Profile/WorkHour 로드 실패 시 저장·추가 차단
- 분석 성공 빈 배열과 5xx 구분
- 공개 링크 404/410과 network/5xx 재시도
- 검색·월 이동 late response 무시
- UTC·미국 시간대 환경에서도 KST 입력 결과 동일
- 결정론 비교에서 AI 문구 없음
- 비교 delta 중립색·텍스트 구분
- 공유 당시 날짜와 고객 고지 1회
- copy library lint·골든 카피
- 키보드·focus·320px

### Runtime 검증

- Backend API를 실제 HTTP client로 호출
- migration 적용 후 PostgreSQL schema SELECT
- Frontend `npm run dev` 실제 렌더
- Preview에서 공개 `/p`, `/d`, `/s`, `/b` 흐름
- Google sandbox 계정으로 create→cancel→delete
- Render Blueprint diff 확인
- Sentry와 서버 로그에 PII가 없는지 확인

## 14. Release 완료 기준

### Release 1

- 잘못된 단위·범위로 graded 결과가 나오지 않음
- production grading gate는 closed
- 외부 AI 호출 이전 동의 증적 테스트 통과
- 미발급 공유 token 404
- 결정론 비교·공유·복사 문구가 사실성 계약 통과

### Release 2

- 로드 실패 후 프로필 덮어쓰기 재현 불가
- 연락처 없는 `/p` 성공 재현 불가
- 오류와 빈 상태가 모든 대상 화면에서 구분됨
- 비-KST 기기와 요청 경합 테스트 통과

### Release 3

- accept/cancel 경합에서 유효한 한 상태만 남음
- 앱 취소 후 Google event 삭제 또는 재시도 상태가 남음
- 중복 WorkHour가 중복 공개 슬롯을 만들지 않음
- 보이지 않은 예약 horizon POST가 거절됨

### Release 4

- Backend 전체 테스트 green
- Frontend unit, copy lint, build green
- moderate dependency는 제거되거나 upstream 대기 사유와 차단 위험이 기록됨
- Preview 브라우저·API·PostgreSQL·Google smoke 완료
- Critical 0, Important 0 독립 적대적 리뷰

## 15. 롤아웃과 롤백

1. 각 Release를 별도 작은 검증 단위로 구성한다. commit은 PM이 요청할 때만 만든다.
2. Preview 배포와 테스트 데이터를 사용해 확인한다.
3. DB migration은 additive라 이전 앱 버전이 안전하게 무시할 수 있어야 한다.
4. grading, legacy share fallback 등 위험 기능은 default closed flag로 즉시 롤백 가능하게 한다.
5. Production 배포 전 env diff, migration 순서, worker 호환, rollback 명령을 기록한다.
6. Production 배포는 PM 승인 후에만 실행한다.
7. 배포 후 실제 URL, Render health, Sentry, latency, outbox backlog를 확인한다.
8. 기대 이벤트가 0으로 멈추는 경우도 감시한다.
9. 기능이 구현·병합·배포까지 끝난 뒤 `README.md`와 `AGENTS.md`를 함께 갱신한다.

## 16. 확정된 PM 기본 결정

- 위험 우선 단계형 안정화 채택
- 구좌·불명확 상품군은 자동 판정하지 않고 neutral
- 공유 legacy fallback은 PII 없는 dry-run 감사 후 종료
- 앱 DB 취소를 우선 확정하고 Google 삭제는 durable retry
- 소개카드 상담 신청은 휴대폰 번호 필수
- Render Starter를 코드 선언과 맞추되 실제 비용·Production 변경은 별도 승인
- 현재 동시 작업 중인 landing·boards·Manager 파일은 이번 구현에서 제외

## 17. 명세 승인 후 다음 단계

이 문서가 승인되면 `writing-plans` 절차로 파일·테스트·마이그레이션·검증 명령을 작은 구현 배치로 나눈다. 구현 계획까지 승인된 뒤 코드 수정을 시작한다.
