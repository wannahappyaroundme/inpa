"""데모 시드 — 화면 렌더 확인용 (★ 실제 운영 데이터 아님, DEMO ONLY).

목적: FE(담보 한눈표/히트맵, 고객 목록, 고객상세)가 빈 화면이 아니라 실제 데이터 체인으로
  렌더되는지 눈으로 확인하기 위한 최소·현실적 데모 셋. 모든 이메일은 @inpa.local 더미.

데이터 체인(이 시드가 성립시키는 것 — calculate_total_analysis / CustomerHeatmapView 기준):
  1) 표준 담보 트리(공유 전역 마스터):
       AnalysisCategory → AnalysisSubCategory → AnalysisDetail(leaf) + ChartDetail
  2) 카탈로그 브리지: InsuranceDetail.analysis_detail(M2M) → AnalysisDetail
       → 고객 보험 담보가 표준 담보 트리에 매핑되는 유일한 경로(히트맵 held_amount의 출처).
  3) 고객 포트폴리오: CustomerInsurance → CustomerInsuranceDetail(detail=InsuranceDetail,
       assurance_amount) → calculate_total_analysis 가 analysis_detail 따라 합산
       → 트리 leaf 의 held_amount(=total_premium) > 0.
  4) PlannerBaseline.coverage_key == AnalysisDetail.name (★ 히트맵 grading 매칭 키),
       baseline_source!=null + is_active=True → 해당 고객 heatmap mode='graded'.

추가 시드 도메인 (v2 — boards / notifications / promotion / billing):
  9)  boards: 게시글 5~8개(demo + neutral 작성) + 댓글·좋아요 + 공지 2 + FAQ 3 + 1:1문의 1
  10) notifications: demo 설계사 알림 5~6개 (일부 미읽음)
  11) promotion: PromotionSample 3~4개 + demo 주문 1~2개(상태 다양)
  12) billing: Plan 2~3개(무료/구독) + demo Subscription(무료) + UsageMeter 약간

멱등: 매 실행 시 데모 마커(설계사 이메일/카탈로그 라벨/NormalizationDict source=seed 등)로
  기존 데모 데이터를 정리한 뒤 재생성 → 재실행해도 중복 없음.

실행:
  PYTHONPATH=<inpa_be> python3 manage.py seed_demo
"""
import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from inpa.accounts.models import Profile
from inpa.analysis.models import (
    AnalysisCategory, AnalysisDetail, AnalysisSubCategory, ChartDetail,
    NormalizationDict,
)
from inpa.billing.models import Plan, Subscription, UsageMeter
from inpa.boards.models import (
    Comment, Faq, Inquiry, Notice, Post, PostLike,
)
from inpa.customers.models import Customer, CustomerTag, PlannerBaseline
from inpa.insurances.models import (
    CustomerInsurance, CustomerInsuranceDetail, Insurance, InsuranceCategory,
    InsuranceDetail, InsuranceSubCategory,
)
from inpa.notifications.models import Notification, NotifType
from inpa.promotion.models import (
    PromotionOrder, PromotionSample, PromotionSampleImage,
)

User = get_user_model()

# ── 데모 마커(멱등 정리 키) ─────────────────────────────────────────────
DEMO_PLANNER_EMAIL = 'demo@inpa.local'        # 로그인 이메일 (메인 데모 설계사 — baseline 보유)
DEMO_PLANNER_PASSWORD = 'demoPass123!'        # 로그인 비번 (데모 전용)
# 보조 데모 설계사 — baseline 0건. mode='neutral' 게이트 시연용(메인 설계사는 owner 스코프 baseline
# 보유로 모든 고객이 graded 가 되므로, neutral 모드는 baseline 없는 별도 owner 로만 보일 수 있다).
DEMO_NEUTRAL_PLANNER_EMAIL = 'demo-neutral@inpa.local'
DEMO_NEUTRAL_PLANNER_PASSWORD = 'demoPass123!'
DEMO_CATALOG_TAG = '[DEMO]'                   # 카탈로그 계층 정리용 라벨 prefix
DEMO_COMPANY_CODES = range(900, 910)          # NormalizationDict 데모 보험사 코드 대역


# ════════════════════════════════════════════════════════════════════════
# 표준 담보 트리 정의 (현실적 부분집합 — 손해보험 위주 4 카테고리)
#   각 AnalysisDetail.name 은 PlannerBaseline.coverage_key 와 그대로 매칭되는 키다.
#   chart_based_amount 단위 = 만원(표준 보장 기준선 물리 저장; 단 판정 권위는 PlannerBaseline).
# ════════════════════════════════════════════════════════════════════════
TREE = [
    # (카테고리, insurance_type, [ (서브, [ (담보명, chart_based_amount(만원)) ]) ])
    ('사망/후유장해', 2, [
        ('사망', [
            ('일반사망', 10000),
            ('상해사망', 10000),
            ('질병사망', 10000),
        ]),
        ('후유장해', [
            ('상해후유장해', 10000),
            ('질병후유장해', 10000),
        ]),
    ]),
    ('진단', 2, [
        ('암', [
            ('암진단비', 5000),
            ('소액암진단비', 1000),
            ('유사암진단비', 1000),
        ]),
        ('뇌', [
            ('뇌졸중진단비', 3000),
            ('뇌출혈진단비', 3000),
        ]),
        ('심장', [
            ('급성심근경색진단비', 3000),
            ('허혈성심장질환진단비', 2000),
        ]),
    ]),
    ('입원/수술', 2, [
        ('입원', [
            ('질병입원일당', 5),
            ('상해입원일당', 5),
        ]),
        ('수술', [
            ('질병수술비', 300),
            ('상해수술비', 300),
            ('암수술비', 500),
        ]),
    ]),
    ('실손', 3, [
        ('급여', [
            ('실손입원급여', 5000),
            ('실손통원급여', 25),
        ]),
        ('비급여', [
            ('실손비급여주사', 250),
            ('실손비급여도수치료', 350),
        ]),
    ]),
]

