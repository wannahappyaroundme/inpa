"""랜딩 스크린샷 촬영용 시드 — 수동 전용 (배포 startCommand 에 절대 넣지 않는다).

목적: www.inpa.kr 랜딩의 제품 스크린샷 5장(대시보드/고객/보장/비교/일정)을
  "진짜 사용 중인 계정"처럼 보이게 하는 촬영 전용 데이터 셋.
  화면 어디에도 [DEMO]/[가칭]/코드형 이름이 보이지 않아야 한다(PM 2026-07-24 지시).

seed_demo 와의 차이:
  - seed_demo  = 기능 렌더 확인용(마커 노출 허용, 자체 [DEMO] 트리 생성).
  - seed_capture = 촬영용(마커 노출 금지, seed_normalization 의 실제 [표준] 트리 재사용).
    → 실행 전제: `python manage.py seed_normalization` 선행(트리 없으면 에러 안내).

멱등/정리 마커:
  - 계정: capture@inpa.local (@inpa.local → cleanup_demo/seed_demo _cleanup 이 함께 정리).
  - 공유 카탈로그 행: '[촬영]' prefix (InsuranceCategory/Insurance).
  - 표준 트리/정규화 사전은 절대 만들지도 지우지도 않는다(공유 전역 마스터 보호).

실행:
  python manage.py seed_normalization   # (없다면) 실제 표준 트리
  python manage.py seed_capture
"""
import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from inpa.accounts.models import Profile
from inpa.analysis.models import AnalysisCategory, AnalysisDetail
from inpa.booking.models import Meeting, WorkHour
from inpa.customers.models import Customer, CustomerTag, PlannerBaseline
from inpa.dashboard.models import MonthlyGoal
from inpa.insurances.models import (
    CustomerInsurance, CustomerInsuranceDetail, Insurance, InsuranceCategory,
    InsuranceDetail, InsuranceSubCategory,
)
from inpa.notifications.models import Notification, NotifType
from inpa.schedule.models import ScheduleItem

User = get_user_model()

CAPTURE_PLANNER_EMAIL = 'capture@inpa.local'
CAPTURE_PLANNER_PASSWORD = 'capturePass123!'
CAPTURE_CATALOG_TAG = '[촬영]'     # 공유 카탈로그 정리 마커(촬영 5개 화면엔 렌더 안 됨)
STD_MARKER = '[표준]'              # seed_normalization 의 실제 트리 마커(읽기 전용)


