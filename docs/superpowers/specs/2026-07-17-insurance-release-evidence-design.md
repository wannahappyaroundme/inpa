# 보험증권 출시 증거 보강 설계

> 2026-07-17. PM은 2026-07-16 보험 검토 기능의 나머지 권장안을 모두 승인했다. Git 과거 기록의 비밀정보 후보 2건은 PM이 위험을 수용해 이번 범위에서 제외한다. 운영 배포와 법률 기능 활성화는 포함하지 않는다.

## 1. 목표

보험 업로드·검토·분석이 실제 출시 환경에 가까운 조건에서도 안전하다는 증거를 네 축으로 보강한다.

1. 보험 화면 회귀 테스트를 저장소와 CI의 정식 게이트로 만든다.
2. 실제 증권은 로컬에서 먼저 비식별화하고, 운영과 분리된 평가기에서만 Claude와 OpenAI를 비교할 수 있게 한다.
3. PostgreSQL·Valkey·S3 호환 비공개 저장소에서 20명×3건 동시 요청과 계정 격리를 검증한다.
4. 실제 브라우저에서 데스크톱·모바일·키보드 흐름을 확인하고, 운영과 분리된 미리보기만 배포한다.

## 2. 승인된 결정

- 운영 공급자는 계속 Claude 한 곳이다. OpenAI는 비공개 오프라인 평가기에만 연결하며 운영 API·워커·기능 스위치에서 참조하지 않는다.
- OpenAI 모델 ID와 키는 `OPENAI_EVAL_MODEL`, `OPENAI_EVAL_API_KEY`로만 주입한다. 코드 기본 모델 ID는 두지 않는다.
- 현재 공식 OpenAI 문서가 권장하는 최신 품질 우선 계열은 GPT-5.6이지만, 실제 실행 모델은 환경변수로 고정하고 보고서에 기록한다.
- OpenAI 호출은 Responses API의 Structured Outputs와 `store=False`를 사용한다. Claude와 동일한 로컬 마스킹 결과, Pydantic 스키마, 출력 개인정보 역검사를 사용한다.
- 실제 증권 155건은 표본 후보일 뿐 정답이 아니다. 독립 정답 1,000담보가 없으므로 공급자 불일치율은 계산할 수 있어도 정확도라고 부르지 않는다.
- 기존 100개 SHA holdout은 개인정보 경계 확인에 한 번 사용한 동결 자료다. 규칙 튜닝이나 반복 점수 개선에 다시 사용하지 않는다.
- `samples/`는 git 밖으로 내보내기 전에도 폴더 `0700`, 파일 `0600`을 강제한다. 파일명·원문·해시·사례별 결과는 stdout, git, CI, Sentry에 남기지 않는다.
- staging 이름, DB, 큐, 저장소, 사용자, 토큰은 운영과 공유하지 않는다. 현재 `render.yaml`은 운영 이름을 사용하므로 staging 배포에 직접 사용하지 않는다.
- 기능 게이트는 staging 부하 실행 순간을 제외하고 `INSURANCE_REVIEW_GATE_ENABLED=False`다. production은 계속 False다.

## 3. 작업 단위

### 3.1 프런트 테스트 게이트

Vitest 4, jsdom, React Testing Library를 Node 20.19 이상에서 사용한다. 보험 업로드, 검토 초안, 원문 보기, 보험 카드, 분석 권위, 공개 공유를 추적 테스트로 복구한다. `STANDARD_MAPPING_AMBIGUOUS`와 `STANDARD_MAPPING_CONTRADICTION`은 안내, 표준 위치 포커스, 최종 반영 차단을 반드시 검사한다. CI는 카피 검사 다음에 `npm run test:run`, 그 다음 운영 빌드를 실행한다.

### 3.2 비공개 공급자 평가

