"""골든셋 정규화 정확도 채점기 (프리런치 리뷰 #18, 2026-07-09).

목적: 사전(NormalizationDict)=인파의 유일 취득 데이터 자산(§ MEMORY qa-audit-backlog)의
정확도를 CI에서 상시 측정 + 회귀 방지. #26(담보 위치 확인 요청) 커뮤니티 루프의
병합 게이트로도 재사용(admin_console::AdminCoverageFlagResolveView).

★ 코퍼스 출처(provenance) — samples/·benchmark/·root data/ 절대 미참조:
  1) seed_dict: `seed_normalization.py::NORMALIZATION_V0` — 인파 자체 큐레이션 사전
     (326→현재 233개 `(company, raw_name, std_name)` 튜플). 보험사 원본 문서 아님.
     여기서 직접 로드(파일 복제 없음) → 시드 데이터가 바뀌면 골든셋도 함께 갱신되므로
     드리프트가 생기지 않는다.
  2) anchor: `data/golden_set.json` — CLAUDE.md §7 gotcha(정규화 substring 함정)에서
     손으로 옮겨 적은 회귀 앵커. 반드시 100% 통과해야 하는 '올바른 매핑' 확정 세트.

★ 결정적 매처만 사용(Claude 미호출, 비용 0·재현 가능):
  prod 매칭 순서(insurances/views.py::_build_normalizer)를 그대로 재현한다.
    (1) admin_verified NormalizationDict exact-match(원문 그대로 | 공백제거) 우선.
    (2) 없으면 core/ocr/claude_parser.py::_match_by_keywords(raw_name) → 파서 경로
        → insurances/coverage_bridge.py::resolve_std_detail() → 표준 leaf.
  ※ 스코프 한계(의도적): `_match_by_keywords` 는 claude_parser.py::_add_coverage 가
    호출 시점에 추가로 적용하는 가드(`_is_treatment_only`/`_is_fixed_benefit_inpatient`,
    괄호 안 '진단' 백스톱 등)를 포함하지 않는다. 이 함수는 그 가드들 이전 단계의
    순수 키워드 매칭만 재현한다 — 스펙 지시(§ verified anchors)대로 최소 재현.
    이 스코프 한계 때문에 정액형 입원(일당) 계열 seed_dict 항목 일부가 '실손' 경로로
    오분류되어 실패로 잡히는데, 실제 운영 파이프라인은 `_add_coverage`의 가드가 이를
    막는다(§7 게이트 리포트 참고, 회귀 아님).

순수 함수 — 부작용 0, DB 읽기만(NormalizationDict/AnalysisDetail 조회).
"""
import json
from pathlib import Path

from inpa.analysis.management.commands.seed_normalization import NORMALIZATION_V0
from inpa.analysis.models import NormalizationDict
from inpa.core.ocr.claude_parser import _is_treatment_only, _match_by_keywords
from inpa.core.ocr.ocrparsing import _is_fixed_benefit_inpatient
from inpa.insurances.coverage_bridge import resolve_std_detail

DATA_PATH = Path(__file__).resolve().parent / 'data' / 'golden_set.json'

