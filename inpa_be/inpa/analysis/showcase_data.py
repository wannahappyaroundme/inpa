"""Internal showcase account specifications made only from fictional data."""

import re
from collections import Counter
from dataclasses import dataclass, fields, is_dataclass
from datetime import date

from django.core.management.base import CommandError


CUSTOMER_COUNT = 50
INSURANCE_COUNT = 80
ANCHOR_CUSTOMER_COUNT = 8
MIN_COVERAGE_COUNT = 160
STAGE_COUNTS = {'db': 14, 'contact': 12, 'meeting': 12, 'contract': 12}
STATUS_COUNTS = {'active': 42, 'hold': 4, 'dormant': 3, 'closed': 1}


@dataclass(frozen=True, slots=True)
class CustomerSpec:
    key: str
    name: str
    birth_date: date
    gender: int
    occupation: str
    phone: str
    source: str
    stage: str
    status: str
    tags: tuple[str, ...]
    memo: str
    family_context: str
    coverage_focus: str


@dataclass(frozen=True, slots=True)
class CoverageSpec:
    name: str
    insured_amount: int
    monthly_premium: int
    renewable: bool


@dataclass(frozen=True, slots=True)
class InsuranceSpec:
    key: str
    customer_key: str
    company_name: str
    product_type: str
    monthly_premium: int
    registered_month_offset: int
    coverages: tuple[CoverageSpec, ...]


