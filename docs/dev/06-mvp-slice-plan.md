# 인파 첫 슬라이스 — MVP 슬라이스 개발 기획서 (스캐폴딩 + 공유뷰A + 히트맵)

> 정본 교차검증: dev/01~05 + foliio 실코드(`customers/calculate.py:245`, `core/ocr/claude_parser.py:430·700`, `insurances/models.py` 8케이스 엔진) + inpa/CLAUDE.md(2026-06-19 확정). 7역할(대표/PM/CTO/BE/FE/디자이너/QA) 토론 합의를 테크리드가 정리한 **착수 직전 기획서**다. 추측은 모두 (추정)으로 표기한다.
>
> **이 문서는 계약·구조·순서만 다룬다. 실제 구현 코드는 쓰지 않는다.** 자매 문서: `dev/07-api-data-contracts.md`(API·데이터 계약), `dev/08-screen-specs-A-heatmap.md`(화면 스펙).

---

## 1. 이 슬라이스의 한 문장

> **증권 1장 → 30초 → "암 진단비 3,000만원 부족" 인사이트 카드 + 담보 히트맵**을, 설계사가 고객 카톡에 **링크 하나로 보내고 그 열람(`share_view`)이 서버에 잡히는 것**까지를 첫 슬라이스로 못 박는다.

비교안내서(§97)·AI 메시지·동의 풀스택·워치독·셀프진단은 **2차 웨이브로 명시 제외**한다. 첫 슬라이스의 목적은 **기능 완성이 아니라 "데모 1건의 느낌 증명"**이다. 이번 컷은 dev/04 fallback 1~2차(OCR + 히트맵 none 중립)와 1:1 정렬되어 있고, **법무 게이트 G1~G5가 하나도 안 풀려도 출시 가능한 영역만** 골라낸 것이 컷의 의도다.

성공 정의는 **북극성 곱셈(발송 × 열람 × 귀속)의 첫 항 '열람(`share_view`)'만 증명**하는 것이다. MAU·가입자수·유료전환 같은 허영지표는 이번 슬라이스 성공정의에서 제외한다.

---

## 2. 스코프 (In / Out)

### 2.1 In Scope — 우선순위 등급별

범례: **P0** = 없으면 데모 불가 / **P1** = 넣되 최소형(happy path) / 포팅 등급 ♻ 무변경 · ◑ 일부개조 · ✦ 신규

