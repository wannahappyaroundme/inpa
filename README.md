# 인파 (Inpa) — 보험설계사 AI 영업 파트너 (신사업)

> **인파(Inpa)** = **인**슈어(Insure) + **파**트너(Partner). 위촉직 보험설계사 곁에서 새 고객을 **발굴 → 보장분석 → 갈아타기 제안**까지 한 흐름으로 끝내주는 AI 영업 파트너.
> 보험 분석/문구 생성은 **Claude AI**.
> 현재 상태: **Phase 1 진행 중** — 백엔드 13개 Django 앱 + 프론트 전체 라우트(공개·인증·관리자 약 60개 페이지) 구현. 구글 연동(소셜로그인+캘린더)·미팅예약·개인 일정·동의 흐름 동작. 컴플라이언스 게이트(병력수집·§97 발행·국외이전)는 정식 출시 전까지 env 플래그로 닫힘.
> **2026-06-26 추가(PM 06.24 피드백)**: 고객 영업화면(4단계 DB·TA·FA·청약 칸반/방치 색상경보/즐겨찾기·고정/아바타·보험나이/정보·계약 탭/명함) · 캘린더 5분류 · 계약 유지율 1·2·3년 + 관리직 ROI 대시보드 · 계약 설명의무 체크리스트 · 판촉물 전자자료(1회 무료→어드민 큐+알림) · 운영 미디어 S3 전환(env 게이트).
> **2026-06-28 추가**: 발굴 입구(셀프진단 링크 위젯 — 홈·고객목록 + 유입경로 `lead_source` 측정) · 화법/문구 라이브러리(`/scripts`, 5카테고리·`{고객명}`/`{설계사명}` 치환·문자광고 가드) · 계약 체크리스트 '불리사항 고지'(§97 설계사 내부전용) · 랜딩·서비스 카피 정직성/쉬운말 교정 · **QA P0 수정**(이메일 인증 링크 복구·OCR max_tokens 8192·고객이력 내부필드 비노출·판촉 이미지 폴백).

> 작명: '당근(당신 근처)'과 같은 결 — 실존 단어 + 약어. **태그라인 후보**: "보험설계사 곁의 영업 파트너"

---

## 이게 뭔가
- 보험설계사가 **새 고객을 찾고(발굴) → 보장을 분석하고 → 제안·갈아타기까지** 한 동선으로 처리하는 도구.
- 보험 분석/문구 생성은 **Claude AI** 사용.
- **Freemium**: 기능은 다 열되 무료는 월 횟수 제한, 헤비유저만 구독.

## 핵심 차별점 (한 줄)
- **갈아타기(승환)를 합법적으로** — 부당승환 규제를 자동 "비교안내서"로 바꿔 방패로.
- **담보 100개+ 전체 '틀'** — 보험사별로 다른 담보명을 정규화해 한눈에 비교.

---

## 폴더 구조 (현재)
```
inpa/
├─ README.md             ← 지금 이 파일
├─ CLAUDE.md             ← AI 에이전트용 프로젝트 가이드 (개발 SSOT)
├─ inpa.code-workspace   ← VS Code 워크스페이스 (신규 + foliio 포팅 참조)
├─ inpa_be/              ← Django 4.2 + DRF 백엔드 (13개 앱)
├─ inpa_fe/              ← Next.js 16 + React 19 프론트엔드
├─ design/               ← 디자인 토큰·로고
├─ render.yaml           ← Render(BE) 배포 블루프린트
└─ docs/                 ← 기획·개발 문서 (아래 참조)
```
> `samples/`(실제 증권 PDF·PII)·`benchmark/`(UI 벤치마킹 참조 스크린샷)는 **로컬 전용 — 커밋 금지**.

## 기획·개발 문서 (`docs/`)
6역할(대표·사업관리·기획·마케터·디자이너·개발) 라운드테이블 토론으로 도출. **[docs/README.md](docs/README.md) 가 인덱스 — 여기서 시작.**