# ── 정확도 회귀 방지선(ratchet) ──
# 2026-07-17 실측(도수치료 경로 교정 + 복합 암 사람 확인 경계): 0.7250
#   (174/240). 앵커 23건, 위험 자동오매핑 0건, 사람 확인 66건.
#   이 비율은 운영 OCR 정확도가 아니라 폴백 키워드의 정확 자동매핑 재현율이다.
# 2026-07-09c 실측(담보 세분류 개별 인식 (b) 수정 후): 0.7125 (171/240). 앵커 23건.
#   → 소액암·갑상선암(유사암 경로에서 분리)/특정암(일반암 경로에서 분리)/질병후유장해·
#     고도후유장해(상해후유장애 경로에서 분리)를 표준 트리 기존 leaf로 개별 라우팅
#     (PARSER_TO_STD 5건 추가 + COVERAGE_KEYWORDS 5개 전용 경로 신설). 13건 교정
#     (157→170) + 신규 앵커 '특정암진단비' 1건 추가 통과(170→171/240).
#   ※ 당시 '특정(소액)암진단비'류는 미해결. 2026-07-17 사람 확인 경계로 전환 완료.
#   ※ 입원일당(c)은 '건드리지 않음': _match_coverage 가 base 입원일당을 의도적으로 None(미매칭)
#     처리하고 prod 는 Claude _CATEGORY_MAP 으로 배치한다(실손 오염 방지 백스톱, 회귀테스트로 고정).
#     키워드 이동은 그 설계를 깨므로 반려.
# 2026-07-09b 실측(사망 세분류 오분류 (d) 수정 후): 0.6569 (157/239). 앵커 15건.
#   → 사망 복합어(재해/질병/상해 사망보험금·보장)가 '사망보험금' tail-substring 에 먹혀
#     일반사망으로 새던 10건 교정.
# 2026-07-09a 최초 실측(seed_dict + anchor 11건 = 238건, dedup 후): 0.6176 (147/238).
# ★ 이 aggregate 는 '대충 무너지지 않는지'만 보는 gross 바닥선이고, 실제 세밀 회귀 감시는
#   23개 회귀 앵커(§7 함정 5 + 3대 진단비/후유장해 대표 매핑 6 + 세분류 8 + 회귀가드 4,
#   100% 하드 게이트)가 담당한다. 단일 시드 항목 회귀는 aggregate 를 0.4%p 만 움직여
#   바닥선을 못 건드릴 수 있으므로, 고빈도·대표 매핑은 골든셋 앵커로 승격해 개별 하드
#   게이트로 지켜야 한다(golden_set.json).
# 임계값은 실측치보다 살짝 낮게 고정(자연스러운 NORMALIZATION_V0 증가로 인한 미세 변동
# 흡수 + 실제 회귀는 잡아냄). 낮은 이유(카테고리별)는 이 모듈 docstring + eval_normalization
# 커맨드 출력 참고: (a) 특수/표적이 아닌 '기저' 수술·처치·실손 경로는 COVERAGE_KEYWORDS에
# 애초에 키워드가 없어 항상 None, (b) 유사암/일반암/상해후유장애로 뭉쳐 있던 소액암·갑상선암·
# 특정암·질병후유장해·고도후유장해는 (2026-07-09c) 전용 경로로 분리 완료,
# (c) 위 스코프 한계로 정액 입원일당이 실손 경로로 오분류, (d) '사망보험금'/'사망보장' 같은
# 범용 키워드가 '재해사망보험금'/'질병사망보장' 등 구체 복합어의 tail-substring 으로 먼저
# 매칭(§7 substring 트랩과 동일 계열, 2026-07-09 수정 완료), (e) '특정(소액)암진단비'처럼
# 하나의 표준 위치로 확정하기 어려운 복합 암 표기는 2026-07-17부터 자동 저장을 차단하고
# 비동기 검토 초안에서 설계사가 원문을 확인해 직접 위치를 선택하도록 전환.
# (a) 기저 수술·처치는 2026-05-12 PM 정책 '진단 금액만 진단비 버킷'으로 의도적 미매칭(버그 아님).
# (c) 입원일당은 키워드 매처가 의도적 None(prod는 Claude 카테고리로 배치, 위 참조) — 건드리지 않음.
# ★ 스코프 노트(2026-07-09c): 이번 수정은 폴백 키워드 매처(COVERAGE_KEYWORDS/PARSER_TO_STD +
#   골든 채점)에 더해 **실 OCR 파이프라인까지 라이브 반영**했다(5-way 완결, 2026-07-02 특수수술
#   확장과 동형): claude_parser.py::_COVERAGE_CATEGORIES 프롬프트 + _CATEGORY_MAP + ocrdata.py
#   dict_detail_data 에 5개 세분류(소액암/갑상선암/특정암/질병후유장해/고도후유장해) 경로 추가.
#   → 새 증권 업로드부터 세분류가 각 표준 leaf 로 저장됨(기존 파싱 데이터는 불변, 마이그레이션 0).
#   Claude 프롬프트 미준수 시엔 부모(유사암/일반암/상해후유장해)로 graceful 폴백(크래시 없음).
#   골든 채점은 폴백 매처만 재현하므로 라이브 세분류는 insurances/tests.py::
#   CoverageSubtypeSplitLiveTests(mock SDK)로 실증. 실 Claude 스팟체크는 배포 후 권장.
GOLDEN_SET_MIN_ACCURACY = 174 / 240
GOLDEN_SET_MIN_EXACT_AUTO_MAPPED = 174
EVALUATION_SCOPE = 'fallback_golden_set_only'
EVALUATION_SCOPE_NOTE = (
    '폴백 키워드 골든셋의 분기 결과이며 운영 OCR 정확도가 아닙니다.')