| # | 항목 | 등급 | 포팅 | 비고 |
|---|---|---|---|---|
| 1 | **스캐폴딩**: 단일 git repo `~/Desktop/inpa` 안 2워크스페이스(`inpa_be` Django4.1+DRF 포팅 / `inpa_fe` Next.js16+TS+Tailwind 신규) | P0 | — | foliio 복사+리네임(weapon→inpa), DB `foliio_db`→`inpa_db`, conda env `inpa`, gunicorn 8001(foliio 8000 분리) |
| 2 | **BE 분석엔진 포팅**: `calculate.py`(`calculate_total_analysis:245`, 8케이스), `CustomerInsurance.calculate`(`numpy_financial.fv`), `claude_parser.py`(`claude_parse:430`), `utils.py extract_text_from_pdf`, `Customer`(share_token/birth_day/gender), `credit.py` | P0 | ♻/◑ | calculate·8케이스·utils=♻무변경 / claude_parser=◑프롬프트만 / Customer=◑+1필드 |
| 3 | **8케이스 골든테스트 이식** (`test_premium_calculation_8cases.py`) → **179 passed 절대불변** | P0 | ♻ | 포팅 무결성 게이트 |
| 4 | **★북극성 계측 Day1 동결**(사후복원 불가): `NorthStarEvent` 모델 + 이벤트 6종 + `share_token?ref=<설계사코드>` 귀속. **DB 첫 마이그레이션에 박음** | P0 | ✦ | 사후복원 불가 → 의존성 무관 맨 앞 |
| 5 | **담보 분류 트리 시드**(`seed_taxonomy`): `AnalysisCategory/SubCategory/Detail/ChartDetail` 4계층 30→100+ 확장(15+ 카테고리), `chart_based_amount`=히트맵 기준선 hook | P0 | ♻+seed | 모든 분석의 입력 |
| 6 | **정규화 사전**: `NormalizationDict`(UNIQUE company+raw_name, hit_count 복리) + `UnmatchedLog` 학습루프. 이번엔 모델+seed+`_add_coverage` 3.5순위 lookup 삽입까지. 베타는 `admin_verified`만 매칭 | P0 | ✦ | 해자(moat). 오매핑=레드라인 |
| 7 | **공유뷰 A** `/s/[token]`: InsightHero(한 줄 인사이트+강조숫자) + 요약 KPI 3카드 + 담보 요약 리스트 + 나이별 보장 막대(FE 도출) + 면책푸터 상시고정 + 하단고정 CTA. 헤더/탭 숨김, 설계사 브랜딩, robots noindex, SSR(카톡 OG) | P0 | ✦ | 1순위 데모 화면 |
| 8 | **공유뷰 A API**: `GET /customer/:id/share/analysis/?token=&ref=`(AllowAny+share_token, calculate_total_analysis 출력 그대로 + insights[] + share_view/referral 서버계측) | P0 | ♻+계측 | |
| 9 | **담보 히트맵** `/customer/:id/analysis`: 15+카테고리×100+담보 3색 그리드, **중립모드 디폴트**(none만 회색), mode 플립 1줄로 graded 전환, 이중인코딩(색각), 모바일 가로스크롤+좌 sticky | P0 | ✦ | none 스캐너만으로 미팅 성립 |
| 10 | **히트맵 API**: `GET /customer/:id/heatmap/`(신규 `customers/heatmap.py`, `heatmap_status(actual,std_baseline,mode)` 판정 **BE 권위**, baseline_source=null→강제 neutral) | P0 | ✦ | |
| 11 | **OCR detect 최소형**: `POST /insurance/detect/`(412 동의게이트 배선 + `_add_coverage` 3.5순위 normalization.lookup 삽입). `consent_overseas_at` 필드 + 호출 전 412 | P1 | ◑ | happy path 위주. 암호화PDF 비번모달·partial_failed는 단건 happy만 |
| 12 | **디자인 토큰 3레이어 SSOT**: `inpa-tokens.css`(:root CSS변수) → Tailwind `theme.extend.colors` 매핑. 블루3종 역할잠금, stylelint `color-no-hex` | P0 | ✦ | |
| 13 | **공용 위생 컴포넌트**: `DisclaimerFooter`(면책 하드코딩, 안전배지 슬롯 물리부재) / `ConsentBadge`(중립워딩) / `Skeleton` / `StickyCTA`(safe-area). 정직성 레드라인을 타입유니온에서 '안전/심의완료/보장' 제외 → 컴파일 차단 | P0 | ✦ | |
| 14 | **CI/인프라**: GitHub private repo + remote 연결, `.github/workflows/ci.yml` path-filter 2잡, gitleaks pre-commit | P0 | ✦ | foliio origin 제거 상태 |
| 15 | **콜드스타트 empty state**: 고객0→[증권 올리기], 보험0→[증권 등록] 발굴 CTA | P1 | ✦ | |

### 2.2 Out of Scope — 2차 웨이브 (명시 제외)

| 항목 | 제외 사유 | 재진입 |
|---|---|---|
| 갈아타기 비교안내서(§97, `GET /customer/:id/compare/`) | G3 법무 미확정, 발행 하드블록 룰 근거 없음 | 2차 웨이브 |
| AI 카톡 메시지(`POST /ai/message/`) | G4 광고심의 미확정 | 2차 웨이브 |
| AI 가드레일 판정(`POST /ai/guardrail_check/`) | 메시지/비교서 후처리용 | 2차 웨이브 |
| 다건 일괄 OCR(`detect_batch/`, partial_failed[] 207) | 단건 detect만 포함 | 후속 |
| 국외이전 동의 풀스택(`/customer/:id/agree`, ConsentLog 6요건, doc_version) | 이번엔 `consent_overseas_at` 필드+412 배선만 | P1 |
| 워치독·만기갱신 cron(`watchdog.py`) | — | Phase 1.5 |
| 셀프진단 인바운드(`/check/:token`) | — | Phase 2(라우트 자리만 선점) |
| 추천코드·바이럴 루프 활성화(더블사이드 보상) | 계측 인프라만 Day1 | Phase 2 |
| 홈 액션큐 풀버전·설계사 KPI 대시보드 | 이번엔 고객목록+상세만 | 후속 |
| 정규화 OCR 자동승격(`ocr_learned`, hit_count≥N) | 베타는 admin_verified만 | 운영 미결 |
| graded 모드 3색 풀가동(enough/short UI) | Q1 법무 확정 전 코드만, neutral 디폴트 | 법무 회신 |
| 히트맵 BE 선계산 캐시(`CoverageMatrix`) | 첫 슬라이스 런타임 계산(조기최적화 회피) | computed_at 자리만 |
| 유료 결제·Plus 과금 ON·워터마크 | 베타 무차감 | 정식 출시 |
| MAU·가입자수·전환율 허영지표 | 북극성 첫 항(열람)만 증명 | — |

---

## 3. ★ 개발 착수 전 더 기획해야 할 것 (갭 체크리스트)

