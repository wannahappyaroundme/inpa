# AI 비교 재정의 — 중립 시각화(판단 제거) (PM 확정, ③) — Spec

> 2026-07-09. PM 지시: 비교를 '갈아타기 판단'이 아니라 **중립 나란히 시각화**로. 제안서 vs 제안서 / 증권 vs 증권 / 종합 vs 종합을 자유롭게 비교, **판단은 설계사**, 인파는 시각화만. §97 부당승환 위험 제거 목적.

## 핵심 판단 (탐사 결과)
- **현재 기능은 이미 대부분 중립**: `_aggregate_side`/`_build_rows`(담보·금액·증감 사실), 보험료 비교, 막대그래프, 추가/삭제/변경/유지 라벨(사실 서술) = 그대로 유지. AI 글(`_generate_guide_draft`)도 이미 권유어 금지·6요건 사실 서술(판단 아님).
- **'판단'인 것 = `switch_verdict.py::compute_verdict`(KEEP/SWITCH/NEUTRAL 결정 + reason + 순편익 숫자) + FE 판정 박스(색 배지)** 하나뿐. 이것을 제거.
- `switch_warnings`(해지환급 손실 추정·면책기간 리셋·이율 변동)는 판정이 아니라 **설계사가 봐야 할 중립 사실** → '확인해야 할 사항' 체크리스트로 남기되 판정 프레이밍/색 제거.
- 사이드가 `portfolio_type`(1=보유/2=제안)에 하드코딩 → 제안 vs 제안, 증권 vs 증권 불가. **A/B 사이드로 디커플**.
- `COMPARE_AI_ENABLED`/`COMPARE_PUBLISH_ENABLED` 게이트는 **그대로 닫아둠**(CPO 법적 판단). 재정의는 위험을 줄이나 게이트 flip은 별도 결정.

## 설계

### 1. BE — 판정(verdict) 제거 (compare.py + switch_verdict.py)
- `CustomerCompareView._respond` 응답에서 **`verdict` 키 제거**. `compute_verdict` 호출 제거(또는 내부 계산은 두되 응답 미포함 — 깔끔히 호출 자체 제거 권장).
- `switch_warnings` → 응답 키 유지하되 **의미 재정의**: 판정 입력이 아니라 '중립 확인 사항'. `switch_verdict.py`에서 `compute_switch_warnings`만 남기고 `compute_verdict`·`_coverage_change`·verdict 관련 제거(또는 deprecated 표시). 파일/함수명이 'switch_verdict'라 오해 소지 → 주석으로 '판정 아님, 중립 유의사항 산출'로 재정의(파일명 리네임은 import 광범위 영향이라 주석 우선).
- 응답 disclaimer: '갈아타기 판정' 뉘앙스 제거 → '나란히 정리한 참고 자료, 판단은 설계사' 중립 문구(§6, honesty redline 기존 문구 재사용).

### 2. BE — 아무 두 세트나 비교 (사이드 디커플)
- `_respond`: `portfolio_type==1/2` 하드 분리 제거. 대신 요청 `side_a_ids`/`side_b_ids`(고객 소유 CustomerInsurance id 집합, 임의 두 세트)로 A/B 구성. **하위호환**: `current_ids`/`proposed_ids` 또는 미지정 시 기존 동작(보유=A, 제안=B) 유지.
- 응답 키 `current`/`proposed` → 하위호환 위해 유지하되 의미는 'A측/B측'(FE 라벨이 중립화). 또는 `side_a`/`side_b` 신규 키 추가 + 기존 유지(FE 전환). **최소 변경: 기존 키 유지 + side_a_ids/side_b_ids 입력 지원**.
- `_aggregate_side`/`_build_rows`는 사이드 무관 → 변경 없음.

### 3. FE — SwitchTab 중립화 (app/customer/[id]/page.tsx)
- **판정 박스(:1487-1531) 제거**: KEEP/SWITCH 색 배지·reason·순편익 숫자 삭제.
- **'확인해야 할 사항' 체크리스트**: switch_warnings의 사실(해지 손실 추정·면책 리셋·이율 변동)을 중립 리스트로(판정 색·'전환 검토' 라벨 없이, '설계사 검토용' 유지).
- **A/B 자유 비교 UI**: '보유 보험(현재)'/'제안 보험' 두 박스 → 라벨 중립화(A안/B안 또는 왼쪽/오른쪽), 어느 보험이든 양쪽에 담을 수 있게(또는 프리셋: 보유vs제안·제안vs제안·증권vs증권). 최소: 라벨 중립화 + side_a_ids/side_b_ids 전송.
- 탭 라벨 '비교 분석' 유지(이미 중립). AI 글 박스 주변 '부당승환' 등 법적 프레이밍 → '나란히 정리' 평이한 말(§6 audience-split: 설계사 화면이라도 headline은 평이하게).
- 탭 노출: 전속(exclusive) 설계사 숨김은 '갈아타기' 전제였음 → 중립 비교는 전속도 유용(제안 vs 제안 등)하므로 **노출 검토**(PM 확인 or 유지). 이번엔 기존 유지(리스크 최소), 주석으로 남김.

### 4. 게이트/문구
- `COMPARE_AI_ENABLED`/`COMPARE_PUBLISH_ENABLED` **불변(닫힘)**. CLAUDE.md §5/§8 §97 문구 + :21 'legitimize switching/§97 shield' 차별점 서술을 **중립 재정의로 갱신**(문서 단계).

### 테스트 (BE)
- 응답에 `verdict` 키 없음(제거 회귀). switch_warnings(중립 유의사항) 유지.
- side_a_ids/side_b_ids로 임의 두 세트 비교(제안 vs 제안 = 둘 다 portfolio_type=2도 가능) → rows/summary 정확. 하위호환(미지정=기존 보유/제안) 유지.
- 기존 `CompareFactsTests` verdict 테스트(:365-395) 갱신/제거. 계약 shape 테스트(:344-354)에서 verdict 키 기대 제거.
- ★ 누수 회귀(analytics/tests.py `test_share_view_excludes_planner_verdict`)는 그대로 통과(verdict 없어짐 = absence 더 강해짐).
- AI 게이트 테스트(닫힘 시 guide null) 유지.

### 마이그레이션 / 컴플라이언스
- 마이그레이션 0(로직·응답만).
- 고객 대면(/s·/d·/c·/b) 무변경(verdict는 원래 고객 미노출, 이제 아예 없음 = 더 안전).
- §97: 인파가 KEEP/SWITCH를 산출하지 않음 = '판단 주체는 설계사' 명확화. 위험 감소.
