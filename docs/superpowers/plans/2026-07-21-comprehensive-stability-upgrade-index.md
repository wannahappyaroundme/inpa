# 인파 종합 안정화 업그레이드 구현 계획 인덱스

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement each release plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 승인된 종합 안정화 설계를 위험 순서대로 구현하되, 각 릴리스를 독립 검증·롤백 가능한 크기로 유지한다.

**Architecture:** 계산·동의·공유 권위부터 fail-closed로 바로잡고, 다음 릴리스에서 화면 상태와 시간대를 안정화한다. 예약은 별도 상태기계와 outbox로 분리하고, 마지막 릴리스에서 품질 게이트와 운영 선언을 정합화한다. 릴리스 사이에는 PM 검토 지점을 둔다.

**Tech Stack:** Django 5.2 LTS/DRF/PostgreSQL, Next.js 16/React 19/TypeScript/Tailwind, Celery/Redis, Google Calendar API, Vitest/Testing Library, Django TestCase, Render/Vercel.

## 승인 기준 문서

- 설계 SSOT: `docs/superpowers/specs/2026-07-21-comprehensive-stability-upgrade.md`
- 이 인덱스는 범위와 실행 순서를 정한다. 세부 계약은 아래 릴리스 계획이 정한다.
- 제품 코드는 릴리스 계획의 RED 테스트부터 수정한다.
- 현재 다른 세션이 수정 중인 랜딩, 게시판 시드, Manager 요금제 파일은 건드리지 않는다.
- 커밋, push, Preview 배포, Production 배포는 자동으로 수행하지 않는다. PM이 요청한 단계까지만 진행한다.
- Production 배포와 Render 비용·플랜 변경은 언제나 별도 명시 승인이 필요하다.

## 실행 순서

| 순서 | 계획 | 차단 위험 | 완료 증거 |
|---:|---|---|---|
| 1 | `2026-07-21-stability-release-1-core-trust.md` | 잘못된 판정, 동의 증적, 공유·비교 사실성 | 골든 계산, 동의 선커밋, snapshot-only 공개, 카피 테스트 |
| 2 | `2026-07-21-stability-release-2-data-integrity.md` | 설정 덮어쓰기, 오류 오인, 요청 경합, KST | 실패·빈 상태 분리, diff PATCH, latest-wins, 브라우저 검증 |
| 3 | `2026-07-21-stability-release-3-booking-sync.md` | 예약 상태 불일치, Google 일정 잔존 | 상태 전이·경합·outbox·재시도·삭제 회귀 테스트 |
| 4 | `2026-07-21-stability-release-4-quality-ops.md` | 관측 공백, 개발도구 실패, 운영 선언 드리프트 | 사용량 계측, hermetic 평가, 오류 경계, 운영 대조표 |

## 릴리스 게이트

```text
Release 1 테스트·Preview 확인
  -> PM 검토
Release 2 테스트·Preview 확인
  -> PM 검토
Release 3 PostgreSQL 경쟁 테스트·Google 테스트 계정 확인
  -> PM 검토
Release 4 전체 회귀·운영 대조
  -> 별도 Production 승인
```

## 공통 종료 형식

각 릴리스 완료 보고는 다음 네 줄을 반드시 채운다.

```text
Changed: [실제 변경]
Verified by: [실행한 명령·API·브라우저]
Result: [실제 수치·응답·화면]
Unverified: [남은 항목과 이유, 없으면 없음]
```

`README.md`와 `AGENTS.md`는 기능이 구현되고, 병합되고, 배포까지 끝난 뒤 마지막 단계에서만 갱신한다.
