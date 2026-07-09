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
from inpa.core.ocr.claude_parser import _match_by_keywords
from inpa.insurances.coverage_bridge import resolve_std_detail

DATA_PATH = Path(__file__).resolve().parent / 'data' / 'golden_set.json'

# ── 정확도 회귀 방지선(ratchet) ──
# 2026-07-09 실측(시드 DB, seed_dict + anchor 11건 = 238건, dedup 후): 0.6176 (147/238).
# ★ 이 aggregate 는 '대충 무너지지 않는지'만 보는 gross 바닥선이고, 실제 세밀 회귀 감시는
#   11개 회귀 앵커(§7 함정 5 + 3대 진단비/후유장해 대표 매핑 6, 100% 하드 게이트)가 담당한다.
#   단일 시드 항목 회귀는 aggregate 를 0.4%p 만 움직여 바닥선을 못 건드릴 수 있으므로,
#   고빈도·대표 매핑은 골든셋 앵커로 승격해 개별 하드 게이트로 지켜야 한다(golden_set.json).
# 임계값은 실측치보다 살짝 낮게 고정(자연스러운 NORMALIZATION_V0 증가로 인한 미세 변동
# 흡수 + 실제 회귀는 잡아냄). 낮은 이유(카테고리별)는 이 모듈 docstring + eval_normalization
# 커맨드 출력 참고: (a) 특수/표적이 아닌 '기저' 수술·처치·실손 경로는 COVERAGE_KEYWORDS에
# 애초에 키워드가 없어 항상 None, (b) 유사암 계열(유사암/소액암/갑상선암/대장점막내암 등)이
# 파서 경로 하나('진단비->암->유사암')로 뭉쳐 있어 세분류 std_name과 항상 불일치,
# (c) 위 스코프 한계로 정액 입원일당이 실손 경로로 오분류, (d) '사망보험금'/'사망보장' 같은
# 범용 키워드가 '재해사망보험금'/'질병사망보장' 등 구체 복합어의 tail-substring 으로 먼저
# 매칭(§7 substring 트랩과 동일 계열), (e) '특정(소액)암진단비'처럼 괄호 삽입어가 키워드
# 연속성을 끊어 구체 키워드 대신 범용 '암진단' 으로 흡수.
# (a)(b)는 설계상 admin_verified 승격을 기다리는 데이터 자산 갭(버그 아님), (c)(d)(e)는
# 코드 개선 여지가 있는 실제 매처 한계 — 이번 스프린트 범위 밖, 후속 리포트 대상.
GOLDEN_SET_MIN_ACCURACY = 0.60


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
           failures:[{company, raw_name, expected, got}], anchor_failures:[...]}
    """
    if entries is None:
        entries = load_golden_set()

    total = passed = 0
    anchor_total = anchor_passed = 0
    failures = []
    anchor_failures = []

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
            if is_anchor:
                anchor_failures.append(failure)

    accuracy = passed / total if total else 0.0
    return {
        'total': total,
        'passed': passed,
        'failed': total - passed,
        'accuracy': accuracy,
        'anchor_total': anchor_total,
        'anchor_passed': anchor_passed,
        'failures': failures,
        'anchor_failures': anchor_failures,
    }


def find_golden_expected(company, raw_name):
    """골든셋에 (company, raw_name)이 정확히 일치하는 항목이 있으면 기대 표준 leaf 이름.

    #26 어드민 승인(accept) 시 '이 승인이 골든셋 기대와 다르다' 경고에 사용(비차단).
    DB 접근 없음(순수 코퍼스 조회) — 여러 번 불러도 저렴.
    """
    for entry in load_golden_set():
        if entry['company'] == company and entry['raw_name'] == raw_name:
            return entry['expected_std_leaf']
    return None
