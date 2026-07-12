# 인파 노트(블로그) — 페르소나 카운슬 종합 + 구현 계획

> 2026-07-12. 전략 SSOT `docs/superpowers/specs/2026-07-12-content-marketing-strategy.md` → 페르소나 카운슬 5인(그로스·SEO / 기획 / 현직 설계사 / 법무·컴플라이언스 / 브랜드·보이스) → 이 계획. **PM 스키마 확인 후 빌드.**

## A. 카운슬 결정 (합의 + 조정)

1. **블로그명 = 인파 노트** (브랜드). iP 마크 + '노트' 워드마크. "정리해주는 동료" = 제품 본질과 직결.
2. **카테고리(공개 라벨 ← 내부 기둥):** `고객 늘리기`(영업·발굴) · `보장분석`(보장분석 실무) · `안심 가이드`(규정·안전, §조항 표기는 라벨에 노출 안 함) · `설계사 이야기`(사례·인터뷰).
3. **★ 기둥 논쟁 조정(그로스 vs 현직설계사):** 그로스="영업이 전환 1위, 균등배분 폐기(45:20:15:20)"; 현직="영업은 포화, 보장분석이 인파 데이터 해자". → **조정: 균등배분 폐기 + 첫 배치는 '차별화된 영업' + '보장분석' 가중.** 일반 영업론(지인 100명 리스트 류)은 배제, 인파 데이터 기반 각도만. 첫 8~10편 = 영업(차별화) 다수 + 보장분석 + 규정 1~2 + 사례 1.
4. **★ 직업급수 조회 = 블로그 글 아니라 인터랙티브 툴 페이지(별건, 고가치).** 인파는 이미 707 직업급수 + `/jobs/search` 보유 → 공개 "직업급수 조회" 툴 = 검색량·재방문·제품연결 최상. **Phase 2 또는 병행 별건**으로 분리(이번 MVP 아님, 명시).
5. **발행 주기 = 주 1편(PM 확정 2026-07-12, "무조건 할 수 있어").** 그로스 페르소나는 격주를 권고(1인 팀 지속성 리스크)했으나 PM이 주 1편 커밋. → 지속성 방어책으로 'Claude 초안→사람 검수(팩트·컴플라이언스·톤)' 워크플로우를 조기 정착시켜 편당 시간을 줄인다. 끊김이 최대 리스크이므로 최소 유지선은 반드시 지킨다.
6. **★ 전환 안전망(그로스 최대 지적, 배포 확장 전 선결):** 인스타/네이버/유튜브로 트래픽 늘리기 전에 **무료 캡처 장치 1개(이메일 옵트인/리드마그넷) 또는 리타겟팅 픽셀** 결정. 없으면 SEO=새는 양동이. 리타겟팅은 개인정보 고지 갱신 수반 → 보수적 검토. **MVP 빌드 대상 아님, 전략 선결 안건으로 명시.**
7. **측정 = 기존 인프라 재사용(신규 0):** UTM 캡처(`lib/useUtmCapture.ts`) + `AdminActivationFunnelView` + `analytics` NorthStarEvent. **★ 엔지니어링 갭: `useUtmCapture`가 랜딩에만 마운트 → 블로그 first-touch 미포착. 루트/블로그 레이아웃으로 이동 필요(이번 빌드 포함).** `analytics`에 `blog_view` 이벤트 추가.

## B. 브랜드 보이스 (원고 규칙)

