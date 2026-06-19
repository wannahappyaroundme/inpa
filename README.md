# 인파 (Inpa) — 보험설계사 AI 영업 파트너 (신사업)

> **인파(Inpa)** = **인**슈어(Insure) + **파**트너(Partner). 위촉직 보험설계사 곁에서 새 고객을 **발굴 → 보장분석 → 갈아타기 제안**까지 한 흐름으로 끝내주는 AI 영업 파트너.
> 보험 분석/문구 생성은 **Claude AI**.
> 현재 상태: **기획 완료 → 개발 시작 단계.**

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
├─ README.md          ← 지금 이 파일
├─ CLAUDE.md          ← AI 에이전트용 프로젝트 가이드
├─ inpa.code-workspace  ← VS Code 워크스페이스 (신규 + 포팅 참조)
├─ docs/              ← 기획·사업 문서 (아래 참조)
└─ (개발 시작 시) frontend/ · backend/ 추가 예정
```

## 기획·개발 문서 (`docs/`)
6역할(대표·사업관리·기획·마케터·디자이너·개발) 라운드테이블 토론으로 도출. **[docs/README.md](docs/README.md) 가 인덱스 — 여기서 시작.**

**기획 7**: [01 개요·비전](docs/01-overview-vision.md) · [02 시장·타겟](docs/02-market-users.md) · [03 기능·MVP](docs/03-product-features.md) · [04 화면(IA·UX)](docs/04-ia-and-ux.md) · [05 AI·데이터](docs/05-ai-and-data.md) · [06 비즈니스모델](docs/06-business-model.md) · [07 GTM·로드맵](docs/07-gtm-and-roadmap.md)

**개발 4** (`docs/dev/`): [01 아키텍처·스택](docs/dev/01-architecture-and-stack.md) · [02 데이터모델·API](docs/dev/02-data-model-and-api.md) · [03 foliio→인파 포팅지도](docs/dev/03-porting-map.md) · [04 빌드계획](docs/dev/04-build-plan.md)

> `docs/_brief.json` = 라운드테이블 원본(토론·결정 12·문서가이드). `docs/_archive-foliio/` = 이전 'Foliio 영업지원 에디션' 명칭 기획 원본(보존).

---

## 기술 스택 (예정 — 기존 Foliio 코드 재활용)
| 영역 | 스택 |
|---|---|
| 프론트 | **Next.js + TypeScript + Tailwind** (Claude Code 개발 최적 · foliio 랜딩도 Next.js · Tailwind=디자인 토큰 그대로) |
| 백엔드 | **Django 4.1 + DRF + Python** (foliio의 `claude_parser`·`calculate.py`(8케이스)·정규화 로직 **그대로 재사용** — 핵심 자산) |
| DB | MariaDB (PostgreSQL 전환 보류 — foliio 포팅비용 0) |
| AI | Anthropic Claude API (비교안내서·정규화=Opus 4.8 / 다건OCR=Haiku / 야간배치=Batches) |
| 재활용/신규 | **재사용=Python 백엔드 로직**(OCR·8케이스·정규화) / **신규=Next.js 프론트**(3축 화면 어차피 신규). FE는 Angular 재사용 대신 Claude-friendly Next.js로 신규 빌드 |

## 개발 시작 순서 ([docs/dev/04-build-plan.md](docs/dev/04-build-plan.md) 기준)
1. **먼저 정할 것 (코드 0줄, 법무 선결)** — ① 보장 기준선 출처 ② 병력 국외이전 동의(consent_overseas_at+ConsentLog) ③ §97 비교안내 정확요건 6항목
2. 프로젝트 스캐폴딩 (frontend/backend) + 공통 컴포넌트
3. **Phase 1**: 증권 업로드(OCR) + 담보 정규화 사전 → 담보 한눈표(히트맵 3색) → 갈아타기 비교안내서 → AI 메시지
   - 게이트 막히면 OCR·히트맵(none 중립)부터 선출시

## 출시 전 브랜드 체크 (이름 = 인파 / Inpa)
- [ ] KIPRIS 상표 검색 (보험 36류·SW 9·42류) — "인파" 보험/금융 출원 여부
- [ ] 도메인 `inpa.co.kr` / `inpa.kr` / `inpa.app` 확보 가능 여부
- [ ] 동명 최종 확인: 인파(人波=군중) 일상어 / BMW INPA(해외 진단툴) / 개발 블로그 등 — 모두 보험 분야 무관이나 검색 충돌 점검

---

*기획 단계 자동 메모리·결정 이력은 기존 foliio 프로젝트 메모리에 누적되어 있음.*
