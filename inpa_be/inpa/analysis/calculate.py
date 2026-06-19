"""보험 분석 계산 엔진 (♻ foliio weapon/customers/calculate.py 벤더링 — 로직 무변경).

cp 후 import만 weapon.→inpa. 교정. 8케이스 보험료 엔진(numpy_financial.fv 포함) ·
calculate_analysis(차트별 한눈표/히트맵 입력) · calculate_total_analysis(표준 담보 트리
집계) 보존. 순수 계산(Claude API 불필요).

집계 단위 차이(foliio 무변경):
  - calculate_analysis     : case.detail.chart_detail 자연 매핑 (한 포트폴리오 차트 뷰)
  - calculate_total_analysis: case.detail.analysis_detail 매핑 (표준 담보 트리 집계 = 히트맵)
"""
import datetime

from dateutil.relativedelta import relativedelta

from inpa.insurances.serializers import CustomerInsuranceSerializer


def _safe_strptime(date_str, fmt='%Y.%m.%d'):
    """안전한 날짜 파싱. 실패 시 None 반환."""
    if not date_str:
        return None
    try:
        return datetime.datetime.strptime(date_str, fmt)
    except (ValueError, TypeError):
        return None


def calculate_analysis(birth_day, case_list, chart_list, insurance_list):
    monthly_premiums = 0  # 월 납입 보험료
    monthly_renewal_premium = 0  # 월 갱신 보험료
    monthly_non_renewal_premium = 0  # 월 비갱신 보험료
    monthly_earned_premium = 0  # 월 적립 보험료
    total_premiums = 0  # 총 보험료
    total_renewal_premium = 0  # 총 갱신 보험료
    total_non_renewal_premium = 0  # 총 비갱신 보험료
    total_earned_premium = 0  # 총 적립 보험료
    total_cancellation_refund = 0  # 총 환급금
    total_cancellation_loss = 0  # 총 손실금
    total_prepaid_insurance_premium = 0
    total_pay_insurance_premium = 0

    case_list_index = {}
    chart_list_index = {}
    chart_id_list = []

    for index, case in enumerate(case_list):
        case['total_premium'] = 0
        case['total_renewal_premium'] = 0
        case['total_non_renewal_premium'] = 0
        case['non_renewal_old_list'] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]  # 무조건 10개
        case['renewal_old_list'] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]  # 무조건 10개
        case['total_premium_list'] = [0] * len(insurance_list)
        case['is_show_old_price'] = False
        case_list_index[case.get('id')] = index

    for index, case in enumerate(chart_list):
        case['total_premium'] = 0
        case['total_renewal_premium'] = 0
        case['total_non_renewal_premium'] = 0
        chart_list_index[case.get('id')] = index
        chart_id_list.append(case.get('id'))

    for insurance_index, customer_insurance in enumerate(insurance_list):
        if customer_insurance.monthly_premiums is not None:
            monthly_premiums += customer_insurance.monthly_premiums
        if customer_insurance.monthly_renewal_premium is not None:
            monthly_renewal_premium += customer_insurance.monthly_renewal_premium
        if customer_insurance.monthly_non_renewal_premium is not None:
            monthly_non_renewal_premium += customer_insurance.monthly_non_renewal_premium

        if customer_insurance.monthly_earned_premium is not None:
            if customer_insurance.insurance_type == 1 and customer_insurance.payment_period_type == 1:
                monthly_earned_premium += customer_insurance.monthly_earned_premium
            elif customer_insurance.insurance_type == 2:
                monthly_earned_premium += customer_insurance.monthly_earned_premium

        if customer_insurance.total_premiums is not None:
            total_premiums += customer_insurance.total_premiums

        if customer_insurance.total_renewal_premium is not None:
            total_renewal_premium += customer_insurance.total_renewal_premium

        if customer_insurance.total_non_renewal_premium is not None:
            total_non_renewal_premium += customer_insurance.total_non_renewal_premium

        if customer_insurance.total_earned_premium is not None:
            total_earned_premium += customer_insurance.total_earned_premium

        # 기납회차 : 계약일, 확인일 Month
        # prepaid_months = 0
        # 기납보험료 : 기납 회차 * 월 보험료
        # prepaid_insurance_premium = prepaid_months * customer_insurance.monthly_premiums
        # 남은회차 아직 필요없음
        # pay_insurance_premium = total_premiums - prepaid_insurance_premium  # 낼 돈

        now_date = datetime.datetime.now()
        birth_day_date = None
        prepaid_months = 0
        contract_old = 0  # bugfix 2026-04-30: customer_insurance.old branch 에서 미초기화 → UnboundLocalError 방지

        # contract_date 는 두 분기 모두에서 사용되므로 먼저 파싱
        contract_date = _safe_strptime(customer_insurance.contract_date)
        if not contract_date:
            contract_date = now_date
        r = relativedelta(now_date, contract_date)
        prepaid_months = r.years * 12 + r.months

        if customer_insurance.payment_period_type == 1:
            if prepaid_months > (customer_insurance.non_renewal_month or 0):
                prepaid_months = customer_insurance.non_renewal_month or 0

        # 기납회차 : 계약일 기준
        if customer_insurance.old:
            # 사용자가 명시한 보험 나이 → contract_old 도 함께 도출
            start_old = customer_insurance.old
            contract_old = customer_insurance.old - (now_date.year - contract_date.year)
            if birth_day:
                birth_day_date = _safe_strptime(birth_day)
        elif birth_day:
            birth_day_date = _safe_strptime(birth_day)
            old_date = relativedelta(now_date, birth_day_date)
            old = old_date.years + 1
            start_old = old
            contract_old = old - (now_date.year - contract_date.year)
        else:
            start_old = 0
            contract_old = 0

        # 기납보험료 : 기납 회차 * 월 보험료
        _monthly_premiums = customer_insurance.monthly_premiums or 0
        prepaid_insurance_premium = prepaid_months * _monthly_premiums  # 낸 돈
        # 남은회차 아직 필요없음
        pay_insurance_premium = total_premiums - prepaid_insurance_premium  # 낼 돈

        total_prepaid_insurance_premium = total_prepaid_insurance_premium + prepaid_insurance_premium
        total_pay_insurance_premium = total_pay_insurance_premium + pay_insurance_premium

        # 환급금
        cancellation_refund = 0
        if customer_insurance.cancellation_refund:
            cancellation_refund = customer_insurance.cancellation_refund

        # 환급 손실금 : 기납 보험료 - 혜약환급금
        cancellation_loss = prepaid_insurance_premium - cancellation_refund
        total_cancellation_refund = total_cancellation_refund + cancellation_refund
        total_cancellation_loss = total_cancellation_loss + cancellation_loss

        customer_insurance_case_list = customer_insurance.case_list.all()
        for case in customer_insurance_case_list:
            index = case_list_index[case.detail.id]

            if case.payment_period_type == 1 or case.payment_period_type == 2:
                case_list[index]['total_non_renewal_premium'] += case.assurance_amount
            if case.payment_period_type == 3:
                case_list[index]['total_renewal_premium'] += case.assurance_amount

            case_list[index]['total_premium'] = case_list[index]['total_renewal_premium'] + case_list[index][
                'total_non_renewal_premium']

            case_list[index]['total_premium_list'][insurance_index] = case.assurance_amount

            # 담보별 warranty_period가 없으면 포트폴리오 레벨 값으로 fallback
            _warranty_period_type = case.warranty_period_type
            _warranty_period = case.warranty_period

            if _warranty_period_type < 4 and not _warranty_period:
                _warranty_period_type = customer_insurance.warranty_period_type or _warranty_period_type
                _warranty_period = customer_insurance.warranty_period
                if _warranty_period_type < 4 and not _warranty_period:
                    continue

            case_list[index]['is_show_old_price'] = True

            if _warranty_period_type == 2:  # 년 인경우
                end_old = contract_old + int(_warranty_period)
            if _warranty_period_type == 1:  # 세 인경우
                end_old = int(_warranty_period)
                if end_old > 100:
                    end_old = 100
            if _warranty_period_type == 3:  # 날짜
                _warranty_period_str = str(_warranty_period)
                if len(_warranty_period_str) == 8:
                    warranty_period_date = _safe_strptime(_warranty_period_str, '%Y%m%d')
                else:
                    warranty_period_date = _safe_strptime(_warranty_period_str, '%Y.%m.%d')
                if not warranty_period_date:
                    warranty_period_date = now_date

                if birth_day_date:
                    end_old = warranty_period_date.year - birth_day_date.year
                else:
                    end_old = start_old + warranty_period_date.year - now_date.year

            if _warranty_period_type == 4:  # 종신
                end_old = 100

            for old_index in range(0, 10):
                old_length_start = (old_index * 10)  # 나이 구간 시작
                old_length_end = (old_index * 10) + 10  # 나이 구간 끝

                # 가입 < end and start < 만기 (15 < 10 and 0 < 45)
                if start_old < old_length_end and old_length_start < end_old:
                    if case.payment_period_type == 1 or case.payment_period_type == 2:
                        case_list[index]['non_renewal_old_list'][old_index] += case.assurance_amount
                    if case.payment_period_type == 3:
                        case_list[index]['renewal_old_list'][old_index] += case.assurance_amount

            chart_detail_id_list = list(case.detail.chart_detail.values_list('id', flat=True))
            # 일반사망 / 재해사망 override 는 생명보험(insurance_type=1) 에서만 의미 있음.
            # 손해보험(type=2) 의 chart_id=1 은 "상해사망" 버킷이므로, 같은 override 를 적용하면
            # 일반사망 case 의 assurance 가 상해사망 차트에 잘못 합산됨 (2026-05-11 보험71 사례).
            # 손해보험에선 자연 매핑(case.detail.chart_detail) 유지.
            if customer_insurance.insurance_type == 1:
                if case.detail.name == '일반사망':
                    chart_detail_id_list = [1]
                if case.detail.name == '재해사망':
                    chart_detail_id_list = [2]

            for chart_id in chart_detail_id_list:
                if chart_id not in chart_id_list:
                    continue

                index = chart_list_index[chart_id]

                if case.payment_period_type == 1 or case.payment_period_type == 2:
                    chart_list[index]['total_non_renewal_premium'] += case.assurance_amount
                    # total_non_renewal_premium = case.assurance_amount
                if case.payment_period_type == 3:
                    chart_list[index]['total_renewal_premium'] += case.assurance_amount

                chart_list[index]['total_premium'] = chart_list[index]['total_renewal_premium'] + chart_list[index][
                    'total_non_renewal_premium']

    result = {
        'insurance_list': CustomerInsuranceSerializer(insurance_list, many=True).data,  # 기본정보
        'monthly_premiums': monthly_premiums,
        'monthly_renewal_premium': monthly_renewal_premium,
        'monthly_non_renewal_premium': monthly_non_renewal_premium,
        'monthly_earned_premium': monthly_earned_premium,
        'total_premiums': total_premiums,
        'total_renewal_premium': total_renewal_premium,
        'total_non_renewal_premium': total_non_renewal_premium,
        'total_earned_premium': total_earned_premium,
        'total_cancellation_refund': total_cancellation_refund,
        'total_cancellation_loss': total_cancellation_loss,
        'total_prepaid_insurance_premium': total_prepaid_insurance_premium,
        'total_pay_insurance_premium': total_pay_insurance_premium,
        'case_list': case_list,
        'chart_list': chart_list,
    }

    return result