> "코드 짜기 전에 값이 확정돼야 막히지 않는" 항목. **blocking=true**는 해당 값이 잠기기 전엔 그 영역 착수 불가. 각 갭에 owner와 디폴트/fallback을 단다.

### 3.1 Blocking 갭 (5종 — Sprint 0 게이트, ALL PASS 또는 fallback 명시 승인 전 Sprint 1 불가)

| # | 갭 | owner | 디폴트/fallback |
|---|---|---|---|
| **B1** | **★북극성 이벤트 6종 스펙 동결**(최우선, 사후복원 불가): `ocr_upload/analysis_complete/share_link_create/share_clipboard_copy/share_view/referral_attributed` 각 페이로드 스키마(필드·타입·중복제거 키) + `?ref=<설계사코드>` 형식 + share_token 결합 규칙. **첫 DB 마이그레이션에 박혀야 귀속이 안 깨짐.** 미동결 시 영구 데이터 손실 | 대표(CPO=CTO) + PM | dev/05 §2-3 스키마 채택 후 동결. fallback 없음(반드시 잠금) |
| **B2** | **담보 정규화 사전 v0 시드 + OCR 골든셋 정답지**: 상위30담보×5사(삼성생명/교보/한화/삼성화재/현대해상) raw_name 청약서·약관 대조(~150행 CSV) + foliio `Test/` 107 PDF 핵심필드 정답 라벨링(데이터 인력 2~3일). **정확도 틀리면 히트맵 전체가 거짓 = 정직성 레드라인 위반.** seed_taxonomy 코딩의 D-0 전제 | 개발(CTO) + PM + 데이터 인력 | 시드 정확도 우선, 양 축소(상위 담보부터). 라벨 미완 시 85% 게이트 측정 불가 |
| **B3** | **공유뷰A 인사이트 카드 '한 줄 인사이트' 산출 규칙 + 중립모드 카피 분기**: "암 3,000만원 부족"의 3,000만원을 어떤 기준선(Q1 미확정)으로? 중립모드에선 '부족' 단정 불가 → 헤드라인을 'X담보 미보유'(none 기반)로 다운톤할지, 강조숫자를 보유액으로 바꿀지. 우선순위(없음>부족? 금액순?)·표기 상한(1 vs Top3)·반올림 단위. **고객 노출이라 정직성 레드라인 직접 적용** | PM + 디자인 + (법무 자체처리) | neutral=none(0원) 항목만 발화, '미보유' 카피. 강조 1개(추정), 베타 A/B |
| **B4** | **FE 스택 G0 PM 명시 승인**: dev/01~04 본문=Angular17 vs task브리프·CLAUDE.md=Next.js. 본 기획은 Next.js로 봉합(BE만 Django 포팅, FE 신규작성)했으나 foliio Angular FE 자산(customer-analysis/-compare, ng2-charts radar)을 버리고 재작성할지 PM 최종승인 필요. **결정 따라 repo구조·FE인력·일정 갈림** | PM(대표 승인) | Next.js 신규 채택(아키텍트 봉합). 공유뷰/히트맵은 net-new라 Angular 재활용분 ≈0 |
| **B5** | **국외이전 동의(G2) 최소형 법적 안전선 대표 승인**: 이번 OCR을 '동의 1탭'(`consent_overseas_at`+412)으로 열 것인가 vs 동의서·ConsentLog 풀스택 P1으로 미룰 것인가. CPO=CTO·외부 법무자문 없음 전제에서 '보수적 자체처리 1탭'의 법적 안전선을 대표가 명시 승인해야 detect 착수 가능. **막히면 데모를 수기입력으로 갈지 사전 합의** | 대표(CPO=CTO) | 동의 1탭 + 412 배선. 막히면 수기입력+히트맵 none 중립으로 데모 성립 |

### 3.2 Non-blocking 갭 (병행 결정 가능 — 출시 전 확정)