# Each row is authored independently and carries no source document or real identity.
_CUSTOMER_ROWS = (
    ('customer-01', '김도윤', '1958-03-12', 1, '퇴직 후 재취업 준비',
     '010-1027-4831', 'introduction', 'db', 'active', ('보장 점검', '가족'),
     '배우자와 함께 보장 내용을 살펴보고 간병 항목을 먼저 확인하기로 함.',
     '배우자와 성인 자녀 2명', '간병과 노후 의료비 중심'),
    ('customer-02', '이서현', '1964-11-25', 2, '의류 매장 운영',
     '010-1148-7052', 'business_card', 'contact', 'active', ('자영업', '건강'),
     '매장 운영 시간을 피해 오전 통화를 선호하며 주요 질병 보장을 궁금해함.',
     '배우자와 함께 거주', '암과 심뇌혈관 보장 중심'),
    ('customer-03', '박지훈', '1971-07-08', 1, '사무 관리직',
     '010-1263-5917', 'event', 'meeting', 'active', ('가족', '상담 예정'),
     '가족 생활비를 고려해 사망과 질병 보장의 균형을 확인하고 있음.',
     '배우자와 대학생 자녀 1명', '가족 생활비와 3대 질병 균형'),
    ('customer-04', '최유진', '1978-01-19', 2, '중학교 교사',
     '010-1384-2469', 'self_diagnosis', 'contract', 'active', ('교육직', '자녀'),
     '자녀 교육 일정에 맞춰 저녁 상담을 선호하며 수술 보장을 비교 중.',
     '배우자와 중학생 자녀 1명', '수술과 입원 보장 균형'),
    ('customer-05', '정현우', '1985-09-03', 1, '소프트웨어 개발자',
     '010-1495-8306', 'direct', 'db', 'active', ('1인 가구', '활동'),
     '주말 활동이 잦아 상해와 운전자 관련 보장을 먼저 살펴보기로 함.',
     '혼자 거주하며 반려동물과 생활', '상해와 운전자 보장 중심'),
    ('customer-06', '한소연', '1991-05-17', 2, '제품 디자이너',
     '010-1572-4185', 'introduction', 'contact', 'active', ('직장인', '의료비'),
     '기존 의료비 보장과 질병 보장의 겹치는 항목을 정리하고 싶어 함.',
     '결혼을 준비 중인 1인 가구', '의료비와 여성 건강 보장 중심'),
    ('customer-07', '조민재', '1997-12-06', 1, '화물차 운전원',
     '010-1639-7524', 'business_card', 'meeting', 'active', ('운전직', '상해'),
     '근무 중 이동이 많아 상해와 운전자 보장 범위를 자세히 확인 중.',
     '배우자와 영유아 자녀 1명', '운전 중 상해와 가족 생활비 중심'),
    ('customer-08', '윤하늘', '2001-08-22', 2, '음식점 운영 보조',
     '010-1756-3098', 'event', 'contract', 'active', ('사회초년생', '기초 보장'),
     '부모님이 준비한 보장을 정리하고 부담이 낮은 범위부터 구성함.',
     '부모님과 함께 거주', '기초 질병과 의료비 보장 중심'),
    ('customer-09', '강준서', '1988-04-11', 1, '기계 설비 기사',
     '010-1813-6472', 'direct', 'db', 'active', ('현장직',),
     '근무 중 다칠 때 필요한 항목을 우선 확인해 보기로 함.',
     '배우자와 자녀 1명', '상해와 수술 보장'),
    ('customer-10', '오다은', '1993-10-29', 2, '도서관 사서',
     '010-1924-5163', 'self_diagnosis', 'db', 'hold', ('재연락',),
     '일정이 정리되는 다음 달 초에 다시 통화하기로 함.',
     '1인 가구', '의료비 보장'),
    ('customer-11', '서지호', '1982-06-14', 1, '가구 제작자',
     '010-1041-9287', 'introduction', 'db', 'active', ('소개',),
     '기존 보장 목록을 먼저 정리한 뒤 상담 일정을 잡기로 함.',
     '배우자와 자녀 2명', '상해와 가족 보장'),
    ('customer-12', '신채원', '1996-02-27', 2, '온라인 판매 운영',
     '010-1162-3745', 'business_card', 'db', 'active', ('자영업',),
     '업무 시간 변동이 커서 메시지로 일정을 조율하고 있음.',
     '배우자와 함께 거주', '질병과 입원 보장'),
    ('customer-13', '배성민', '1975-12-09', 1, '건물 관리원',
     '010-1285-6409', 'event', 'db', 'active', ('건강 점검',),
     '정기 건강검진 전에 보장 내용을 한 번 살펴보고 싶어 함.',
     '배우자와 성인 자녀 1명', '3대 질병 보장'),
    ('customer-14', '문예린', '1989-08-31', 2, '학원 강사',
     '010-1397-2058', 'direct', 'db', 'active', ('교육직',),
     '퇴근 뒤 통화를 선호하며 수술과 입원 항목을 확인 중.',
     '1인 가구', '수술과 입원 보장'),
    ('customer-15', '송태윤', '1994-03-16', 1, '영상 편집자',
     '010-1514-8792', 'self_diagnosis', 'db', 'active', ('온라인 문의',),
     '등록된 증권을 한 화면에서 먼저 확인해 보기로 함.',
     '배우자와 함께 거주', '의료비와 질병 보장'),
    ('customer-16', '임수아', '1980-09-24', 2, '꽃집 운영',
     '010-1647-5321', 'introduction', 'db', 'active', ('자영업', '가족'),
     '가족의 보장 내용을 차례로 정리하기로 함.',
     '배우자와 자녀 2명', '가족 질병 보장'),
    ('customer-17', '홍재원', '1986-05-06', 1, '전기 기술자',
     '010-1768-9143', 'business_card', 'db', 'active', ('기술직',),
     '현장 업무에 맞는 상해 보장 범위를 확인하고 있음.',
     '배우자와 자녀 1명', '상해와 후유장해 보장'),
    ('customer-18', '구나연', '1999-01-28', 2, '반려동물 미용사',
     '010-1889-4670', 'event', 'db', 'dormant', ('분기 연락',),
     '당분간 기존 보장을 유지하고 분기마다 안부를 나누기로 함.',
     '1인 가구', '기초 의료비 보장'),
    ('customer-19', '남승우', '1969-07-21', 1, '인쇄소 운영',
     '010-1956-7318', 'direct', 'db', 'active', ('자영업', '노후'),
     '배우자와 노후 의료비 준비 범위를 함께 확인하고 있음.',
     '배우자와 함께 거주', '노후 의료비와 간병 보장'),
    ('customer-20', '양지민', '1992-11-13', 2, '세무 사무원',
     '010-1073-6854', 'self_diagnosis', 'db', 'active', ('직장인',),
     '현재 납입액과 보장 구성을 먼저 정리해 달라고 요청함.',
     '배우자와 자녀 1명', '질병과 생활비 보장'),
    ('customer-21', '백도현', '1984-02-18', 1, '물류 관리직',
     '010-1194-3507', 'introduction', 'contact', 'active', ('소개',),
     '주말 오전에 보장 목록을 보며 통화하기로 함.',
     '배우자와 자녀 2명', '상해와 질병 보장'),
    ('customer-22', '노서아', '1995-06-30', 2, '편집 기획자',
     '010-1326-8041', 'business_card', 'contact', 'active', ('직장인',),
     '의료비 보장의 갱신 항목을 중심으로 살펴보고 있음.',
     '1인 가구', '의료비 보장'),
    ('customer-23', '심준혁', '1977-10-07', 1, '주방 설비 운영',
     '010-1437-6295', 'event', 'contact', 'active', ('자영업',),
     '사업 일정에 맞춰 두 번으로 나누어 상담하기로 함.',
     '배우자와 성인 자녀 1명', '3대 질병과 간병 보장'),
    ('customer-24', '안유나', '1987-04-26', 2, '초등학교 교사',
     '010-1558-2704', 'direct', 'contact', 'hold', ('재연락',),
     '학기 일정을 마친 뒤 상담 시간을 다시 정하기로 함.',
     '배우자와 자녀 1명', '수술과 입원 보장'),
    ('customer-25', '류시우', '1990-12-15', 1, '조경 관리사',
     '010-1679-5486', 'self_diagnosis', 'contact', 'active', ('현장직',),
     '상해 보장과 일상생활 배상 항목을 확인 중.',
     '배우자와 함께 거주', '상해와 배상 보장'),
    ('customer-26', '전하린', '1998-07-04', 2, '공연 기획자',
     '010-1791-9362', 'introduction', 'contact', 'active', ('사회초년생',),
     '현재 예산 안에서 기본 보장을 먼저 구성하고 싶어 함.',
     '1인 가구', '기초 질병 보장'),
    ('customer-27', '권민규', '1981-01-23', 1, '자동차 정비사',
     '010-1842-7139', 'business_card', 'contact', 'active', ('기술직',),
     '상해와 운전자 항목을 나누어 비교하고 있음.',
     '배우자와 자녀 2명', '운전자와 상해 보장'),
    ('customer-28', '황예진', '1993-05-12', 2, '식품 연구원',
     '010-1963-4257', 'event', 'contact', 'active', ('연구직',),
     '질병 진단 항목별 차이를 확인한 뒤 다시 통화하기로 함.',
     '배우자와 함께 거주', '질병 진단 보장'),
    ('customer-29', '고성호', '1973-09-28', 1, '택배 영업소 운영',
     '010-1096-8524', 'direct', 'contact', 'dormant', ('분기 연락',),
     '현재 보장을 유지하며 가을에 다시 살펴보기로 함.',
     '배우자와 성인 자녀 2명', '운전자와 간병 보장'),
    ('customer-30', '장수빈', '2000-02-09', 2, '제과사',
     '010-1217-6048', 'self_diagnosis', 'contact', 'active', ('기초 보장',),
     '처음 준비하는 보장이라 용어부터 차근차근 확인하고 있음.',
     '부모님과 함께 거주', '기초 의료비 보장'),
    ('customer-31', '차준영', '1983-11-02', 1, '공장 품질 관리자',
     '010-1348-2975', 'introduction', 'meeting', 'active', ('상담 진행',),
     '보장별 금액을 확인하고 다음 상담에서 우선순위를 정하기로 함.',
     '배우자와 자녀 1명', '질병과 상해 보장'),
    ('customer-32', '주서윤', '1991-03-20', 2, '요가 강사',
     '010-1469-7351', 'business_card', 'meeting', 'active', ('건강 관리',),
     '입원과 수술 보장을 중심으로 상담을 이어가고 있음.',
     '1인 가구', '입원과 수술 보장'),
    ('customer-33', '우태경', '1979-06-17', 1, '냉동 설비 기사',
     '010-1581-4623', 'event', 'meeting', 'active', ('기술직',),
     '기존 증권 두 건의 겹치는 상해 항목을 정리하고 있음.',
     '배우자와 자녀 2명', '상해와 후유장해 보장'),
    ('customer-34', '민가은', '1988-12-24', 2, '출판 편집자',
     '010-1692-8406', 'direct', 'meeting', 'hold', ('일정 조율',),
     '출장을 마치면 다음 상담 날짜를 정하기로 함.',
     '배우자와 함께 거주', '질병과 의료비 보장'),
    ('customer-35', '진현수', '1967-08-05', 1, '농산물 판매 운영',
     '010-1715-3289', 'self_diagnosis', 'meeting', 'active', ('노후',),
     '간병과 주요 질병 항목을 가족과 함께 확인 중.',
     '배우자와 성인 자녀 2명', '간병과 3대 질병 보장'),
    ('customer-36', '표예원', '1996-10-11', 2, '치과 위생사',
     '010-1836-5974', 'introduction', 'meeting', 'active', ('의료직',),
     '의료비와 치아 보장을 나누어 살펴보고 있음.',
     '1인 가구', '의료비와 치아 보장'),
    ('customer-37', '도건우', '1985-01-16', 1, '소방 설비 점검원',
     '010-1947-2608', 'business_card', 'meeting', 'active', ('현장직',),
     '현장 업무 중 상해와 수술 보장 범위를 확인하고 있음.',
     '배우자와 자녀 1명', '상해와 수술 보장'),
    ('customer-38', '마지안', '1994-09-07', 2, '공방 운영',
     '010-1068-9145', 'event', 'meeting', 'dormant', ('분기 연락',),
     '공방 이전을 마친 뒤 보장 점검을 다시 시작하기로 함.',
     '배우자와 함께 거주', '질병과 배상 보장'),
    ('customer-39', '석우진', '1976-04-30', 1, '버스 운전원',
     '010-1189-4732', 'direct', 'meeting', 'active', ('운전직',),
     '운전자와 상해 보장을 한 번에 확인하고 있음.',
     '배우자와 자녀 2명', '운전자와 상해 보장'),
    ('customer-40', '공서희', '1989-07-25', 2, '아동 상담사',
     '010-1312-7860', 'self_diagnosis', 'meeting', 'active', ('상담 진행',),
     '가족 보장을 정리한 뒤 본인 보장을 확인하는 순서로 진행 중.',
     '배우자와 자녀 1명', '가족 질병 보장'),
    ('customer-41', '엄도훈', '1982-02-14', 1, '목공소 운영',
     '010-1423-5096', 'introduction', 'contract', 'active', ('정기 점검',),
     '현재 보장을 유지하며 반기마다 내용을 살펴보기로 함.',
     '배우자와 자녀 2명', '상해와 질병 보장'),
    ('customer-42', '변채린', '1997-06-01', 2, '호텔 서비스 담당',
     '010-1544-8371', 'business_card', 'contract', 'active', ('직장인',),
     '기본 의료비 보장을 마련하고 다음 점검 시기를 정함.',
     '1인 가구', '기초 의료비 보장'),
    ('customer-43', '하민석', '1970-10-18', 1, '세탁소 운영',
     '010-1665-2948', 'event', 'contract', 'active', ('자영업',),
     '주요 질병 보장을 정리하고 배우자 자료도 다음에 보기로 함.',
     '배우자와 함께 거주', '3대 질병 보장'),
    ('customer-44', '곽소희', '1986-03-27', 2, '행정 사무원',
     '010-1786-6514', 'direct', 'contract', 'hold', ('재연락',),
     '가족 일정이 정리되면 정기 점검 날짜를 잡기로 함.',
     '배우자와 자녀 1명', '질병과 수술 보장'),
    ('customer-45', '성재민', '1992-08-08', 1, '사진 스튜디오 운영',
     '010-1897-4250', 'self_diagnosis', 'contract', 'active', ('자영업',),
     '상해와 배상 보장을 확인하고 정기 점검을 이어가기로 함.',
     '배우자와 함께 거주', '상해와 배상 보장'),
    ('customer-46', '나예지', '1999-11-21', 2, '보육 교사',
     '010-1978-9036', 'introduction', 'contract', 'active', ('교육직',),
     '의료비와 질병 보장을 기본 범위로 구성함.',
     '1인 가구', '의료비와 질병 보장'),
    ('customer-47', '원준호', '1974-05-09', 1, '금속 가공 기술자',
     '010-1089-5724', 'business_card', 'contract', 'active', ('정기 확인',),
     '현재 보장을 유지하고 연말에 다시 내용을 확인하기로 함.',
     '배우자와 성인 자녀 1명', '상해와 간병 보장'),
    ('customer-48', '방수연', '1981-09-15', 2, '공인중개사',
     '010-1231-8467', 'event', 'contract', 'active', ('자영업',),
     '질병 진단과 입원 항목을 정리해 둔 상태임.',
     '배우자와 자녀 2명', '질병과 입원 보장'),
    ('customer-49', '추동현', '1987-12-03', 1, '건축 설계사',
     '010-1352-6189', 'direct', 'contract', 'active', ('직장인',),
     '가족 보장과 본인 상해 보장을 나누어 관리하기로 함.',
     '배우자와 자녀 1명', '가족과 상해 보장'),
    ('customer-50', '김유정', '1995-04-23', 2, '공예 강사',
     '010-1473-2905', 'self_diagnosis', 'contract', 'closed', ('관리 종료',),
     '현재 구성으로 정리를 마치고 필요한 때 다시 확인하기로 함.',
     '1인 가구', '기초 질병 보장'),
)

