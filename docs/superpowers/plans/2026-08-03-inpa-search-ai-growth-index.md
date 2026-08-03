# Inpa Search and AI Growth Implementation Plan Index

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement each release plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 보험설계사가 실제로 찾는 질문에서 인파의 공개 근거가 검색엔진과 AI 답변에 발견되게 만들고, 그 유입이 가입 후 7일 안의 첫 분석과 첫 공유로 이어지는지 측정한다.

**Architecture:** 색인 허용 대상을 명시한 allowlist와 URL 비식별화를 먼저 배포한다. 이어서 실제 제품 화면과 현장 절차를 근거로 한 정적 검색 허브 7개를 공개하고, 마지막으로 브라우저 안에서만 동작하는 도구·자료 3개와 기존 활성화 퍼널의 검색·AI 채널 분해를 배포한다. 기존 Google Search Console·네이버 서치어드바이저 등록은 유지하고 오류가 확인된 경우에만 다시 제출한다.

**Tech Stack:** Next.js 16.2.9 App Router, React 19.2, TypeScript, Tailwind v4, Vitest, Vercel Analytics/Speed Insights, Sentry, Django 5.2 LTS/DRF, PostgreSQL/SQLite, Vercel, Render, GitHub Actions.

## 승인 기준 문서

- 설계 SSOT: `docs/superpowers/specs/2026-08-03-inpa-search-ai-growth-design.md`
- 이 인덱스는 실행 순서와 배포 게이트를 정한다. 코드 계약은 각 릴리스 계획이 정한다.
- 제품 코드는 각 계획의 RED 테스트부터 수정한다.
- 2026-08-03 PM이 계획, 개발, 운영 배포를 명시적으로 요청했다.
- 운영 등록은 이미 완료된 것으로 보고 Google Search Console·네이버 서치어드바이저를 새로 등록하지 않는다.
- 새로운 CMS, 외부 채널 운영, 유료 링크, `llms.txt`, 원시 직업급수 데이터, 보장명 정규화 사전 공개는 이번 범위에서 제외한다.

## 실행 순서

| 순서 | 계획 | 핵심 위험 | 완료 증거 |
|---:|---|---|---|
| 1 | `2026-08-03-inpa-search-ai-growth-release-1-safe-indexing.md` | 토큰·고객 ID가 분석 도구에 남음, 서비스 화면 색인, sitemap/noindex 충돌 | 비식별화 단위 테스트, 메타·robots·sitemap 계약 테스트, Preview·운영 URL 확인 |
| 2 | `2026-08-03-inpa-search-ai-growth-release-2-evidence-hubs.md` | 얕은 SEO 문서, 제품과 다른 주장, 내부 링크 부족 | 7개 정적 페이지, 실제 화면 근거, 구조화 데이터·모바일 브라우저 검수 |
| 3 | `2026-08-03-inpa-search-ai-growth-release-3-resources-measurement.md` | 도구 계산 오차, 개인정보 저장, 허위 채널 귀속, 방문 수만 보는 지표 | 골든 계산 테스트, 무저장 확인, 검색·AI 채널별 7일 활성화 API/UI 테스트 |

## 브랜치와 배포 원칙

```text
origin/master 최신화
  -> codex/inpa-search-ai-safe-indexing
  -> PR·CI·운영 배포·운영 확인
  -> 최신 master에서 codex/inpa-search-ai-evidence-hubs
  -> PR·CI·운영 배포·운영 확인
  -> 최신 master에서 codex/inpa-search-ai-resources-measurement
  -> PR·CI·운영 배포·운영 확인
  -> README.md + AGENTS.md 운영 상태 문서화
```

- 공유 작업 폴더는 다른 세션 변경이 있으므로 구현에 사용하지 않는다. 각 릴리스는 `superpowers:using-git-worktrees`로 `/tmp`의 격리 worktree에서 시작한다.
- 각 PR을 만들기 직전에 `git fetch origin`과 `origin/master..HEAD`를 확인하고 해당 릴리스 파일만 stage한다.
- Vercel과 Render는 `master` 병합 후 자동 배포된다. 이번 변경에는 파괴적 DB migration이 없다.
- 각 운영 배포 후 실제 URL, 응답 헤더, canonical/robots, sitemap, Sentry 오류, Vercel Web Vitals를 확인한다.
- 릴리스 2나 3에서 문제가 생겨도 릴리스 1의 개인정보 보호 변경은 롤백하지 않는다.

## 릴리스 간 중단 조건

- 민감 URL canary가 Vercel Analytics 또는 Sentry 전송 전 데이터에 한 글자라도 남으면 다음 릴리스로 진행하지 않는다.
- 공개 페이지가 제품에서 제공하지 않는 기능을 주장하거나 규정·보험 판단을 대신하면 공개하지 않는다.
- 보험나이 골든 케이스가 백엔드와 다르면 도구를 공개하지 않는다.
- GitHub Actions, Vercel 배포, Render health, 운영 smoke test 중 하나라도 실패하면 다음 릴리스 병합을 중단한다.

## 공통 종료 형식

각 릴리스 완료 보고는 아래 네 줄과 운영 URL을 포함한다.

```text
Changed: [실제 변경]
Verified by: [실행한 명령·API·브라우저]
Result: [실제 수치·응답·화면]
Unverified: [남은 항목과 이유, 없으면 없음]
```

`README.md`와 `AGENTS.md`는 세 릴리스가 구현·병합·운영 검증된 뒤 마지막 문서 전용 변경에서 갱신한다.