| # | 갭 | owner |
|---|---|---|
| N1 | **충족 3색 임계치 변수화 + 기준선 출처(Q1/G1) 권위**: `coverage-thresholds.ts` 80/30 + `std_baseline*0.7` 전부 (추정). 중립모드 출시면 당장 안 쓰지만 3색 활성화 시점의 출처·권위(금감원/보험연구원/자체+면책)를 누가 언제. `chart_based_amount` 100+ 담보별 실제 시드값 작성 주체. 데모 시 '왜 부족이라 단정하냐' 답변 스크립트 | PM + 개발 + (법무 자체처리) |
| N2 | **면책·동의·CTA 카피 6종 확정문안**(히트맵/공유뷰/동의/CTA/ExpertBanner/StickyCTA): 미확정이면 DisclaimerFooter/ConsentBadge 타입유니온 잠금도 불가. 글자수·줄수가 푸터 높이·CTA 겹침에 직접 영향. CTA[맞춤설계 받기]가 어떤 동선(연락처/상담폼/전화/카톡)으로 + 클릭 계측 이벤트명 | PM + 디자인 + (법무 자체처리) |
| N3 | **share_token 만료·회수·noindex 정책(Q4)**: `share_expires_at` 자리만 확보. 만료 TTL·회수 동선·열람로그 보존기간·만료 응답코드(410?)·ExpiredView 분기 미정. 민감 분석 단톡방 영구노출 사고 방지책 데모 전 합의 | PM + 개발 + 보안 |
| N4 | **공유뷰 개인정보 노출 범위 + 마스킹**: 고객명 마스킹(홍**), gender null 표기, 병력(민감정보) 노출 범위. 응답에 어디까지 내릴지. Test PDF 107장 실고객 PII(병력/주민번호) QA 픽스처 커밋 시 마스킹/익명화 + gitleaks 통과 선결 | PM + 보안 + QA |
| N5 | **북극성 ref_code 발급 체계**: `?ref=<설계사코드>` 생성·유일성·URL노출 위변조 방지 미설계(귀속 정확도 근간). Day1 스키마는 박되 발급 로직 설계 필요. share_view 신뢰KPI 중복·봇·카톡 인앱 프리뷰 카운팅 규칙(분모 오염 방지) | 개발(CTO) + PM |
| N6 | **설계사 브랜딩 vs 'Powered by 인파' 노출 비율**(추정 상단70%설계사/하단 1줄): 바이럴 귀속(인파 노출) vs 설계사 신뢰(본인 브랜딩) 상충. 데모 화면 바로 보이는 부분 → 첫 시안 전 결정. 베타 A/B | PM + 마케터 |
| N7 | **디자인 산출물(Figma/와이어프레임) 부재**: 공유뷰A·히트맵 픽셀 스펙(8pt 그리드, 인사이트 히어로 레이아웃, 셀 24/32px·탭영역 44px, 100+담보 IA 아코디언 기본상태·정렬·가로컬럼)이 있어야 컴포넌트 props 확정. 토큰 동기화 방식(복사 vs symlink) SSOT 드리프트 방지 | 디자인 |
| N8 | **OCR 추출률 85% 게이트 분모 정의 + 정규화 오매핑 허용 임계**: '7필드' vs 100+ 확장필드, 필드별 가중치(담보명·금액>상품명). 측정단위 안정해지면 PASS/FAIL 불가. 오매핑률 임계(추정 ≤5%) + 거짓충분이 거짓공백보다 위험 등급. 미분류 셀 노출 OCR 신뢰도 임계 | QA + 개발 |
| N9 | **베타 설계사 모집 경로·일정 + 데모 실증권 확보 동선**: 데모1건+정성인터뷰가 성공정의인데 설계사를 어느 지점/학원 단톡에서 언제(GTM). 본인 실증권 확보 시 개인정보 처리 사전 합의 | 대표 + 마케터 |
| N10 | **디바이스·접근성 매트릭스 실기기 확보**: 갤럭시 중저가·아이폰SE 실기 또는 BrowserStack 스테이징(deuteranopia/protanopia 명도차≥40·엄지도달·야외 저휘도 amber 가독성·iOS홈바/갤럭시 제스처바 safe-area 겹침). 환경 owner 미지정 | 개발 + 디자인 + PM |

---

## 4. 아키텍처 결정 (착수 전 봉합한 문서 모순)

토론에서 합의한 **확정 결정** 4건. 모두 dev 문서 간 모순을 테크리드가 봉합한 것이다.

### 4.1 FE 스택 모순 봉합 → Next.js 신규 (BE만 Django 포팅)

| | dev/01~04 본문 | task 브리프·CLAUDE.md | **확정** |
|---|---|---|---|
| FE | Angular17 재활용 | Next.js+TS+Tailwind | **Next.js 신규 작성** |

**근거**: "foliio 재활용 = BE Python 한정." 공유뷰A·히트맵·인사이트카드는 foliio FE(Angular)에 없는 net-new 화면이라 재활용분이 ≈0. 공유뷰는 foliio share-view의 "헤더숨김+토큰뷰" **개념만** 차용, 히트맵은 신규. 모바일퍼스트·PWA·카톡 OG SSR은 Next.js 우월. dev 문서 본문의 Angular 표기는 dev/05·CLAUDE.md가 정정한 것으로 간주. (PM 최종 승인 필요 = 갭 B4)