CUSTOMERS = tuple(
    CustomerSpec(
        key=row[0],
        name=row[1],
        birth_date=date.fromisoformat(row[2]),
        gender=row[3],
        occupation=row[4],
        phone=row[5],
        source=row[6],
        stage=row[7],
        status=row[8],
        tags=row[9],
        memo=row[10],
        family_context=row[11],
        coverage_focus=row[12],
    )
    for row in _CUSTOMER_ROWS
)

ANCHOR_CUSTOMER_KEYS = tuple(customer.key for customer in CUSTOMERS[:8])

_COVERAGE_AMOUNTS = {
    '일반사망': 50_000_000,
    '상해사망': 50_000_000,
    '일반암진단': 30_000_000,
    '유사암진단': 5_000_000,
    '고액암진단': 20_000_000,
    '암수술': 5_000_000,
    '항암약물치료': 10_000_000,
    '방사선치료': 10_000_000,
    '표적항암치료': 10_000_000,
    '뇌혈관질환진단': 20_000_000,
    '뇌졸중진단': 10_000_000,
    '뇌혈관수술': 10_000_000,
    '허혈성심장질환진단': 20_000_000,
    '급성심근경색진단': 10_000_000,
    '심혈관수술': 10_000_000,
    '질병수술': 2_000_000,
    '상해수술': 2_000_000,
    '질병입원일당': 50_000,
    '상해입원일당': 50_000,
    '질병후유장해': 30_000_000,
    '상해후유장해': 50_000_000,
    '간병인입원일당': 150_000,
    '간병인지원': 150_000,
    '장기요양진단': 20_000_000,
    '치매진단': 20_000_000,
    '경도치매진단': 10_000_000,
    '중증치매진단': 30_000_000,
    '골절진단': 500_000,
    '깁스치료': 300_000,
    '화상진단': 500_000,
    '일상생활배상': 100_000_000,
    '운전자벌금': 30_000_000,
    '변호사비용': 50_000_000,
    '교통사고처리지원': 200_000_000,
    '의료비입원': 50_000_000,
    '의료비통원': 250_000,
    '비급여주사': 2_500_000,
    '비급여도수치료': 3_500_000,
    '치아임플란트': 1_000_000,
    '치아크라운': 500_000,
}

