# www 랜딩 승격과 인파 이야기 이전 설계

> 확정일: 2026-07-20
> 사용자 승인: `new.inpa.kr/test` 후보를 `www.inpa.kr` 메인으로 승격하고, 기존 4단 요금표를 넣으며, 영화형 인파 이야기는 `www.inpa.kr/story`에서 유지한다.

## 1. 목표

1. `www.inpa.kr/`에서 서비스 중심 후보 랜딩을 정식 메인으로 제공한다.
2. 후보의 간단한 베타 안내를 무료·Manager·Plus·Super 4단 요금표로 교체한다.
3. 기존 영화형 인파 이야기를 `www.inpa.kr/story`로 옮긴다.
4. `new.inpa.kr/`과 `new.inpa.kr/test` 방문자는 새 `www` 주소로 자동 이동한다.
5. 블로그, 문의, 로그인, 가입, FAQ, 약관, 개인정보처리방침, 데이터 처리 안내와 UTM 계측을 보존한다.

## 2. 확정 주소

| 방문 주소 | 최종 동작 |
|---|---|
| `https://www.inpa.kr/` | 서비스 중심 메인 랜딩 200 |
| `https://www.inpa.kr/story` | 영화형 인파 이야기 200 |
| `https://new.inpa.kr/` | `https://www.inpa.kr/story`로 308 이동, 검색값 보존 |
| `https://new.inpa.kr/test` | `https://www.inpa.kr/`로 308 이동, 검색값 보존 |
| `https://www.inpa.kr/new` | `https://www.inpa.kr/story`로 영구 이동 |
| `https://www.inpa.kr/new/test` | `https://www.inpa.kr/`로 영구 이동 |

`new.inpa.kr`은 더 이상 화면을 직접 렌더하지 않는다. 기존 북마크와 광고 주소만 새 공식 주소로 연결한다.

## 3. 메인 랜딩 구성

현재 `/test` 후보의 순서와 실제 제품 화면 5종을 유지한다.

1. 헤더
2. 실제 대시보드가 보이는 첫 화면
3. 핵심 사실 3개
4. 실제 제품 화면 5종 탭과 확대 보기
5. 4단계 사용 흐름
6. 차별점
7. 개인 설계사·관리직 대상 가치
8. 무료·Manager·Plus·Super 4단 요금표
9. FAQ
10. 역할 안내
11. 마지막 가입 행동
12. 푸터와 문의 위젯

헤더의 요금 링크는 `#pricing`으로 이동한다. `인파 이야기 60초 보기`는 `/story`로 이동한다. 블로그는 헤더 또는 모바일 메뉴와 푸터에서 열 수 있고, 익명 문의 위젯은 기존 `www` 메인과 같은 방식으로 유지한다.

## 4. 요금표

`brand-story-sections.tsx`의 `PricingFourTiers`를 그대로 공용 사용한다. 별도 복사본을 만들지 않는다.

- 무료: 0원
- Manager: 월 19,900원, VAT 별도
- Plus: 월 19,900원, VAT 별도
- Super: 월 39,900원, VAT 별도
- 연 결제 문구와 한도는 현재 운영 요금표의 단일 원본을 따른다.
- 첫 결제 보너스는 서버 설정이 실제 켜져 있을 때만 노출한다.
- 메인 랜딩의 가입 링크는 원래 UTM 값을 보존한다.

`PricingFourTiers`는 선택적인 `id`와 `registerHref`만 받는다. 기본 사용처의 화면과 링크는 바뀌지 않는다.

## 5. 인파 이야기

`/story`는 기존 `CinemaLanding`의 영화 장면, 소리 선택, 건너뛰기, 스크롤형 브랜드 소개를 유지한다.

- canonical은 `https://www.inpa.kr/story`다.
- 서비스 링크는 같은 `www` 도메인에서 열린다.
- 기존 영화 CTA 계측은 유지하되 새 공식 위치와 맞는 유입값을 사용한다.
- `new.inpa.kr/`은 이 주소로 영구 이동해 기존 공유 링크를 보호한다.

## 6. 검색과 분석

- `/`은 검색 허용, canonical `/`, 기존 Organization·Website·SoftwareApplication JSON-LD를 유지한다.
- `/story`는 검색 허용, canonical `/story`다.
- 이전 테스트 페이지의 `noindex` 페이지는 사용자에게 제공하지 않는다.
- 기존 `landing_test_*` 분석 이벤트 이름은 시계열 연속성을 위해 유지한다.
- 로그인·가입 버튼은 원래 UTM만 전달하고 다른 검색값은 전달하지 않는다.

## 7. 상태와 접근성

- 제품 이미지 실패 시 설명과 CTA가 남는다.
- 확대 화면은 ESC 닫기, 포커스 가두기, 원래 버튼 복귀를 유지한다.
- 모바일 메뉴는 열림 상태와 접근 가능한 이름을 유지한다.
- 모든 누를 수 있는 요소는 최소 44px 높이를 유지한다.
- 390px, 768px, 1440px에서 가로 넘침과 잘림이 없어야 한다.
- 움직임 줄이기 설정에서 영화·등장 효과가 과도하게 재생되지 않는다.

## 8. 변경 범위

### 변경

- `app/page.tsx`
- `app/story/page.tsx`
- `app/new/page.tsx`
- `app/new/test/page.tsx`
- `components/test-landing.tsx`를 정식 이름으로 이동
- `components/test-product-gallery.tsx`를 정식 이름으로 이동
- `lib/test-landing-content.ts`와 테스트를 정식 이름으로 이동
- `components/brand-story-sections.tsx`
- `components/cinema-landing.tsx`
- `lib/new-host-routing.ts`와 테스트
- `proxy.ts`
- `package.json`의 랜딩 검사 경로

### 변경하지 않음

- 백엔드, DB, 결제 로직, 요금 한도
- 로그인·가입·블로그·문의 API
- 실제 제품 캡처 이미지
- 서비스 내부 화면

## 9. 완료 기준

- 주소 규칙 자동검사가 308 이동 목적지와 검색값 보존을 확인한다.
- 랜딩 콘텐츠와 링크 자동검사가 `/story`, 제품 화면 5종, UTM 보존을 확인한다.
- 프론트 단위검사, 화면 동작검사, 문구 검사, Next 운영 빌드가 모두 통과한다.
- 로컬 운영 빌드에서 세 화면 크기와 헤더·푸터·문의·요금·스토리 링크를 실제로 확인한다.
- 콘솔 오류가 없다.
- 구현 후 정확성·접근성·검색·분석·회귀 위험 관점의 최종 검토를 수행한다.

## 10. 배포 안전

코드 구현과 로컬 검증을 먼저 완료한다. 커밋, PR, `master` 병합과 운영 배포는 프로젝트 Git·배포 규칙에 따라 별도 명시 승인 후 수행한다. 운영 배포 시 `www`, `/story`, 두 `new` 이전 주소를 실제로 다시 확인한다.