# ════════════════════════════════════════════════════════════════════════
# 고객 30명 — 자연스러운 가명(연예인·유명인 동명 회피), 실제같은 번호.
#   (이름, 생일, 성별 1남/2여, 전화, 단계, 상태, 색, 태그, 메모,
#    m_ago=등록 몇 달 전, day=등록일, lc_days=마지막 연락 며칠 전,
#    fa=(m_ago, day)|None, fav, pin)
#   김인파/이인파/최인파 = PM 지정 대표 가명(각각 FA/TA/청약 배치).
# ════════════════════════════════════════════════════════════════════════
CUSTOMERS = [
    # ── 이번 달 신규(5) ──────────────────────────────────────────────
    {'name': '김인파', 'birth': '1991.02.14', 'gender': 1, 'phone': '010-1207-4368',
     'stage': 'meeting', 'status': 'active', 'color': 'blue', 'tags': ['VIP'],
     'memo': '보장 점검 요청. 실손 갱신 안내 필요. 다음 상담 때 새 설계안 설명 예정.',
     'm_ago': 0, 'day': 3, 'lc_days': 1, 'fa': (0, 10), 'fav': True, 'pin': True},
    {'name': '박준혁', 'birth': '1987.09.02', 'gender': 1, 'phone': '010-1230-1957',
     'stage': 'db', 'status': 'active', 'color': 'green', 'tags': ['소개'],
     'memo': '오세아님 소개. 자녀 어린이보험 관심. 이번 주 첫 연락 예정.',
     'm_ago': 0, 'day': 18, 'lc_days': 2, 'fa': None, 'fav': False, 'pin': False},
    {'name': '윤서아', 'birth': '1994.11.27', 'gender': 2, 'phone': '010-1253-4079',
     'stage': 'db', 'status': 'active', 'color': 'purple', 'tags': ['신규'],
     'memo': '소개 카드로 상담 신청. 주말 오후 통화 희망.',
     'm_ago': 0, 'day': 20, 'lc_days': 0, 'fa': None, 'fav': False, 'pin': False},
    {'name': '신지후', 'birth': '1998.05.16', 'gender': 1, 'phone': '010-1276-2835',
     'stage': 'contact', 'status': 'active', 'color': 'yellow', 'tags': ['신규'],
     'memo': '사회초년생. 실손과 운전자보험부터 시작하고 싶다고 함.',
     'm_ago': 0, 'day': 14, 'lc_days': 3, 'fa': None, 'fav': False, 'pin': False},
    {'name': '배소율', 'birth': '1992.08.09', 'gender': 2, 'phone': '010-1299-7391',
     'stage': 'db', 'status': 'active', 'color': '', 'tags': [],
     'memo': '블로그 보고 연락. 치아보험 견적 문의.',
     'm_ago': 0, 'day': 21, 'lc_days': 1, 'fa': None, 'fav': False, 'pin': False},
    # ── 지난달(4) ────────────────────────────────────────────────────
    {'name': '정다은', 'birth': '1989.03.30', 'gender': 2, 'phone': '010-1322-5062',
     'stage': 'meeting', 'status': 'active', 'color': 'red', 'tags': ['VIP'],
     'memo': '2차 상담 완료. 암보험 증액 검토 중. 남편 보험도 함께 점검 예정.',
     'm_ago': 1, 'day': 5, 'lc_days': 4, 'fa': (1, 12), 'fav': True, 'pin': False},
    {'name': '오세아', 'birth': '1978.12.03', 'gender': 2, 'phone': '010-1345-8247',
     'stage': 'contract', 'status': 'active', 'color': 'blue', 'tags': ['VIP'],
     'memo': '치매간병보험 청약 완료. 8월 만기 화재보험 갱신 안내 예정.',
     'm_ago': 1, 'day': 8, 'lc_days': 2, 'fa': (1, 15), 'fav': False, 'pin': False},
    {'name': '문지호', 'birth': '1996.06.21', 'gender': 1, 'phone': '010-1368-2514',
     'stage': 'contact', 'status': 'active', 'color': 'green', 'tags': [],
     'memo': '통화 2회. 보험료 부담을 걱정해 최소 설계부터 제안하기로.',
     'm_ago': 1, 'day': 17, 'lc_days': 6, 'fa': None, 'fav': False, 'pin': False},
    {'name': '홍세영', 'birth': '1984.01.19', 'gender': 2, 'phone': '010-1391-6420',
     'stage': 'db', 'status': 'active', 'color': '', 'tags': [],
     'memo': '지역 모임에서 만남. 기존 설계사와 정리되면 연락 주기로.',
     'm_ago': 1, 'day': 23, 'lc_days': 4, 'fa': None, 'fav': False, 'pin': False},
    # ── 2달 전(5) ────────────────────────────────────────────────────
    {'name': '이수민', 'birth': '1993.07.28', 'gender': 2, 'phone': '010-1414-3748',
     'stage': 'meeting', 'status': 'active', 'color': 'yellow', 'tags': [],
     'memo': '종합건강보험 가입. 생일 축하 문자 예약해 둘 것.',
     'm_ago': 2, 'day': 4, 'lc_days': 3, 'fa': (0, 4), 'fav': False, 'pin': False},
    {'name': '강태윤', 'birth': '1990.07.08', 'gender': 1, 'phone': '010-1437-1936',
     'stage': 'meeting', 'status': 'active', 'color': 'blue', 'tags': [],
     'memo': '운전자보험 가입. 암보험은 아내와 상의 후 결정하기로.',
     'm_ago': 2, 'day': 11, 'lc_days': 5, 'fa': (0, 8), 'fav': False, 'pin': False},
    {'name': '김도현', 'birth': '1981.10.25', 'gender': 1, 'phone': '010-1460-9471',
     'stage': 'contact', 'status': 'active', 'color': 'red', 'tags': ['갱신 예정'],
     'memo': '9월 실손 갱신. 갱신 전 보장 점검 상담 잡기로.',
     'm_ago': 2, 'day': 19, 'lc_days': 3, 'fa': None, 'fav': False, 'pin': False},
    {'name': '임채원', 'birth': '1997.04.06', 'gender': 2, 'phone': '010-1483-5163',
     'stage': 'db', 'status': 'active', 'color': '', 'tags': [],
     'memo': '셀프진단으로 유입. 보장 요약 링크 열람 확인.',
     'm_ago': 2, 'day': 24, 'lc_days': 6, 'fa': None, 'fav': False, 'pin': False},
    {'name': '한승우', 'birth': '1986.02.11', 'gender': 1, 'phone': '010-1506-4685',
     'stage': 'contract', 'status': 'active', 'color': 'green', 'tags': [],
     'memo': '정기보험 청약 완료. 소개 고객 2명 약속받음.',
     'm_ago': 2, 'day': 9, 'lc_days': 7, 'fa': (1, 26), 'fav': False, 'pin': False},
    # ── 3달 전(5) ────────────────────────────────────────────────────
    {'name': '최인파', 'birth': '1985.05.23', 'gender': 1, 'phone': '010-1529-7238',
     'stage': 'contract', 'status': 'active', 'color': 'purple', 'tags': ['VIP'],
     'memo': '종합건강보험 청약 완료. 자녀 태아보험 상담 예약 잡을 것.',
     'm_ago': 3, 'day': 7, 'lc_days': 2, 'fa': (1, 20), 'fav': True, 'pin': False},
    {'name': '송민재', 'birth': '1995.09.14', 'gender': 1, 'phone': '010-1552-8392',
     'stage': 'contact', 'status': 'active', 'color': '', 'tags': [],
     'memo': '이직 준비 중이라 8월 이후 다시 연락 달라고 함.',
     'm_ago': 3, 'day': 13, 'lc_days': 9, 'fa': None, 'fav': False, 'pin': False},
    {'name': '백하은', 'birth': '1999.12.30', 'gender': 2, 'phone': '010-1575-2719',
     'stage': 'db', 'status': 'active', 'color': 'yellow', 'tags': ['신규'],
     'memo': '첫 직장 입사. 부모님이 들어준 보험 정리부터 시작.',
     'm_ago': 3, 'day': 22, 'lc_days': 4, 'fa': None, 'fav': False, 'pin': False},
    {'name': '노윤재', 'birth': '1983.08.17', 'gender': 1, 'phone': '010-1598-6134',
     'stage': 'meeting', 'status': 'active', 'color': 'blue', 'tags': [],
     'memo': '증권 3건 등록 완료. 다음 미팅에서 보장 한눈표 설명 예정.',
     'm_ago': 3, 'day': 3, 'lc_days': 2, 'fa': (0, 15), 'fav': False, 'pin': False},
    {'name': '심서우', 'birth': '1992.03.08', 'gender': 2, 'phone': '010-1621-4582',
     'stage': 'contact', 'status': 'hold', 'color': '', 'tags': [],
     'memo': '해외 출장 중. 9월 귀국 후 다시 연락하기로.',
     'm_ago': 3, 'day': 27, 'lc_days': 32, 'fa': None, 'fav': False, 'pin': False},
    # ── 4달 전(4) ────────────────────────────────────────────────────
    {'name': '구자윤', 'birth': '1988.06.05', 'gender': 1, 'phone': '010-1644-2967',
     'stage': 'contract', 'status': 'active', 'color': 'green', 'tags': [],
     'memo': '정기보험 유지 중. 연말 보장 리뷰 약속.',
     'm_ago': 4, 'day': 6, 'lc_days': 4, 'fa': (3, 18), 'fav': False, 'pin': False},
    {'name': '남주하', 'birth': '1996.10.02', 'gender': 2, 'phone': '010-1667-8137',
     'stage': 'contract', 'status': 'active', 'color': '', 'tags': [],
     'memo': '어린이보험(첫째) 청약 완료. 둘째 출산 예정, 11월 태아보험 상담.',
     'm_ago': 4, 'day': 15, 'lc_days': 6, 'fa': (1, 6), 'fav': False, 'pin': False},
    {'name': '양준서', 'birth': '1979.11.11', 'gender': 1, 'phone': '010-1690-3459',
     'stage': 'meeting', 'status': 'active', 'color': 'red', 'tags': ['갱신 예정'],
     'memo': '10월 운전자보험 만기. 만기 전 리모델링 상담 진행 중.',
     'm_ago': 4, 'day': 21, 'lc_days': 6, 'fa': (2, 2), 'fav': False, 'pin': False},
    {'name': '위성진', 'birth': '1994.01.26', 'gender': 1, 'phone': '010-1713-1524',
     'stage': 'db', 'status': 'active', 'color': '', 'tags': [],
     'memo': '헬스장 지인. 상해보험 관심만 있고 아직 구체 계획 없음.',
     'm_ago': 4, 'day': 28, 'lc_days': 13, 'fa': None, 'fav': False, 'pin': False},
    # ── 5달 전(4) + 6달 전(3) — 목록·트렌드 볼륨용 ───────────────────
    {'name': '엄태리', 'birth': '1990.04.18', 'gender': 2, 'phone': '010-1736-9268',
     'stage': 'contract', 'status': 'active', 'color': 'blue', 'tags': [],
     'memo': '암보험 유지. 매월 첫째 주 안부 문자 발송 중.',
     'm_ago': 5, 'day': 9, 'lc_days': 5, 'fa': (4, 25), 'fav': False, 'pin': False},
    {'name': '도현우', 'birth': '1987.07.15', 'gender': 1, 'phone': '010-1759-6215',
     'stage': 'meeting', 'status': 'active', 'color': '', 'tags': [],
     'memo': '재상담 요청. 회사 단체보험과 중복 정리 원함.',
     'm_ago': 5, 'day': 16, 'lc_days': 3, 'fa': (0, 15), 'fav': False, 'pin': False},
    {'name': '석주원', 'birth': '1982.09.28', 'gender': 1, 'phone': '010-1782-1873',
     'stage': 'meeting', 'status': 'active', 'color': 'yellow', 'tags': [],
     'memo': '보장 한눈표 공유 완료. 아내분 증권도 등록 예정.',
     'm_ago': 5, 'day': 23, 'lc_days': 2, 'fa': (0, 21), 'fav': False, 'pin': False},
    {'name': '진예솔', 'birth': '1998.02.20', 'gender': 2, 'phone': '010-1805-3596',
     'stage': 'meeting', 'status': 'active', 'color': 'green', 'tags': ['신규'],
     'memo': '치아보험 가입. 다음 달 실손 전환 상담 예정.',
     'm_ago': 5, 'day': 27, 'lc_days': 1, 'fa': (0, 18), 'fav': False, 'pin': False},
    {'name': '표진우', 'birth': '1984.12.12', 'gender': 1, 'phone': '010-1828-6748',
     'stage': 'contract', 'status': 'active', 'color': '', 'tags': [],
     'memo': '종합건강보험 유지. 소개로 문지호님 연결해 줌.',
     'm_ago': 6, 'day': 10, 'lc_days': 5, 'fa': (5, 22), 'fav': False, 'pin': False},
    {'name': '하은채', 'birth': '1991.05.07', 'gender': 2, 'phone': '010-1851-9351',
     'stage': 'contact', 'status': 'dormant', 'color': '', 'tags': [],
     'memo': '연락 두절. 분기별 안부 문자만 유지.',
     'm_ago': 6, 'day': 18, 'lc_days': 55, 'fa': None, 'fav': False, 'pin': False},
    {'name': '곽민서', 'birth': '1995.11.03', 'gender': 2, 'phone': '010-1874-5912',
     'stage': 'db', 'status': 'active', 'color': '', 'tags': [],
     'memo': '동창 모임에서 만남. 보험 리모델링에 관심.',
     'm_ago': 6, 'day': 25, 'lc_days': 5, 'fa': None, 'fav': False, 'pin': False},
]