_ANCHOR_COVERAGE_NAMES = (
    (
        '일반사망', '일반암진단', '유사암진단', '뇌혈관질환진단',
        '허혈성심장질환진단', '질병수술', '질병입원일당',
        '간병인입원일당', '간병인지원', '장기요양진단', '치매진단',
        '경도치매진단', '중증치매진단', '뇌졸중진단',
        '급성심근경색진단', '뇌혈관수술', '심혈관수술',
        '의료비입원', '의료비통원', '비급여주사', '비급여도수치료',
    ),
    (
        '일반사망', '일반암진단', '유사암진단', '고액암진단', '암수술',
        '항암약물치료', '방사선치료', '표적항암치료',
        '뇌혈관질환진단', '뇌졸중진단', '뇌혈관수술',
        '허혈성심장질환진단', '급성심근경색진단', '심혈관수술',
        '질병수술', '질병입원일당', '의료비입원', '의료비통원',
        '치아임플란트', '치아크라운', '일상생활배상',
    ),
    (
        '일반사망', '상해사망', '일반암진단', '유사암진단',
        '뇌혈관질환진단', '허혈성심장질환진단', '질병후유장해',
        '상해후유장해', '질병수술', '상해수술', '질병입원일당',
        '상해입원일당', '암수술', '항암약물치료', '뇌졸중진단',
        '급성심근경색진단', '골절진단', '화상진단', '일상생활배상',
        '의료비입원', '의료비통원',
    ),
    (
        '일반사망', '일반암진단', '유사암진단', '뇌혈관질환진단',
        '허혈성심장질환진단', '암수술', '질병수술', '상해수술',
        '질병입원일당', '상해입원일당', '항암약물치료', '방사선치료',
        '표적항암치료', '골절진단', '깁스치료', '화상진단',
        '일상생활배상', '의료비입원', '의료비통원',
        '치아임플란트', '치아크라운',
    ),
    (
        '상해사망', '상해후유장해', '상해수술', '상해입원일당',
        '골절진단', '깁스치료', '화상진단', '일상생활배상',
        '운전자벌금', '변호사비용', '교통사고처리지원', '일반암진단',
        '유사암진단', '뇌혈관질환진단', '허혈성심장질환진단',
        '질병수술', '의료비입원', '의료비통원', '비급여주사',
        '비급여도수치료', '치아크라운',
    ),
    (
        '의료비입원', '의료비통원', '비급여주사', '비급여도수치료',
        '질병입원일당', '질병수술', '상해입원일당', '상해수술',
        '골절진단', '깁스치료', '화상진단', '일반암진단',
        '유사암진단', '암수술', '항암약물치료', '뇌혈관질환진단',
        '허혈성심장질환진단', '치아임플란트', '치아크라운',
        '일상생활배상', '상해후유장해',
    ),
    (
        '상해사망', '상해후유장해', '상해수술', '상해입원일당',
        '골절진단', '깁스치료', '화상진단', '일상생활배상',
        '운전자벌금', '변호사비용', '교통사고처리지원', '일반사망',
        '일반암진단', '뇌혈관질환진단', '허혈성심장질환진단',
        '질병수술', '뇌졸중진단', '급성심근경색진단',
        '의료비입원', '의료비통원', '질병후유장해',
    ),
    (
        '일반사망', '일반암진단', '유사암진단', '뇌혈관질환진단',
        '허혈성심장질환진단', '질병수술', '질병입원일당',
        '간병인입원일당', '간병인지원', '장기요양진단', '치매진단',
        '경도치매진단', '중증치매진단', '암수술', '항암약물치료',
        '뇌졸중진단', '급성심근경색진단', '의료비입원',
        '의료비통원', '일상생활배상', '상해후유장해',
    ),
)