# 차트 표시 단위(ChartDetail) — 한눈표 도넛/차트용 몇 개 (insurance_type, chart_type, name, 기준만원)
CHARTS = [
    (2, 1, '사망보장', 10000),
    (2, 1, '진단보장', 5000),
    (2, 1, '입원수술보장', 300),
    (3, 1, '실손보장', 5000),
]


# ════════════════════════════════════════════════════════════════════════
# 정규화 사전(NormalizationDict) 데모: 보험사별 담보명 원문 → 표준 담보(AnalysisDetail.name)
#   company 코드는 데모 대역(900~). 실제 보험사 코드 아님.
# ════════════════════════════════════════════════════════════════════════
NORMALIZATION = [
    # (company, 보험사 담보 원문, 표준 담보명)
    (901, '일반사망보험금', '일반사망'),
    (901, '재해사망특약', '상해사망'),
    (901, '암진단특약(유사암제외)', '암진단비'),
    (901, '소액암진단금', '소액암진단비'),
    (901, '뇌졸중진단비Ⅱ', '뇌졸중진단비'),
    (901, '급성심근경색증진단비', '급성심근경색진단비'),
    (901, '질병입원일당(1일이상)', '질병입원일당'),
    (901, '질병수술비(1~5종)', '질병수술비'),
    (902, '일반사망', '일반사망'),
    (902, '상해후유장해(3~100%)', '상해후유장해'),
    (902, '암보장특약', '암진단비'),
    (902, '유사암진단비', '유사암진단비'),
    (902, '뇌출혈진단금', '뇌출혈진단비'),
    (902, '허혈성심장질환진단비', '허혈성심장질환진단비'),
    (902, '상해입원일당', '상해입원일당'),
    (902, '상해수술비', '상해수술비'),
    (903, '질병사망보장', '질병사망'),
    (903, '질병후유장해(3~100%)', '질병후유장해'),
    (903, '암진단비Ⅰ', '암진단비'),
    (903, '암직접치료수술비', '암수술비'),
    (903, '뇌졸중진단비', '뇌졸중진단비'),
    (903, '급성심근경색진단금', '급성심근경색진단비'),
    (904, '실손의료비(질병입원)', '실손입원급여'),
    (904, '실손의료비(질병통원)', '실손통원급여'),
    (904, '비급여주사료', '실손비급여주사'),
    (904, '비급여도수·체외충격파·증식치료', '실손비급여도수치료'),
    (904, '소액암진단비(갑상선등)', '소액암진단비'),
    (904, '상해사망후유장해', '상해사망'),
]


# ── 고객 정의 (이름, 생년 YYYY.MM.DD, 성별 1남/2여, 태그라벨, 만기/메모) ─────
CUSTOMERS = [
    # idx 0,1 → 포트폴리오 보유(히트맵 held_amount>0), idx 0 → PlannerBaseline 보유(graded)
    {'name': '김영수', 'birth_day': '1985.03.12', 'gender': 1, 'tags': ['VIP', '갱신임박'],
     'memo': '[DEMO] 갈아타기 검토 중. 만기 3개월.', 'color': 'red'},
    {'name': '이지은', 'birth_day': '1990.07.21', 'gender': 2, 'tags': ['신규상담'],
     'memo': '[DEMO] 보장 공백 점검 요청.', 'color': 'blue'},
    {'name': '박철민', 'birth_day': '1978.11.05', 'gender': 1, 'tags': ['소개고객'],
     'memo': '[DEMO] 지인 소개. 첫 미팅 예정.', 'color': 'green'},
    {'name': '최수진', 'birth_day': '1995.02.28', 'gender': 2, 'tags': ['신규상담', '온라인'],
     'memo': '[DEMO] 온라인 유입. 실손 관심.', 'color': 'yellow'},
    {'name': '정대호', 'birth_day': '1969.09.09', 'gender': 1, 'tags': ['VIP', '장기고객'],
     'memo': '[DEMO] 장기 고객. 자녀 보험 문의.', 'color': 'purple'},
    {'name': '한가람', 'birth_day': '2001.12.01', 'gender': 2, 'tags': [],
     'memo': '[DEMO] 사회초년생. 보장 설계 신규.', 'color': ''},
]