# ── 월별 등록 증권(대시보드 '월별 보험료 추이' 완만한 우상향) ─────────────
#   (고객명, 보험 이름, 월납보험료(원), m_ago, day, 납입회차)
#   이번 달 합계 ≈ 102만 / 지난달 89만 / … / 5달 전 38.5만.
#   납입회차 = 유지현황(회차 타이머) 도넛 분산: 26+ = 유지 안정 다수,
#   1~3 = 신규 계약 일부, 12·24 = 13/25회차 임박 각 1건(기능 시연).
#   계약일은 회차와 모순 없게 등록월에서 (회차-1)개월 역산해 자동 계산.
INSURANCES = [
    # 이번 달 (김인파 2건은 포트폴리오에서 별도 생성: 89,000 + 14,900)
    ('최인파', '치매간병보험',   187_000, 0, 8,  2),
    ('이수민', '종합건강보험',   132_000, 0, 6,  1),
    ('진예솔', '치아보험',        48_000, 0, 20, 3),
    ('도현우', '암보험',         178_000, 0, 17, 1),
    ('강태윤', '운전자보험',      13_900, 0, 10, 1),
    ('한승우', '정기보험',        56_200, 0, 12, 26),
    ('석주원', '종합건강보험',   145_000, 0, 22, 38),
    ('진예솔', '실손의료비보험',  15_900, 0, 20, 1),
    ('남주하', '어린이보험',      75_000, 0, 15, 2),
    ('노윤재', '상해보험',        64_100, 0, 16, 30),
    # 지난달 (합 89만)
    ('오세아', '치매간병보험',   215_000, 1, 9,  1),
    ('정다은', '암보험',         168_000, 1, 14, 2),
    ('한승우', '정기보험',        95_000, 1, 27, 24),
    ('남주하', '어린이보험',     124_000, 1, 7,  28),
    ('구자윤', '종합건강보험',   142_000, 1, 19, 45),
    ('엄태리', '간편건강보험',   146_000, 1, 24, 33),
    # 2달 전 (합 74만)
    ('이수민', '실손의료비보험',  15_900, 2, 5,  26),
    ('강태윤', '종합건강보험',   125_000, 2, 12, 12),
    ('김도현', '운전자보험',      12_100, 2, 20, 40),
    ('양준서', '암보험',         178_000, 2, 8,  31),
    ('표진우', '간편건강보험',   152_000, 2, 15, 52),
    ('엄태리', '치아보험',        43_000, 2, 22, 29),
    ('위성진', '상해보험',        99_000, 2, 26, 3),
    ('심서우', '실손의료비보험',  14_900, 2, 3,  64),
    ('곽민서', '운전자보험',      13_500, 2, 17, 36),
    ('백하은', '치아보험',        41_600, 2, 28, 27),
    ('하은채', '상해보험',        45_000, 2, 9,  44),
    # 3달 전 (합 61만)
    ('최인파', '종합건강보험',   158_000, 3, 10, 39),
    ('구자윤', '정기보험',        89_000, 3, 16, 28),
    ('노윤재', '암보험',         142_000, 3, 5,  31),
    ('송민재', '운전자보험',      12_800, 3, 21, 50),
    ('표진우', '치아보험',        47_200, 3, 25, 33),
    ('엄태리', '실손의료비보험',  15_000, 3, 12, 61),
    ('양준서', '상해보험',       146_000, 3, 18, 26),
    # 4달 전 (합 52만)
    ('엄태리', '암보험',         156_000, 4, 8,  30),
    ('표진우', '종합건강보험',   132_000, 4, 14, 42),
    ('구자윤', '운전자보험',      11_900, 4, 22, 27),
    ('하은채', '치아보험',        51_000, 4, 19, 38),
    ('곽민서', '간편건강보험',    93_000, 4, 26, 29),
    ('위성진', '실손의료비보험',  14_600, 4, 11, 55),
    ('남주하', '상해보험',        61_500, 4, 27, 34),
    # 5달 전 (합 38.5만)
    ('표진우', '정기보험',       145_000, 5, 12, 46),
    ('하은채', '암보험',          65_000, 5, 18, 28),
    ('곽민서', '어린이보험',      78_000, 5, 24, 35),
    ('엄태리', '운전자보험',      97_000, 5, 7,  31),
]