_ANCHOR_PRODUCT_TYPES = (
    ('종합보장형', '간병보장형', '의료비보장형'),
    ('건강보장형', '질병보장형', '의료비보장형'),
    ('종합보장형', '질병보장형', '상해보장형'),
    ('건강보장형', '질병보장형', '의료비보장형'),
    ('상해보장형', '운전자보장형', '건강보장형'),
    ('의료비보장형', '건강보장형', '질병보장형'),
    ('상해보장형', '운전자보장형', '종합보장형'),
    ('간병보장형', '질병보장형', '건강보장형'),
)

_GENERAL_COVERAGE_NAMES = (
    '일반암진단',
    '유사암진단',
    '뇌혈관질환진단',
    '허혈성심장질환진단',
    '질병수술',
    '상해수술',
    '질병입원일당',
    '상해입원일당',
    '골절진단',
    '깁스치료',
    '상해후유장해',
    '일상생활배상',
    '의료비입원',
    '의료비통원',
    '운전자벌금',
    '간병인지원',
)

_COMPANIES = (
    '생활보장사 A',
    '생활보장사 B',
    '생활보장사 C',
    '생활보장사 D',
)
_PRODUCT_TYPES = (
    '종합보장형',
    '건강보장형',
    '질병보장형',
    '상해보장형',
    '간병보장형',
    '어린이보장형',
    '운전자보장형',
    '의료비보장형',
)
_MONTH_OFFSETS = (
    (5,) * 8
    + (4,) * 10
    + (3,) * 12
    + (2,) * 14
    + (1,) * 17
    + (0,) * 19
)
_POLICY_CUSTOMER_KEYS = (
    tuple(key for key in ANCHOR_CUSTOMER_KEYS for _ in range(3))
    + tuple(
        key
        for key in (customer.key for customer in CUSTOMERS[8:22])
        for _ in range(2)
    )
    + tuple(customer.key for customer in CUSTOMERS[22:])
)


