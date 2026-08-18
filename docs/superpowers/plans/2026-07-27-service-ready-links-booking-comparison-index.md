# 공개 링크·예약 안내·여러 증권 비교 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 고객에게 바로 서비스할 수 있도록 공개 서명 링크를 정상화하고, 실제 고객 예약 문구를 만들며, 같은 증권을 양쪽에 중복 선택할 수 있는 여러 증권 비교 UX를 순서대로 출시한다.

**Architecture:** 세 결함은 데이터 계약이 다른 독립 하위 시스템이므로 세 개 릴리스로 분리한다. Release 1은 프런트 경로 토큰 경계, Release 2는 예약 설정과 서버 권위 메시지, Release 3은 비교 선택 상태와 결과 표시를 각각 독립 테스트한다. Release 2의 실제 링크 열기 검증만 Release 1에 의존한다.

**Tech Stack:** Next.js 16.2.9, React 19.2.4, TypeScript 5, Tailwind CSS 4, Vitest 4, Django 5.2 LTS, Django REST Framework, PostgreSQL/SQLite.

## Global Constraints

- 승인 설계는 `docs/superpowers/specs/2026-07-27-public-signed-route-token-normalization-design.md`, `2026-07-27-booking-message-composer-design.md`, `2026-07-27-multi-policy-overlap-selection-design.md` 세 문서다.
- 구현 시작점은 실행 시점의 최신 `origin/master`다. 현재 `feat/design-refactor` 작업 폴더의 사용자 변경을 섞지 않는다.
- 실행 시 `superpowers:using-git-worktrees`를 사용해 `codex/service-ready-links-booking-comparison` 격리 작업공간을 만든다.
- Release 1, 2, 3은 각각 테스트·preview 검증·리뷰가 가능한 독립 결과물이어야 한다.
- DB migration, signed token 포맷, compare API shape는 변경하지 않는다.
- 화면 카피는 쉬운 한국어, 긍정형 다음 행동, em-dash 금지 규칙을 지킨다.
- 고객 화면에는 인코딩, 서명, 토큰, API 같은 내부 용어를 노출하지 않는다.
- 운영 고객 데이터에 동의 제출·철회 또는 예약 생성을 하지 않는다. 운영 검증은 읽기 전용 GET만 허용한다.
- 운영 배포는 preview 검증 뒤 PM의 별도 승인을 받아야 한다.
- 아래 커밋 단계는 실행 세션에서 PM이 별도로 커밋을 요청한 경우에만 수행한다.

---

## 릴리스 지도

| 순서 | 구현 계획 | 사용자 결과 | 독립 배포 |
|---|---|---|---|
| 1 | [공개 서명 링크 경로 토큰 정규화](./2026-07-27-release-1-public-signed-link-token-normalization.md) | 동의·예약·영입 링크가 raw/encoded 경로에서 정상 열림 | 가능, P0 우선 |
| 2 | [실제 고객 예약 문구·전체 링크 composer](./2026-07-27-release-2-booking-message-composer.md) | 일정 화면에서 고객 선택, 실제 문구와 전체 링크 생성·복사 | Release 1 이후 |
| 3 | [여러 증권 양쪽 중복 선택](./2026-07-27-release-3-multi-policy-overlap-selection.md) | 한 카드에서 왼쪽·오른쪽 독립 선택, 같은 증권 양쪽 포함 | 독립 가능 |

## 실행 전 기준선

- [ ] **Step 1: 원격 최신 상태와 현재 오염 범위를 기록한다.**

Run:

```bash
git fetch origin
git status --short --branch
git log --oneline -10 origin/master
```

Expected:

- 현재 작업 폴더의 수정·미추적 파일은 그대로 남아 있다.
- 새 구현의 base SHA는 실행 기록에 남는다.
- `git diff`나 파일 이동으로 기존 사용자 변경을 정리하지 않는다.

- [ ] **Step 2: 최신 master에서 격리 작업공간을 만든다.**

`superpowers:using-git-worktrees` 지침에 따라 충돌 없는 경로를 고른 뒤 다음 의미의 작업공간을 만든다.

```bash
git worktree add /Users/kyungsbook/Desktop/inpa-service-ready-links-booking-comparison -b codex/service-ready-links-booking-comparison origin/master
```

Expected:

- 새 작업공간의 `git status --short`가 비어 있다.
- `git rev-parse HEAD`가 실행 직전 `origin/master`와 같다.
- 기존 `feat/design-refactor` 작업 폴더는 변경되지 않는다.

- [ ] **Step 3: Next 16 동적 경로 문서를 읽고 기준선을 검증한다.**

Read:

```text
inpa_fe/node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/dynamic-routes.md
inpa_fe/node_modules/next/dist/docs/01-app/03-api-reference/04-functions/use-params.md
inpa_fe/AGENTS.md
```

Run:

```bash
cd inpa_fe
npm run test:unit
npm run test:run
npm run lint:copy
npm run build
```

```bash
cd inpa_be
./venv/bin/python manage.py check
./venv/bin/python manage.py test inpa.booking.tests.BookingCoreTests inpa.analysis.tests.CompareFactsTests -v 2
```