# ── 김인파 보장 포트폴리오 (보장 한눈표 + 여러 증권 비교 화면 주인공) ─────
#   담보명 = seed_normalization [표준] 트리의 실제 leaf 이름과 정확히 일치해야 한다.
#   (담보명, 보장금액(원), 케이스 월보험료(원), payment_period_type 1=비갱신/3=갱신, 원문 담보명)
PORTFOLIO_MAIN = {
    'name': '종합건강보험', 'monthly': 89_000, 'contract': '2019.05.20',
    'expiry': '2079.05.20',
    'coverages': [
        ('일반사망',           50_000_000, 18_000, 1, '일반사망보험금'),
        ('상해후유장해',      100_000_000,  9_500, 1, '상해후유장해(3~100%)'),
        ('일반암진단비',       30_000_000, 21_000, 1, '암진단비(유사암제외)'),
        ('유사암진단비',        6_000_000,  3_200, 1, '유사암진단비'),
        ('뇌졸중진단비',       20_000_000, 11_800, 1, '뇌졸중진단비'),
        ('급성심근경색진단비',  20_000_000,  8_900, 1, '급성심근경색증진단비'),
        ('질병수술비',            3_000_000,  4_600, 1, '질병수술비(1~5종)'),
        ('상해수술비',            3_000_000,  3_100, 1, '상해수술비'),
        ('질병입원일당',              30_000,  5_400, 1, '질병입원일당(1일이상)'),
        ('상해입원일당',              30_000,  3_500, 1, '상해입원일당'),
    ],
}
PORTFOLIO_SILSON = {
    'name': '실손의료비보험', 'monthly': 14_900, 'contract': '2021.03.15',
    'expiry': '2121.03.15',
    'coverages': [
        ('실손입원급여',       50_000_000,  7_800, 3, '상해질병입원의료비(급여)'),
        ('실손통원급여',           250_000,  3_400, 3, '상해질병통원의료비(급여)'),
        ('실손비급여주사',        2_500_000,  1_900, 3, '비급여주사료'),
        ('실손비급여도수치료',    3_500_000,  1_800, 3, '비급여도수치료·체외충격파'),
    ],
}
PORTFOLIO_PROPOSAL = {
    'name': '새 보장 설계안', 'monthly': 132_000, 'contract': '2026.08.01',
    'expiry': '2086.08.01',
    'coverages': [
        ('일반사망',          100_000_000, 24_000, 1, '일반사망보험금'),
        ('일반암진단비',       50_000_000, 32_000, 1, '암진단비(유사암제외)'),
        ('유사암진단비',       20_000_000,  8_100, 1, '유사암진단비'),
        ('뇌졸중진단비',       30_000_000, 16_500, 1, '뇌졸중진단비'),
        ('뇌출혈진단비',       30_000_000,  9_200, 1, '뇌출혈진단비'),
        ('급성심근경색진단비',  30_000_000, 12_400, 1, '급성심근경색증진단비'),
        ('질병입원일당',              50_000,  8_300, 1, '질병입원일당(1일이상)'),
        ('허혈성심장질환진단비', 20_000_000, 10_500, 1, '허혈성심장질환진단비'),
    ],
}