def _coverage_specs(names: tuple[str, ...], seed: int) -> tuple[CoverageSpec, ...]:
    return tuple(
        CoverageSpec(
            name=name,
            insured_amount=_COVERAGE_AMOUNTS[name],
            monthly_premium=1_200 + ((seed + index) % 11) * 530,
            renewable=(seed + index) % 3 == 0,
        )
        for index, name in enumerate(names)
    )


def _build_insurance_specs() -> tuple[InsuranceSpec, ...]:
    customer_occurrences: Counter[str] = Counter()
    policies = []
    for index, (customer_key, month_offset) in enumerate(
        zip(_POLICY_CUSTOMER_KEYS, _MONTH_OFFSETS),
        start=1,
    ):
        policy_position = customer_occurrences[customer_key]
        customer_occurrences[customer_key] += 1
        if customer_key in ANCHOR_CUSTOMER_KEYS:
            anchor_index = ANCHOR_CUSTOMER_KEYS.index(customer_key)
            start = policy_position * 7
            names = _ANCHOR_COVERAGE_NAMES[anchor_index][start:start + 7]
            product_type = _ANCHOR_PRODUCT_TYPES[anchor_index][policy_position]
        else:
            start = (index * 3) % len(_GENERAL_COVERAGE_NAMES)
            names = tuple(
                _GENERAL_COVERAGE_NAMES[
                    (start + coverage_index) % len(_GENERAL_COVERAGE_NAMES)
                ]
                for coverage_index in range(4)
            )
            product_type = _PRODUCT_TYPES[(index - 1) % len(_PRODUCT_TYPES)]

        policies.append(InsuranceSpec(
            key=f'policy-{index:02d}',
            customer_key=customer_key,
            company_name=_COMPANIES[(index - 1) % len(_COMPANIES)],
            product_type=product_type,
            monthly_premium=29_000 + ((index * 7_300) % 128_000),
            registered_month_offset=month_offset,
            coverages=_coverage_specs(names, seed=index),
        ))
    return tuple(policies)


