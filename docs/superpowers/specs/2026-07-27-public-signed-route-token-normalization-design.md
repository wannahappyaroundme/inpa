# 공개 서명 링크 경로 토큰 정규화 설계

**작성일:** 2026-07-27  
**상태:** 사용자 최종 승인, 상세 구현 계획 작성 완료, 구현 전  
**우선순위:** P0 운영 결함

**구현 계획:** `docs/superpowers/plans/2026-07-27-release-1-public-signed-link-token-normalization.md`

## 1. 문제와 확인된 근거

고객 본인 동의 링크 `/c/<token>`이 운영 브라우저에서 `유효하지 않은 링크입니다.`로 끝난다.

운영에서 같은 토큰을 비교한 결과:

- 프런트 `/c/<token>` 경로 자체는 200으로 열린다.
- 토큰을 API 경로에 한 번 인코딩하면 `/api/v1/c/<token>/`은 200으로 동의 내용을 반환한다.
- `%3A`가 포함된 경로 파라미터를 다시 `encodeURIComponent`하면 `%253A`가 되고, 백엔드는 `LINK_INVALID` 404를 반환한다.
- 실제 운영 브라우저에서도 `링크를 열 수 없어요 / 유효하지 않은 링크입니다.`가 재현됐다.

원인은 데이터나 토큰 만료가 아니라 Next 동적 경로와 API 경로 사이의 이중 인코딩이다.

같은 Django signed token 형식을 쓰는 공개 경로도 동일 위험이 있다.

- `/c/[token]`: 고객 본인 동의
- `/b/[token]`: 고객 예약
- `/r/[token]`: 공개 설계사 영입 지원
- `/r/manage/[token]`: 지원 관리
- `/recruiting/join/[token]`: 팀 합류

`/recruiting/join/[token]`에는 이미 `normalizeRecruitingRouteToken`과 raw/encoded/malformed 회귀 테스트가 있어 올바른 선례로 쓸 수 있다.

## 2. 목표

1. raw signed token과 한 번 URL 인코딩된 signed token을 같은 정상 토큰으로 해석한다.
2. API 요청 직전에는 경로 세그먼트를 정확히 한 번만 인코딩한다.
3. 이중 인코딩, 잘못된 `%` escape, 허용되지 않은 문자는 API로 보내기 전에 안전하게 거절한다.
4. 모든 Django signed token 공개 경로가 한 가지 공용 규칙을 사용한다.
5. 404 위조 링크와 410 만료 링크의 기존 백엔드 의미를 유지한다.

## 3. 비목표

- 토큰 포맷, salt, TTL, 서명 키 변경
- DB 테이블 또는 마이그레이션 추가
- 공개 링크를 영구 링크로 변경
- `/s`, `/d`, `/p`의 별도 ref/token 계약 변경
- 이메일 인증·비밀번호 재설정 쿼리 파라미터 변경

## 4. 선택한 설계

### 4.1 공용 정규화 함수

프런트에 signed route token 전용 순수 함수를 둔다.

계약:

```text
normalizeSignedRouteToken(value: unknown): string | null
```

규칙:

1. 문자열이 아니면 `null`.
2. `decodeURIComponent`를 정확히 한 번 실행한다.
3. decode가 실패하면 `null`.
4. decode 결과가 `.` 또는 `..`이면 `null`.
5. decode 결과가 Django signed token 안전 문자 집합 `A-Z a-z 0-9 . _ : -` 밖의 문자를 포함하면 `null`.
6. 통과한 raw token만 반환한다.

이 규칙은 다음을 보장한다.

| 입력 | 결과 |
|---|---|
| raw `payload:timestamp:signature` | 정상 raw token |
| `payload%3Atimestamp%3Asignature` | 정상 raw token |
| `payload%253Atimestamp...` | 1회 decode 뒤 `%3A`가 남아 거절 |
| `broken%2` | decode 실패로 거절 |
| `/`, `%2F`, 공백 포함 | 안전 문자 검사에서 거절 |

기존 `normalizeRecruitingRouteToken`은 공용 함수로 대체하거나 공용 함수를 호출하는 얇은 호환 wrapper로 유지한다. 토큰 정규화 규칙은 한 곳에만 존재해야 한다.

### 4.2 경로와 API의 책임 분리

- 동적 route page/component: 경로 파라미터를 공용 함수로 raw token으로 정규화한다.
- `lib/api.ts`: raw token을 `encodeURIComponent`로 정확히 한 번 인코딩해 API 경로를 만든다.
- route 정규화가 실패하면 네트워크 요청을 보내지 않고 해당 공개 화면의 기존 안전한 링크 오류 상태를 보여준다.
- 백엔드는 기존 `signing.loads` 검증과 404/410 응답을 그대로 유지한다.

### 4.3 적용 범위

| 프런트 경로 | 적용 |
|---|---|
| `/c/[token]` | GET, 동의 제출, 철회에 같은 normalized token 사용 |
| `/b/[token]` | 예약 정보 GET, 예약 요청 POST에 같은 normalized token 사용 |
| `/r/[token]` | 공개 지원 조회·제출에 normalized token 사용 |
| `/r/manage/[token]` | 조회·연락 중단 등 모든 관리 동작에 normalized token 사용 |
| `/recruiting/join/[token]` | 기존 정상 동작을 공용 helper로 통합 |

## 5. 사용자 상태

| 상태 | 화면 |
|---|---|
| 정상 | 기존 공개 동의·예약·영입 화면 |
| 만료 410 | 담당자에게 새 링크를 요청하는 기존 안내 |
| 위조/잘못된 경로 404 | 링크를 다시 확인하거나 새 링크를 요청하는 기존 안내 |
| 일시적 네트워크 실패 | 만료로 오인하지 않고 같은 화면에서 다시 불러오기 |

고객 화면에는 인코딩, 서명, 토큰 같은 내부 용어를 노출하지 않는다.

## 6. 테스트

### 6.1 순수 함수

- raw signed token 통과
- `%3A` 인코딩 token 통과
- double encoded token 거절
- 잘못된 `%` escape 거절
- slash·공백·제어문자 거절
- `.`·`..` 거절

### 6.2 공개 페이지

- `/c`: encoded route token으로 GET 성공
- `/c`: 같은 token으로 POST 동의 및 철회 성공
- `/b`: encoded route token으로 GET 성공
- `/b`: 같은 token으로 예약 POST 성공
- `/r`, `/r/manage`, `/recruiting/join`: raw와 encoded token이 같은 API raw token으로 전달됨
- 정규화 실패 시 API mock 호출 0회

### 6.3 운영 검증

- 운영 `/c` 링크가 실제 동의 항목을 표시
- 운영 `/b` 링크가 실제 고객 예약 화면을 표시
- 읽기 전용 GET 검증을 먼저 수행
- 동의 제출·철회와 예약 생성은 로컬/테스트 데이터로 검증하며 운영 고객 데이터를 변경하지 않는다.

## 7. 배포와 롤백

- 프런트 전용 호환 수정으로 DB·백엔드 배포 순서 의존성이 없다.
- Next 빌드, 관련 프런트 테스트, 공개 route 브라우저 검증 후 preview 배포한다.
- 운영 배포는 사용자 별도 승인 후 진행한다.
- 롤백은 해당 프런트 버전으로 되돌린다.
