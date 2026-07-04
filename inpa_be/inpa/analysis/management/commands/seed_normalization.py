"""정규화 사전 v0 시드 — 표준 담보 트리 + 보험사별 담보명 정규화 매핑.

★★★ V0 스타터 데이터 경고 ★★★
이 파일의 데이터는 실제 보험사 약관 원문과 대조·검증된 권위 데이터가 아닙니다.
보험 도메인 지식을 바탕으로 현실적으로 구성한 초기 스타터셋입니다.

프로덕션 사용 전 반드시:
  1) 실제 보험사 약관·증권 원문과 대조 검증 필요
  2) 프로젝트 게이트 '보장 기준선(코어담보) 출처·면책 정의' 선결 후 승인
  3) 도메인 전문가(설계사, 준법감시인) 검토 필요

chart_based_amount 단위: 만원 (표준 보장 기준선 물리 저장; 판정 권위는 PlannerBaseline).
company 코드: ocrdata.py LossInsurance·LifeInsurance index 기반 (데모 대역 900-909 외).

멱등 실행 (2026-07-04 LB-1 시드 안전화 — identity-true upsert):
  PYTHONPATH=<inpa_be> python3 manage.py seed_normalization
  → 자연키(부모 FK + name) get_or_create 업서트. 기존 행 PK 보존 →
    InsuranceDetail.analysis_detail M2M 링크·NormalizationDict FK 생존.
  → SeedMarker(key='seed_normalization') 버전이 SEED_VERSION과 같으면 no-op
    (부팅 경로 무해화). --force 로 우회, 데이터 변경 시 SEED_VERSION 수동 bump.
  → 삭제 없음: 코드에서 사라진 행은 고아(orphan)로 로그만. --prune(기본 OFF,
    배포에서 미사용)일 때만 seed 출처 행 한정 삭제(admin_verified/ocr_learned 및
    M2M 링크가 걸린 leaf는 보호 — 절대 삭제하지 않음).
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from inpa.analysis.models import (
    AnalysisCategory,
    AnalysisDetail,
    AnalysisSubCategory,
    NormalizationDict,
    SeedMarker,
)

# ── 시드 데이터 버전 (STANDARD_TREE/NORMALIZATION_V0 데이터 변경 시 수동 bump) ──
SEED_VERSION = 'v1'
MARKER_KEY = 'seed_normalization'

# ── 멱등 마커 (seed_demo의 '[DEMO]' 와 충돌 없는 별도 prefix) ─────────────
STD_MARKER = '[표준]'

# ── 보험사 코드 (ocrdata.py index 기반) ──────────────────────────────────
# LossInsurance.company 인덱스
MERITZ   = 1   # 메리츠화재
SAMSUNG_LOSS = 2   # 삼성화재
HANHWA_LOSS  = 6   # 한화손해
HYUNDAI  = 7   # 현대해상
DB_LOSS  = 11  # DB손해
KB_LOSS  = 12  # KB손해
NH_LOSS  = 15  # NH농협손해
흥국     = 8   # 흥국화재

# LifeInsurance.company 인덱스 — 생명보험은 200번대로 구분 (손해와 코드 공간 분리)
# 생명보험: 기본 offset 200 + LifeInsurance index
# 교보생명=201, 삼성생명=206, 한화생명=213, 교보라이프플래닛=200, 동양생명=202 등
KYOBO_LIFE   = 201  # 교보생명
SAMSUNG_LIFE = 206  # 삼성생명
HANHWA_LIFE  = 213  # 한화생명
DONGYANG     = 202  # 동양생명
NH_LIFE      = 222  # NH농협생명


# ════════════════════════════════════════════════════════════════════════
# 표준 담보 트리 v0 — 카테고리 → 서브 → 담보(leaf)
# ★ V0 스타터: 약관 원문 대조 검증 전 데이터.
#   형식: (카테고리명, insurance_type, [ (서브명, [ (담보명, chart_based_amount만원) ]) ])
#   insurance_type: 0=공통, 1=생명, 2=손해, 3=공통(실손)
# ════════════════════════════════════════════════════════════════════════
STANDARD_TREE = [
    # ── 1. 사망 / 후유장해 ───────────────────────────────────────────────
    ('사망/후유장해', 0, [
        ('사망', [
            ('일반사망',            10000),   # 1억 기준
            ('질병사망',            10000),
            ('상해사망',            10000),
            ('재해사망',            10000),
        ]),
        ('후유장해', [
            ('상해후유장해',         10000),
            ('질병후유장해',          5000),
            ('고도후유장해',         10000),
        ]),
    ]),

    # ── 2. 진단 — 암 ────────────────────────────────────────────────────
    ('진단-암', 0, [
        ('일반암', [
            ('일반암진단비',          5000),   # 5천만 기준
            ('특정암진단비',          3000),
        ]),
        ('유사암/소액암', [
            ('유사암진단비',          1000),
            ('소액암진단비',          1000),
            ('갑상선암진단비',         500),
            ('대장점막내암진단비',      500),
        ]),
    ]),

    # ── 3. 진단 — 뇌혈관 ────────────────────────────────────────────────
    ('진단-뇌혈관', 0, [
        ('뇌혈관', [
            ('뇌졸중진단비',          3000),
            ('뇌출혈진단비',          3000),
            ('뇌혈관질환진단비',       2000),
        ]),
    ]),

    # ── 4. 진단 — 심혈관 ────────────────────────────────────────────────
    ('진단-심혈관', 0, [
        ('심혈관', [
            ('급성심근경색진단비',     3000),
            ('허혈성심장질환진단비',   2000),
        ]),
    ]),

    # ── 5. 입원 일당 ────────────────────────────────────────────────────
    ('입원일당', 0, [
        ('질병입원', [
            ('질병입원일당',             5),   # 단위: 만원/일
            ('질병중환자실입원일당',      10),
        ]),
        ('상해입원', [
            ('상해입원일당',             5),
            ('상해중환자실입원일당',      10),
        ]),
        ('암입원', [
            ('암입원일당',              10),
        ]),
        # 특수입원: 종합보험 미매칭 담보 확장 (2026-07-02).
        # chart_based_amount = 차트 표시 참고값 (만원/일 단위) — 판정 기준 아님(PlannerBaseline 전용).
        # 중립(NEUTRAL) 표시 전용: 베이스라인 없으면 금액만 노출, 넉넉/적정/부족 판정 안 함.
        # ★ 중환자실입원일당은 '질병중환자실입원일당'(기존)과 별개 leaf — 특약 단독 가입 상품 대응.
        ('특수입원', [
            ('중환자실입원일당',          10),
            ('환경성질환입원일당',          8),
            ('14대질병입원일당',           10),
            ('여성특정질병입원일당',         8),
            ('희귀난치성질환입원일당',      10),
        ]),
    ]),

    # ── 5-2. 입원비 (일회성 총액 — 일당과 단위 다름, 별도 leaf 로 분리) ────
    ('입원비', 0, [
        ('질병입원', [
            ('질병입원비',             300),   # 단위: 만원 (총액)
        ]),
        ('상해입원', [
            ('상해입원비',             300),   # 단위: 만원 (총액)
        ]),
        ('암입원', [
            ('암입원비',               500),   # 단위: 만원 (총액)
        ]),
    ]),

    # ── 6. 수술비 ────────────────────────────────────────────────────────
    ('수술비', 0, [
        ('질병수술', [
            ('질병수술비',             300),
            ('암수술비',               500),
        ]),
        ('상해수술', [
            ('상해수술비',             300),
        ]),
        # 특수수술: 종합보험 미매칭 담보 확장 (2026-07-02).
        # chart_based_amount = 차트 표시 참고값 (만원 단위) — 판정 기준 아님(PlannerBaseline 전용).
        # 중립(NEUTRAL) 표시 전용: 베이스라인 없으면 금액만 노출, 넉넉/적정/부족 판정 안 함.
        ('특수수술', [
            ('골절수술비',             300),
            ('화상수술비',             300),
            ('조혈모세포이식수술비',   1000),
            ('장기이식수술비',         1000),
            ('각막이식수술비',          500),
            ('흉터복원수술비',          300),
            ('인공관절수술비',          500),
            ('호흡기수술비',            300),
        ]),
    ]),

    # ── 7. 실손 의료비 (표준형) ─────────────────────────────────────────
    ('실손의료비', 3, [
        ('급여', [
            ('실손입원급여',          5000),
            ('실손통원급여',            25),   # 단위: 만원/회
        ]),
        ('비급여', [
            ('실손비급여주사',          250),
            ('실손비급여도수치료',       350),
            ('실손비급여MRI',           300),
        ]),
    ]),

    # ── 8. 운전자 ────────────────────────────────────────────────────────
    ('운전자보장', 2, [
        ('벌금/합의금', [
            ('대물벌금',               500),
            ('대인벌금',               500),
            ('형사합의실손비',          2000),
        ]),
        ('변호사', [
            ('변호사선임비',            500),
        ]),
    ]),

    # ── 9. 기타 생활 ─────────────────────────────────────────────────────
    ('기타보장', 0, [
        ('배상책임', [
            ('일상생활배상책임',        1000),
            ('가족생활배상책임',        1000),
        ]),
    ]),

    # ── 10. 처치 (항암 약물/방사선 — 진단비와 분리, 그래프 오염 방지) ──────
    ('처치', 0, [
        ('항암', [
            ('항암약물치료비',          200),   # 단위: 만원 (V0 스타터 — 약관 미검증)
            ('항암방사선치료비',        200),
        ]),
        # 표적항암: 종합보험 미매칭 담보 확장 (2026-07-02).
        # chart_based_amount = 차트 표시 참고값 (만원 단위) — 판정 기준 아님(PlannerBaseline 전용).
        # 중립(NEUTRAL) 표시 전용: 베이스라인 없으면 금액만 노출, 넉넉/적정/부족 판정 안 함.
        ('표적항암', [
            ('표적항암약물치료비',       200),
            ('표적항암방사선치료비',     200),
        ]),
    ]),
]


# ════════════════════════════════════════════════════════════════════════
# 정규화 사전 v0 — 보험사별 담보 원문 → 표준 담보명 매핑
# ★ V0 스타터: 실제 약관 원문 대조 검증 전 데이터.
#   형식: (company코드, 보험사 담보 원문, 표준 담보명)
#   UNIQUE(company, raw_name) 준수 — 동일 보험사·원문 중복 없음.
# ════════════════════════════════════════════════════════════════════════
NORMALIZATION_V0 = [

    # ────────────────────────────────────────────────
    # 메리츠화재 (MERITZ=1)
    # ────────────────────────────────────────────────
    (MERITZ, '일반사망보험금',                   '일반사망'),
    (MERITZ, '재해사망보험금',                   '재해사망'),
    (MERITZ, '질병사망보험금',                   '질병사망'),
    (MERITZ, '상해후유장해급여금',               '상해후유장해'),
    (MERITZ, '일반암진단급여금',                 '일반암진단비'),
    (MERITZ, '유사암진단급여금',                 '유사암진단비'),
    (MERITZ, '소액암진단급여금',                 '소액암진단비'),
    (MERITZ, '갑상선암진단급여금',               '갑상선암진단비'),
    (MERITZ, '뇌졸중진단급여금',                 '뇌졸중진단비'),
    (MERITZ, '뇌출혈진단급여금',                 '뇌출혈진단비'),
    (MERITZ, '뇌혈관질환진단급여금',             '뇌혈관질환진단비'),
    (MERITZ, '급성심근경색증진단급여금',          '급성심근경색진단비'),
    (MERITZ, '허혈성심장질환진단급여금',          '허혈성심장질환진단비'),
    (MERITZ, '질병입원일당급여금',               '질병입원일당'),
    (MERITZ, '상해입원일당급여금',               '상해입원일당'),
    (MERITZ, '암입원일당급여금',                 '암입원일당'),
    (MERITZ, '질병수술급여금(1~5종)',            '질병수술비'),
    (MERITZ, '상해수술급여금',                   '상해수술비'),
    (MERITZ, '암수술급여금',                     '암수술비'),
    (MERITZ, '실손의료비(입원·급여)',             '실손입원급여'),
    (MERITZ, '실손의료비(통원·급여)',             '실손통원급여'),
    (MERITZ, '비급여주사료',                     '실손비급여주사'),
    (MERITZ, '비급여도수·체외충격파·증식치료',   '실손비급여도수치료'),
    (MERITZ, '비급여MRI/MRA',                   '실손비급여MRI'),
    (MERITZ, '대물사고처리지원금(벌금)',          '대물벌금'),
    (MERITZ, '형사합의실손비',                   '형사합의실손비'),

    # ────────────────────────────────────────────────
    # 삼성화재 (SAMSUNG_LOSS=2)
    # ────────────────────────────────────────────────
    (SAMSUNG_LOSS, '일반사망',                   '일반사망'),
    (SAMSUNG_LOSS, '재해사망',                   '재해사망'),
    (SAMSUNG_LOSS, '질병사망',                   '질병사망'),
    (SAMSUNG_LOSS, '상해후유장해(3%~100%)',       '상해후유장해'),
    (SAMSUNG_LOSS, '일반암진단비',               '일반암진단비'),
    (SAMSUNG_LOSS, '특정(소액)암진단비',          '소액암진단비'),
    (SAMSUNG_LOSS, '유사암진단비',               '유사암진단비'),
    (SAMSUNG_LOSS, '뇌졸중진단비',               '뇌졸중진단비'),
    (SAMSUNG_LOSS, '급성심근경색진단비',          '급성심근경색진단비'),
    (SAMSUNG_LOSS, '허혈성심장질환진단비',        '허혈성심장질환진단비'),
    (SAMSUNG_LOSS, '뇌혈관질환진단비',            '뇌혈관질환진단비'),
    (SAMSUNG_LOSS, '질병입원일당',               '질병입원일당'),
    (SAMSUNG_LOSS, '상해입원일당',               '상해입원일당'),
    (SAMSUNG_LOSS, '질병수술비(1~5종)',           '질병수술비'),
    (SAMSUNG_LOSS, '상해수술비',                 '상해수술비'),
    (SAMSUNG_LOSS, '암수술비',                   '암수술비'),
    (SAMSUNG_LOSS, '실손입원의료비(급여)',         '실손입원급여'),
    (SAMSUNG_LOSS, '실손통원의료비(급여)',         '실손통원급여'),
    (SAMSUNG_LOSS, '비급여주사료실손',            '실손비급여주사'),
    (SAMSUNG_LOSS, '비급여도수치료실손',          '실손비급여도수치료'),
    (SAMSUNG_LOSS, '일상생활배상책임',            '일상생활배상책임'),

    # ────────────────────────────────────────────────
    # 한화손해 (HANHWA_LOSS=6)
    # ────────────────────────────────────────────────
    (HANHWA_LOSS, '일반사망보험금',              '일반사망'),
    (HANHWA_LOSS, '재해사망특약',               '재해사망'),
    (HANHWA_LOSS, '질병사망보장',               '질병사망'),
    (HANHWA_LOSS, '상해후유장해(3~100%)',        '상해후유장해'),
    (HANHWA_LOSS, '고도후유장해(80%이상)',        '고도후유장해'),
    (HANHWA_LOSS, '암진단비(유사암포함)',         '일반암진단비'),
    (HANHWA_LOSS, '암진단비(유사암제외)',         '일반암진단비'),
    (HANHWA_LOSS, '유사암진단비',               '유사암진단비'),
    (HANHWA_LOSS, '갑상선암진단비',             '갑상선암진단비'),
    (HANHWA_LOSS, '뇌졸중진단비',               '뇌졸중진단비'),
    (HANHWA_LOSS, '뇌출혈진단비',               '뇌출혈진단비'),
    (HANHWA_LOSS, '급성심근경색증진단비',        '급성심근경색진단비'),
    (HANHWA_LOSS, '질병입원일당(3일이상)',        '질병입원일당'),
    (HANHWA_LOSS, '상해입원일당(3일이상)',        '상해입원일당'),
    (HANHWA_LOSS, '질병수술비',                 '질병수술비'),
    (HANHWA_LOSS, '상해수술비',                 '상해수술비'),
    (HANHWA_LOSS, '실손입원급여의료비',          '실손입원급여'),
    (HANHWA_LOSS, '실손통원급여의료비',          '실손통원급여'),
    (HANHWA_LOSS, '비급여주사치료',             '실손비급여주사'),

    # ────────────────────────────────────────────────
    # 현대해상 (HYUNDAI=7)
    # ────────────────────────────────────────────────
    (HYUNDAI, '일반사망보험금',                  '일반사망'),
    (HYUNDAI, '재해사망보험금',                  '재해사망'),
    (HYUNDAI, '상해사망보험금',                  '상해사망'),
    (HYUNDAI, '상해후유장해보험금(3~100%)',       '상해후유장해'),
    (HYUNDAI, '일반암진단금',                    '일반암진단비'),
    (HYUNDAI, '특정(소액)암진단금',              '소액암진단비'),
    (HYUNDAI, '유사암진단금',                    '유사암진단비'),
    (HYUNDAI, '갑상선암진단금',                  '갑상선암진단비'),
    (HYUNDAI, '뇌졸중진단금',                    '뇌졸중진단비'),
    (HYUNDAI, '뇌출혈진단금',                    '뇌출혈진단비'),
    (HYUNDAI, '급성심근경색증진단금',             '급성심근경색진단비'),
    (HYUNDAI, '허혈성심장질환진단금',             '허혈성심장질환진단비'),
    (HYUNDAI, '질병입원일당(1일이상)',             '질병입원일당'),
    (HYUNDAI, '상해입원일당(1일이상)',             '상해입원일당'),
    (HYUNDAI, '질병수술비(1~5종수술)',            '질병수술비'),
    (HYUNDAI, '상해수술비(1~5종수술)',            '상해수술비'),
    (HYUNDAI, '암수술비',                        '암수술비'),
    (HYUNDAI, '실손의료비(급여입원)',             '실손입원급여'),
    (HYUNDAI, '실손의료비(급여통원)',             '실손통원급여'),
    (HYUNDAI, '비급여주사료(실손)',               '실손비급여주사'),
    (HYUNDAI, '비급여MRI촬영료(실손)',            '실손비급여MRI'),
    (HYUNDAI, '일상생활배상책임(Hi)',             '일상생활배상책임'),
    (HYUNDAI, '대물사고벌금',                    '대물벌금'),
    (HYUNDAI, '형사합의금',                      '형사합의실손비'),

    # ────────────────────────────────────────────────
    # DB손해 (DB_LOSS=11)
    # ────────────────────────────────────────────────
    (DB_LOSS, '일반사망',                        '일반사망'),
    (DB_LOSS, '재해사망',                        '재해사망'),
    (DB_LOSS, '일반상해사망',                    '상해사망'),
    (DB_LOSS, '상해후유장해(3~100%)',             '상해후유장해'),
    (DB_LOSS, '일반암진단비Ⅰ',                   '일반암진단비'),
    (DB_LOSS, '유사암진단비',                    '유사암진단비'),
    (DB_LOSS, '소액암진단비(갑상선 등)',           '소액암진단비'),
    (DB_LOSS, '뇌졸중진단비',                    '뇌졸중진단비'),
    (DB_LOSS, '뇌출혈진단비',                    '뇌출혈진단비'),
    (DB_LOSS, '급성심근경색증진단비',             '급성심근경색진단비'),
    (DB_LOSS, '허혈성심장질환진단비',             '허혈성심장질환진단비'),
    (DB_LOSS, '질병입원일당',                    '질병입원일당'),
    (DB_LOSS, '상해입원일당',                    '상해입원일당'),
    (DB_LOSS, '질병수술비(1~5종)',               '질병수술비'),
    (DB_LOSS, '상해수술비',                      '상해수술비'),
    (DB_LOSS, '실손입원의료비(급여)',              '실손입원급여'),
    (DB_LOSS, '실손통원의료비(급여)',              '실손통원급여'),
    (DB_LOSS, '비급여주사료(실손)',               '실손비급여주사'),
    (DB_LOSS, '비급여도수치료(실손)',             '실손비급여도수치료'),
    (DB_LOSS, '자동차사고벌금',                  '대물벌금'),

    # ────────────────────────────────────────────────
    # KB손해 (KB_LOSS=12)
    # ────────────────────────────────────────────────
    (KB_LOSS, '일반사망',                        '일반사망'),
    (KB_LOSS, '재해사망',                        '재해사망'),
    (KB_LOSS, '질병사망',                        '질병사망'),
    (KB_LOSS, '상해후유장해(3~100%)',             '상해후유장해'),
    (KB_LOSS, '일반암진단비',                    '일반암진단비'),
    (KB_LOSS, '소액암진단비',                    '소액암진단비'),
    (KB_LOSS, '유사암진단비(갑상선·경계성)',       '유사암진단비'),
    (KB_LOSS, '뇌졸중진단비',                    '뇌졸중진단비'),
    (KB_LOSS, '급성심근경색진단비',               '급성심근경색진단비'),
    (KB_LOSS, '질병입원일당(3일이상)',             '질병입원일당'),
    (KB_LOSS, '상해입원일당',                    '상해입원일당'),
    (KB_LOSS, '질병수술비',                      '질병수술비'),
    (KB_LOSS, '상해수술비',                      '상해수술비'),
    (KB_LOSS, '실손입원급여',                    '실손입원급여'),
    (KB_LOSS, '실손통원급여',                    '실손통원급여'),
    (KB_LOSS, '비급여주사료실손',                '실손비급여주사'),

    # ────────────────────────────────────────────────
    # 삼성생명 (SAMSUNG_LIFE=206)
    # ────────────────────────────────────────────────
    (SAMSUNG_LIFE, '일반사망',                   '일반사망'),
    (SAMSUNG_LIFE, '재해사망보험금',              '재해사망'),
    (SAMSUNG_LIFE, '질병사망보험금',              '질병사망'),
    (SAMSUNG_LIFE, '재해후유장해급여금(3~100%)', '상해후유장해'),
    (SAMSUNG_LIFE, '질병후유장해(3~100%)',        '질병후유장해'),
    (SAMSUNG_LIFE, '일반암진단급여금',            '일반암진단비'),
    (SAMSUNG_LIFE, '유사암진단급여금',            '유사암진단비'),
    (SAMSUNG_LIFE, '뇌졸중진단급여금',            '뇌졸중진단비'),
    (SAMSUNG_LIFE, '뇌혈관질환진단급여금',        '뇌혈관질환진단비'),
    (SAMSUNG_LIFE, '급성심근경색진단급여금',      '급성심근경색진단비'),
    (SAMSUNG_LIFE, '질병입원급여금(입원일당)',     '질병입원일당'),
    (SAMSUNG_LIFE, '상해입원급여금(입원일당)',     '상해입원일당'),
    (SAMSUNG_LIFE, '질병수술급여금',              '질병수술비'),
    (SAMSUNG_LIFE, '상해수술급여금',              '상해수술비'),

    # ────────────────────────────────────────────────
    # 한화생명 (HANHWA_LIFE=213)
    # ────────────────────────────────────────────────
    (HANHWA_LIFE, '일반사망',                    '일반사망'),
    (HANHWA_LIFE, '재해사망',                    '재해사망'),
    (HANHWA_LIFE, '질병사망',                    '질병사망'),
    (HANHWA_LIFE, '상해80%이상후유장해',          '고도후유장해'),
    (HANHWA_LIFE, '상해후유장해(3~100%)',         '상해후유장해'),
    (HANHWA_LIFE, '질병후유장해(3~100%)',         '질병후유장해'),
    (HANHWA_LIFE, '암진단급여금Ⅰ(일반암)',        '일반암진단비'),
    (HANHWA_LIFE, '소액암진단급여금',             '소액암진단비'),
    (HANHWA_LIFE, '유사암진단급여금',             '유사암진단비'),
    (HANHWA_LIFE, '뇌졸중진단급여금',             '뇌졸중진단비'),
    (HANHWA_LIFE, '뇌출혈진단급여금',             '뇌출혈진단비'),
    (HANHWA_LIFE, '급성심근경색진단급여금',        '급성심근경색진단비'),
    (HANHWA_LIFE, '질병입원급여금',               '질병입원일당'),
    (HANHWA_LIFE, '상해입원급여금',               '상해입원일당'),
    (HANHWA_LIFE, '질병수술급여금',               '질병수술비'),
    (HANHWA_LIFE, '상해수술급여금',               '상해수술비'),

    # ────────────────────────────────────────────────
    # 교보생명 (KYOBO_LIFE=201)
    # ────────────────────────────────────────────────
    (KYOBO_LIFE, '일반사망보험금',               '일반사망'),
    (KYOBO_LIFE, '재해사망보험금',               '재해사망'),
    (KYOBO_LIFE, '상해후유장해급여(3~100%)',      '상해후유장해'),
    (KYOBO_LIFE, '질병후유장해급여(3~100%)',      '질병후유장해'),
    (KYOBO_LIFE, '일반암진단보험금',             '일반암진단비'),
    (KYOBO_LIFE, '소액암(유사암)진단보험금',      '소액암진단비'),
    (KYOBO_LIFE, '뇌졸중진단보험금',             '뇌졸중진단비'),
    (KYOBO_LIFE, '급성심근경색진단보험금',        '급성심근경색진단비'),
    (KYOBO_LIFE, '질병입원일당',                 '질병입원일당'),
    (KYOBO_LIFE, '상해입원일당',                 '상해입원일당'),
    (KYOBO_LIFE, '질병수술비',                   '질병수술비'),
    (KYOBO_LIFE, '상해수술비',                   '상해수술비'),
    (KYOBO_LIFE, '암수술비',                     '암수술비'),

    # ────────────────────────────────────────────────
    # NH농협손해 (NH_LOSS=15)
    # ────────────────────────────────────────────────
    (NH_LOSS, '일반사망보험금',                  '일반사망'),
    (NH_LOSS, '재해사망보험금',                  '재해사망'),
    (NH_LOSS, '상해후유장해보험금',              '상해후유장해'),
    (NH_LOSS, '일반암진단보험금',                '일반암진단비'),
    (NH_LOSS, '유사암진단보험금',                '유사암진단비'),
    (NH_LOSS, '뇌졸중진단보험금',                '뇌졸중진단비'),
    (NH_LOSS, '급성심근경색진단보험금',           '급성심근경색진단비'),
    (NH_LOSS, '질병입원일당(입원3일이상)',         '질병입원일당'),
    (NH_LOSS, '상해입원일당',                    '상해입원일당'),
    (NH_LOSS, '질병수술비',                      '질병수술비'),
    (NH_LOSS, '상해수술비',                      '상해수술비'),
    (NH_LOSS, '실손입원의료비(급여)',              '실손입원급여'),
    (NH_LOSS, '실손통원의료비(급여)',              '실손통원급여'),

    # ────────────────────────────────────────────────
    # 수술/처치 섹션 신규 alias (실샘플 unmatched 기반 — 충돌 없는 신규만)
    # ※ 베타 normalizer 훅은 admin_verified만 신뢰 → 아래 SEED alias는 베타 미발동,
    #   1순위 _CATEGORY_MAP + 프롬프트로 매칭. 정식 출시 시 admin 검수→승격으로 활성(데이터 자산).
    # ────────────────────────────────────────────────
    (HANHWA_LOSS, '암수술비',                    '암수술비'),
    (HANHWA_LOSS, '방사선약물치료비',             '항암방사선치료비'),
    (HANHWA_LOSS, '항암방사선약물치료비',         '항암방사선치료비'),
    (MERITZ, '항암약물치료비',                   '항암약물치료비'),

    # ────────────────────────────────────────────────
    # 특수수술 alias (2026-07-02 확장 — 종합보험 미매칭 담보)
    # ────────────────────────────────────────────────
    (MERITZ, '골절수술비',                       '골절수술비'),
    (MERITZ, '화상수술비',                       '화상수술비'),
    (MERITZ, '조혈모세포이식수술비',             '조혈모세포이식수술비'),
    (MERITZ, '장기이식수술비',                   '장기이식수술비'),
    (MERITZ, '각막이식수술비',                   '각막이식수술비'),
    (MERITZ, '흉터복원수술비',                   '흉터복원수술비'),
    (MERITZ, '인공관절수술비',                   '인공관절수술비'),
    (MERITZ, '호흡기수술비',                     '호흡기수술비'),
    (SAMSUNG_LOSS, '골절수술비',                 '골절수술비'),
    (SAMSUNG_LOSS, '화상수술비',                 '화상수술비'),
    (SAMSUNG_LOSS, '조혈모세포이식수술비',       '조혈모세포이식수술비'),
    (SAMSUNG_LOSS, '장기이식수술비',             '장기이식수술비'),
    (SAMSUNG_LOSS, '각막이식수술비',             '각막이식수술비'),
    (SAMSUNG_LOSS, '흉터복원수술비',             '흉터복원수술비'),
    (SAMSUNG_LOSS, '인공관절수술비',             '인공관절수술비'),
    (SAMSUNG_LOSS, '호흡기수술비',               '호흡기수술비'),
    (HYUNDAI, '골절수술비',                      '골절수술비'),
    (HYUNDAI, '화상수술비',                      '화상수술비'),
    (HYUNDAI, '조혈모세포이식수술비',            '조혈모세포이식수술비'),
    (HYUNDAI, '장기이식수술비',                  '장기이식수술비'),
    (HYUNDAI, '각막이식수술비',                  '각막이식수술비'),
    (HYUNDAI, '흉터복원수술비',                  '흉터복원수술비'),
    (HYUNDAI, '인공관절수술비',                  '인공관절수술비'),
    (HYUNDAI, '호흡기수술비',                    '호흡기수술비'),

    # ────────────────────────────────────────────────
    # 특수입원 alias (2026-07-02 확장 — 종합보험 미매칭 담보)
    # ★ '중환자실입원일당'은 '질병중환자실입원일당'(기존 leaf)과 별개.
    # ────────────────────────────────────────────────
    (MERITZ, '중환자실입원일당',                 '중환자실입원일당'),
    (MERITZ, '환경성질환입원일당',               '환경성질환입원일당'),
    (MERITZ, '14대질병입원일당',                 '14대질병입원일당'),
    (MERITZ, '여성특정질병입원일당',             '여성특정질병입원일당'),
    (MERITZ, '희귀난치성질환입원일당',           '희귀난치성질환입원일당'),
    (SAMSUNG_LOSS, '중환자실입원일당',           '중환자실입원일당'),
    (SAMSUNG_LOSS, '환경성질환입원일당',         '환경성질환입원일당'),
    (SAMSUNG_LOSS, '14대질병입원일당',           '14대질병입원일당'),
    (SAMSUNG_LOSS, '여성특정질병입원일당',       '여성특정질병입원일당'),
    (SAMSUNG_LOSS, '희귀난치성질환입원일당',     '희귀난치성질환입원일당'),
    (HYUNDAI, '중환자실입원일당',                '중환자실입원일당'),
    (HYUNDAI, '환경성질환입원일당',              '환경성질환입원일당'),
    (HYUNDAI, '14대질병입원일당',                '14대질병입원일당'),
    (HYUNDAI, '여성특정질병입원일당',            '여성특정질병입원일당'),
    (HYUNDAI, '희귀난치성질환입원일당',          '희귀난치성질환입원일당'),

    # ────────────────────────────────────────────────
    # 표적항암 alias (2026-07-02 확장 — 종합보험 미매칭 담보)
    # ────────────────────────────────────────────────
    (MERITZ, '표적항암약물치료비',               '표적항암약물치료비'),
    (MERITZ, '표적항암방사선치료비',             '표적항암방사선치료비'),
    (SAMSUNG_LOSS, '표적항암약물치료비',         '표적항암약물치료비'),
    (SAMSUNG_LOSS, '표적항암방사선치료비',       '표적항암방사선치료비'),
    (HYUNDAI, '표적항암약물치료비',              '표적항암약물치료비'),
    (HYUNDAI, '표적항암방사선치료비',            '표적항암방사선치료비'),
    (HANHWA_LOSS, '표적항암약물치료비',          '표적항암약물치료비'),
    (HANHWA_LOSS, '표적항암방사선치료비',        '표적항암방사선치료비'),
]


class Command(BaseCommand):
    help = (
        '표준 담보 트리 + 정규화 사전 v0 시드 (identity-true upsert, 멱등).\n'
        '기존 행 PK 보존 — M2M 링크·NormalizationDict FK 생존. 삭제 없음(--prune 별도).\n'
        '★ V0 스타터 데이터 — 약관 원문 대조 검증 전. 프로덕션 전 도메인 전문가 검토 필요.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--force', action='store_true',
            help='SeedMarker 버전이 최신이어도 강제 재실행')
        parser.add_argument(
            '--prune', action='store_true',
            help='코드에 없는 seed 출처 고아 행 삭제 (기본 OFF — 배포에서 미사용). '
                 'admin_verified/ocr_learned 및 M2M 링크 걸린 leaf 는 보호')

    @transaction.atomic
    def handle(self, *args, **options):
        force = options['force']
        prune = options['prune']

        # ── 0) 버전 마커 가드: 부팅 경로(no-op) 무해화 ──
        marker = SeedMarker.objects.filter(key=MARKER_KEY).first()
        if marker and marker.version == SEED_VERSION and not force and not prune:
            self.stdout.write(
                f'=== seed_normalization: 이미 최신({SEED_VERSION}) — 건너뜀 '
                '(강제 실행: --force) ===')
            return

        self.stdout.write('=== seed_normalization v0 시작 (upsert) ===')
        self.stdout.write(
            '★ 경고: V0 스타터 데이터. 약관 원문 대조 미완료. '
            '프로덕션 전 도메인 검증 필수 (게이트: 보장 기준선 출처 정의).'
        )

        detail_by_name = self._seed_tree()
        norm_stats = self._seed_normalization(detail_by_name)
        orphan_stats = self._handle_orphans(prune=prune)

        SeedMarker.objects.update_or_create(
            key=MARKER_KEY, defaults={'version': SEED_VERSION})

        cat_count = AnalysisCategory.objects.filter(
            name__startswith=STD_MARKER).count()
        detail_count = len(detail_by_name)

        self.stdout.write(self.style.SUCCESS('=== seed_normalization 완료 ==='))
        self.stdout.write(f'  표준 카테고리   : {cat_count}개')
        self.stdout.write(f'  표준 담보(leaf) : {detail_count}개')
        self.stdout.write(
            f'  정규화 사전     : 생성 {norm_stats["created"]} / 갱신 {norm_stats["updated"]} / '
            f'보호 {norm_stats["protected"]} (skip={norm_stats["skipped"]})'
        )
        self.stdout.write(
            f'  고아(orphan)    : 트리 {orphan_stats["tree"]}건 / 사전 {orphan_stats["dict"]}건 '
            f'{"→ prune 삭제 " + str(orphan_stats["pruned"]) + "건" if prune else "(로그만 — 삭제 없음)"}'
        )
        self.stdout.write(
            f'  마커            : {MARKER_KEY}={SEED_VERSION} (재부팅 시 no-op)'
        )

    # ── 1) 표준 담보 트리 — 자연키(부모 FK + name) upsert. PK 보존 ─────────
    def _seed_tree(self):
        """AnalysisCategory→Sub→Detail get_or_create 업서트. 반환: {담보명: AnalysisDetail}.

        기존 행은 PK를 유지한 채 비-키 속성(order/insurance_type/chart_based_amount)만
        갱신 → InsuranceDetail.analysis_detail M2M·NormalizationDict FK 생존.
        ★ [표준] leaf 이름 변경 금지(PlannerBaseline coverage_key가 이름에 묶임).
        """
        detail_by_name = {}
        created = updated = 0
        for c_order, (cat_name, ins_type, subs) in enumerate(STANDARD_TREE, start=1):
            cat, c_new = AnalysisCategory.objects.get_or_create(
                name=f'{STD_MARKER}{cat_name}',
                defaults={'insurance_type': ins_type, 'order': c_order},
            )
            created += c_new
            updated += self._sync_fields(
                cat, insurance_type=ins_type, order=c_order)
            for s_order, (sub_name, details) in enumerate(subs, start=1):
                sub, s_new = AnalysisSubCategory.objects.get_or_create(
                    category=cat,
                    name=sub_name,
                    defaults={'insurance_type': ins_type, 'order': s_order},
                )
                created += s_new
                updated += self._sync_fields(
                    sub, insurance_type=ins_type, order=s_order)
                for d_order, (det_name, based_amount) in enumerate(details, start=1):
                    det, d_new = AnalysisDetail.objects.get_or_create(
                        sub_category=sub,
                        name=det_name,
                        defaults={'order': d_order,
                                  'chart_based_amount': based_amount},
                    )
                    created += d_new
                    updated += self._sync_fields(
                        det, order=d_order, chart_based_amount=based_amount)
                    detail_by_name[det_name] = det

        total = len(detail_by_name)
        self.stdout.write(
            f'  [1] 표준 담보 트리: 카테고리 {len(STANDARD_TREE)}개, 담보 {total}개 '
            f'(신규 {created} / 갱신 {updated} — 기존 PK 보존)'
        )
        return detail_by_name

    @staticmethod
    def _sync_fields(obj, **fields):
        """비-키 필드만 비교 후 변경 시 저장. 반환: 1(갱신) / 0(무변경)."""
        changed = []
        for k, v in fields.items():
            if getattr(obj, k) != v:
                setattr(obj, k, v)
                changed.append(k)
        if changed:
            obj.save(update_fields=changed)
            return 1
        return 0

    # ── 2) 정규화 사전 — (company, raw_name) 자연키 upsert. seed 출처만 ────
    def _seed_normalization(self, detail_by_name):
        """NormalizationDict upsert. 반환: dict(created/updated/protected/skipped).

        ★ 자연키 (company, raw_name)에 admin_verified/ocr_learned 행이 이미 있으면
          절대 건드리지 않음(protected). seed 출처 행만 std_detail/confidence 갱신
          (hit_count는 보존 — 데이터 복리 자산).
        """
        created = updated = protected = skipped = 0
        skipped_names = []

        for company, raw_name, std_name in NORMALIZATION_V0:
            std_detail = detail_by_name.get(std_name)
            if std_detail is None:
                skipped += 1
                skipped_names.append(f'[{company}] {raw_name} → {std_name}(없음)')
                continue
            row = NormalizationDict.objects.filter(
                company=company, raw_name=raw_name).first()
            if row is None:
                NormalizationDict.objects.create(
                    std_detail=std_detail,
                    company=company,
                    raw_name=raw_name,
                    source=NormalizationDict.SOURCE_SEED,
                    confidence=80,   # v0 스타터: 약관 미검증 → 신뢰도 80 (admin_verified=100)
                    hit_count=0,
                )
                created += 1
            elif row.source != NormalizationDict.SOURCE_SEED:
                # admin_verified / ocr_learned — 어떤 코드 경로에서도 불변
                protected += 1
            else:
                if row.std_detail_id != std_detail.id or row.confidence != 80:
                    row.std_detail = std_detail
                    row.confidence = 80
                    row.save(update_fields=['std_detail', 'confidence'])
                    updated += 1

        if skipped_names:
            self.stdout.write(
                f'  [경고] 표준 담보명 미매칭 skip {skipped}건:\n'
                + '\n'.join(f'    {s}' for s in skipped_names)
            )
        self.stdout.write(
            f'  [2] 정규화 사전: 생성 {created} / 갱신 {updated} / 보호 {protected} '
            f'(skip={skipped})'
        )
        return {'created': created, 'updated': updated,
                'protected': protected, 'skipped': skipped}

    # ── 3) 고아 처리 — 로그만(기본) / --prune 시 seed 출처 한정 삭제 ────────
    def _handle_orphans(self, prune):
        """코드(STANDARD_TREE/NORMALIZATION_V0)에서 사라진 DB 행을 탐지.

        기본: 로그만 남기고 절대 삭제하지 않음(배포 경로 무해).
        --prune: seed 출처 행만 삭제하되, 아래는 보호(삭제 스킵 + 로그):
          - admin_verified/ocr_learned alias가 걸린 leaf (CASCADE 로 검수 자산이
            지워지는 것 방지)
          - InsuranceDetail.analysis_detail M2M 링크가 걸린 leaf (고객 스캔 데이터
            집계가 끊기는 것 방지)
        """
        # 코드 기준 자연키 집합
        code_cats = {f'{STD_MARKER}{c}' for c, _t, _s in STANDARD_TREE}
        code_subs = set()
        code_dets = set()
        for cat_name, _t, subs in STANDARD_TREE:
            for sub_name, details in subs:
                code_subs.add((f'{STD_MARKER}{cat_name}', sub_name))
                for det_name, _amt in details:
                    code_dets.add((f'{STD_MARKER}{cat_name}', sub_name, det_name))
        code_aliases = {(c, r) for c, r, _s in NORMALIZATION_V0}

        # 트리 고아 (leaf → sub → cat 순으로 수집)
        orphan_dets = [
            d for d in AnalysisDetail.objects.filter(
                sub_category__category__name__startswith=STD_MARKER
            ).select_related('sub_category__category')
            if (d.sub_category.category.name, d.sub_category.name, d.name)
            not in code_dets
        ]
        orphan_subs = [
            s for s in AnalysisSubCategory.objects.filter(
                category__name__startswith=STD_MARKER).select_related('category')
            if (s.category.name, s.name) not in code_subs
        ]
        orphan_cats = [
            c for c in AnalysisCategory.objects.filter(
                name__startswith=STD_MARKER)
            if c.name not in code_cats
        ]

        # 사전 고아 — [표준] 트리를 가리키는 seed 출처 행 중 코드에 없는 alias
        orphan_dict_rows = [
            n for n in NormalizationDict.objects.filter(
                source=NormalizationDict.SOURCE_SEED,
                std_detail__sub_category__category__name__startswith=STD_MARKER,
            )
            if (n.company, n.raw_name) not in code_aliases
        ]

        tree_orphans = len(orphan_dets) + len(orphan_subs) + len(orphan_cats)
        for d in orphan_dets:
            self.stdout.write(f'  [고아] leaf: {d.sub_category.category.name}/'
                              f'{d.sub_category.name}/{d.name} (pk={d.pk})')
        for s in orphan_subs:
            self.stdout.write(f'  [고아] sub: {s.category.name}/{s.name} (pk={s.pk})')
        for c in orphan_cats:
            self.stdout.write(f'  [고아] cat: {c.name} (pk={c.pk})')
        for n in orphan_dict_rows:
            self.stdout.write(f'  [고아] 사전: [{n.company}] {n.raw_name} (pk={n.pk})')

        pruned = 0
        if prune:
            # 사전 고아: seed 출처만 — 안전 삭제
            for n in orphan_dict_rows:
                n.delete()
                pruned += 1
            # leaf 고아: 검수 자산·고객 링크 보호 가드
            for d in orphan_dets:
                if d.aliases.exclude(
                        source=NormalizationDict.SOURCE_SEED).exists():
                    self.stdout.write(
                        f'  [보호] leaf {d.name}: admin_verified/ocr_learned alias '
                        '존재 — 삭제 스킵')
                    continue
                if d.insurancedetail_set.exists():
                    self.stdout.write(
                        f'  [보호] leaf {d.name}: 고객 스캔 M2M 링크 존재 — 삭제 스킵')
                    continue
                d.aliases.all().delete()  # 남은 seed alias 정리 후 leaf 삭제
                d.delete()
                pruned += 1
            # sub/cat 고아: 자식이 완전히 비었을 때만
            for s in orphan_subs:
                if not s.details.exists():
                    s.delete()
                    pruned += 1
            for c in orphan_cats:
                if not c.sub_categories.exists():
                    c.delete()
                    pruned += 1
            self.stdout.write(f'  [3] prune: 고아 {pruned}건 삭제 (seed 출처 한정)')
        elif tree_orphans or orphan_dict_rows:
            self.stdout.write(
                f'  [3] 고아 {tree_orphans + len(orphan_dict_rows)}건 — 삭제하지 않음 '
                '(정리하려면 --prune)')

        return {'tree': tree_orphans, 'dict': len(orphan_dict_rows),
                'pruned': pruned}