def calculate_total_analysis(birth_day, case_list, chart_list, insurance_list):
    monthly_premiums = 0  # 월 납입 보험료
    monthly_renewal_premium = 0  # 월 갱신 보험료
    monthly_non_renewal_premium = 0  # 월 비갱신 보험료
    monthly_earned_premium = 0  # 월 적립 보험료
    total_premiums = 0  # 총 보험료
    total_renewal_premium = 0  # 총 갱신 보험료
    total_non_renewal_premium = 0  # 총 비갱신 보험료
    total_earned_premium = 0  # 총 적립 보험료
    total_cancellation_refund = 0  # 총 환급금
    total_cancellation_loss = 0  # 총 손실금
    total_prepaid_insurance_premium = 0
    total_pay_insurance_premium = 0

    case_list_index = {}
    case_id_list = []
    chart_list_index = {}
    chart_id_list = []

    for index, case in enumerate(case_list):
        case['total_premium'] = 0
        case['total_renewal_premium'] = 0
        case['total_non_renewal_premium'] = 0
        case['non_renewal_old_list'] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]  # 무조건 10개
        case['renewal_old_list'] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]  # 무조건 10개
        case['total_premium_list'] = [0] * len(insurance_list)
        case['is_show_old_price'] = False
        case_list_index[case.get('id')] = index
        case_id_list.append(case.get('id'))

    for index, case in enumerate(chart_list):
        case['total_premium'] = 0
        case['total_renewal_premium'] = 0
        case['total_non_renewal_premium'] = 0
        chart_list_index[case.get('id')] = index
        chart_id_list.append(case.get('id'))

    for insurance_index, customer_insurance in enumerate(insurance_list):
        if customer_insurance.monthly_premiums is not None:
            monthly_premiums += customer_insurance.monthly_premiums
        if customer_insurance.monthly_renewal_premium is not None:
            monthly_renewal_premium += customer_insurance.monthly_renewal_premium
        if customer_insurance.monthly_non_renewal_premium is not None:
            monthly_non_renewal_premium += customer_insurance.monthly_non_renewal_premium

        if customer_insurance.monthly_earned_premium is not None:
            if customer_insurance.insurance_type == 1 and customer_insurance.payment_period_type == 1:
                monthly_earned_premium += customer_insurance.monthly_earned_premium
            elif customer_insurance.insurance_type == 2:
                monthly_earned_premium += customer_insurance.monthly_earned_premium

        if customer_insurance.total_premiums is not None:
            total_premiums += customer_insurance.total_premiums

        if customer_insurance.total_renewal_premium is not None:
            total_renewal_premium += customer_insurance.total_renewal_premium

        if customer_insurance.total_non_renewal_premium is not None:
            total_non_renewal_premium += customer_insurance.total_non_renewal_premium

        if customer_insurance.total_earned_premium is not None:
            total_earned_premium += customer_insurance.total_earned_premium

        now_date = datetime.datetime.now()
        prepaid_months = 0
        # 기납회차 : 계약일, 확인일 Month
        if customer_insurance.old:
            contract_old = customer_insurance.old
            start_old = customer_insurance.old
        else:
            contract_date = _safe_strptime(customer_insurance.contract_date)
            if not contract_date:
                contract_date = now_date
            r = relativedelta(now_date, contract_date)
            prepaid_months = r.years * 12 + r.months

            if customer_insurance.payment_period_type == 1:
                if prepaid_months > (customer_insurance.non_renewal_month or 0):
                    prepaid_months = customer_insurance.non_renewal_month or 0

            if birth_day:
                birth_day_date = _safe_strptime(birth_day)
                old_date = relativedelta(now_date, birth_day_date)
                old = old_date.years + 1
                start_old = old
                contract_old = old - (now_date.year - contract_date.year)
            else:
                start_old = 0
                contract_old = 0

        # 기납보험료 : 기납 회차 * 월 보험료
        _monthly_premiums = customer_insurance.monthly_premiums or 0
        prepaid_insurance_premium = prepaid_months * _monthly_premiums  # 낸 돈
        # 남은회차 아직 필요없음
        _total_premiums = customer_insurance.total_premiums or 0
        pay_insurance_premium = _total_premiums - prepaid_insurance_premium  # 낼 돈

        total_prepaid_insurance_premium = total_prepaid_insurance_premium + prepaid_insurance_premium
        total_pay_insurance_premium = total_pay_insurance_premium + pay_insurance_premium
        # 환급금
        cancellation_refund = 0
        if customer_insurance.cancellation_refund:
            cancellation_refund = customer_insurance.cancellation_refund

        # 환급 손실금 : 기납 보험료 - 혜약환급금
        cancellation_loss = prepaid_insurance_premium - cancellation_refund
        total_cancellation_refund = total_cancellation_refund + cancellation_refund
        total_cancellation_loss = total_cancellation_loss + cancellation_loss

        customer_insurance_case_list = customer_insurance.case_list.all()

        for case in customer_insurance_case_list:
            analysis_detail_id_list = list(case.detail.analysis_detail.values_list('id', flat=True))
            for analysis_id in analysis_detail_id_list:
                if analysis_id not in case_id_list:
                    continue

                index = case_list_index[analysis_id]

                if case.payment_period_type == 1 or case.payment_period_type == 2:
                    case_list[index]['total_non_renewal_premium'] += case.assurance_amount
                if case.payment_period_type == 3:
                    case_list[index]['total_renewal_premium'] += case.assurance_amount

                case_list[index]['total_premium'] = case_list[index]['total_renewal_premium'] + case_list[index][
                    'total_non_renewal_premium']

                case_list[index]['total_premium_list'][insurance_index] = case.assurance_amount

                # 담보별 warranty_period가 없으면 포트폴리오 레벨 값으로 fallback
                _warranty_period_type = case.warranty_period_type
                _warranty_period = case.warranty_period

                if _warranty_period_type < 4 and not _warranty_period:
                    _warranty_period_type = customer_insurance.warranty_period_type or _warranty_period_type
                    _warranty_period = customer_insurance.warranty_period
                    if _warranty_period_type < 4 and not _warranty_period:
                        continue

                case_list[index]['is_show_old_price'] = True

                if _warranty_period_type == 2:  # 년 인경우
                    end_old = contract_old + int(_warranty_period)
                if _warranty_period_type == 1:  # 세 인경우
                    end_old = int(_warranty_period)
                    if end_old > 100:
                        end_old = 100
                if _warranty_period_type == 3:  # 날짜
                    _warranty_period_str = str(_warranty_period)
                    if len(_warranty_period_str) == 8:
                        warranty_period_date = datetime.datetime.strptime(_warranty_period_str, '%Y%m%d')
                    else:
                        warranty_period_date = datetime.datetime.strptime(_warranty_period_str, '%Y.%m.%d')

                    if birth_day_date:
                        end_old = warranty_period_date.year - birth_day_date.year
                    else:
                        end_old = start_old + warranty_period_date.year - now_date.year

                if _warranty_period_type == 4:  # 종신
                    end_old = 100

                for old_index in range(0, 10):
                    old_length_start = (old_index * 10)  # 나이 구간 시작
                    old_length_end = (old_index * 10) + 10  # 나이 구간 끝

                    # 가입 < end and start < 만기 (15 < 10 and 0 < 45)
                    if start_old < old_length_end and old_length_start < end_old:
                        if case.payment_period_type == 1 or case.payment_period_type == 2:
                            case_list[index]['non_renewal_old_list'][old_index] += case.assurance_amount
                        if case.payment_period_type == 3:
                            case_list[index]['renewal_old_list'][old_index] += case.assurance_amount

            chart_detail_id_list = list(case.detail.chart_detail.values_list('id', flat=True))
            for chart_id in chart_detail_id_list:
                if chart_id not in chart_id_list:
                    continue

                index = chart_list_index[chart_id]

                if case.payment_period_type == 1 or case.payment_period_type == 2:
                    chart_list[index]['total_non_renewal_premium'] += case.assurance_amount
                    # total_non_renewal_premium = case.assurance_amount
                if case.payment_period_type == 3:
                    chart_list[index]['total_renewal_premium'] += case.assurance_amount

                chart_list[index]['total_premium'] = chart_list[index]['total_renewal_premium'] + chart_list[index][
                    'total_non_renewal_premium']

    result = {
        'insurance_list': CustomerInsuranceSerializer(insurance_list, many=True).data,  # 기본정보
        'monthly_premiums': monthly_premiums,
        'monthly_renewal_premium': monthly_renewal_premium,
        'monthly_non_renewal_premium': monthly_non_renewal_premium,
        'monthly_earned_premium': monthly_earned_premium,
        'total_premiums': total_premiums,
        'total_renewal_premium': total_renewal_premium,
        'total_non_renewal_premium': total_non_renewal_premium,
        'total_earned_premium': total_earned_premium,
        'total_cancellation_refund': total_cancellation_refund,
        'total_cancellation_loss': total_cancellation_loss,
        'total_prepaid_insurance_premium': total_prepaid_insurance_premium,
        'total_pay_insurance_premium': total_pay_insurance_premium,
        'case_list': case_list,
        'chart_list': chart_list,
    }

    return result
