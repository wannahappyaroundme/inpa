# 검색·AI 노출(SEO/AEO) 토대 + 공개 FAQ — 설계

> 2026-07-12. PM 확정: 구글·네이버 검색 + AI 도구(ChatGPT·Gemini·Claude·Perplexity)에서 인파가 노출되도록 기술 토대 + 공개 FAQ 1개 + 랜딩/공개 페이지 SEO 보강. **FE only, BE·마이그레이션 0, 고객 대면 토큰 라우트(/s·/d·/c·/b·/p) 무변경.** 프로덕션·브랜드 인증 완료 상태.

## 목표
- 구글·네이버 검색 색인 + 리치결과 대상이 되게 한다.
- AI 답변 엔진(GPTBot·ClaudeBot·PerplexityBot·Google-Extended 등)이 공개 페이지를 크롤/인용하게 허용하고, 인파가 무엇인지 구조화된 사실로 제공한다.
- 고객 개인정보 링크(토큰 5종)·어드민·API는 모든 봇 차단 유지(현행).

## 현재 상태(탐사)
- `app/robots.ts`: `userAgent:"*"` 하나. allow `/$`,`/legal/`,`/data-policy`; disallow 토큰 5종·`/admin`·`/api`. sitemap 참조.
- `app/sitemap.ts`: 공개 4페이지(랜딩·terms·privacy·data-policy).
- `app/layout.tsx`: title/description/keywords/OG/twitter/PWA/themeColor 있음. `metadataBase` = `NEXT_PUBLIC_SITE_URL` ?? `https://www.inpa.kr`.
- **JSON-LD 구조화 데이터 없음.** 네이버 인증 메타 없음. llms.txt 없음. 공개 FAQ 페이지 없음(인앱 boards FAQ는 로그인 전용, 별개).

## 설계 (FE only)

### 1. robots.txt 개편 — AI 봇 명시 허용 (`app/robots.ts`)
- 기존 `*` 규칙 유지(공개 페이지 allow / 토큰·admin·api disallow).
- AI 봇을 이름으로 명시 허용(각각 공개 페이지 allow, 토큰·admin·api disallow 동일):
  `GPTBot`, `OAI-SearchBot`, `ChatGPT-User`(OpenAI) · `ClaudeBot`, `Claude-User`, `anthropic-ai`(Anthropic) · `PerplexityBot`, `Perplexity-User`(Perplexity) · `Google-Extended`(구글 AI/Gemini) · `Bingbot` · `Applebot-Extended`.
- 규칙 배열 = 봇별 objects + 마지막 `*`. 상수 `AI_BOTS`/공통 allow·disallow로 중복 제거.
- ⚠️ 토큰 라우트는 트레일링 슬래시(`/s/`…) 유지(§ 기존 gotcha: `/s` 접두 매칭이 `/schedule`까지 막음).

### 2. 구조화 데이터(JSON-LD) — `components/structured-data.tsx`(신규)
- 순수 컴포넌트 `JsonLd({ data })` → `<script type="application/ld+json">` (React 안전 직렬화, dangerouslySetInnerHTML JSON.stringify).
- 상수 `ORGANIZATION`, `WEBSITE`, `SOFTWARE_APP` export(사실 데이터, `metadataBase` 기준 절대 URL). 랜딩(`app/page.tsx`)에 3종 부착.
  - `Organization`: name "인파(Inpa)", legalName "(주)서울엘엔에스금융컨설팅", url, logo(120 PNG 절대 URL), email hello.fingo.official@gmail.com, brand 핀고.
  - `WebSite`: name·url·inLanguage "ko".
  - `SoftwareApplication`: name "인파(Inpa)", applicationCategory "BusinessApplication", operatingSystem "Web", description, offers(무료 시작 = price 0, priceCurrency "KRW"). 요금 구체 숫자는 stale 위험이라 offers는 무료 항목만.
- `FAQPage`는 /faq 에서 그 페이지의 Q&A로 생성(4번).
- ★ 정직성 레드라인: 조작된 평점(aggregateRating)·후기·수상 스키마 금지(있지도 않은 신뢰신호 날조 안 함).