기존 `legacy`, `review` 의미를 바꾸지 않고 `openai_review`를 진단 전용 변형으로 추가한다. 출시 게이트는 계속 Claude `review`와 신뢰 가능한 사람 검토 결과만 본다. OpenAI가 더 좋은 수치를 보여도 운영 공급자를 자동으로 바꾸지 않는다.

정답이 없는 표본 준비 단계는 다음만 한다.

- 고유 SHA 단위로 중복을 묶는다.
- development 36개 집합에서 전자 PDF·이미지 PDF·암호화·마스킹 성공을 집계한다.
- 비식별 줄과 opaque case ID만 접근 통제 폴더에 만든다.
- 개별 원문이나 상품·담보명을 보고서에 쓰지 않는다.

실제 100건·1,000담보 점수 실행은 독립 정답과 `OPENAI_EVAL_API_KEY`가 모두 있을 때만 가능하다. 없으면 명령은 공급자 호출 전에 안전 코드로 중단한다.

### 3.3 동시성·저장소 증거

로컬 Docker의 PostgreSQL 16, Valkey 8, MinIO를 운영 대체물이 아닌 프로토콜 검증 환경으로 사용한다. PostgreSQL 경쟁 테스트는 skip 없이 통과해야 한다. Valkey는 Celery JSON 큐·재전달·동시 실행 상한을, MinIO는 private alias·정확한 key 삭제·공개 URL 부재를 검증한다.

60건 HTTP runner는 실제 staging 자격증명과 합성 fixture가 준비될 때만 실행한다. runner는 60건 202, 교차 계정 노출 0, 중복 합산 0, stale overwrite 0, 정확한 교체 200+409, 개인정보 출력 0을 요구한다. 기존 45초 총 제한은 60건 drain 시간과 분리하며 owner별 queue wait와 end-to-end p95를 측정한다.

### 3.4 브라우저·미리보기

로컬 브라우저 검증은 합성 계정과 합성 PDF만 사용한다. 데스크톱과 모바일에서 업로드, 진행 상태, 확인 사유, 같은 위치 재확인, 키보드 포커스, 공유 연락 요청을 확인한다. jsdom 결과를 실제 브라우저·스크린리더 결과로 표현하지 않는다.

원격 미리보기는 브랜치 push 후 Vercel Preview와 staging API가 모두 분리됐을 때만 연결한다. CLI 인증이 없으면 코드는 준비하되 배포 성공을 주장하지 않는다. Render staging은 유료 자원 생성 전용 구성 파일을 사용하며 운영 `inpa-be`를 변경하지 않는다.

## 4. 출시 기준과 중단 기준

통과 기준:

- 프런트 전체 테스트·카피 검사·Next 운영 빌드 통과
- 백엔드 전체 테스트·Django check·migration drift 0
- PostgreSQL 경쟁 테스트 skip 0
- 현재 코드 secret scan 0
- 실제 브라우저에서 핵심 흐름과 키보드 포커스 확인
- 60건 staging을 실행한 경우 교차 귀속·중복 합산·stale overwrite 모두 0

중단 기준:

- 원문 또는 식별정보가 공급자 입력·응답·로그·평가 보고서에 남음
- 정답 없이 공급자 결과를 정확도로 표현함
- staging이 production DB·R2·Valkey·서비스 이름을 공유함
- feature gate가 production에서 열림
- 미확정 보험이 분석·공유에 포함됨

## 5. 현재 외부 차단점

- 로컬에는 OpenAI 평가 키와 모델 설정이 없다.
- 실제 표본에는 독립 정답 manifest와 1,000담보 truth가 없다.
- GitHub CLI와 Vercel CLI 인증이 만료·부재 상태다. Git remote 읽기 인증은 가능하다.
- Render·Cloudflare staging 자격증명이 없고 현재 blueprint는 운영 이름을 쓴다.

이 항목들은 코드를 막지 않는다. 관련 도구와 fail-closed 계약을 먼저 완성하고, 실제 외부 실행은 자격증명이 준비된 범위까지만 수행한다.