- 5원칙: 선배처럼(강의 X) · 쉬운 말 · **답 먼저**(AEO) · 과장 없이(정직성) · 도구는 마지막·적합성 프레이밍.
- 글 스켈레톤: 제목(검색어 포함) → 훅 → **핵심 답 박스(브랜드컬러 좌측 바)** → 본문(H2/H3 = 실제 질문 문장, 표·체크리스트) → 인파 연결 1문단(fit-framing) → **정직성 1줄** → 다음 행동 CTA(`먼저 확인해보기`) + 관련글·/faq. 분량 1,500~2,500자.
- **커버 = 일러스트 0, 타이포 자동 OG.** 흰 배경 + 기둥색 **옅은 틴트 블록**(★ 히트맵 등급색 혼동 방지 = 원색은 작은 라벨 칩만) + 제목 + iP 마크(항상 파랑). MVP는 `cover_image`(PM 업로드) 우선, **타이포 자동 OG 라우트는 Phase 2**.

## C. 법무 가드레일 (원고 필수 준수)

- **한 줄 원칙:** 개념·규정·영업기법 '설명' = 안전 / 특정 상품·회사 '추천·비교·유도' = 광고·중개(금지, 인파 중개-안-함 기조 직결).
- DON'T(초안 스톱): 특정 보험사·상품 실명 우호 노출/비교, 소비자 대상 "가입하세요/갈아타면 이득", 결과·수치 보장, 조작 통계·"1위/인증" 배지, 규정글 단정적 법률자문 어투, 실제 고객 식별정보(각색), 사례를 '승환 성과'로 프레이밍.
- DO: 추상·개념 설명 + **공식 출처 링크(law.go.kr·금감원·협회)**, 가공/합성 예시, fit-framing CTA, 사례는 '설계사 업무 경험'(시간 절감·상담 명확) 수준.
- **YMYL/E-E-A-T:** 실명 바이라인/**감수자** 노출, 조문·수치 정확+**날짜 스탬프('2026-07 기준')**, 규정글 버전 스탬프(법 개정 트리거). AI 초안 OK지만 **규정·조문은 사람이 원문 대조 검수**.
- **디스클레이머(§6 확장, CPO 확정 필요):** 전 글 푸터 1줄(중개-안-함 + 약관·개인정보 링크) + **안심 가이드 글 1줄 추가**("일반 정보, 법률자문 아님, 소속사 컴플라이언스·금감원 확인"). 사례 수치글 "결과는 개별 상황 상이".
- ★ **실변호사 검토 선행(Pillar 2·3 확장 전):** 인파 블로그의 §95-4/자율심의 범위 밖 의견, §97·금소법 6대원칙 문구, 사례 초상·성과 릴리스 문안, 과태료 수치.

## D. 구현 계획 (Phase 1 = 한 덩어리로 출고, 기획 권고)

### BE (`boards` 앱 재사용 — Notice/Faq = shared·admin-write 동형, 새 앱 안 만듦)
- `boards/models.py::BlogPost`: `title(200)·slug(unique,index)·body(TextField 마크다운)·excerpt(200,blank)·cover_image(R2 ImageField,null)·category(choices 4)·tags(CharField comma,blank)·author(FK User SET_NULL null)·is_published(bool F)·published_at(dt null)·seo_title(60,blank)·seo_description(160,blank)·is_noindex(bool F 안전밸브)·view_count(PosInt 0)·created/updated`. 마이그레이션 1(additive). **OwnedQuerySetMixin 쓰지 않음**(global/shared, boards 예외군).
- 직렬화: List(본문 제외)·Detail(전체)·Admin(write). `boards/views.py::BlogPostPublicView`(AllowAny, `is_published=True` 필터, slug 조회; 어드민 토큰이면 draft도) + `blog/posts/sitemap/`(published `{slug,updated_at}[]`).
- `admin_console`: BlogPost CRUD(list incl draft·create·update·delete·publish 토글, IsAdmin) + **게시 시 카피 검사**(`core/copyguard.py` 확장: em-dash·금지어를 title/body/excerpt 스캔 → 경고 반환, 비차단).
- URL: `config/urls.py`/앱 urls 마운트(`/api/v1/blog/...`, `/api/v1/admin/blog/...`).

### FE
- `lib/api.ts`: 공개 `listBlogPosts(category?)·getBlogPost(slug)` + 타입. `lib/adminApi.ts`: admin CRUD + `uploadBlogCover`(R2 멀티파트, `uploadProfileImage` 패턴).
- 공개 `app/blog/page.tsx`(서버, 목록+카테고리 탭 `?category=`, 페이지네이션) + `app/blog/[slug]/page.tsx`(서버, `react-markdown`+`remark-gfm` 렌더, `generateMetadata` title/desc/OG/canonical/noindex, **BlogPosting JSON-LD** = `structured-data.tsx` `blogPosting()` 신규). 라이트 고정.
- 어드민 `app/admin/blog/page.tsx`(목록) + `app/admin/blog/new` · `[id]/edit`(전용 풀폭 에디터: 제목→슬러그 자동+수정(발행 후 변경 경고)·카테고리·태그·커버 업로드 미리보기·요약(카운터)·SEO 접기·**마크다운 툴바+실시간 미리보기(공개 렌더와 동일 컴포넌트)**·저장/게시 분리·비공개 미리보기). **에디터 UX 1급 투자**(주간 발행 지속 관건, 기획 리스크).
- SEO 배선: `app/sitemap.ts` 발행글 slug **동적 열거**(BE sitemap 엔드포인트), `app/robots.ts` ALLOW에 `/blog`, `lib/public-og.ts` 글별 OG(cover_image), `structured-data.tsx` `blogPosting()`.
- **UTM 갭 수정:** `useUtmCapture`를 루트 레이아웃(클라 래퍼)로 이동 → 블로그 first-touch 포착.
- 신규 의존성: `react-markdown` + `remark-gfm`(경량).

### 슬러그 정책(사전 확정)
- 제목에서 자동 생성(공백→`-`, 한글 허용) + **PM 수정 가능**. 발행 후 변경 시 경고(기존 링크·SEO 손실). 한글 슬러그는 구글이 처리(복사 시 %-인코딩되나 브라우저 표시는 정상).

### Phase 2 (후속)
- 타이포 자동 OG(`opengraph-image` 라우트) · **직업급수 조회 툴 페이지** · 관련글 모듈 · RSS · view_count 노출 · (검토 후) 이메일 옵트인/리드마그넷.

## E. 초석 글 주제 (첫 10편, 카운슬 키워드 종합 — 확정 전 초안)
1. (영업·차별) 신입 보험설계사, 지인 영업 다음에 할 일 · 2. (영업) 상담 예약률 높이는 문자·화법 · 3. (보장분석) 보험 증권 보는 법(설계사용) · 4. (보장분석) 갱신형 vs 비갱신형, 숫자로 보는 차이 · 5. (보장분석) 3대 진단비(암·뇌·심장) 기초 · 6. (보장분석) 회사마다 다른 담보 이름, 왜 그럴까(정규화=인파 데이터) · 7. (안심) 부당승환, 어디까지 괜찮고 어디부터 위험한가 · 8. (안심) 비교안내서 바르게 쓰는 법 · 9. (사례) 증권 분석 30분→3분(실측, 각색) · 10. (영업) 고객이 갈아타고 싶다 할 때, 비교안내서 없이 설명하면 생기는 위험.
- 전부 §C 가드레일·§B 보이스 적용. 규정글(7·8)은 실변호사 검토·출처 링크·날짜 스탬프.

## 검증(빌드 후)
- BE `check`+`test inpa`(BlogPost/공개/어드민/카피검사 회귀). FE `build`+`lint:copy`. 프로덕션 실서버로 /blog·/blog/[slug]·robots(/blog)·sitemap(동적)·BlogPosting JSON-LD·어드민 발행 왕복 실출력. 적대 다중 렌즈 검증.

## 비목표(YAGNI, MVP)
- Tag M2M · 댓글 · 예약발행 · RSS · 다국어 · AI 초안버튼 · 타이포 자동OG(Phase2) · 직업급수 툴(별건).
