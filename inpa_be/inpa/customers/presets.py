"""설계사 기준선(PlannerBaseline) v0 스타터 프리셋 — 상품군별 현실적 가설 기준선.

★★★ V0 스타터 데이터 경고 ★★★
이 파일의 권장 하한/상한(recommend_min/max) 수치는 **약관 원문·금융감독원 출처와 대조 검증되지 않은
v0 가설값**입니다. 보험 도메인 상식을 바탕으로 구성한 초기 스타터셋일 뿐, 권위 데이터가 아닙니다.

따라서 이 프리셋을 적용하면 PlannerBaseline.baseline_source='preset' 이 되어 분석 mode 가
neutral → graded 로 바뀝니다(부족/충분 판정이 켜짐). 이는 의도된 동작이지만,
**설계사가 수치를 검토·수정하기 전까지는 '판정의 권위'가 미검증 프리셋에 있다는 뜻**입니다.
응답 note·docstring 으로 이 한계를 항상 명시합니다(정직성 레드라인).

프로덕션 사용 전 반드시:
  1) 프로젝트 게이트 '보장 기준선(코어담보) 출처·면책 정의' 선결
  2) 실제 약관·금감원 가이드 대조 검증
  3) 도메인 전문가(설계사, 준법감시인) 검토 후 수치 확정

데이터 규약:
  - coverage_key: seed_normalization.py STANDARD_TREE 의 표준 담보명(AnalysisDetail.name)과 일치해야
    히트맵/비교 판정에서 매칭된다. 불일치하면 그 담보는 neutral 로 남는다(안전한 디폴트).
  - unit: 1=만원 (STANDARD_TREE chart_based_amount 와 동일 단위)
  - gender=None → 남/여 공통 (히트맵 _pick_baseline 이 공통으로 완화 매칭)
  - age_band: '20s'|'30s'|'40s'|'50s'|'60s+' (analysis/views._age_band 와 동일 표기)
"""
from __future__ import annotations  # 3.9 호환: PEP 604(int | None) 주석 지연 평가

# 멱등/식별 라벨 — 적용된 프리셋의 출처를 PlannerBaseline.preset_origin 에 기록한다.
PRESET_ORIGIN_V0 = 'v0_starter'

# baseline_source 물리 키 — null 이 아니면 분석 graded 게이트가 열린다(준법 통제점).
BASELINE_SOURCE_PRESET = 'preset'

# 적용 시 항상 함께 내려보내는 한계 고지(정직성 레드라인). 응답 note 로 그대로 사용.
PRESET_NOTE = (
    'v0 스타터 — 약관·금감원 출처 미확정, 검토 후 사용'
)

# 연령대 표기 — analysis/views._age_band 와 동일해야 매칭된다.
_AGE_BANDS = ('20s', '30s', '40s', '50s', '60s+')

# 상품군 상수 (PlannerBaseline.PRODUCT_GROUP_* 와 동일 정수값)
_LIFE = 1
_NONLIFE = 2
_INDEMNITY = 3
_ANNUITY = 4

# ════════════════════════════════════════════════════════════════════════
# 상품군별 v0 스타터 기준선 (★가설값 — 약관·금감원 미검증)
#
# 형식: product_group -> [ (coverage_key, [ (age_band, min만원, max만원) ]) ]
#   - min/max 는 권장 하한/상한(만원). max=None → 상한 없음.
#   - gender 는 전부 None(공통) — v0 은 성별 구분 없이 단순화. 설계사가 추후 세분화.
#
# coverage_key 는 STANDARD_TREE 표준 담보명과 정확히 일치(매칭 키).
# ════════════════════════════════════════════════════════════════════════
PRESET_V0: dict[int, list[tuple[str, list[tuple[str, int, int | None]]]]] = {

    # ── 손해(2) — 진단/입원/수술 중심 (★v0 가설) ──────────────────────────
    _NONLIFE: [
        ('일반암진단비', [
            ('20s', 3000, None), ('30s', 5000, None), ('40s', 5000, None),
            ('50s', 3000, None), ('60s+', 2000, None),
        ]),
        ('유사암진단비', [
            ('20s', 1000, None), ('30s', 1000, None), ('40s', 1000, None),
            ('50s', 1000, None), ('60s+', 500, None),
        ]),
        ('뇌졸중진단비', [
            ('20s', 2000, None), ('30s', 3000, None), ('40s', 3000, None),
            ('50s', 3000, None), ('60s+', 2000, None),
        ]),
        ('급성심근경색진단비', [
            ('20s', 2000, None), ('30s', 3000, None), ('40s', 3000, None),
            ('50s', 3000, None), ('60s+', 2000, None),
        ]),
        ('상해후유장해', [
            ('20s', 10000, None), ('30s', 10000, None), ('40s', 10000, None),
            ('50s', 10000, None), ('60s+', 5000, None),
        ]),
        ('질병수술비', [
            ('20s', 200, None), ('30s', 300, None), ('40s', 300, None),
            ('50s', 300, None), ('60s+', 200, None),
        ]),
        ('상해수술비', [
            ('20s', 200, None), ('30s', 300, None), ('40s', 300, None),
            ('50s', 300, None), ('60s+', 200, None),
        ]),
        ('질병입원일당', [
            ('20s', 3, None), ('30s', 5, None), ('40s', 5, None),
            ('50s', 5, None), ('60s+', 5, None),
        ]),
        ('상해입원일당', [
            ('20s', 3, None), ('30s', 5, None), ('40s', 5, None),
            ('50s', 5, None), ('60s+', 5, None),
        ]),
    ],

    # ── 생명(1) — 사망보장 중심 (★v0 가설) ───────────────────────────────
    _LIFE: [
        ('일반사망', [
            ('20s', 5000, None), ('30s', 10000, None), ('40s', 20000, None),
            ('50s', 10000, None), ('60s+', 5000, None),
        ]),
        ('질병사망', [
            ('20s', 5000, None), ('30s', 10000, None), ('40s', 10000, None),
            ('50s', 5000, None), ('60s+', 3000, None),
        ]),
        ('재해사망', [
            ('20s', 5000, None), ('30s', 10000, None), ('40s', 10000, None),
            ('50s', 5000, None), ('60s+', 3000, None),
        ]),
    ],

    # ── 실손(3) — 표준형 한 묶음 (★v0 가설, 연령 무관 단순화) ──────────────
    _INDEMNITY: [
        ('실손입원급여', [
            ('20s', 5000, None), ('30s', 5000, None), ('40s', 5000, None),
            ('50s', 5000, None), ('60s+', 5000, None),
        ]),
        ('실손통원급여', [
            ('20s', 25, None), ('30s', 25, None), ('40s', 25, None),
            ('50s', 25, None), ('60s+', 25, None),
        ]),
    ],

    # ── 연금저축(4) — v0 미정의(수치 가설조차 보류). 빈 리스트 = 적용 0건. ──
    _ANNUITY: [],
}


def iter_preset_rows(product_group: int):
    """주어진 상품군의 (coverage_key, age_band, gender, min, max) 튜플을 순회.

    gender 는 v0 전부 None(공통). PRESET_V0 에 없는 상품군은 빈 이터레이터.
    """
    for coverage_key, bands in PRESET_V0.get(product_group, []):
        for age_band, recommend_min, recommend_max in bands:
            yield coverage_key, age_band, None, recommend_min, recommend_max