Expected: 기준선 테스트·카피 검사·빌드·Django check가 모두 성공한다. 기준선 실패가 있으면 구현과 섞지 않고 실패 명령과 원문을 먼저 기록한다.

## 릴리스 게이트

- [ ] **Step 4: Release 1을 RED → GREEN → 브라우저 순서로 완료한다.**

완료 기준:

```text
raw token = 정상
한 번 encoded token = 정상
double encoded token = API 호출 전 차단
404/410 = 새 링크 요청 안내
network/429/5xx = 같은 화면에서 다시 불러오기
```

Release 1 preview에서 `/c`와 `/b`의 읽기 전용 GET을 확인한다. 운영 배포가 필요하면 PM에게 별도 승인을 요청한다.

- [ ] **Step 5: Release 2를 서버 문구 → 공용 composer → 설정 화면 순서로 완료한다.**

완료 기준:

```text
가짜 고객명 0건
줄임표 예약 URL 0건
미치환 placeholder 0건
dirty 설정 PATCH 성공 뒤에만 booking request POST
복사 실패를 성공으로 표시하지 않음
```

로컬 테스트 고객으로 `/b/<signed-token>`을 열고 예약 요청·수락·일정 반영까지 검증한다.

- [ ] **Step 6: Release 3을 선택 모델 → 카드 → 실행 상태 → 결과 카피 순서로 완료한다.**

완료 기준:

```text
왼쪽 = A1, A2, A3
오른쪽 = A1, A2, B1
A1과 A2가 양쪽 배열에 각각 한 번 포함
선택 변경 뒤 이전 결과 복사 차단
오류·402 중에도 선택 카드 유지
사용자 화면의 증권 A/B·비교 묶음 A/B 0건
```

## 통합 검증과 출시

- [ ] **Step 7: 세 릴리스 통합 회귀를 실행한다.**

Run:

```bash
cd inpa_fe
npm run test:unit
npm run test:run
npm run test:copy-lint
npm run lint:copy
npm run build
```

```bash
cd inpa_be
./venv/bin/python manage.py check
./venv/bin/python manage.py test inpa -v 1
```

Expected:

- FE unit/Vitest/copy/build 모두 성공
- BE 전체 테스트와 Django check 성공
- migration 변경 0건

- [ ] **Step 8: preview에서 데스크톱·모바일·실제 흐름을 검증한다.**

브라우저 검증표:

| 화면 | Desktop | Mobile | 실패 주입 |
|---|---:|---:|---:|
| `/c/<token>` | 동의 항목 표시 | 가로 넘침 없음 | 503 뒤 재시도 |
| `/b/<token>` | 슬롯 표시 | 버튼 44px 이상 | 409 뒤 슬롯 갱신 |
| 일정 예약 설정 | 고객 검색·실제 문구 | 전체 URL 줄바꿈 | PATCH/POST/clipboard 실패 |
| 여러 증권 비교 | 양쪽 중복 선택·결과 | 카드·CTA 조작 가능 | compare 500/402 |

- [ ] **Step 9: 독립 리뷰의 Critical·Important 지적을 닫는다.**

검토 관점:

```text
correctness: 토큰 decode/encode 횟수, 요청 세대 가드, stale 결과
security: owner scope, signed token 검증 유지, 운영 mutation 금지
UX/accessibility: retry, empty/error/loading, keyboard, aria-live, 44px
copy/compliance: 왼쪽/오른쪽 용어, 권유 문구 없음, em-dash 없음
```

Critical 또는 Important 지적이 남아 있으면 preview 승인 요청을 하지 않는다. 수용하지 않은 지적은 기술적 근거와 재현 결과를 기록한다.

- [ ] **Step 10: PM 승인 뒤에만 운영 배포하고 실제 URL을 읽기 전용으로 확인한다.**

배포 전:

```text
FE/BE 환경변수 diff 확인
DB migration 없음 확인
Vercel 이전 production version 확인
Render 이전 commit 확인
롤백 대상 version 기록
```

배포 후:

```text
www.inpa.kr 상태 200
Render /healthz/ 정상
운영 /c 링크 GET 정상
운영 /b 링크 GET 정상
Sentry 신규 오류 5분 관찰
```

- [ ] **Step 11: 구현·merge·운영 배포가 모두 끝난 뒤 두 문서를 갱신한다.**

Modify:

```text
README.md
AGENTS.md
```

README에는 PM이 확인할 수 있도록 사용자 변화, 검증 결과, 운영 상태를 한국어로 기록한다. AGENTS에는 토큰 경계 규칙, 예약 composer 권위, 비교 선택 상태·카피 계약과 검증 commit을 짧게 반영한다.

## 최종 보고 형식

```text
Changed: 공개 링크, 실제 예약 안내, 여러 증권 양쪽 중복 선택 요약
Verified by: 실제 실행한 FE/BE 테스트, build, browser, preview/production URL
Result: 응답 상태, 렌더 결과, A1+A2+A3 대 A1+A2+B1 실제 payload
Unverified: 남은 항목과 이유
```