### 4.2 foliio Python 재사용 = '복사 후 리네임(vendoring)' 확정

| 방식 | 판정 | 사유 |
|---|---|---|
| A. pip 패키지화(`foliio-core`) | ✗ | weapon 앱 강결합, 패키지 경계 부재, foliio 리팩터 필요 |
| B. 마이크로서비스 호출 | ✗ | foliio prod 가동 중 → 결합·장애전파. calculate는 순수함수라 HTTP 오버헤드 낭비 |
| **C. 복사 후 리네임(vendoring)** | **✓** | 즉시 착수, 인파 독립 진화, foliio 무영향 |

**근거**: 8케이스 엔진은 **검증완료·변경동결 자산** → 복사 시 동기화 부담 ≈0(골든테스트가 회귀 가드). `claude_parser`는 어차피 ◑(프롬프트 개조)라 복사 필수.

**복사 절차(Sprint1 W1)**: ① `weapon/`→`inpa/` 리네임, import 일괄 치환 → ② DB `foliio_db`→`inpa_db`, env/systemd 리네임 → ③ 불필요 앱(banners/campaigns/feedback/promotion/community)은 복사하되 INSTALLED_APPS 주석(삭제 비용 > 방치) → ④ **8케이스 골든테스트 즉시 이식 → pytest green = 포팅 무결성 게이트**.

### 4.3 신규 모델 네이밍 = NormalizationDict + foliio 4계층

dev/05의 `StandardCoverage`/`CoverageMatrix` 신규 테이블 **기각**. foliio `insurances/models.py` 4계층(`AnalysisCategory~ChartDetail`)을 `calculate.py`가 입력으로 받으므로, 새 테이블을 만들면 **8케이스 엔진과 단절**. `CoverageMatrix`(선계산 캐시) 아이디어만 `computed_at` 자리로 흡수(런타임 계산 채택, 캐시 보류 = 조기최적화 회피).

### 4.4 히트맵 status 권위 = BE 단일 진실 원천

히트맵 status 판정(`none/short/enough`)·임계 `*0.7`·neutral/graded 플립은 **전부 BE**. FE는 status 문자열 → CSS변수 클래스 매핑만. dev/05의 `coverage-thresholds.ts`(FE 상수)와 충돌 → **BE 권위로 결정**(정직성 레드라인을 클라가 쥐면 위험). 단, 10칸→연속 보장구간 막대는 **FE 도출**(foliio 2026-06 원칙, BE 무변경).

---

## 5. Repo 구조 / env / tooling / CI

### 5.1 단일 repo · 2워크스페이스

모노레포 편입 **기각**(FE가 Angular→Next로 갈려 코드공유 이점이 BE Python으로 한정).

```
~/Desktop/inpa/                       # 단일 git repo
├── inpa_be/                          # Django 4.1 + DRF (foliio 포팅)
│   ├── config/settings/{base,local,idc}.py   # foliio 패턴 그대로
│   ├── inpa/                         # 'weapon' → 'inpa' 리네임
│   │   ├── core/                     # ♻ utils.py / ocr/claude_parser.py(◑프롬프트)
│   │   ├── customers/                # ♻ calculate.py / Customer(+consent_overseas_at) / ✦heatmap.py
│   │   ├── insurances/               # ♻ models 8케이스 / ✦normalization.py / ✦NormalizationDict
│   │   ├── membership/               # ♻ credit.py (+ai kind, 이번 미사용)
│   │   ├── analytics/                # ✦ NorthStarEvent (Day1 핵심)
│   │   └── …(banners/campaigns/feedback/promotion/community = 복사하되 미등록)
│   ├── requirements.txt              # foliio 동일(신규 의존성 0)
│   └── manage.py                     # 기본 idc — 로컬은 settings.local 강제
├── inpa_fe/                          # Next.js 16 + TS + Tailwind (신규)
│   ├── app/(planner)/customer/[id]/  # 설계사 인증 앱뷰 (히트맵)
│   ├── app/s/[token]/page.tsx        # ★ 공유뷰A (헤더숨김·공개·SSR+OG·noindex)
│   ├── components/heatmap/           # ★ 3색 그리드
│   ├── components/insight-card/      # ★ 삼쩜삼형 인사이트
│   ├── components/hygiene/           # ★ DisclaimerFooter/ConsentBadge/Skeleton/StickyCTA
│   └── lib/api/                      # BE 클라이언트 + 타입 SSOT
├── design/tokens/inpa-tokens.css     # ★ 토큰 3레이어 SSOT (확인완료)
├── docs/                             # dev/06·07·08 정본
└── scripts/{verify.sh, seed_taxonomy 래퍼}
```

### 5.2 env / DB / 포트