INSURANCES = _build_insurance_specs()

_SHOWCASE_MARKERS = (
    '[demo]',
    '[촬영]',
    '데모',
    '테스트',
    '촬영용',
    'sample',
    'dummy',
)
_REAL_INSURER_OR_RESULT_TERMS = (
    '삼성생명',
    '삼성화재',
    '교보생명',
    '한화생명',
    '현대해상',
    'db손해보험',
    'kb손해보험',
    '메리츠화재',
    '흥국생명',
    '신한라이프',
    '동양생명',
    '미래에셋생명',
    '라이나생명',
    'aia생명',
    'nh농협생명',
    '롯데손해보험',
    '하나손해보험',
    'aig손해보험',
    '업계 1위',
    '최고 실적',
    '수상 실적',
    '계약 달성',
    '매출 달성',
    'mdrt',
)


def _renderable_strings(value):
    if isinstance(value, str):
        yield value
    elif is_dataclass(value):
        for field in fields(value):
            yield from _renderable_strings(getattr(value, field.name))
    elif isinstance(value, tuple):
        for item in value:
            yield from _renderable_strings(item)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CommandError(message)


def validate_showcase_specs() -> None:
    """Raise CommandError before DB writes when counts/names/date rules disagree."""
    _require(CUSTOMER_COUNT == 50, '고객 수 상수를 확인해 주세요.')
    _require(INSURANCE_COUNT == 80, '증권 수 상수를 확인해 주세요.')
    _require(ANCHOR_CUSTOMER_COUNT == 8, '핵심 고객 수를 확인해 주세요.')
    _require(MIN_COVERAGE_COUNT == 160, '최소 담보 수를 확인해 주세요.')
    _require(len(CUSTOMERS) == CUSTOMER_COUNT, '고객 자료 수를 확인해 주세요.')
    _require(len(INSURANCES) == INSURANCE_COUNT, '증권 자료 수를 확인해 주세요.')

    customer_keys = tuple(customer.key for customer in CUSTOMERS)
    names = tuple(customer.name for customer in CUSTOMERS)
    phones = tuple(customer.phone for customer in CUSTOMERS)
    _require(len(set(customer_keys)) == CUSTOMER_COUNT, '고객 키 중복을 확인해 주세요.')
    _require(len(set(names)) == CUSTOMER_COUNT, '고객 이름 중복을 확인해 주세요.')
    _require(len(set(phones)) == CUSTOMER_COUNT, '고객 전화 중복을 확인해 주세요.')
    _require(
        all(re.fullmatch(r'010-1\d{3}-\d{4}', phone) for phone in phones),
        '고객 전화 형식을 확인해 주세요.',
    )
    _require(
        Counter(customer.stage for customer in CUSTOMERS) == STAGE_COUNTS,
        '고객 단계 분포를 확인해 주세요.',
    )
    _require(
        Counter(customer.status for customer in CUSTOMERS) == STATUS_COUNTS,
        '고객 상태 분포를 확인해 주세요.',
    )
    _require(
        all(date(1940, 1, 1) <= customer.birth_date <= date(2005, 12, 31)
            for customer in CUSTOMERS),
        '고객 생년월일 범위를 확인해 주세요.',
    )
    _require(
        all(customer.gender in {1, 2} for customer in CUSTOMERS),
        '고객 성별 값을 확인해 주세요.',
    )
    _require(
        all(customer.tags and customer.memo for customer in CUSTOMERS),
        '고객 태그와 메모를 확인해 주세요.',
    )

    _require(
        len(ANCHOR_CUSTOMER_KEYS) == ANCHOR_CUSTOMER_COUNT
        and set(ANCHOR_CUSTOMER_KEYS).issubset(customer_keys),
        '핵심 고객 구성을 확인해 주세요.',
    )
    anchors = tuple(
        customer for customer in CUSTOMERS
        if customer.key in ANCHOR_CUSTOMER_KEYS
    )
    _require(
        len({customer.birth_date.year for customer in anchors}) == 8
        and {customer.gender for customer in anchors} == {1, 2}
        and len({customer.family_context for customer in anchors}) == 8
        and len({customer.coverage_focus for customer in anchors}) == 8,
        '핵심 고객의 연령과 생활 맥락을 확인해 주세요.',
    )

    policy_keys = tuple(policy.key for policy in INSURANCES)
    _require(
        len(set(policy_keys)) == INSURANCE_COUNT,
        '증권 키 중복을 확인해 주세요.',
    )
    _require(
        all(policy.customer_key in customer_keys for policy in INSURANCES),
        '증권의 고객 연결을 확인해 주세요.',
    )
    _require(
        {policy.customer_key for policy in INSURANCES} == set(customer_keys),
        '모든 고객에게 증권을 배분해 주세요.',
    )
    _require(
        all(policy.company_name in _COMPANIES for policy in INSURANCES)
        and {policy.company_name for policy in INSURANCES} == set(_COMPANIES),
        '합성 회사 이름을 확인해 주세요.',
    )
    _require(
        all(policy.product_type in _PRODUCT_TYPES for policy in INSURANCES),
        '일반 상품 유형을 확인해 주세요.',
    )
    _require(
        all(
            policy.monthly_premium > 0
            and isinstance(policy.coverages, tuple)
            and policy.coverages
            and all(
                coverage.insured_amount > 0 and coverage.monthly_premium > 0
                for coverage in policy.coverages
            )
            for policy in INSURANCES
        ),
        '증권 보험료와 담보 구성을 확인해 주세요.',
    )

    month_counts = Counter(
        policy.registered_month_offset for policy in INSURANCES
    )
    _require(set(month_counts) == set(range(6)), '최근 6개월 범위를 확인해 주세요.')
    oldest_to_newest = tuple(month_counts[offset] for offset in range(5, -1, -1))
    _require(
        all(earlier <= later for earlier, later in zip(
            oldest_to_newest,
            oldest_to_newest[1:],
        )),
        '최근 6개월 증권 흐름을 확인해 주세요.',
    )

    policy_counts = Counter(policy.customer_key for policy in INSURANCES)
    coverage_counts = Counter()
    for policy in INSURANCES:
        coverage_counts[policy.customer_key] += len(policy.coverages)
    _require(
        all(2 <= policy_counts[key] <= 4 for key in ANCHOR_CUSTOMER_KEYS),
        '핵심 고객별 증권 수를 확인해 주세요.',
    )
    _require(
        all(12 <= coverage_counts[key] <= 25 for key in ANCHOR_CUSTOMER_KEYS),
        '핵심 고객별 담보 수를 확인해 주세요.',
    )
    _require(
        sum(coverage_counts[key] for key in ANCHOR_CUSTOMER_KEYS)
        >= MIN_COVERAGE_COUNT,
        '핵심 고객 전체 담보 수를 확인해 주세요.',
    )

    renderable = tuple(_renderable_strings((CUSTOMERS, INSURANCES)))
    lowered = tuple(text.lower() for text in renderable)
    forbidden_terms = _SHOWCASE_MARKERS + _REAL_INSURER_OR_RESULT_TERMS
    _require(
        not any(term in text for text in lowered for term in forbidden_terms),
        '화면 문자열 금칙어를 확인해 주세요.',
    )
    _require(
        not any(
            re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', text)
            or re.search(r'\b\d{6}-[1-4]\d{6}\b', text)
            for text in renderable
        ),
        '고객 식별 정보 형식을 확인해 주세요.',
    )


validate_showcase_specs()
