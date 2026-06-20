# 인파 (Inpa) — Claude Code 가이드

> 보험설계사용 AI 영업지원 웹앱 신사업. **인파(Inpa) = 인슈어(Insure) + 파트너(Partner)** = 보험설계사 곁의 영업 파트너.
> 코드는 `~/Desktop/foliio`(Foliio 분석판, 고년차용)에서 포팅·재활용.
> **현재: Phase 0(개발 문서 정리) 완료, Phase 1(BE 스캐폴딩) 착수 직전.**
> `docs/dev/00~24` 개발 문서 24종 + FE 스캐폴드(`inpa_fe/`, Next.js, 데모 5페이지) 존재. BE(`inpa_be/`) 미착수.

## 핵심 컨텍스트
- **타겟**: 원수사·GA 위촉직(개인사업자) 보험설계사. 1순위 신입(발굴 절박), 2순위 중견(관리).
- **가치**: 새 고객 발굴 → 보장분석 → 갈아타기 제안을 한 동선으로. 분석=영업 행동의 시작점.
- **차별점**: ①갈아타기(승환)를 자동 비교안내서로 합법화(부당승환 §97 방패) ②담보 100+ 전체 '틀' + 보험사별 담보명 정규화.
- **BM**: Freemium (기능 다 열되 무료 월 횟수 제한, 헤비유저 구독).

## 스택 (2026-06-19 확정 — Claude Code 개발 최적)
- **FE: Next.js + TypeScript + Tailwind** (Angular 대신 — Claude Code 개발 속도·디자인 토큰 매핑 유리. foliio 랜딩도 Next.js 16).
- **BE: Django 4.1 + DRF + Python** — foliio의 `core/ocr/claude_parser`·`customers/calculate.py`(8케이스, numpy_financial)·담보 정규화 로직을 **그대로 재사용**(재포팅 위험 회피 = 핵심 자산).
- DB: **PostgreSQL**(운영=Neon 무료, 로컬=SQLite) — 2026-06-21 Railway 무료티어 폐지로 MariaDB→PG 전환(Django ORM이라 코드 영향 0, `psycopg2-binary`). / AI: Claude API(비교안내서·정규화=Opus 4.8 / 다건OCR=Haiku / 야간=Batches).
- **재사용=Python 백엔드 / 신규=Next.js 프론트**(3축 화면은 어차피 신규). Angular 컴포넌트는 재구현.
- 디자인 토큰: `design/tokens/inpa-tokens.css`(:root CSS변수) → Tailwind config 매핑. 로고: `design/logo/*.svg`.
- CPO=CTO 겸임(사용자 결정). 외부 법무 자문 계약 없음 → 컴플라이언스 게이트는 보수적 기본값+공개 가이드(협회·금감원)로 자체 처리, 유료 정식출시 전 재검토.

## 확정 결정 (2026-06-19 세션)
- **인증 = 이메일/비밀번호 전용** (카카오 OAuth 폐기). 회원가입→이메일 인증→로그인→비번찾기(이메일 토큰). 비번 해시 PBKDF2(Django 기본). 토큰은 별도 테이블 없이 Django 서명 토큰.
- **데이터 가시성**: 게시판(SNS 피드)·공지·FAQ·판촉물 샘플 = **공유**(전 설계사). 그 외(고객·동의·보험·분석·비교·캘린더·KPI·알림·기준) = **소유자 전용**(OwnedQuerySetMixin+IsOwner). 1:1문의=작성자+관리자. 판촉물 주문=소유자+관리자. `Customer.owner on_delete=CASCADE`.
- **배포 = GitHub 자동배포(무료 $0)**: FE→Vercel, BE→Render(무료, `render.yaml`), DB→Neon(무료 PostgreSQL), CI=GitHub Actions(gitleaks·commitlint). 이메일=Resend. (Railway는 무료티어 폐지로 제외)
- **랜딩페이지**(`/`, 공개): 히어로 "**설계사님은 클로징만 준비하세요**".
- **판촉물** = 샘플 사진 + 구글폼식 입력 + 예약 → 운영팀 수동 주문제작(자동발송 없음). (구 'promotion 14종 자동생성' 모델 폐기)
- 한도(Freemium): 베타 무제한(`FREE_TIER_UNLIMITED`), 수치·결제는 정식 전. planner_baseline 프리셋: 베타는 직접입력만.

## 문서 (`docs/`)
- **`docs/dev/00-INDEX.md` = 개발 문서 마스터 지도(SSOT 진입점)**. 전체 라우트맵·문서 인덱스·스트림↔엔티티 매핑.
- `docs/dev/02-data-model-and-api.md` — **데이터모델 정본(SSOT, 42 엔티티 + 가시성 매트릭스)**.
- `docs/dev/01`(아키텍처) `11`(인증) `12`(고객/OCR) `13`(공유) `14·16`(컴플라이언스/법무) `15`(대시보드) `17`(게시판) `18`(모바일) `19`(관리자) `20`(데브옵스) `21`(판촉물) `22`(알림) `23`(요금제) `24`(랜딩) — 스트림별 명세.
- `docs/01~07`(루트) — 사업·제품 기획 원본(Foliio 영업지원 에디션 명칭). `docs/_archive-foliio/` — 구 기획 아카이브.

## 개발 착수 전 게이트 (코드 0줄, 선결)
1. 보장 기준선(코어담보) 출처·면책 정의
2. 민감정보(병력) Claude API 국외이전 동의서 — **법무 선결**
3. 갈아타기 비교안내 법적 요건(§97) 확정
→ 이 3개 전에 AI 분석/비교안내서 기능 빌드 시작 금지. 막히면 OCR·담보표(중립 기능)부터.

## 빌드 순서 (docs/07 §0)
공통 컴포넌트 → 증권 OCR+담보 정규화 → 담보 한눈표 → 갈아타기 비교표 → 고객 메시지 → 고객상세/공백.
(포팅 지도: foliio의 `core/ocr/claude_parser.py`·`customers/calculate.py`·`insurances/models.py` 기준 — 보험사별 담보명 정규화 사전을 `_add_coverage` 매칭 단계에 끼움.)

## 작업 원칙 (사용자 = PM, 비개발자)
- 새 기능은 계획 합의 후 실행 (Plan 90% / Execute 10%). 코드 전 로드맵으로 설명.
- 한국어 소통. 컨설팅 용어 지양, 쉬운 말.
- 컴플라이언스(국외이전 동의·부당승환·광고심의)는 기능의 게이트 — 우회 금지.

## 정직성 레드라인 (제품 원칙)
- "심의 완료/안전" 배지 금지(보증책임). AI 생성물엔 "AI 초안·최종책임 설계사" 면책 고정.
- 원탭 자동발송 없음(카카오 불가) → 클립보드 복사/카톡 열기까지만.