# ── 김인파(1991년생 30대 남) 기준 PlannerBaseline — 넉넉/적정/부족 3색이 섞이게 ──
#   (coverage_key=[표준] leaf 이름, min원, max원)
#   보유: 일반사망 5천(부족<1억), 상해후유장해 1억(적정), 일반암 3천(적정),
#         유사암 600만(부족<1천), 뇌졸중 2천(적정), 뇌출혈 0(부족),
#         급성심근경색 2천(넉넉>1.5천), 질병수술비 300만(넉넉>200만),
#         질병입원일당 3만(적정), 실손입원급여 5천(적정).
BASELINES = [
    ('일반사망',           100_000_000, 300_000_000),
    ('상해후유장해',        50_000_000, 200_000_000),
    ('일반암진단비',        30_000_000,  50_000_000),
    ('유사암진단비',        10_000_000,  20_000_000),
    ('뇌졸중진단비',        10_000_000,  30_000_000),
    ('급성심근경색진단비',    5_000_000,  15_000_000),
    ('질병수술비',              500_000,   2_000_000),
    ('상해수술비',              500_000,   3_000_000),
    ('질병입원일당',             20_000,      50_000),
    ('상해입원일당',             20_000,      50_000),
    ('실손입원급여',        30_000_000, 100_000_000),
]