```
# inpa_be/.env (foliio 슬롯 승계 + 인파 분리)
SECRET_KEY=                # 신규 생성 (foliio 키 재사용 금지)
DJANGO_DEFAULT_DATABASE_NAME=inpa_db
CLAUDE_API_KEY=            # 인파 전용 키 (월 예산 캡 분리) — BE 전용, NEXT_PUBLIC 절대금지
KAKAO_REST_API_KEY=       # 인파 신규 카카오 앱 (foliio app_id 공유 금지)
SENTRY_DSN=
SENTRY_ENVIRONMENT=inpa-prod   # foliio 노이즈 격리
```

| 항목 | 값 | 근거 |
|---|---|---|
| DB | MariaDB, `utf8mb4_unicode_ci` init_command 그대로 | 한글 WHERE 안전(foliio failure 트랩) |
| conda env | `inpa` | foliio `foliio`/`backup` env 무손상 |
| gunicorn 포트 | **8001** | foliio 8000과 분리 |
| AI 키 | `CLAUDE_API_KEY` BE `.env`에만 | FE `NEXT_PUBLIC_*`에 시크릿 금지. AI 호출 100% BE 경유 |

**무게이트 특이점**: 공유뷰A·히트맵은 추출 후 서버연산 → `CLAUDE_API_KEY` 없이도 동작(detect만 AI). 콜드스타트 선출시 가능.

**신규 테이블 4종 + 마이그레이션/시드 순서**:
```
makemigrations → migrate → seed_taxonomy → loadinitialmemberships
  1. AnalysisCategory~ChartDetail   ♻ 모델무변경 + seed 30→100+   ← 최선행
  2. NormalizationDict + UnmatchedLog ✦ 담보명 정규화(해자)
  3. Customer +consent_overseas_at   ◑ 1필드 (스키마 Day1 박음)
  4. NorthStarEvent (analytics)      ✦ Day1 필수 — 사후복원 불가
```

### 5.3 tooling

| 영역 | 도구 | 근거 |
|---|---|---|
| BE lint/format | flake8(120) + black (foliio `setup.cfg` 승계) | 동일 컨벤션 |
| BE test | pytest(`--reuse-db`, `settings.test`) | 8케이스 골든 이식 |
| FE lint | ESLint + Prettier + **stylelint `color-no-hex`** | raw hex 차단 = 토큰 SSOT 강제 |
| FE 타입 | `tsc --noEmit` (Next16 빌드 검증) | |
| 시크릿 | gitleaks pre-commit | 보안 baseline |

### 5.4 CI (착수 전 P0: GitHub private repo + remote 연결 — foliio origin 제거 상태)

```yaml
# .github/workflows/ci.yml — path-filter 2잡
be:  # inpa_be/** 변경 시
  - pytest (8케이스 골든 179 = 회귀 게이트, 실패 시 빌드 차단)
  - flake8 (legacy non-blocking)
fe:  # inpa_fe/** 변경 시
  - tsc --noEmit + next build
  - stylelint (color-no-hex)
  - 정직성 금지카피 grep (안전배지/AI보장 골든 회귀)
공통: gitleaks
```

---

## 6. 빌드 순서 / 스프린트

```
[Sprint 0 선행·코드0줄]  ── 블로커 5종 잠금 (ALL PASS or fallback 승인)
        │
[Sprint 1] 부트스트랩 + 데이터 뿌리 + ★계측 Day1
        │   (8케이스 골든 green = 포팅 무결성 게이트)
        ▼
[Sprint 2] BE 분석 API → FE 히트맵 → FE 공유뷰A
            └ calculate_total_analysis 출력의 소비자라 BE 선행 필수
```

**의존성 강제 근거**: ① 계측은 의존성과 무관하게 맨 앞(사후복원 불가) → ② 정규화 사전은 OCR 직후(매핑 틀리면 히트맵 전체 거짓) → ③ 히트맵·공유뷰는 `calculate_total_analysis` 출력의 소비자라 BE 분석/시드가 반드시 선행 → ④ 1순위 데모 화면은 히트맵이 아니라 **공유뷰A**(북극성 첫 곱 '열람=share_view'를 만드는 유일한 화면).

### Sprint 0 (선행, 코드 0줄) — 블로커 잠금
★북극성 6종 스펙 동결 + 정규화 사전 v0 ~150행 CSV + OCR 골든셋 107PDF 라벨링 + 면책/인사이트 카피 6종 확정 + FE스택 G0·국외이전 1탭 대표 승인 + 디자인 토큰 SSOT(`inpa-tokens.css` 확정완료, Tailwind 매핑) + GitHub private repo·remote·CI 활성화. **ALL PASS 또는 fallback 명시 승인 시 Sprint 1 착수.**

