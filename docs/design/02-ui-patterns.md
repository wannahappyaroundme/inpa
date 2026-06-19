# 인파 UI 패턴 & 레퍼런스 스크린

> 사용자 제공 예시(`inpa/*.jpeg`: 삼쩜삼·토스페이먼츠·럽맘) 분석 → 인파 화면에 적용할 구체 패턴. `00-design-system.md`·`01-brand-and-logo.md` 보완. 작성 2026-06-19.

## 0. 한눈 방향 — 예시에서 뽑은 "느낌"
- **흰/연한 배경 · 넉넉한 여백 · 큰 볼드 한글 타이포 · 둥근 카드(약한 그림자) · 절제된 색** (= 직방×무신사 방향과 일치)
- **"한 줄 인사이트 + 강조 숫자" 히어로** (삼쩜삼: "앞으로 **약 2,187만원** 더 내야 해요" — 숫자만 파란 하이라이트)
- **토스풍 밝은 파란색 `#3182F6`을 서브컬러로** (강조 숫자·진행바·info·보조 CTA) ← 사용자 지정
- **모바일 퍼스트**(설계사·고객 현장) + **데이터 화면은 토스식 웹 대시보드**(KPI 카드·캘린더 그리드)

## 1. 레퍼런스 스크린 → 인파 화면 매핑

| 예시(`inpa/`) | 핵심 패턴 | 인파 적용 |
|---|---|---|
| [mainconcept.jpeg](../../mainconcept.jpeg) 삼쩜삼 | 한 줄 인사이트+**강조 숫자** 히어로 · 진행바 · 요약 카드 · 배너(전문가 확인) · 섹션헤더(eyebrow+title) · **하단 고정 CTA** | **고객 공유뷰(진단 결과)** · 고객 상세 분석 요약 · 홈 액션 인사이트 |
| [mainpage.jpeg](../../mainpage.jpeg) 토스 | LNB · **KPI 카드 4** · **데이터 캘린더 그리드(색 범례)** · 우측 패널 · FAB | **설계사 웹 대시보드**(고객/실적 KPI) · 만기/액션 캘린더 |
| [board.jpeg](../../board.jpeg) 럽맘 | **가로스크롤 필터칩** · 카드 피드(eyebrow 라벨+제목+본문/번호리스트) · 하단 탭바 | 발굴 플레이북/상품 가이드 · 고객 리스트 · 커뮤니티 |
| [calender.jpeg](../../calender.jpeg) 럽맘 | 상단 탭(**ink-bar**) · **세그먼트 컨트롤** · 캘린더 카드(선택일=채운 원+도트+라벨) · 미래일 dimmed | **만기·생일·액션 캘린더**(선택일=액션, 도트=이벤트) |

## 2. 채택 컴포넌트 (모바일 RN 용어 ↔ 우리 Next.js 구현)

| 패턴 | 모바일 용어(참고) | 인파(Next.js + Tailwind) |
|---|---|---|
| 필터 칩 | Chip/Pill, horizontal scroll | `overflow-x-auto` + 칩 버튼(active=채움) |
| 상단 탭 | Top Tab(ink-bar) | 탭 컴포넌트 + active underline |
| 세그먼트 | Segmented Control | toggle group(채운 active) |
| 카드 | Card/Surface(elevation) | `rounded-2xl border shadow-sm` |
| 하단 탭바 | Bottom Tab Navigator | 모바일 sticky 하단 nav (홈/고객/발굴/분석/내정보) |
| 캘린더 | react-native-calendars | `react-day-picker` 또는 커스텀 7-col grid |
| 강조 숫자 | inline highlight `<Text>` | `<span class="text-[--accent-blue] font-bold">` |
| 진행바 | Progress | div + width% (애니메이션=framer-motion) |
| 하단 고정 CTA | Sticky Bottom CTA | `fixed bottom-0` 버튼(safe-area 패딩) |
| 바텀시트 | @gorhom/bottom-sheet | `vaul`(웹 바텀시트) |
| FAB/상담 | Floating Action Button | `fixed` 챗 버튼 |
| 숫자 포맷 | toLocaleString | `Intl.NumberFormat('ko-KR')`, 표는 `tabular-nums` |

## 3. 색 적용 규칙 (토스 블루 추가 반영 — `inpa-tokens.css`)

| 용도 | 토큰 | hex |
|---|---|---|
| 강조 숫자·인사이트·진행바·info·링크·보조 CTA | **`--accent-blue`** | `#3182F6` (토스풍) |
| 1차 CTA·헤더·브랜드·로고 | `--brand` | `#1E40C4` (딥인디고) |
| 히트맵 충분·제안선(데이터) | `--proposal`/`--cov-enough` | `#3B5BDB` |
| 기존 보유(Before) | `--existing` | `#12B5A4` |
| 위험(해지손해·§97 불리점) | `--danger` | `#E03131` |

- **블루 3종은 절대 한 요소에 교차 금지**: 액센트(UI 강조) vs 데이터(차트/셀) vs 브랜드(CTA/헤더) 역할 고정.
- **정직성 레드라인**: 강조색으로 공포 과장 금지(불리점이 아닌 숫자에 red 남발 X). 안전배지 색(그린 체크·금색 인증) 디자인 금지.

## 4. 플랫폼 메모
- 인파 = **Next.js 웹 + 모바일 퍼스트 반응형**(현장에서 앱처럼). **PWA**로 홈화면 추가 지원.
- 예시 3장은 RN 네이티브앱이지만, **같은 '느낌'을 Next.js + Tailwind로 동일 구현 가능**(컴포넌트 매핑 §2). 웹페이지 구동 결정 유지.
- 스토어 배포 네이티브앱이 필요해지면 그때 React Native로 확장(현재는 웹 우선).

> 다음: 이 패턴으로 **고객 공유뷰(삼쩜삼형 인사이트 카드)** 와 **담보 한눈표 히트맵**을 첫 시안으로.