class Command(BaseCommand):
    help = '랜딩 스크린샷 촬영용 데이터 시드 (수동 전용, seed_normalization 선행 필요).'

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write('=== seed_capture 시작 (촬영 전용) ===')

        if not AnalysisCategory.objects.filter(
                name__startswith=STD_MARKER).exists():
            raise CommandError(
                '실제 표준 트리가 없습니다. 먼저 `python manage.py seed_normalization` '
                '을 실행하세요.')

        self._cleanup()
        planner = self._seed_planner()
        catalog = self._seed_catalog()
        by_name = self._seed_customers(planner)
        self._seed_insurances(by_name)
        self._seed_portfolios(by_name['김인파'], catalog)
        self._seed_baselines(planner)
        self._seed_goals(planner)
        self._seed_schedule(planner, by_name)
        self._seed_booking(planner, by_name)
        self._seed_notifications(planner, by_name)

        self.stdout.write(self.style.SUCCESS('=== seed_capture 완료 ==='))
        self.stdout.write(f'  로그인: {CAPTURE_PLANNER_EMAIL} / {CAPTURE_PLANNER_PASSWORD}')
        self.stdout.write(f'  김인파 고객 id: {by_name["김인파"].id} (보장/비교 촬영용)')

    # ── 멱등 정리 ────────────────────────────────────────────────────────
    def _cleanup(self):
        User.objects.filter(email=CAPTURE_PLANNER_EMAIL).delete()  # CASCADE 일괄
        InsuranceCategory.objects.filter(
            name__startswith=CAPTURE_CATALOG_TAG).delete()
        Insurance.objects.filter(name__startswith=CAPTURE_CATALOG_TAG).delete()

    # ── 설계사 ───────────────────────────────────────────────────────────
    def _seed_planner(self):
        user = User.objects.create_user(
            email=CAPTURE_PLANNER_EMAIL, password=CAPTURE_PLANNER_PASSWORD)
        user.is_active = True
        user.save(update_fields=['is_active'])
        now = timezone.now()
        Profile.objects.create(
            user=user, name='박도윤',           # 홈 인사말 노출(계정 아이디 노출 방지)
            email_verified_at=now, onboarding_completed_at=now,
            agent_type=Profile.AGENT_NONLIFE,
            affiliation='한빛금융서비스', title='팀장',
            affiliation_type=Profile.AFFILIATION_GA,
            license_self_declared=True)
        self.stdout.write(f'  [1] 설계사 {user.email}')
        return user

    # ── 카탈로그: [표준] leaf 와 1:1 연결(공유 트리는 절대 변경 안 함) ────
    def _seed_catalog(self):
        needed = {c[0] for c in (PORTFOLIO_MAIN['coverages']
                                 + PORTFOLIO_SILSON['coverages']
                                 + PORTFOLIO_PROPOSAL['coverages'])}
        std_by_name = {
            d.name: d for d in AnalysisDetail.objects.filter(
                sub_category__category__name__startswith=STD_MARKER,
                name__in=needed)}
        missing = needed - set(std_by_name)
        if missing:
            raise CommandError(f'[표준] 트리에 없는 담보명: {missing}')

        icat = InsuranceCategory.objects.create(
            insurance_type=2, name=f'{CAPTURE_CATALOG_TAG}촬영용', order=999)
        isub = InsuranceSubCategory.objects.create(
            insurance_type=2, category=icat, name='보장', order=1)
        catalog = {}
        for order, (name, std) in enumerate(sorted(std_by_name.items()), start=1):
            idet = InsuranceDetail.objects.create(
                sub_category=isub, name=name[:20], order=order,
                chart_based_amount=std.chart_based_amount)
            idet.analysis_detail.add(std)
            catalog[name] = idet
        self.stdout.write(f'  [2] 카탈로그 {len(catalog)}개 ↔ [표준] leaf 연결')
        return catalog

    # ── 날짜 헬퍼 ────────────────────────────────────────────────────────
    @staticmethod
    def _month_shift(base, months_ago):
        y, m = base.year, base.month
        m -= months_ago
        while m <= 0:
            m += 12
            y -= 1
        return y, m

    def _kst_dt(self, m_ago, day, hour=11, minute=0):
        """m_ago 달 전 day 일의 KST aware datetime (저장은 UTC)."""
        today = timezone.localdate()
        y, m = self._month_shift(today, m_ago)
        # 미래 방지: 이번 달(m_ago=0)인데 day 가 오늘보다 뒤면 오늘로 클램프
        if m_ago == 0:
            day = min(day, today.day)
        day = min(day, 28)
        naive = datetime.datetime(y, m, day, hour, minute)
        return timezone.make_aware(naive)

    # ── 고객 30명 ────────────────────────────────────────────────────────
    def _seed_customers(self, planner):
        now = timezone.now()
        tag_cache = {}
        by_name = {}
        for spec in CUSTOMERS:
            cust = Customer.objects.create(
                owner=planner, name=spec['name'], birth_day=spec['birth'],
                gender=spec['gender'], mobile_phone_number=spec['phone'],
                memo=spec['memo'], color=spec['color'],
                sales_stage=spec['stage'], status=spec['status'],
                is_favorite=spec['fav'], is_pinned=spec['pin'],
                is_agree_term=True)
            for label in spec['tags']:
                tag = tag_cache.get(label)
                if tag is None:
                    tag, _ = CustomerTag.objects.get_or_create(
                        owner=planner, label=label, defaults={'color': ''})
                    tag_cache[label] = tag
                cust.tags.add(tag)
            created = self._kst_dt(spec['m_ago'], spec['day'], hour=10)
            fa_at = (self._kst_dt(*spec['fa'], hour=14)
                     if spec['fa'] else None)
            Customer.objects.filter(pk=cust.pk).update(
                created_at=created,
                fa_reached_at=fa_at,   # save() 훅이 찍은 now 를 의도값으로 교체
                last_contacted_at=now - datetime.timedelta(
                    days=spec['lc_days'], hours=3))
            by_name[spec['name']] = cust
        self.stdout.write(f'  [3] 고객 {len(by_name)}명')
        return by_name

    # ── 월별 등록 증권(추이 차트 + 이번 달 보험료) ───────────────────────
    def _seed_insurances(self, by_name):
        now = timezone.now()
        n = 0
        for cust_name, ins_name, monthly, m_ago, day, round_no in INSURANCES:
            cust = by_name[cust_name]
            # 계약일 = 등록월에서 (회차-1)개월 역산 → 회차와 계약일이 모순 없다.
            cy, cm = self._month_shift(
                timezone.localdate(), m_ago + round_no - 1)
            ci = CustomerInsurance.objects.create(
                customer=cust, insurance_type=2, name=ins_name,
                portfolio_type=1, payment_period_type=1, payment_period=20,
                warranty_period_type=1, warranty_period=100,
                contract_date=f'{cy}.{cm:02d}.{min(day, 28):02d}',
                expiry_date='2086.01.01',
                monthly_premiums=monthly, monthly_assurance_premium=monthly,
                insured_name=cust.name, contractor_name=cust.name,
                is_same_insured=True, current_payment_period=round_no,
                # 비교/분석 선택 가능 상태(FE selectable 조건)
                review_status='confirmed', analysis_included=True,
                confirmed_at=now, confirmation_source='manual')
            CustomerInsurance.objects.filter(pk=ci.pk).update(
                created_at=self._kst_dt(m_ago, day, hour=15))
            n += 1
        self.stdout.write(f'  [4] 등록 증권 {n}건 (최근 6개월 우상향)')

    # ── 김인파 포트폴리오(보유 2건 + 제안 1건) ───────────────────────────
    def _seed_portfolios(self, customer, catalog):
        now = timezone.now()
        # 국외이전 동의 완료 상태(헤더 '동의 전' 문구 대신 완료 상태로 촬영)
        Customer.objects.filter(pk=customer.pk).update(
            consent_overseas_at=now - datetime.timedelta(days=14))
        for spec, ptype, m_ago, day, round_no in (
                (PORTFOLIO_MAIN, 1, 0, 3, 87),      # 2019.05 계약 ≈ 87회차
                (PORTFOLIO_SILSON, 1, 0, 3, 64),    # 2021.03 계약 ≈ 64회차
                (PORTFOLIO_PROPOSAL, 2, 0, 12, None)):
            ci = CustomerInsurance.objects.create(
                customer=customer, insurance_type=2, name=spec['name'],
                portfolio_type=ptype,
                payment_period_type=1, payment_period=20,
                warranty_period_type=1, warranty_period=100,
                contract_date=spec['contract'], expiry_date=spec['expiry'],
                monthly_premiums=spec['monthly'],
                monthly_assurance_premium=spec['monthly'],
                insured_name=customer.name, contractor_name=customer.name,
                is_same_insured=True,
                current_payment_period=round_no,
                review_status='confirmed', analysis_included=True,
                confirmed_at=now, confirmation_source='manual')
            for name, amount, prem, pp_type, raw in spec['coverages']:
                CustomerInsuranceDetail.objects.create(
                    insurance=ci, detail=catalog[name], raw_name=raw,
                    assurance_amount=amount, premium=prem,
                    payment_period_type=pp_type,
                    payment_period=20 if pp_type == 1 else 1,
                    warranty_period_type=1, warranty_period='100')
            ci.set_renewal_month()
            ci.calculate()
            ci.save()
            CustomerInsurance.objects.filter(pk=ci.pk).update(
                created_at=self._kst_dt(m_ago, day, hour=16))
        self.stdout.write('  [5] 김인파 포트폴리오: 보유 2건 + 제안 1건')

    # ── 기준(넉넉/적정/부족 3색) ─────────────────────────────────────────
    def _seed_baselines(self, planner):
        for key, lo, hi in BASELINES:
            PlannerBaseline.objects.create(
                owner=planner, coverage_key=key,
                product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
                age_band='30s', gender=1,
                recommend_min=lo, recommend_max=hi, unit=2,
                baseline_source='planner', is_active=True)
        self.stdout.write(f'  [6] 기준 {len(BASELINES)}개 (30대 남)')

    # ── 월 목표(이번 달 + 지난 5개월) ────────────────────────────────────
    def _seed_goals(self, planner):
        today = timezone.localdate()
        # target_premium 은 전 월 150만 고정: 추이 차트의 '목표' 점선이 6개월 평균이라
        # 월마다 다르면 목표 카드(150만)와 숫자가 어긋나 보인다(검증 워크플로우 지적).
        targets = [(0, 10, 1_500_000), (1, 10, 1_500_000), (2, 8, 1_500_000),
                   (3, 8, 1_500_000), (4, 6, 1_500_000), (5, 6, 1_500_000)]
        for m_ago, meetings, premium in targets:
            y, m = self._month_shift(today, m_ago)
            MonthlyGoal.objects.create(
                owner=planner, year_month=f'{y:04d}-{m:02d}',
                target_meetings=meetings, target_premium=premium)
        self.stdout.write('  [7] 월 목표 6개월치')

    # ── 일정(이번 달 5분류 골고루 + 오늘 3건) ────────────────────────────
    def _seed_schedule(self, planner, by_name):
        today = timezone.localdate()

        def ev(day_offset_or_day, hour, minute, title, category,
               cust=None, kind=ScheduleItem.KIND_EVENT, this_month_day=None):
            if this_month_day is not None:
                d = today.replace(day=min(this_month_day, 28))
            else:
                d = today + datetime.timedelta(days=day_offset_or_day)
            start = timezone.make_aware(
                datetime.datetime(d.year, d.month, d.day, hour, minute))
            ScheduleItem.objects.create(
                owner=planner, kind=kind, category=category, title=title,
                customer=by_name.get(cust) if cust else None,
                start_at=start,
                end_at=start + datetime.timedelta(hours=1))

        # 오늘 3건 (대시보드 '오늘의 일정' 카드)
        ev(0, 10, 30, '김인파님 보장 상담', ScheduleItem.CAT_MEETING, '김인파')
        ev(0, 14, 0, '팀 주간 회의', ScheduleItem.CAT_TASK)
        ev(0, 16, 30, '정다은님 설계안 전달', ScheduleItem.CAT_MEETING, '정다은')
        # 이번 달 과거·미래 (달력을 채우는 용도)
        ev(None, 9, 30, '이수민님 첫 상담', ScheduleItem.CAT_MEETING, '이수민',
           this_month_day=2)
        ev(None, 11, 0, '최인파님 청약 서류 정리', ScheduleItem.CAT_MEETING,
           '최인파', this_month_day=7)
        ev(None, 15, 0, '보수교육 수강', ScheduleItem.CAT_TASK,
           this_month_day=9)
        ev(None, 18, 30, '도현우님 저녁 상담', ScheduleItem.CAT_MEETING,
           '도현우', this_month_day=15)
        ev(None, 10, 0, '오세아님 화재보험 만기 안내', ScheduleItem.CAT_RENEWAL,
           '오세아', this_month_day=17)
        ev(None, 13, 30, '석주원님 증권 등록', ScheduleItem.CAT_MEETING,
           '석주원', this_month_day=21)
        ev(2, 10, 0, '진예솔님 실손 전환 상담', ScheduleItem.CAT_MEETING,
           '진예솔')
        ev(4, 14, 0, '김도현님 실손 갱신 상담', ScheduleItem.CAT_RENEWAL,
           '김도현')
        ev(6, 15, 30, '월말 실적 정리', ScheduleItem.CAT_TASK)
        # 생일(매년 반복, 이번 달 날짜)
        for name, md_day in (('이수민', 28), ('강태윤', 8)):
            ScheduleItem.objects.create(
                owner=planner, kind=ScheduleItem.KIND_EVENT,
                category=ScheduleItem.CAT_ANNIVERSARY,
                title=f'{name}님 생일', customer=by_name[name],
                anniversary_md=f'{today.month:02d}-{md_day:02d}',
                all_day=True)
        # 할 일
        due = timezone.make_aware(datetime.datetime(
            today.year, today.month, min(today.day + 1, 28), 12, 0))
        ScheduleItem.objects.create(
            owner=planner, kind=ScheduleItem.KIND_TODO,
            category=ScheduleItem.CAT_TASK,
            title='김인파님 새 설계안 제안서 준비', customer=by_name['김인파'],
            start_at=due)
        ScheduleItem.objects.create(
            owner=planner, kind=ScheduleItem.KIND_TODO,
            category=ScheduleItem.CAT_ETC,
            title='판촉물(달력) 주문 수량 확정', start_at=due)
        self.stdout.write('  [8] 일정: 이번 달 15건 + 생일 2 + 할일 2')

    # ── 예약(가용시간 + 대기 1건 + 확정 1건) ─────────────────────────────
    def _seed_booking(self, planner, by_name):
        for weekday in range(5):   # 월~금 10:00-18:00
            WorkHour.objects.create(
                owner=planner, weekday=weekday,
                start_time=datetime.time(10, 0), end_time=datetime.time(18, 0))
        today = timezone.localdate()

        def meet_dt(days, hour):
            d = today + datetime.timedelta(days=days)
            return timezone.make_aware(
                datetime.datetime(d.year, d.month, d.day, hour, 0))

        pending = Meeting.objects.create(
            owner=planner, customer=by_name['윤서아'],
            start_at=meet_dt(2, 14), duration_min=60,
            method=Meeting.METHOD_IN_PERSON,
            customer_note='주말이 아니면 오후 2시 이후가 좋아요.',
            status=Meeting.STATUS_PENDING)
        Meeting.objects.create(
            owner=planner, customer=by_name['박준혁'],
            start_at=meet_dt(1, 11), duration_min=60,
            method=Meeting.METHOD_IN_PERSON,
            location_detail='강남역 2번 출구 카페',
            status=Meeting.STATUS_CONFIRMED)
        self.stdout.write('  [9] 예약: 가용시간 월~금 + 대기 1 + 확정 1')
        return pending

    # ── 알림(종 배지 — 미읽음 3건) ──────────────────────────────────────
    def _seed_notifications(self, planner, by_name):
        today = timezone.localdate()
        pending_meeting = Meeting.objects.filter(
            owner=planner, status=Meeting.STATUS_PENDING).first()
        Notification.objects.create(
            owner=planner, notif_type=NotifType.MEETING_BOOKED,
            title='윤서아님이 상담을 신청했어요',
            body='모레 오후 2시 대면 상담 요청이 도착했어요. 수락하면 일정에 등록됩니다.',
            customer=by_name['윤서아'], meeting=pending_meeting,
            target_date=today + datetime.timedelta(days=2), is_read=False)
        Notification.objects.create(
            owner=planner, notif_type=NotifType.BIRTHDAY_SOON,
            title='이수민님 생일이 다가와요',
            body='나흘 뒤 이수민님 생일이에요. 축하 메시지를 준비해 보세요.',
            customer=by_name['이수민'],
            target_date=today + datetime.timedelta(days=4), is_read=False)
        Notification.objects.create(
            owner=planner, notif_type=NotifType.EXPIRY_SOON,
            title='오세아님 화재보험 만기 안내',
            body='다음 달 만기 예정이에요. 갱신 상담을 미리 잡아 보세요.',
            customer=by_name['오세아'],
            target_date=today + datetime.timedelta(days=24), is_read=False)
        self.stdout.write('  [10] 알림 3건(미읽음)')