### 3. llms.txt — `public/llms.txt`(신규, 정적)
- llms.txt 관례(마크다운): 한 줄 요약 + 주요 공개 링크(랜딩·FAQ·약관·개인정보) + "인파가 무엇인지" 3~5줄. 크롤 봇/LLM이 사이트 맥락을 빠르게 잡게.
- 정직성 동일 적용(중개 안 하는 분석·정리 도구).

### 4. 공개 FAQ 페이지 — `app/faq/page.tsx`(신규)
- 라이트 고정, 랜딩 톤. 데이터는 `FAQ_ITEMS`(질문/답변 배열) 단일 소스 → 화면 렌더 + `FAQPage` JSON-LD 동시 생성(불일치 방지).
- metadata: title "자주 묻는 질문", description, canonical `/faq`, OG(기존 public-og 또는 기본).
- 질문(정직성·§6 easy-words 준수, 과장·배지 금지, em-dash 금지):
  1. 인파는 어떤 서비스인가요?
  2. 누구에게 맞나요?(위촉직 보험설계사)
  3. 보험 증권은 어떻게 분석하나요?
  4. 인파가 보험을 중개하거나 권유하나요? → **아니요, 분석·정리 소프트웨어**(honesty redline 문구).
  5. 비교 분석(갈아타기)은 어떻게 돕나요? → 중립 시각화, 판단은 설계사.
  6. 요금은 어떻게 되나요? → 무료 시작 + 유료 요금제(구체 숫자는 랜딩 링크, stale 회피).
  7. 고객 개인정보는 어떻게 관리되나요? → 동의 기반·최소 수집(‘안전’ 배지 아님, 사실 서술 + 개인정보처리방침 링크).
  8. 모바일에서도 쓸 수 있나요?
  9. 어떻게 시작하나요? → 가입 CTA.
- 하단 가입/랜딩 CTA + 내부 링크.

### 5. 메타·사이트맵·인증 보강
- `app/sitemap.ts`: `/faq` 추가(priority 0.6, monthly).
- `app/layout.tsx`: `verification.other['naver-site-verification']`·`google` = env(`NEXT_PUBLIC_NAVER_SITE_VERIFICATION`/`NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION`, 미설정 시 미출력). canonical = 페이지별 `alternates.canonical`(랜딩·faq).
- 랜딩/공개 페이지 SEO 보강(디자인 불변, 시맨틱·크롤 텍스트만):
  - 시맨틱 헤딩 확인(정확한 h1 1개 + h2 섹션), 이미지 `alt` 채우기, 크롤 가능한 1~2줄 소개 문구(‘인파는 보험설계사를 위한 AI 영업 파트너입니다…’)가 텍스트로 존재하는지 확인/보강, 푸터에 `/faq` 링크 추가.
  - **디자인·레이아웃·데이터·라우팅 무변경**(렌더 텍스트/속성만 보강).

### 6. PM 콘솔 작업(비코드, 단계 안내)
- 네이버 서치어드바이저: 사이트 등록 → 인증(메타값 받아 env/코드 반영·재배포) → 사이트맵 제출.
- 구글 서치콘솔: (도메인 인증 완료) 사이트맵 `sitemap.xml` 제출.

## 검증
- FE `npm run build`(typecheck) + `lint:copy`(em-dash·준비중; 신규 FAQ/llms 카피 포함).
- JSON-LD 유효성(구글 리치결과 테스트 형식), robots.txt 봇 규칙 렌더 확인(`/robots.txt` 출력), sitemap `/faq` 포함, `/faq` 렌더.
- 적대적 다중 렌즈 검증: (a) 스키마·robots 정확성 + 현행 AI 봇 UA, (b) 카피 정직성·§6, (c) 빌드·모바일·디자인·완결성 크리틱(누락 베스트프랙티스).
- BE·마이그레이션·고객 대면 토큰 라우트 무변경.

## 비목표(YAGNI)
- 블로그/콘텐츠 허브, 다국어(hreflang), 사이트 내부 검색(SearchAction), 조작 신뢰신호 스키마 — 이번 범위 아님.