def load_golden_set():
    """골든셋 코퍼스 = NORMALIZATION_V0(source='seed_dict') + 앵커(source='anchor').

    반환: [{company, raw_name, expected_std_leaf, source, note?}, ...]
    ★ (company, raw_name) 기준 dedup — 앵커가 시드와 겹치면 앵커가 우선(하드 게이트).
      고빈도 담보(3대 진단비 등)를 앵커로 승격해도 중복 카운트되지 않는다.
    """
    by_key = {}
    for company, raw_name, std_name in NORMALIZATION_V0:
        by_key[(company, raw_name)] = {
            'company': company,
            'raw_name': raw_name,
            'expected_std_leaf': std_name,
            'source': 'seed_dict',
        }

    with open(DATA_PATH, encoding='utf-8') as f:
        payload = json.load(f)
    for anchor in payload.get('anchors', []):
        key = (anchor['company'], anchor['raw_name'])
        by_key[key] = {  # 앵커 우선(시드와 겹쳐도 덮어씀 = 중복 제거 + 하드 게이트 승격)
            'company': anchor['company'],
            'raw_name': anchor['raw_name'],
            'expected_std_leaf': anchor['expected_std_leaf'],
            'source': 'anchor',
            'note': anchor.get('note', ''),
        }
    return list(by_key.values())


def _match_std_leaf_name(company, raw_name):
    """prod 매칭 순서 재현: (1) admin_verified 사전 exact-match → (2) 키워드 매처.

    insurances/views.py::_build_normalizer 와 동일 우선순위·조건.
    매칭 실패(경로 없음/표준 트리에 leaf 없음) 시 None.
    """
    no_space = raw_name.replace(' ', '')
    entry = (
        NormalizationDict.objects
        .filter(company=company, source=NormalizationDict.SOURCE_ADMIN_VERIFIED)
        .filter(raw_name__in=[raw_name, no_space])
        .select_related('std_detail')
        .first()
    )
    if entry is not None:
        return entry.std_detail.name

    path = _match_by_keywords(raw_name)
    if path is None:
        return None
    cat_name, sub_name, det_name = path
    std_detail = resolve_std_detail(cat_name, sub_name, det_name)
    return std_detail.name if std_detail else None


def evaluate_golden_set(entries=None):
    """골든셋 채점. 순수 함수(부작용 0) — DB 읽기만.

    반환: {total, passed, failed, accuracy, anchor_total, anchor_passed,
           exact_auto_mapped, safe_human_review, unsafe_auto_mapped,
           safe_decision_rate, failures:[...], unsafe_failures:[...],
           anchor_failures:[...]}
    """
    if entries is None:
        entries = load_golden_set()

    total = passed = 0
    anchor_total = anchor_passed = 0
    failures = []
    anchor_failures = []
    safe_review_failures = []
    unsafe_failures = []

    for entry in entries:
        company = entry['company']
        raw_name = entry['raw_name']
        expected = entry['expected_std_leaf']
        is_anchor = entry.get('source') == 'anchor'

        got = _match_std_leaf_name(company, raw_name)

        total += 1
        if is_anchor:
            anchor_total += 1

        if got == expected:
            passed += 1
            if is_anchor:
                anchor_passed += 1
        else:
            failure = {
                'company': company, 'raw_name': raw_name,
                'expected': expected, 'got': got,
            }
            failures.append(failure)
            if _is_safe_human_review(raw_name, got):
                safe_review_failures.append(failure)
            else:
                unsafe_failures.append(failure)
            if is_anchor:
                anchor_failures.append(failure)

    accuracy = passed / total if total else 0.0
    exact_auto_mapped = passed
    safe_human_review = len(safe_review_failures)
    unsafe_auto_mapped = len(unsafe_failures)
    safe_decision_rate = (
        (exact_auto_mapped + safe_human_review) / total if total else 0.0)
    return {
        'total': total,
        'passed': passed,
        'failed': total - passed,
        'accuracy': accuracy,
        'exact_auto_mapped': exact_auto_mapped,
        'safe_human_review': safe_human_review,
        'unsafe_auto_mapped': unsafe_auto_mapped,
        'safe_decision_rate': safe_decision_rate,
        'anchor_total': anchor_total,
        'anchor_passed': anchor_passed,
        'failures': failures,
        'safe_review_failures': safe_review_failures,
        'unsafe_failures': unsafe_failures,
        'anchor_failures': anchor_failures,
    }


def _is_safe_human_review(raw_name, got):
    """폴백 결과가 운영 가드에서 차단되거나 미매칭이면 사람 확인으로 분류."""
    if got is None:
        return True
    if got == '실손입원급여' and _is_fixed_benefit_inpatient(raw_name):
        return True
    if got.endswith('진단비') and _is_treatment_only(raw_name):
        return True
    return False


def find_golden_expected(company, raw_name):
    """골든셋에 (company, raw_name)이 정확히 일치하는 항목이 있으면 기대 표준 leaf 이름.

    #26 어드민 승인(accept) 시 '이 승인이 골든셋 기대와 다르다' 경고에 사용(비차단).
    DB 접근 없음(순수 코퍼스 조회) — 여러 번 불러도 저렴.
    """
    for entry in load_golden_set():
        if entry['company'] == company and entry['raw_name'] == raw_name:
            return entry['expected_std_leaf']
    return None