**기획 7**: [01 개요·비전](docs/01-overview-vision.md) · [02 시장·타겟](docs/02-market-users.md) · [03 기능·MVP](docs/03-product-features.md) · [04 화면(IA·UX)](docs/04-ia-and-ux.md) · [05 AI·데이터](docs/05-ai-and-data.md) · [06 비즈니스모델](docs/06-business-model.md) · [07 GTM·로드맵](docs/07-gtm-and-roadmap.md)

**개발 문서** (`docs/dev/`, 00~25): **[00 INDEX(마스터 지도·SSOT 진입점)](docs/dev/00-INDEX.md)** 에서 시작. 데이터모델 정본은 [02 데이터모델·API](docs/dev/02-data-model-and-api.md)(42 엔티티 + 가시성 매트릭스). 이후 03 포팅지도 · 04 빌드계획 · 05~10(사전준비·MVP슬라이스·API계약·히트맵·컴플라이언스·기준선) · 11~25(인증·고객/OCR·공유·카피·대시보드·법무·게시판·모바일·관리자·데브옵스·판촉물·알림·요금제·랜딩·배포가이드).

> `docs/_brief.json` = 라운드테이블 원본(토론·결정 12·문서가이드). `docs/_archive-foliio/` = 이전 'Foliio 영업지원 에디션' 명칭 기획 원본(보존).

---

## 기술 스택 (확정·구현됨 — 기존 Foliio 코드 재활용)
| 영역 | 스택 |
|---|---|
| 프론트 | **Next.js 16 + React 19 + TypeScript + Tailwind** (구현 완료 · Claude Code 개발 최적 · Tailwind=디자인 토큰 그대로) |
| 백엔드 | **Django 4.2 + DRF + Python 3.11** (foliio의 `claude_parser`·`calculate.py`(8케이스)·정규화 로직 **그대로 재사용** — 핵심 자산) |
| DB | **PostgreSQL** (운영=Neon 무료 / 로컬=SQLite) — 2026-06-21 MariaDB→PG 전환(Django ORM이라 코드 영향 0, `psycopg2-binary`) |
| AI | Anthropic Claude API (비교안내서·정규화=Opus 4.8 / 다건OCR=Haiku / 야간배치=Batches) |
| 배포 | FE→**Vercel** · BE→**Render**(`render.yaml`) · DB→**Neon** · CI=GitHub Actions(BE check+test · FE build · gitleaks) — 전부 GitHub 연동 자동배포($0) |
| 재활용/신규 | **재사용=Python 백엔드 로직**(OCR·8케이스·정규화) / **신규=Next.js 프론트**(3축 화면 어차피 신규). FE는 Angular 재사용 대신 Claude-friendly Next.js로 신규 빌드(완료) |

## 빌드 로드맵 (진행 중 — [docs/dev/04-build-plan.md](docs/dev/04-build-plan.md) 기준)
1. **먼저 정할 것 (코드 0줄, 법무 선결)** — ① 보장 기준선 출처 ② 병력 국외이전 동의(consent_overseas_at+ConsentLog) ③ §97 비교안내 정확요건 6항목 — *컴플라이언스 게이트로 env에 닫아둠.*
2. ✅ 프로젝트 스캐폴딩(`inpa_be`/`inpa_fe`) + 공통 컴포넌트 — **완료**
3. **Phase 1 (진행 중)**: 증권 업로드(OCR) + 담보 정규화 사전 → 담보 한눈표(히트맵 3색) → 갈아타기 비교안내서 → AI 메시지
   - 게이트 막히면 OCR·히트맵(none 중립)부터 선출시

## 출시 전 브랜드 체크 (이름 = 인파 / Inpa)
- [ ] KIPRIS 상표 검색 (보험 36류·SW 9·42류) — "인파" 보험/금융 출원 여부
- [ ] 도메인 `inpa.co.kr` / `inpa.kr` / `inpa.app` 확보 가능 여부
- [ ] 동명 최종 확인: 인파(人波=군중) 일상어 / BMW INPA(해외 진단툴) / 개발 블로그 등 — 모두 보험 분야 무관이나 검색 충돌 점검

---

*결정 이력·세션 메모리는 인파 프로젝트 메모리(`.claude/projects/.../memory/MEMORY.md`)에 누적. 기획 초기 일부 이력은 foliio 프로젝트 메모리에 있음.*