class Command(BaseCommand):
    help = '화면 렌더 확인용 데모 데이터 시드 (멱등). 실제 운영 데이터 아님.'

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write('=== seed_demo 시작 (DEMO ONLY) ===')

        self._cleanup()                                    # 멱등: 기존 데모 정리
        detail_by_name = self._seed_tree()                 # 1) 표준 담보 트리 + 차트
        catalog_by_std_name = self._seed_catalog(detail_by_name)  # 2) 카탈로그 + analysis_detail M2M
        self._seed_normalization(detail_by_name)           # 3) 정규화 사전
        planner = self._seed_planner()                     # 4) 데모 설계사 + Profile
        customers = self._seed_customers(planner)          # 5) 고객 6명
        self._seed_portfolios(customers, catalog_by_std_name)  # 6) 고객 2명 포트폴리오(held>0)
        graded_customer = self._seed_baselines(planner, customers)  # 7) 고객 1명 baseline(graded)
        # 8) 보조: baseline 없는 설계사 + 고객 1명 → mode='neutral' 시연
        neutral_planner, neutral_customer = self._seed_neutral_demo(catalog_by_std_name)
        # 9~12) 추가 도메인 시드
        self._seed_boards(planner, neutral_planner, customers)
        self._seed_notifications(planner, customers)
        samples = self._seed_promotion_samples()
        self._seed_promotion_orders(planner, samples)
        self._seed_billing(planner)

        self.stdout.write(self.style.SUCCESS('=== seed_demo 완료 ==='))
        self.stdout.write(f'  [메인] 로그인 이메일 : {DEMO_PLANNER_EMAIL}')
        self.stdout.write(f'  [메인] 로그인 비번   : {DEMO_PLANNER_PASSWORD}')
        self.stdout.write(f'  [메인] 고객 id 목록  : {[c.id for c in customers]}')
        self.stdout.write(f'  graded 고객 id      : {graded_customer.id} '
                          f'(이름={graded_customer.name}, owner={planner.email})')
        self.stdout.write(f'  [neutral] 로그인 이메일: {DEMO_NEUTRAL_PLANNER_EMAIL} '
                          f'/ 비번 {DEMO_NEUTRAL_PLANNER_PASSWORD}')
        self.stdout.write(f'  neutral 고객 id     : {neutral_customer.id} '
                          f'(이름={neutral_customer.name}, owner={neutral_planner.email})')

    # ── 멱등 정리 ────────────────────────────────────────────────────────
    def _cleanup(self):
        """데모 마커 기준으로 기존 데모 데이터 삭제 (재실행 안전).

        설계사(owner) 삭제 시 Customer/CustomerInsurance/PlannerBaseline 등이 CASCADE.
        공유 전역 마스터(표준 트리/카탈로그/정규화/게시판 공용/판촉물샘플/요금제)는
        데모 라벨 기준으로만 정리한다.
        """
        # 설계사 → CASCADE 로 고객/포트폴리오/baseline/태그/알림/주문 연쇄 삭제
        User.objects.filter(
            email__in=[DEMO_PLANNER_EMAIL, DEMO_NEUTRAL_PLANNER_EMAIL]).delete()

        # 정규화 사전(데모 보험사 코드 대역)
        NormalizationDict.objects.filter(company__in=list(DEMO_COMPANY_CODES)).delete()

        # 카탈로그 계층(데모 라벨 prefix)
        InsuranceCategory.objects.filter(name__startswith=DEMO_CATALOG_TAG).delete()
        Insurance.objects.filter(name__startswith=DEMO_CATALOG_TAG).delete()

        # 표준 담보 트리(데모 라벨 prefix) — 카테고리 CASCADE 로 sub/detail 정리
        AnalysisCategory.objects.filter(name__startswith=DEMO_CATALOG_TAG).delete()
        ChartDetail.objects.filter(name__startswith=DEMO_CATALOG_TAG).delete()

        # 공유 게시판 (공지/FAQ/게시글 — [DEMO] 마커 본문 기준)
        Post.objects.filter(title__startswith=DEMO_CATALOG_TAG).delete()
        Notice.objects.filter(title__startswith=DEMO_CATALOG_TAG).delete()
        Faq.objects.filter(question__startswith=DEMO_CATALOG_TAG).delete()

        # 판촉물 샘플 (공유 — [DEMO] 마커 이름 기준) + CASCADE 로 이미지·주문 정리
        PromotionSample.objects.filter(name__startswith=DEMO_CATALOG_TAG).delete()

        # 요금제 (공유 — [DEMO] 마커 display_name 기준)
        Plan.objects.filter(display_name__startswith=DEMO_CATALOG_TAG).delete()

    # ── 1) 표준 담보 트리 + 차트 ─────────────────────────────────────────
    def _seed_tree(self):
        """AnalysisCategory→Sub→Detail + ChartDetail. 반환: {담보명: AnalysisDetail}."""
        detail_by_name = {}
        for c_order, (cat_name, ins_type, subs) in enumerate(TREE, start=1):
            cat = AnalysisCategory.objects.create(
                insurance_type=ins_type, name=f'{DEMO_CATALOG_TAG}{cat_name}', order=c_order)
            for s_order, (sub_name, details) in enumerate(subs, start=1):
                sub = AnalysisSubCategory.objects.create(
                    insurance_type=ins_type, category=cat, name=sub_name, order=s_order)
                for d_order, (det_name, based) in enumerate(details, start=1):
                    det = AnalysisDetail.objects.create(
                        sub_category=sub, name=det_name, order=d_order, chart_based_amount=based)
                    detail_by_name[det_name] = det

        for ch_order, (ins_type, chart_type, name, based) in enumerate(CHARTS, start=1):
            ChartDetail.objects.create(
                insurance_type=ins_type, chart_type=chart_type,
                name=f'{DEMO_CATALOG_TAG}{name}', order=ch_order, chart_based_amount=based)

        total_details = AnalysisDetail.objects.filter(
            sub_category__category__name__startswith=DEMO_CATALOG_TAG).count()
        self.stdout.write(f'  [1] 표준 담보 트리: 담보 {total_details}개 + 차트 {len(CHARTS)}개')
        return detail_by_name

    # ── 2) 카탈로그 최소 + analysis_detail M2M(체인 성립) ────────────────
    def _seed_catalog(self, detail_by_name):
        """InsuranceCategory→Sub→Detail 최소 + 표준 담보 M2M 연결.

        담보 1:1 로 카탈로그 InsuranceDetail 을 만들고 같은 이름의 AnalysisDetail 에 연결.
        반환: {표준담보명: InsuranceDetail} — 포트폴리오 케이스가 참조할 카탈로그 담보.
        """
        Insurance.objects.create(
            name=f'{DEMO_CATALOG_TAG}데모종합보험', order=1, insurance_type=2)

        icat = InsuranceCategory.objects.create(
            insurance_type=2, name=f'{DEMO_CATALOG_TAG}데모상품', order=1)
        isub = InsuranceSubCategory.objects.create(
            insurance_type=2, category=icat, name='보장', order=1)

        catalog_by_std_name = {}
        for order, (std_name, std_detail) in enumerate(detail_by_name.items(), start=1):
            idet = InsuranceDetail.objects.create(
                sub_category=isub, name=std_name[:20], order=order,
                chart_based_amount=std_detail.chart_based_amount)
            idet.analysis_detail.add(std_detail)          # ★ 체인 핵심: 카탈로그→표준 담보
            catalog_by_std_name[std_name] = idet

        self.stdout.write(f'  [2] 카탈로그: InsuranceDetail {len(catalog_by_std_name)}개 → '
                          f'analysis_detail M2M 연결 완료')
        return catalog_by_std_name

    # ── 3) 정규화 사전 ───────────────────────────────────────────────────
    def _seed_normalization(self, detail_by_name):
        created = 0
        skipped = 0
        for company, raw_name, std_name in NORMALIZATION:
            std = detail_by_name.get(std_name)
            if std is None:
                skipped += 1
                continue
            NormalizationDict.objects.create(
                std_detail=std, company=company, raw_name=raw_name,
                source=NormalizationDict.SOURCE_SEED, confidence=100, hit_count=0)
            created += 1
        self.stdout.write(f'  [3] 정규화 사전: {created}행 (skip={skipped})')

    # ── 4) 데모 설계사 + Profile ─────────────────────────────────────────
    def _seed_planner(self):
        user = User.objects.create_user(
            email=DEMO_PLANNER_EMAIL, password=DEMO_PLANNER_PASSWORD)
        user.is_active = True                              # 이메일 인증 완료 상태
        user.save(update_fields=['is_active'])
        now = timezone.now()
        Profile.objects.create(
            user=user,
            email_verified_at=now,                        # IsEmailVerified 게이트 통과
            onboarding_completed_at=now,
            agent_type=Profile.AGENT_NONLIFE,             # 손해 설계사
            affiliation='[DEMO] 인파데모대리점',
            license_self_declared=True,
        )
        self.stdout.write(f'  [4] 데모 설계사: {user.email} (is_active=True, email_verified)')
        return user

    # ── 5) 고객 6명 ──────────────────────────────────────────────────────
    def _seed_customers(self, planner):
        customers = []
        tag_cache = {}
        for spec in CUSTOMERS:
            cust = Customer.objects.create(
                owner=planner, name=spec['name'], birth_day=spec['birth_day'],
                gender=spec['gender'], memo=spec['memo'], color=spec['color'],
                mobile_phone_number='010-0000-0000', is_agree_term=True)
            for label in spec['tags']:
                tag = tag_cache.get(label)
                if tag is None:
                    tag, _ = CustomerTag.objects.get_or_create(
                        owner=planner, label=label, defaults={'color': ''})
                    tag_cache[label] = tag
                cust.tags.add(tag)
            customers.append(cust)
        self.stdout.write(f'  [5] 고객 {len(customers)}명 생성 (owner={planner.email})')
        return customers

    # ── 6) 고객 2명 포트폴리오 (held_amount > 0) ─────────────────────────
    def _seed_portfolios(self, customers, catalog_by_std_name):
        """고객 idx 0, 1 에 보유 포트폴리오 + 담보 케이스 → 히트맵 held_amount>0.

        담보 케이스의 detail=InsuranceDetail(analysis_detail 연결됨) 이므로
        calculate_total_analysis 가 표준 담보 leaf 에 assurance_amount 를 합산한다.
        """
        # 고객 idx 0(김영수): graded 대상. 사망/암/뇌/심장 담보 보유(부족·충분·과다 섞이게).
        self._make_portfolio(
            customers[0], catalog_by_std_name, name='[DEMO]종합보장보험(보유)',
            contract_date='2018.04.01', expiry_date='2055.04.01',
            coverages=[
                # (표준담보명, 보장금액(원), 납입타입, 보장타입, 보장기간)
                ('일반사망', 50_000_000, 1, 1, '100'),        # baseline 1억 → shortage 유도
                ('암진단비', 30_000_000, 1, 1, '100'),        # baseline 3~5천 → adequate 유도
                ('뇌졸중진단비', 50_000_000, 1, 1, '100'),    # baseline ~3천 → over 유도
                ('급성심근경색진단비', 20_000_000, 1, 1, '100'),
                ('질병입원일당', 30_000, 1, 1, '100'),
            ])
        # 고객 idx 1(이지은): 보유 보험은 있으나 매칭되는 baseline 없음 →
        #   메인 설계사가 owner 스코프 baseline 보유라 mode 는 'graded' 이지만,
        #   이 고객 담보엔 coverage_key 매칭이 없어 칸별 status 는 모두 'neutral'(단정 금지).
        #   held_amount 는 그대로 표시(중립 사실 표시 허용).
        self._make_portfolio(
            customers[1], catalog_by_std_name, name='[DEMO]실손+진단보험(보유)',
            contract_date='2020.09.15', expiry_date='2060.09.15',
            coverages=[
                ('실손입원급여', 50_000_000, 1, 1, '100'),
                ('암진단비', 20_000_000, 1, 1, '100'),
                ('상해수술비', 5_000_000, 1, 1, '100'),
            ])
        self.stdout.write('  [6] 포트폴리오: 고객 2명에 보유 보험 + 담보 케이스 생성 '
                          '(held_amount>0)')

    def _make_portfolio(self, customer, catalog_by_std_name, name,
                        contract_date, expiry_date, coverages):
        ci = CustomerInsurance.objects.create(
            customer=customer, insurance_type=2, name=name,
            portfolio_type=1,                              # 1=보유(갈아타기 좌측)
            payment_period_type=1, payment_period=20,
            warranty_period_type=1, warranty_period=100,
            contract_date=contract_date, expiry_date=expiry_date,
            monthly_premiums=80000, monthly_assurance_premium=80000,
            insured_name=customer.name, contractor_name=customer.name,
            is_same_insured=True)
        for std_name, amount, pp_type, w_type, w_period in coverages:
            idet = catalog_by_std_name.get(std_name)
            if idet is None:
                continue
            CustomerInsuranceDetail.objects.create(
                insurance=ci, detail=idet,
                assurance_amount=amount, premium=10000,
                payment_period_type=pp_type, payment_period=20,
                warranty_period_type=w_type, warranty_period=w_period)
        # 보험료 엔진(무변경) 호출 — 합계 필드 채움
        ci.set_renewal_month()
        ci.calculate()
        ci.save()
        return ci

    # ── 7) 고객 1명 PlannerBaseline (graded) ─────────────────────────────
    def _seed_baselines(self, planner, customers):
        """고객 idx 0(김영수) → 설계사 baseline 보유 → 그 고객 heatmap mode='graded'.

        baseline 은 owner(설계사) 소유이며 coverage_key==AnalysisDetail.name 으로 매칭.
        김영수: 1985년생(40대), gender=1(남) → age_band='40s'.
        boundary 의도(원 단위): 일반사망 보유 5천 < min 1억 → shortage,
          암진단비 보유 3천 ∈ [3천,5천] → adequate, 뇌졸중 보유 5천 > max 3천 → over.
        """
        graded_customer = customers[0]
        gc_band = '40s'        # 1985년생 → 40대
        gc_gender = graded_customer.gender   # 1=남

        baselines = [
            # (coverage_key=담보명, min(원), max(원))
            ('일반사망', 100_000_000, 300_000_000),       # 보유 5천 → shortage
            ('암진단비', 30_000_000, 50_000_000),         # 보유 3천 → adequate
            ('뇌졸중진단비', 10_000_000, 30_000_000),     # 보유 5천 → over
            ('급성심근경색진단비', 10_000_000, 30_000_000),  # 보유 2천 → adequate
        ]
        for coverage_key, lo, hi in baselines:
            PlannerBaseline.objects.create(
                owner=planner, coverage_key=coverage_key,
                product_group=PlannerBaseline.PRODUCT_GROUP_NONLIFE,
                age_band=gc_band, gender=gc_gender,
                recommend_min=lo, recommend_max=hi, unit=2,    # 2=원
                baseline_source='planner',                     # ★ 살아있는 출처 → graded
                is_active=True)
        self.stdout.write(f'  [7] PlannerBaseline: {len(baselines)}개 '
                          f'(graded 고객={graded_customer.name}, id={graded_customer.id})')
        return graded_customer

    # ── 8) 보조 데모 설계사(baseline 0건) + 고객 1명 → mode='neutral' 시연 ─
    def _seed_neutral_demo(self, catalog_by_std_name):
        """baseline 없는 owner 의 고객 → 히트맵 mode='neutral'(부족/충분 단정 금지).

        CustomerHeatmapView 의 neutral 게이트는 owner 스코프(=설계사가 살아있는 baseline 을
        하나라도 보유하는가)로 결정된다. 따라서 진짜 neutral 모드는 baseline 없는 별도
        설계사로만 보일 수 있어, 이 보조 계정으로 시연한다. 포트폴리오는 두어 held_amount
        표시(중립이어도 사실 표시 허용)도 함께 확인한다.
        """
        user = User.objects.create_user(
            email=DEMO_NEUTRAL_PLANNER_EMAIL, password=DEMO_NEUTRAL_PLANNER_PASSWORD)
        user.is_active = True
        user.save(update_fields=['is_active'])
        now = timezone.now()
        Profile.objects.create(
            user=user, email_verified_at=now, onboarding_completed_at=now,
            agent_type=Profile.AGENT_NONLIFE, affiliation='[DEMO] 인파데모대리점(neutral)',
            license_self_declared=True)

        customer = Customer.objects.create(
            owner=user, name='무기준데모고객', birth_day='1992.06.15', gender=2,
            memo='[DEMO] baseline 없는 설계사의 고객 → 히트맵 neutral 모드 시연.',
            color='blue', mobile_phone_number='010-0000-0000', is_agree_term=True)
        self._make_portfolio(
            customer, catalog_by_std_name, name='[DEMO]진단보험(보유)',
            contract_date='2021.03.01', expiry_date='2061.03.01',
            coverages=[
                ('암진단비', 20_000_000, 1, 1, '100'),
                ('일반사망', 30_000_000, 1, 1, '100'),
            ])
        self.stdout.write(f'  [8] neutral 시연: 설계사 {user.email}(baseline 0) + '
                          f'고객 {customer.name}(id={customer.id})')
        return user, customer

    # ── 9) 게시판 (Post·Comment·PostLike·Notice·Faq·Inquiry) ─────────────
    def _seed_boards(self, planner, neutral_planner, customers):
        """공유 게시글 5~8개 (demo + neutral 작성) + 댓글·좋아요 + 공지 2 + FAQ 3 + 1:1문의 1.

        게시판 데이터 가시성(boards/models.py §0):
          Post/Comment/PostLike — 공유(author FK만 기록, owner 스코프 없음).
          Notice/Faq            — 공개 읽기, 관리자 쓰기.
          Inquiry               — 비공개(owner=planner).
        """
        now = timezone.now()

        # ── 공지사항 2개 ────────────────────────────────────────────────
        n1 = Notice.objects.create(
            author=planner,
            title=f'{DEMO_CATALOG_TAG} 인파 베타 서비스 오픈 안내',
            body=(
                '[DEMO] 인파(Inpa) 베타 서비스가 오픈되었습니다.\n'
                '담보 한눈표·갈아타기 비교표 등 주요 기능을 무료로 사용할 수 있습니다.\n'
                '피드백은 1:1 문의로 남겨주세요. (★ 데모 전용 콘텐츠, 운영 데이터 아님)'
            ),
            is_pinned=True,
            is_published=True,
            published_at=now,
        )
        Notice.objects.create(
            author=planner,
            title=f'{DEMO_CATALOG_TAG} 보장분석 기능 업데이트 안내 (v0.2)',
            body=(
                '[DEMO] 히트맵 graded 모드에서 shortage/adequate/over 색상 구분이 개선되었습니다.\n'
                '자세한 사항은 FAQ를 참고하세요.'
            ),
            is_pinned=False,
            is_published=True,
            published_at=now,
        )

        # ── FAQ 3개 ─────────────────────────────────────────────────────
        Faq.objects.create(
            author=planner,
            category='기능문의',
            question=f'{DEMO_CATALOG_TAG} 담보 한눈표란 무엇인가요?',
            answer=(
                '[DEMO] 고객의 현재 보유 보험을 표준 담보 체계로 정규화하여 '
                '보장 현황을 한 화면에서 확인할 수 있는 기능입니다.\n'
                '부족(shortage)/충분(adequate)/초과(over) 상태를 색상으로 시각화합니다.'
            ),
            order=1,
        )
        Faq.objects.create(
            author=planner,
            category='기능문의',
            question=f'{DEMO_CATALOG_TAG} 갈아타기 비교표는 어떻게 활용하나요?',
            answer=(
                '[DEMO] 보험업법 §97 기준 부당승환 방지 안내서를 AI가 초안 생성합니다.\n'
                '★ AI 생성물 = 초안이며 최종 책임은 설계사 본인에게 있습니다. (면책 고정)'
            ),
            order=2,
        )
        Faq.objects.create(
            author=planner,
            category='요금결제',
            question=f'{DEMO_CATALOG_TAG} 무료 플랜 사용 한도는 어떻게 되나요?',
            answer=(
                '[DEMO] 무료 플랜은 OCR 10건/월, AI 분석 10건/월, 판촉물 주문 5건/월을 '
                '제공합니다. 베타 기간에는 한도가 적용되지 않을 수 있습니다.'
            ),
            order=3,
        )

        # ── 공유 게시글 6개 (demo 4 + neutral 2) ────────────────────────
        post_specs = [
            # (author, title, body, category, pinned)
            (planner,
             f'{DEMO_CATALOG_TAG} 갱신 임박 고객 응대 노하우 공유',
             '[DEMO] 갱신 3개월 전 연락 타이밍이 핵심입니다. '
             '문자+카카오 알림 순서를 잡아두면 성공률이 크게 올라요.',
             '영업팁', False),
            (planner,
             f'{DEMO_CATALOG_TAG} 실손보험 4세대 전환 안내 정리',
             '[DEMO] 4세대 실손 전환 포인트를 요약했습니다. '
             '비급여 본인부담률 변화에 주의하세요. (★ AI 초안, 최종 책임은 설계사 본인)',
             '상품정보', False),
            (planner,
             f'{DEMO_CATALOG_TAG} 신입 설계사 첫 달 루틴 후기',
             '[DEMO] 하루 콜드콜 30건 목표 + 인파 보장분석으로 첫 미팅 전환율을 높였습니다.',
             '경험공유', False),
            (planner,
             f'{DEMO_CATALOG_TAG} 인파 히트맵 기능 사용 팁',
             '[DEMO] shortage 항목 클릭 시 추천 상품 연결 기능이 곧 추가될 예정입니다. '
             '기대해주세요!',
             '공지', True),
            (neutral_planner,
             f'{DEMO_CATALOG_TAG} 암 진단비 기준 공유 (40대 남성)',
             '[DEMO] 40대 남성 기준 암진단비 3천만 원 이상 권장이라는 업계 기준을 공유합니다.',
             '영업팁', False),
            (neutral_planner,
             f'{DEMO_CATALOG_TAG} GA 소속 설계사 계약 관리 방법',
             '[DEMO] GA 소속이라 원수사 계약과 GA 계약을 구분 관리해야 해서 인파 메모 기능을 활용 중입니다.',
             '경험공유', False),
        ]
        posts = []
        for author, title, body, category, pinned in post_specs:
            p = Post.objects.create(
                author=author, title=title, body=body,
                category=category, pinned=pinned, view_count=0, like_count=0,
            )
            posts.append(p)

        # ── 댓글 (게시글 0·1·4에 달기) ──────────────────────────────────
        c1 = Comment.objects.create(
            post=posts[0], author=neutral_planner,
            body='[DEMO] 저도 같은 방식으로 하고 있어요. 갱신 알림을 인파에서 자동으로 잡아주면 더 좋겠네요.',
        )
        Comment.objects.create(
            post=posts[0], author=planner, parent=c1,
            body='[DEMO] 맞아요! 알림 기능 곧 업데이트 예정입니다.',
        )
        Comment.objects.create(
            post=posts[1], author=neutral_planner,
            body='[DEMO] 4세대 전환 자료 감사합니다. 고객 설명용으로 써볼게요.',
        )
        Comment.objects.create(
            post=posts[4], author=planner,
            body='[DEMO] 인파 기준선에도 반영해뒀어요. 확인해보세요!',
        )

        # like_count 캐시 업데이트가 필요하므로 직접 갱신
        def _add_like(post, user):
            PostLike.objects.create(post=post, user=user)
            Post.objects.filter(pk=post.pk).update(like_count=post.like_count + 1)

        _add_like(posts[0], neutral_planner)
        _add_like(posts[1], neutral_planner)
        _add_like(posts[4], planner)

        # comment_count 캐시 업데이트
        Post.objects.filter(pk=posts[0].pk).update(comment_count=2)
        Post.objects.filter(pk=posts[1].pk).update(comment_count=1)
        Post.objects.filter(pk=posts[4].pk).update(comment_count=1)

        # ── demo 설계사의 1:1 문의 1개 ──────────────────────────────────
        Inquiry.objects.create(
            owner=planner,
            category=Inquiry.CATEGORY_FEATURE,
            title='[DEMO] 고객 분석 결과 PDF 내보내기 기능 요청',
            body=(
                '[DEMO] 담보 한눈표와 갈아타기 비교표를 PDF로 출력해서 고객에게 직접 보여줄 수 있으면 좋겠습니다. '
                '현재 화면 캡처로 대신하고 있는데 해상도가 낮아서 불편합니다.'
            ),
            status=Inquiry.STATUS_OPEN,
        )

        self.stdout.write(
            f'  [9] 게시판: 공지 2 + FAQ 3 + 게시글 {len(posts)} + 댓글 4 + 좋아요 3 + 1:1문의 1'
        )

    # ── 10) 알림 (demo 설계사 전용) ──────────────────────────────────────
    def _seed_notifications(self, planner, customers):
        """demo 설계사에게 알림 5~6개 (일부 미읽음).

        NotifType 7종 중 6종 커버: expiry_soon / birthday_soon / consult_reminder /
          task_due / share_unread / board_comment.
        target_date 있는 알림 → UniqueConstraint(owner, notif_type, target_date, customer) 준수.
        board_comment 는 target_date=None + customer=None 이므로 constraint 대상 아님.
        """
        today = timezone.now().date()

        notifs = [
            # (notif_type, title, body, target_date, customer, is_read)
            (
                NotifType.EXPIRY_SOON,
                '김영수 고객 계약 만기 임박',
                '[DEMO] 김영수 고객의 종합보장보험이 30일 후 만기됩니다. 갱신 안내를 준비하세요.',
                today + datetime.timedelta(days=30),
                customers[0],
                False,   # 미읽음
            ),
            (
                NotifType.BIRTHDAY_SOON,
                '이지은 고객 생일 7일 전',
                '[DEMO] 이지은 고객 생일이 7일 후입니다. 생일 메시지를 준비해보세요.',
                today + datetime.timedelta(days=7),
                customers[1],
                False,   # 미읽음
            ),
            (
                NotifType.CONSULT_REMINDER,
                '박철민 고객 상담 약속 D-1',
                '[DEMO] 내일 박철민 고객과 첫 미팅 약속이 있습니다. 보장분석을 미리 확인하세요.',
                today + datetime.timedelta(days=1),
                customers[2],
                False,   # 미읽음
            ),
            (
                NotifType.TASK_DUE,
                '최수진 고객 실손 검토 마감일',
                '[DEMO] 최수진 고객 실손 비교 검토 마감이 내일입니다.',
                today + datetime.timedelta(days=1),
                customers[3],
                True,    # 읽음
            ),
            (
                NotifType.SHARE_UNREAD,
                '정대호 고객 — 공유 링크 미열람',
                '[DEMO] 정대호 고객이 공유된 보장분석 링크를 아직 열람하지 않았습니다.',
                today,
                customers[4],
                True,    # 읽음
            ),
            (
                NotifType.BOARD_COMMENT,
                '내 게시글에 댓글이 달렸습니다',
                '[DEMO] "갱신 임박 고객 응대 노하우 공유" 게시글에 새 댓글이 달렸습니다.',
                None,    # board_comment는 target_date 없음
                None,    # customer 없음
                False,   # 미읽음
            ),
        ]

        created = 0
        for notif_type, title, body, target_date, customer, is_read in notifs:
            Notification.objects.create(
                owner=planner,
                notif_type=notif_type,
                title=title,
                body=body,
                target_date=target_date,
                customer=customer,
                is_read=is_read,
            )
            created += 1

        unread = sum(1 for *_, is_read in notifs if not is_read)
        self.stdout.write(f'  [10] 알림: {created}개 생성 (미읽음 {unread}개)')

    # ── 11) 판촉물 샘플 + demo 주문 ────────────────────────────────────────
    def _seed_promotion_samples(self):
        """PromotionSample 3~4개 + PromotionSampleImage placeholder.

        샘플 이미지: S3 미연동 단계이므로 placeholder URL 사용.
        form_fields: 실제 주문 폼을 시연할 수 있도록 다양한 타입 정의.
        """
        sample_specs = [
            {
                'name': f'{DEMO_CATALOG_TAG} 2027 탁상달력',
                'category': PromotionSample.CATEGORY_CALENDAR,
                'description': '[DEMO] 고품질 탁상달력. 설계사 이름·연락처 인쇄 가능. 납기 2~3주.',
                'is_available': True,
                'sort_order': 1,
                'form_fields': [
                    {'key': 'quantity', 'label': '수량', 'type': 'number',
                     'required': True, 'min': 50, 'max': 1000},
                    {'key': 'name_text', 'label': '인쇄 이름·연락처', 'type': 'text',
                     'required': True, 'placeholder': '예: 홍길동 설계사 010-1234-5678'},
                    {'key': 'color', 'label': '표지 색상', 'type': 'radio',
                     'required': True, 'options': ['빨강', '파랑', '초록', '베이지']},
                ],
                'image_url': 'https://placehold.co/400x300?text=달력+샘플',
            },
            {
                'name': f'{DEMO_CATALOG_TAG} 고급 다이어리 (A5)',
                'category': PromotionSample.CATEGORY_DIARY,
                'description': '[DEMO] A5 양장 다이어리. 로고 각인 가능. 최소 주문 30권.',
                'is_available': True,
                'sort_order': 2,
                'form_fields': [
                    {'key': 'quantity', 'label': '수량', 'type': 'number',
                     'required': True, 'min': 30, 'max': 500},
                    {'key': 'logo_engraving', 'label': '로고 각인 여부', 'type': 'radio',
                     'required': True, 'options': ['있음', '없음']},
                    {'key': 'delivery_address', 'label': '배송지 주소', 'type': 'textarea',
                     'required': True},
                ],
                'image_url': 'https://placehold.co/400x300?text=다이어리+샘플',
            },
            {
                'name': f'{DEMO_CATALOG_TAG} 보험 안내 에코백',
                'category': PromotionSample.CATEGORY_LIFE,
                'description': '[DEMO] 친환경 에코백. 전면 인쇄 가능. 납기 3~4주.',
                'is_available': True,
                'sort_order': 3,
                'form_fields': [
                    {'key': 'quantity', 'label': '수량', 'type': 'number',
                     'required': True, 'min': 100},
                    {'key': 'print_text', 'label': '인쇄 문구', 'type': 'text',
                     'required': False, 'placeholder': '예: 인파손해보험 홍길동'},
                ],
                'image_url': 'https://placehold.co/400x300?text=에코백+샘플',
            },
            {
                'name': f'{DEMO_CATALOG_TAG} 미니 우산 (단종 예정)',
                'category': PromotionSample.CATEGORY_LIFE,
                'description': '[DEMO] 접이식 미니 우산. 재고 소진 후 단종 예정.',
                'is_available': False,   # 품절/단종 배지 시연
                'sort_order': 4,
                'form_fields': [
                    {'key': 'quantity', 'label': '수량', 'type': 'number',
                     'required': True, 'min': 50},
                ],
                'image_url': 'https://placehold.co/400x300?text=우산+샘플',
            },
        ]

        samples = []
        for spec in sample_specs:
            image_url = spec.pop('image_url')
            sample = PromotionSample.objects.create(**spec)
            PromotionSampleImage.objects.create(
                sample=sample,
                image_url=image_url,
                is_primary=True,
                sort_order=0,
            )
            samples.append(sample)

        self.stdout.write(
            f'  [11a] 판촉물 샘플: {len(samples)}개 (이미지 각 1장, '
            f'주문가능 {sum(s.is_available for s in samples)}개 / '
            f'품절 {sum(not s.is_available for s in samples)}개)'
        )
        return samples

    def _seed_promotion_orders(self, planner, samples):
        """demo 설계사의 판촉물 주문 2개 (상태 다양 — pending, producing)."""
        # 주문 1: 달력 — pending (접수 단계)
        order1 = PromotionOrder.objects.create(
            owner=planner,
            sample=samples[0],   # 탁상달력
            form_response={
                'quantity': 100,
                'name_text': '[DEMO] 인파데모 설계사 010-0000-0000',
                'color': '파랑',
            },
            status=PromotionOrder.STATUS_PENDING,
            admin_note='',
        )

        # 주문 2: 다이어리 — producing (제작 중) + 상태 이력 로그 시연
        order2 = PromotionOrder.objects.create(
            owner=planner,
            sample=samples[1],   # 다이어리
            form_response={
                'quantity': 50,
                'logo_engraving': '있음',
                'delivery_address': '[DEMO] 서울시 강남구 테헤란로 123',
            },
            status=PromotionOrder.STATUS_PRODUCING,
            admin_note='[DEMO] 로고 시안 확인 완료. 제작 진행 중.',
        )
        # 상태 이력 로그 (producing 전 단계: pending → reviewing → producing)
        from inpa.promotion.models import PromotionOrderStatusLog
        PromotionOrderStatusLog.objects.create(
            order=order2, to_status=PromotionOrder.STATUS_PENDING,
            changed_by=planner, note='[DEMO] 주문 접수',
        )
        PromotionOrderStatusLog.objects.create(
            order=order2, to_status=PromotionOrder.STATUS_REVIEWING,
            changed_by=planner, note='[DEMO] 시안 검토 시작',
        )
        PromotionOrderStatusLog.objects.create(
            order=order2, to_status=PromotionOrder.STATUS_PRODUCING,
            changed_by=planner, note='[DEMO] 로고 시안 확인 완료, 제작 진행',
        )

        self.stdout.write(
            f'  [11b] 판촉물 주문: 2개 '
            f'(주문#{order1.pk} pending, 주문#{order2.pk} producing+이력3)'
        )

    # ── 12) Billing — Plan + Subscription + UsageMeter ─────────────────
    def _seed_billing(self, planner):
        """Plan 2개(무료/플러스) + demo Subscription(무료 활성) + UsageMeter 약간.

        Plan은 공유 전역 데이터이므로 [DEMO] prefix display_name으로 생성.
        _cleanup에서 display_name__startswith=DEMO_CATALOG_TAG 로 정리.
        code는 unique이므로 demo_ prefix 사용.
        """
        now = timezone.now()
        ym = UsageMeter.current_month()

        # 요금제 2개
        plan_free = Plan.objects.create(
            code='demo_free',
            display_name=f'{DEMO_CATALOG_TAG} 무료 플랜',
            price_krw=0,
            description='[DEMO] 베타 무료 플랜. OCR 10건/AI분석 10건/판촉물 5건 월 한도.',
            limit_ocr=10,
            limit_ai_compare=5,
            limit_analysis=10,
            limit_promotion=5,
            is_active=True,
        )
        plan_plus = Plan.objects.create(
            code='demo_plus',
            display_name=f'{DEMO_CATALOG_TAG} Plus 플랜',
            price_krw=29000,
            description='[DEMO] Plus 플랜. 모든 기능 무제한.',
            limit_ocr=None,
            limit_ai_compare=None,
            limit_analysis=None,
            limit_promotion=None,
            is_active=True,
        )

        # demo 설계사 구독: 무료 플랜 활성
        # OneToOneField → 이미 존재하면 업데이트(signal 등에서 선생성 가능)
        Subscription.objects.update_or_create(
            user=planner,
            defaults={
                'plan': plan_free,
                'status': 'active',
                'expires_at': None,   # 무료 = 무기한
            },
        )

        # UsageMeter: 이번 달 일부 사용량 기록 (한도 내 정상 범위)
        usage_rows = [
            ('ocr', 3),
            ('ai_compare', 2),
            ('analysis', 5),
            ('promotion', 1),
        ]
        for action, count in usage_rows:
            UsageMeter.objects.create(
                user=planner, action=action, year_month=ym, count=count,
            )

        self.stdout.write(
            f'  [12] 빌링: Plan {plan_free.code} + {plan_plus.code} + '
            f'Subscription(demo, free, active) + UsageMeter {len(usage_rows)}행'
        )
