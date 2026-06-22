"""파서 담보(ocrdata dict_detail_data) → 표준 담보 트리(seed_normalization) 브리지.

[P0] OCR 저장 시 InsuranceDetail.analysis_detail M2M를 연결해야 calculate/heatmap이
보유금액을 집계한다(없으면 held=0). 파서 taxonomy와 표준 트리는 이름 체계가 달라
(예: 일반암 vs 일반암진단비, 상해후유장애 vs 상해후유장해) 명시 매핑이 필요하다.

설계: STANDARD_TREE(seed_normalization)는 동결(PlannerBaseline 프리셋이 그 이름에 묶임).
파서 leaf → 표준 leaf 이름을 이 맵으로 잇고, persist에서 .analysis_detail.add() 한다.

키 = 파서 (category, subcategory, detail) — claude_parser `_CATEGORY_MAP` 정본 27 leaf.
미대응(맵 부재) 3개는 의도적으로 미연결(held=0): (상해,상해,재해상해),
(실손 의료비,질병/상해,처방조제비) — STANDARD_TREE에 대응 leaf가 없음.
파서가 못 내는 표준 leaf(입원일당 전체·수술비 전체)는 추후 '처치 3-섹션'이 채운다.
"""
from inpa.analysis.models import AnalysisDetail

# 표준 트리 카테고리 마커(seed_normalization.STD_MARKER). seed_demo 동명 leaf와 충돌 방지.
_STD_MARKER = '[표준]'

# (파서 cat, 파서 sub, 파서 det) → 표준 AnalysisDetail.name
PARSER_TO_STD = {
    # 사망 (동일)
    ('사망', '일반', '일반사망'): '일반사망',
    ('사망', '질병', '질병사망'): '질병사망',
    ('사망', '상해', '상해사망'): '상해사망',
    ('사망', '재해', '재해사망'): '재해사망',
    # 상해 후유장해 (★ 장애→장해)
    ('상해', '상해', '상해후유장애'): '상해후유장해',
    # 진단비 — 암 (suffix 진단비)
    ('진단비', '암', '일반암'): '일반암진단비',
    ('진단비', '암', '유사암'): '유사암진단비',
    # 진단비 — 뇌
    ('진단비', '뇌', '뇌혈관'): '뇌혈관질환진단비',
    ('진단비', '뇌', '뇌졸중'): '뇌졸중진단비',
    ('진단비', '뇌', '뇌출혈'): '뇌출혈진단비',
    # 진단비 — 심혈관
    ('진단비', '심혈관', '허혈성'): '허혈성심장질환진단비',
    ('진단비', '심혈관', '급성심근경색'): '급성심근경색진단비',
    # 운전자 (공백 제거)
    ('운전자진단비', '합의금', '형사 합의 실손비'): '형사합의실손비',
    ('운전자진단비', '벌금', '대물 벌금'): '대물벌금',
    ('운전자진단비', '벌금', '대인 벌금'): '대인벌금',
    ('운전자진단비', '변호사', '변호사 선임비'): '변호사선임비',
    # 기타 배상책임 (동일)
    ('기타', '일상', '일상생활배상책임'): '일상생활배상책임',
    ('기타', '가족', '가족생활배상책임'): '가족생활배상책임',
    # 실손 의료비 (질병·상해 입원/통원 → 급여로 합류; 처방조제비는 대응 없음)
    ('실손 의료비', '질병', '질병 입원 의료비'): '실손입원급여',
    ('실손 의료비', '질병', '질병 통원 의료비'): '실손통원급여',
    ('실손 의료비', '상해', '상해 입원 의료비'): '실손입원급여',
    ('실손 의료비', '상해', '상해 통원 의료비'): '실손통원급여',
    ('실손 의료비', '비급여', '비급여 도수치료'): '실손비급여도수치료',
    ('실손 의료비', '비급여', '비급여 MR/MRA'): '실손비급여MRI',
    ('실손 의료비', '비급여', '비급여 주사료'): '실손비급여주사',
}


def resolve_std_detail(cat_name, sub_name, det_name):
    """파서 (cat,sub,det) → 표준 AnalysisDetail | None.

    매핑 없거나 표준 트리에 행이 없으면 None(graceful — 연결 안 함, held=0).
    동명 leaf(seed_demo) 충돌 방지를 위해 [표준] 카테고리로 한정.
    """
    std_name = PARSER_TO_STD.get((cat_name, sub_name, det_name))
    if not std_name:
        return None
    return (
        AnalysisDetail.objects
        .filter(name=std_name, sub_category__category__name__startswith=_STD_MARKER)
        .first()
    )
