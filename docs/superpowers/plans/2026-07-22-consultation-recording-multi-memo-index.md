# 상담 녹음·AI 요약·여러 메모 구현 계획 인덱스

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 여러 메모를 먼저 안전하게 공개하고, 원본 녹음과 AI 요약은 법적·운영 게이트를 분리한 채 순차 검증한다.

**Architecture:** `customers`에는 영구 고객 메모만 두고, 민감한 원음·업로드·요약 실행은 새 `consultations` 앱에 둔다. 세 릴리스는 additive migration과 독립 기능 게이트를 사용해 앞 단계가 뒤 단계 없이도 완전한 제품 기능으로 동작한다.

**Tech Stack:** Django 5.2, DRF 3.16, PostgreSQL/SQLite, Celery 5.6, Cloudflare R2 S3 API, NAVER CLOVA Speech, Anthropic Messages API, Next.js 16, React 19, TypeScript, Tailwind v4, Vitest.

## Global Constraints

- 프로덕션 배포와 기능 게이트 공개는 각각 PM의 명시적 승인을 받는다.
- 현재 다른 작업의 수정 파일을 보존하고 이번 계획에 적힌 파일만 단계별로 stage한다.
- PM이 요청하기 전에는 commit하지 않는다. 각 태스크의 커밋 명령은 승인 뒤에만 실행한다.
- 원본 녹음은 인파 저장공간에서 녹음 종료 기준 최대 7일만 보관한다.
- 녹음 하나당 사용자 AI 요약 실행은 한 번이며 관리자도 재요약할 수 없다.
- 대화문·원음·메모 본문·프롬프트·AI 응답 원문은 로그·Sentry·분석 이벤트에 넣지 않는다.
- 음성 원본은 Anthropic에 전달하지 않는다. 식별정보를 줄인 텍스트만 요약 모델에 전달한다.
- 모델 ID와 모든 공급자 비밀값은 서버 환경변수로만 주입한다.
- 사용자 화면에는 쉬운 한국어와 다음 행동을 쓰며 `—`, `불가`, `준비 중`, `안 됩니다`를 쓰지 않는다.
- 서비스 화면은 light-fixed로 유지하고 기존 `Card`, 색상 토큰, 버튼 스타일을 재사용한다.
- 공개 화면(`/s`, `/d`, `/c`, `/b`)에는 원음·상담 메모를 노출하지 않는다.
- 서버가 모든 소유권·동의·한도·파일 형식·상태 전이를 다시 검증한다.
- 분석 이벤트에는 stable event type과 owner/customer FK, 상태 enum만 저장하고 원음·대화문·메모 본문·파일 key는 저장하지 않는다.

---

## 배포 단위

1. [Release 1: 여러 메모와 기존 메모 이관](./2026-07-22-consultation-recording-release-1-multiple-memos.md)
2. [Release 2: 상담 녹음과 7일 자동 삭제](./2026-07-22-consultation-recording-release-2-recording-retention.md)
3. [Release 3: 녹음당 한 번 AI 요약](./2026-07-22-consultation-recording-release-3-ai-summary.md)

각 릴리스는 다음 순서로만 진행한다.

```text
Release 1 코드·마이그레이션·UI 검증
→ PM 프리뷰 확인
→ PM 프로덕션 배포 승인
→ Release 2 내부 계정 파일럿
→ 삭제·실기기 증거 확인
→ Release 3 내부 계정 파일럿
→ 정확도·비용·동의 증거 확인
→ PM 일반 공개 승인
```

## 기술 결정 근거

- 브라우저는 `MediaRecorder.isTypeSupported()`로 실제 지원 형식을 고르고 `timeslice` 조각을 만든다.
- R2 multipart는 5MiB 이상 동일 크기 part가 필요하므로 브라우저 버퍼는 8MiB로 묶고 마지막 part만 작게 허용한다.
- 앱은 6일 23시간 45분에 원음 삭제를 시작하고 15분마다 정리한다. R2 lifecycle은 6일로 설정해 최대 24시간 지연돼도 7일 이내가 되도록 2차 안전망으로 둔다.
- CLOVA Speech 장문 비동기 작업은 `/recognizer/upload`로 접수하고 발급된 token을 `/recognizer/{token}`으로만 조회한다.
- Claude structured output은 `output_config.format` JSON Schema로 네 구역 배열을 강제한다.
- 오디오 실길이 검증은 Python 3.11용 binary wheel이 제공되는 `av==18.0.0`으로 수행한다.
- Anthropic SDK는 structured output을 지원하는 `anthropic==0.117.1`로 올리되 기존 OCR 회귀 테스트를 먼저 통과시킨다.

## 전체 완료 기준

- Backend: `python manage.py check`, 전체 `python manage.py test inpa`, PostgreSQL 동시성 테스트 통과
- Frontend: `npm run test:run`, `npm run lint:copy`, `npm run build` 통과
- Migration: 운영과 같은 PostgreSQL에서 apply 뒤 행 수·본문 해시·제약 직접 조회
- Runtime: 로컬 API 실제 호출, 브라우저 렌더, iPhone Safari·Android Chrome·Samsung Internet 실기기 확인
- Storage: 업로드·재생·조기 삭제·7일 삭제·고아 multipart·만료 URL 확인
- Privacy: 로그·Sentry fixture에서 원음·대화문·메모·식별정보 0건
- AI: 동시 100요청 외부 예약 1회, 골드셋 중대 환각·화자 반전·식별정보 누락 0건

## 기능 사용 계측 계약

`NorthStarEvent`에 다음 stable string을 추가하고 `log_event`의 기존 실패 격리 계약을 재사용한다. 각 릴리스의 API service에서 transaction 성공 뒤 기록하고 payload는 아래 enum·숫자만 허용한다.

```text
consultation_memo_created: source=manual|ai_summary|legacy_migrated
consultation_memo_edited: source=manual|ai_summary|legacy_migrated
consultation_recording_started: mime_family=webm|mp4
consultation_recording_completed: duration_bucket=<15|15-30|30-45|45-60
consultation_recording_source_deleted: reason=early_delete|retention_expired|consent_revoked|customer_deleted
consultation_summary_requested: benefit=customer_first|monthly
consultation_summary_succeeded: duration_bucket, plan_code
consultation_summary_failed: outcome=failed|ambiguous|cancelled, error_code enum
consultation_summary_upgrade_viewed: limit_kind=success_count
```

`inpa_be/inpa/analytics/models.py`, `history.py`, tests를 각 릴리스에서 함께 수정한다. 관리자 집계에는 건수와 전환율만 추가하며 event payload에 본문 길이 외의 content-derived 값도 넣지 않는다.

## 외부 운영 선행 조건

- 전용 비공개 R2 bucket과 `consultation-recordings/` prefix 생성
- 허용 origin을 `https://www.inpa.kr`과 실제 preview origin으로 제한하고 `ETag`를 CORS 노출 헤더에 추가
- 미완료 multipart 1일 삭제, 완성 원음 prefix 6일 lifecycle을 최대 7일 보관의 2차 안전망으로 설정
- NAVER CLOVA Speech 도메인·Invoke URL·Secret Key 발급과 음원 임시 보관·파기 조건 서면 확인
- Anthropic 상용 API 계약·보관 정책과 실제 선택 모델의 structured output 지원 확인
- 상담 녹음·민감정보·국외이전 동의문 최종 승인