### Sprint 1 (W1~W2) — 부트스트랩 + 데이터 뿌리 + ★계측 Day1
단일 repo 2워크스페이스 부트스트랩 → foliio BE 복사+리네임(weapon→inpa: utils/calculate/Customer/credit, 불필요앱 INSTALLED_APPS 주석) → settings local/idc 분리·MariaDB utf8mb4·.env 시크릿 분리 → **8케이스 골든테스트 즉시 이식 pytest green**(포팅 무결성 게이트) → **★NorthStarEvent 모델+마이그레이션**(share_view/referral_attributed 첫 마이그레이션 박기) → `seed_taxonomy`(AnalysisCategory/Detail 100+ + NormalizationDict v0) + `consent_overseas_at` 1필드.
**데모**: 분석 JSON 출력 + `share_view` 이벤트 적재.

### Sprint 2 (W3~W4) — 분석표면 + 화면
BE `heatmap.py` 신규(`heatmap_status` neutral 디폴트 폴백) + `GET /customer/:id/heatmap/` + `GET /customer/:id/share/analysis/?token=&ref=`(계측 발화) + detect 412 게이트 배선·`_add_coverage` 3.5순위 normalization.lookup 삽입 → FE 공용 위생 4종(DisclaimerFooter/ConsentBadge/Skeleton/StickyCTA, 안전배지 슬롯 물리삭제)+토큰 import → 히트맵 그리드(client useQuery, 이중인코딩, 가로스크롤+sticky) + 공유뷰A(SSR+Query hydration, InsightHero 인사이트카드+강조숫자, noindex) 병행.
**데모(= 슬라이스 게이트)**: 공유링크 열면 인사이트카드(고객 폰에서 share_view 서버적재), 설계사는 3색 히트맵 = 데모1건 한 사이클.

---

## 7. 게이트 분리 전략 (막힐 때 중립기능 우회)

이번 슬라이스의 모든 P0는 **이미 fallback 모드로 설계**되어 게이트와 분리된다.

```
                  추출(입력단)              서버연산(무게이트)
   증권 ──OCR/detect──► [담보 입력] ──► calculate ──► 히트맵 ──► 공유뷰A
            ▲ 412 동의게이트              (게이트 없음)
            │ G2만 여기 물림
            └─ 막히면 [수기입력] 으로 우회 ──────────────────┘
```

| 게이트 | 막힘 영역 | 우회 |
|---|---|---|
| **기준선 출처(G1/Q1)** | 히트맵 3색 graded | **중립모드 디폴트**: none(0원)만 회색/표기, enough/short는 코드만 작성·UI 보류. `mode='graded'` 1줄 플립. **발굴 가치의 80%는 "이 담보 아예 없네요"** → 중립모드만으로 미팅 성립 |
| **국외이전 동의(G2)** | OCR(detect) 입력단 **유일한 진짜 블로커** | ① '동의 1탭'(`consent_overseas_at`+412 배선)으로 처리 → ② 그래도 막히면 **수기입력 + 히트맵 none 중립**으로 데모 성립. OCR 봉인. **공유뷰A·히트맵 자체는 어떤 게이트에도 안 막힘** |
| **§97·광고심의(G3/G5)** | — | 이번 슬라이스에 해당 기능 자체가 없음. 분리 끝 |

**경계 명시(IA 문서 충돌 봉합)**: dev/04-ia-and-ux:165는 "동의 미수신=히트맵 블러+잠금"이라 적혀 충돌하나, **히트맵 화면 블러는 UX 표현이지 데이터 게이트가 아니다**(디자이너 봉합). **412는 detect(OCR)에만 물린다** — 공유뷰A·히트맵은 추출 후 서버연산이라 무게이트 경로. 단, 히트맵을 그리려면 이미 detect로 담보가 입력돼 있어야 하므로, '히트맵 단독 선출시'에는 **수기입력 폴백 동선**이 필요(데이터 진입 경로 = 갭 B5와 연동). 이 경계를 AC에 명시한다.

---

## 8. 수용기준 (Acceptance Criteria)

### 8.1 기술 완료선 (코드 작성 ≠ 완료 — 빌드 차단 게이트)

| AC | 기준 | 검증 방법 | 차단 |
|---|---|---|---|
| AC-1 | **8케이스 골든 179 passed 불변** (calculate.py 무변경 증명) | `pytest …test_premium_calculation_8cases.py` | ✅ |
| AC-2 | **OCR 추출률 ≥ 85%** | foliio `Test/` 107 PDF 골든셋 측정(분모 정의=갭 N8) | ✅ |
| AC-3 | **정규화 오매핑률 ≤ 5%**(추정) | 보험사별 매핑 골든셋 | ✅ |
| AC-4 | **정직성 금지카피 100건 100% 차단** | CI grep 골든 회귀 | ✅ |
| AC-5 | **heatmap_status 4상태 전수 PASS** (none/short/enough/neutral, boundary=`*0.7` 정확히 → enough) | 단위테스트. `baseline_source==null`→강제 neutral(enough/short 절대 노출 0) | ✅ |
| AC-6 | **면책 푸터 상시노출** (전 화면 하단 고정, 스크롤·접기 불가) + 안전배지 DOM·번들 grep 0건 | DOM 검증 + grep | ✅ |
| AC-7 | **증권 업로드 → 히트맵 렌더 5분 내** 도달 | 실측(계측 funnel) | — |
| AC-8 | **share_view 서버 1건 적재**: 공유링크 생성 → **다른 기기** 열람 시 서버 이벤트 1건(중복 가드), `?ref=` 있으면 referral_attributed | 다른 기기 E2E + DB SELECT | ✅ |
| AC-9 | **공유뷰 무인증 공개** + 잘못/만료 token → 안내(빈 데이터 노출 0) + robots noindex | curl + 브라우저 | ✅ |
| AC-10 | **detect 412 게이트**: `consent_overseas_at is None` → 412 `{reason:'CONSENT_OVERSEAS_REQUIRED'}`. token 직접 호출해도 BE 차단(UI 숨김≠방어) | curl 직접 | ✅ |
| AC-11 | **음수 guard**: `monthly_non_renewal_premium = max(0, assurance−renewal)` 음수 노출 0건 | 단위테스트 | ✅ |
| AC-12 | `npm run build` + `tsc --noEmit` + `pytest` 무오류 | CI | ✅ |

### 8.2 제품 검증선 (정성 — 허영지표 배제)

- [ ] **데모 1건 성립**: 설계사 본인 실증권으로 히트맵(중립모드) → 공유링크 → 고객 폰 열람까지 **한 사이클이 끊김 없이** 돈다.
- [ ] **베타 설계사가 "이 공유뷰를 실제 고객에게 보내고 싶다"고 말하는가**(정성 인터뷰). "분석이 정확하다"가 아니라 **"보내고 싶다"**가 검증선 — 북극성 첫 곱(발송 의도)의 증거.

### 8.3 명시적 비-목표

비교안내서 전환·유료 결제·MAU·가입자수·전환율은 이번 슬라이스 성공정의에서 **제외**. 곱셈형 북극성의 **첫 항(열람=`share_view`)만** 증명한다.

---

## 9. 착수 순서 한눈 (의존성 강제)

```
D-0  [데이터] seed_taxonomy 100+ 담보 트리 + 정규화 v0 ~150행   ← 히트맵 컬럼 정의의 전제
     [인프라] git remote + CI 활성화                          (병렬)
D-1  [BE] foliio 복사+리네임 → 8케이스 골든 green              (포팅 무결성 게이트)
     [디자인] inpa-tokens.css 3레이어 SSOT                     (병렬)
D-2  [BE] ★NorthStarEvent 모델+마이그레이션 (Day1 박기)
     [BE] heatmap.py status 판정 (neutral 폴백)
D-3  [FE] 공용 위생 4종 + 토큰 import
     이후: 공유뷰A SSR + 인사이트카드 + 히트맵 그리드 병행
```

---

## 10. 핵심 요약 (테크리드 정리)

- **1순위 데모 화면은 히트맵이 아니라 공유뷰A** — 북극성 곱셈의 첫 곱 '열람(share_view)'을 만드는 유일한 화면.
- **이번 컷 = dev/04 fallback 1~2차와 1:1 정렬** — 법무 게이트 G1~G5가 하나도 안 풀려도 출시 가능한 영역만 골라냄.
- **유일한 진짜 블로커는 코드가 아니라 데이터·법무·계측 4종**: ① 정규화 사전 v0 시드 ② 충족 임계 출처(neutral로 우회) ③ 북극성 6종 스펙 동결(사후복원 불가) ④ 디자인 토큰 SSOT. 이 넷이 잠기면 개발은 따라온다.
- **게이트는 detect(OCR)에만 물린다** — 공유뷰A·히트맵은 무게이트 서버연산. 막히면 수기입력+히트맵 none 중립으로 데모 성립.
- **계측 Day1 동결이 첫 배포 전 절대조건**(사후복원 불가) — DB 첫 마이그레이션에 `share_token?ref=` 박기.
- **성공정의는 허영지표 배제** — `share_view` 서버적재 1건 + 설계사 "보내고 싶다" 정성검증 + 8케이스 179 불변.
