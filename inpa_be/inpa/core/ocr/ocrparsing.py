# from inpa.core.ocr.LIG.ligmain import LIG_company_parsing
# from inpa.core.ocr.SAMSUNG.samsungmain import SAMSUNG_company_parsing
import json
import os
import threading
from inpa.core.ocr.ocrdata import Ocr_Data, LossInsurance, LifeInsurance
import re
from datetime import datetime

# def ocr_parsing(extract_data_list):
#     lst_result = None
#     if any("LIG" in item for item in extract_data_list):
#         cls_ocr_data = LIG_company_parsing(extract_data_list)
#     elif any("삼성" in item for item in extract_data_list):
#         cls_ocr_data = SAMSUNG_company_parsing(extract_data_list)

#     return cls_ocr_data


def is_number(value):
    return isinstance(value, (int, float))


def find_string_by_number(data_list, keyword, position):
    for data in data_list:
        # 키워드 위치 찾기
        keyword_index = data.find(keyword)

        if keyword_index != -1:
            if position < 0:  # 키워드 앞의 문자열을 찾음
                if position == -1:
                    # 키워드와 붙어있는 문자열 추출 (앞쪽)
                    pre_search = data[:keyword_index].strip()

                    # 마지막 공백 이후의 문자열 추출
                    last_space_index = pre_search.rfind(' ')
                    result = pre_search[last_space_index + 1:] if last_space_index != -1 else pre_search
                    return result
                else:
                    lst_data = data.split()
                    indexes = [index for index, element in enumerate(lst_data) if keyword in element]
                    search_index = indexes[0] + position + 1
                    return lst_data[search_index]
            else:
                if position == 1:
                    post_search = data[keyword_index + len(keyword):].strip()

                    # 첫 번째 공백 전까지의 문자열 추출
                    first_space_index = post_search.find(' ')
                    result = post_search[:first_space_index] if first_space_index != -1 else post_search
                    return result

                else:
                    lst_data = data.split()
                    search_index = lst_data.index(keyword) + position - 1
                    return lst_data[search_index]
    return None


def find_string_by_string(extract_data_list, search_word, search_split):
    # if 'R(' in search_split:
    #     loc_info = search_split.split(':')
    #     remove_word = loc_info[0][2:-1]
    #     for i, data in enumerate(extract_data_list):
    #         if search_word in data:
    #             if remove_word in data:
    #                 return None
    #             lst_part_data = []
    #             lst_part_data_length = len(loc_info)
    #             part_index = 1
    #             while part_index < lst_part_data_length:
    #                 lst_part_data.append(loc_info[part_index])
    #                 part_index = part_index + 1
    #             part_search_split = ':'.join(lst_part_data)
    #             result = find_string_by_string([data], search_word, part_search_split)
    #             return result
    #     return None

    if 'S(' in search_split:
        loc_info = search_split.split(':')
        if len(loc_info) == 4:
            up_and_down_offset = int(loc_info[0])
            left_and_right_offset = int(loc_info[1])
            split_char = loc_info[2][2:-1]  # S() 안의 문자 추출
            target_index = int(loc_info[3])

            for i, data in enumerate(extract_data_list):
                if search_word in data:
                    if up_and_down_offset != 0:
                        data = extract_data_list[i+up_and_down_offset]
                        lst_data = data.split()
                        find_data = lst_data[left_and_right_offset]
                        target_data = find_data.split(split_char)
                    else:
                        #lst_data = data.split(search_word)
                        search_word_index = data.index(search_word) + len(search_word)
                        if search_word_index < len(data):
                            lst_space_data = data.split(search_word)
                            lst_indexes = [index for index, item in enumerate(lst_space_data) if search_word in item]
                            if left_and_right_offset > 0:
                                result = find_string_by_number([lst_space_data[1]], split_char, target_index)
                            elif left_and_right_offset < 0:
                                result = find_string_by_number([lst_space_data[0]], split_char, target_index)
                        else:
                            # search_word_index = data.index(search_word)
                            # lst_data = data[:search_word_index].split()
                            search_word_index = data.index(search_word) + len(search_word)
                            if search_word_index < len(data):
                                lst_space_data = data.split(search_word)
                                lst_indexes = [index for index, item in enumerate(lst_space_data) if search_word in item]
                                if left_and_right_offset > 0:
                                    pass
                                elif left_and_right_offset < 0:
                                    result = find_string_by_number(lst_space_data, split_char, left_and_right_offset)
                    return result.strip()

        return None

    elif '년 월 일' in search_split:
        loc_info = search_split.split(':')
        index_offset = int(loc_info[0])
        date_format = loc_info[1].split()
        target_index = int(loc_info[2])

        for i, data in enumerate(extract_data_list):
            if search_word in data:
                target_i = i + index_offset
                if 0 <= target_i < len(extract_data_list):
                    target_data = extract_data_list[target_i].split()
                    date_indices = [idx for idx, part in enumerate(target_data) if any(df in part for df in date_format)]
                    start_idx = date_indices[target_index*3]
                    result = ' '.join(target_data[start_idx:start_idx + len(date_format)])
                    # '년', '월'을 '.'로 대체하고, '일'을 제거
                    formatted_result = result.replace('년 ', '.').replace('월 ', '.').replace('일', '')
                    return formatted_result
    elif search_split.find(':') == 0:
        position = int(search_split[1:])
        for i, data in enumerate(extract_data_list):
            if search_word in data:
                keyword_index = data.find(search_word)
                if position == -1:
                    # 키워드와 붙어있는 문자열 추출 (앞쪽)
                    result = data[:keyword_index]
                    return result
                else:
                    result = data[:keyword_index+position+1]
                    return result
    elif search_split.find(':') > 0 and search_split.find('SPACE') > 0:
        lst_search_split = search_split.split(':')
        for data in extract_data_list:
            if search_word in data:
                start_index = data.find(search_word) + len(search_word) + int(lst_search_split[0])-1
                space_count = 0
                end_index = start_index

                # 다음 공백까지의 문자열 추출
                while space_count <= int(lst_search_split[2]) and end_index < len(data):
                    if data[end_index] == ' ':
                        space_count += 1
                    end_index += 1

                result = data[start_index:end_index].strip()
                return result
    elif search_split.find(':') > 0:
        lst_search_split = search_split.split(':')
        up_and_down_offset = int(lst_search_split[0])
        left_and_right_offset = int(lst_search_split[1])
        for i, data in enumerate(extract_data_list):
                if search_word in data:
                    if up_and_down_offset != 0:
                        data = extract_data_list[i+up_and_down_offset]
                        lst_data = data.split()
                        result = lst_data[left_and_right_offset]
                        return result


# extract_data_list : ocr에서 읽은 전체 데이터
# dict_detail_data : 화면에 보여주기 위해 저장할 카테고리
# arr_detail_data : json을 중심으로 파싱하기 위한 규격 및 정의
def find_detail_data(extract_data_list, lst_check_use_data, dict_detail_data, arr_detail_data):
    #try:
        for i, data in enumerate(extract_data_list):
            # lst_detail_data의 모든 원소가 data 문자열 안에 있는지 확인
            if lst_check_use_data[i] == 1:
                continue
            lst_detail_data_species = arr_detail_data['분류'].split()
            all_exist = all(element in data for element in lst_detail_data_species)
            if all_exist == True:
                lst_class_value = arr_detail_data['위치'].split('->')
                str_first_value = lst_class_value[0].replace(' ', '')
                if str_first_value in dict_detail_data:
                    str_sub_value = lst_class_value[1]
                    if str_sub_value in dict_detail_data[str_first_value]:
                        str_total_value = lst_class_value[2]
                        str_value = ''
                        key_exists = any("납입기간" in item for item in arr_detail_data.keys())
                        if key_exists == True:
                            try:
                                search_word = arr_detail_data['납입기간']
                                if is_number(arr_detail_data['납입기간_LOC']):
                                    data_pos = arr_detail_data['납입기간_LOC']
                                    payment_period_data = int(find_string_by_number([data], search_word, data_pos))
                                    payment_period_unit = arr_detail_data['납입기간단위']
                                    str_value = f'{payment_period_data}:{payment_period_unit}'
                            except (ValueError, IndexError, KeyError) as e:
                                print(f'template parsing error (납입기간): {e}')
                                break

                        key_exists = any("보장기간" in item for item in arr_detail_data.keys())
                        if key_exists == True:
                            try:
                                search_word = arr_detail_data['보장기간']
                                if is_number(arr_detail_data['보장기간_LOC']):
                                    data_pos = arr_detail_data['보장기간_LOC']
                                    coverage_period_data = int(find_string_by_number([data], search_word, data_pos))
                                else:
                                    search_split = arr_detail_data['보장기간_LOC']
                                    coverage_period_data = int(find_string_by_string([data], search_word, search_split))
                                coverage_period_unit = arr_detail_data['보장기간단위']
                                str_value = f'{str_value}:{coverage_period_data}:{coverage_period_unit}'
                            except (ValueError, IndexError, KeyError) as e:
                                print(f'template parsing error (보장기간): {e}')
                                break
                        key_exists = any("보장금액" in item for item in arr_detail_data.keys())
                        if key_exists == True:
                            try:
                                if arr_detail_data['보장금액'] == 'last':
                                    lst_data = data.split()
                                    str_coverage_amount = lst_data[-1].replace(',', '').replace('원', '').replace('(', '').replace(')', '')
                                    coverage_amount = int(str_coverage_amount)
                                else:
                                    search_word = arr_detail_data['보장금액']
                                    if is_number(arr_detail_data['보장금액_LOC']):
                                        data_pos = arr_detail_data['보장금액_LOC']
                                        coverage_period_data = find_string_by_number([data], search_word, data_pos)
                                        str_coverage_amount = coverage_period_data.replace(',', '').replace('원', '').replace('(', '').replace(')', '')
                                        coverage_amount = int(str_coverage_amount)
                            except (ValueError, IndexError, KeyError) as e:
                                print(f'template parsing error (보장금액): {e}')
                                break

                        str_value = f'{str_value}:{coverage_amount}'
                        dict_detail_data[str_first_value][str_sub_value][str_total_value].append(str_value)
                        lst_check_use_data[i] = 1
        return
    # except:
    #     print("ERROR!!!!!!!!!!!!!!!")
    #     return


def add_asterisks(search_data):
    # '-1' 또는 '-2' 뒤의 위치 찾기
    index_1 = search_data.find('-1')
    index_2 = search_data.find('-2')

    # 가장 마지막 위치 결정 (둘 중 하나는 -1이 될 수 있음)
    index = max(index_1, index_2)

    # ')' 바로 앞의 공백 제거
    search_data = search_data.replace(' )', ')')

    if index != -1:
        # '-1' 또는 '-2' 다음의 부분을 추출
        part_after = search_data[index + 2:]

        # '*'의 개수 세기
        asterisk_count = part_after.count('*')

        # '*'가 6개 미만이면 필요한 만큼 추가
        if asterisk_count < 6:
            additional_asterisks = '*' * (6 - asterisk_count)
            search_data = search_data[:index + 2] + additional_asterisks + part_after.lstrip('*')

    return search_data


def _extract_optional_currency_field(extract_data_list, ocr_data, target_dict, field_name):
    """템플릿에 정의된 금액 필드를 추출. 키가 없으면 스킵."""
    try:
        search_word = ocr_data[field_name]
        loc_key = f'{field_name}_LOC'
        if is_number(ocr_data[loc_key]):
            data_pos = ocr_data[loc_key]
            search_data = find_string_by_number(extract_data_list, search_word, data_pos)
        else:
            data_pos = ocr_data[loc_key]
            search_data = find_string_by_string(extract_data_list, search_word, data_pos)
        search_data = search_data.replace(',', '').replace('원', '').replace('(', '').replace(')', '')
        target_dict[field_name] = int(search_data)
    except (KeyError, ValueError, TypeError, AttributeError):
        pass


def _extract_optional_number_field(extract_data_list, ocr_data, target_dict, field_name):
    """템플릿에 정의된 숫자 필드를 추출. 키가 없으면 스킵."""
    try:
        search_word = ocr_data[field_name]
        loc_key = f'{field_name}_LOC'
        if is_number(ocr_data[loc_key]):
            data_pos = ocr_data[loc_key]
            search_data = find_string_by_number(extract_data_list, search_word, data_pos)
        else:
            data_pos = ocr_data[loc_key]
            search_data = find_string_by_string(extract_data_list, search_word, data_pos)
        target_dict[field_name] = int(float(search_data))
    except (KeyError, ValueError, TypeError, AttributeError):
        pass


def get_ocr_data(extract_data_list, ocr_data):
    ocrdata = Ocr_Data()
    if ocr_data['보험종류'] == 0:
        life_company = ocr_data['생명보험']
        ocrdata.dict_life_head_data['생명보험'] = LifeInsurance.company.index(life_company)
        ocrdata.dict_life_head_data['상품명'] = ocr_data['상품명']
        search_word = ocr_data['계약자']
        if is_number(ocr_data['계약자_LOC']):
            pass
        else:
            # search_data = find_string_by_string(extract_data_list, search_word, data_pos)
            # modified_data = add_asterisks(search_data)
            data_pos = ocr_data['계약자_LOC']
            search_data = find_string_by_string(extract_data_list, search_word, data_pos)
            ocrdata.dict_life_head_data['계약자'] = search_data
        search_word = ocr_data['납입기간']
        if is_number(ocr_data['납입기간_LOC']):
            pass
        else:
            data_pos = ocr_data['납입기간_LOC']
            search_data = find_string_by_string(extract_data_list, search_word, data_pos)
            search_data = search_data.replace(' ', '')
            # '~' 또는 '-'를 기준으로 날짜 분리
            dates = re.split('~|-', search_data)

            # 정규 표현식을 사용하여 날짜 형식 확인
            valid_dates = len(dates) >= 2 and all(
                re.match(r'\d{4}\.\d{2}\.\d{2}', d) for d in dates[:2]
            )

            if valid_dates:
                # 날짜 포맷 변경
                date_format = "%Y.%m.%d"
                date1 = datetime.strptime(dates[0], date_format)
                date2 = datetime.strptime(dates[1], date_format)

                # 년수 차이 계산
                year_difference = abs(date2.year - date1.year)
                ocrdata.dict_life_head_data['납입기간'] = year_difference
                ocrdata.dict_life_head_data['계약일'] = dates[0]
                ocrdata.dict_life_head_data['만기일'] = dates[1]

        search_word = ocr_data['피보험자']
        if is_number(ocr_data['피보험자_LOC']):
            data_pos = ocr_data['피보험자_LOC']
            search_data = find_string_by_number(extract_data_list, search_word, data_pos)
            ocrdata.dict_life_head_data['피보험자'] = search_data

        search_word = ocr_data['보장기간']
        try:
            if is_number(ocr_data['보장기간_LOC']):
                data_pos = ocr_data['보장기간_LOC']
                search_data = find_string_by_number(extract_data_list, search_word, data_pos)
                ocrdata.dict_life_head_data['보장기간'] = int(search_data)
            else:
                data_pos = ocr_data['보장기간_LOC']
                search_data = find_string_by_string(extract_data_list, search_word, data_pos)
                ocrdata.dict_life_head_data['보장기간'] = int(search_data)
        except (KeyError, ValueError, TypeError) as e:
            ocrdata.dict_life_head_data['보장기간'] = search_word

        search_word = ocr_data['월납입보험료']
        if is_number(ocr_data['월납입보험료_LOC']):
            data_pos = ocr_data['월납입보험료_LOC']
            search_data = find_string_by_number(extract_data_list, search_word, data_pos)
            search_data = search_data.replace(',', '').replace('원', '').replace('(', '').replace(')', '')
            ocrdata.dict_life_head_data['월납입보험료'] = int(search_data)
        else:
            data_pos = ocr_data['월납입보험료_LOC']
            search_data = find_string_by_string(extract_data_list, search_word, data_pos)
            search_data = search_data.replace(',', '').replace('원', '').replace('(', '').replace(')', '')
            ocrdata.dict_life_head_data['월납입보험료'] = int(search_data)

        # === 추가 필드 추출 (템플릿에 정의된 경우에만) ===
        _extract_optional_currency_field(extract_data_list, ocr_data, ocrdata.dict_life_head_data, '월주계약보험료')
        _extract_optional_currency_field(extract_data_list, ocr_data, ocrdata.dict_life_head_data, '월특약보험료')
        _extract_optional_currency_field(extract_data_list, ocr_data, ocrdata.dict_life_head_data, '월적립보험료')
        _extract_optional_currency_field(extract_data_list, ocr_data, ocrdata.dict_life_head_data, '해약환급금')
        _extract_optional_number_field(extract_data_list, ocr_data, ocrdata.dict_life_head_data, '갱신증가율')
        _extract_optional_number_field(extract_data_list, ocr_data, ocrdata.dict_life_head_data, '갱신특약만기일')

    else:
        loss_company = ocr_data['손해보험']
        ocrdata.dict_loss_head_data['손해보험'] = LossInsurance.company.index(loss_company)
        ocrdata.dict_loss_head_data['상품명'] = ocr_data['상품명']
        search_word = ocr_data['계약자']
        if is_number(ocr_data['계약자_LOC']):
            data_pos = ocr_data['계약자_LOC']
            search_data = find_string_by_number(extract_data_list, search_word, data_pos)
            ocrdata.dict_loss_head_data['계약자'] = search_data
        else:
            # search_data = find_string_by_string(extract_data_list, search_word, data_pos)
            # modified_data = add_asterisks(search_data)
            data_pos = ocr_data['계약자_LOC']
            search_data = find_string_by_string(extract_data_list, search_word, data_pos)
            ocrdata.dict_loss_head_data['계약자'] = search_data

        search_word = ocr_data['납입기간']
        if is_number(ocr_data['납입기간_LOC']):
            data_pos = ocr_data['납입기간_LOC']
            search_data = find_string_by_number(extract_data_list, search_word, data_pos)
            ocrdata.dict_loss_head_data['납입기간'] = int(search_data)
        else:
            data_pos = ocr_data['납입기간_LOC']
            search_data = find_string_by_string(extract_data_list, search_word, data_pos)
            search_data = search_data.replace(' ', '')
            # '~' 또는 '-'를 기준으로 날짜 분리
            dates = re.split('~|-', search_data)

            # 정규 표현식을 사용하여 날짜 형식 확인
            valid_dates = len(dates) >= 2 and all(
                re.match(r'\d{4}\.\d{2}\.\d{2}', d) for d in dates[:2]
            )

            if valid_dates:
                # 날짜 포맷 변경
                date_format = "%Y.%m.%d"
                date1 = datetime.strptime(dates[0], date_format)
                date2 = datetime.strptime(dates[1], date_format)

                # 년수 차이 계산
                year_difference = abs(date2.year - date1.year)
                ocrdata.dict_loss_head_data['납입기간'] = year_difference
                ocrdata.dict_loss_head_data['계약일'] = dates[0]
                ocrdata.dict_loss_head_data['만기일'] = dates[1]

        search_word = ocr_data['피보험자']
        if is_number(ocr_data['피보험자_LOC']):
            data_pos = ocr_data['피보험자_LOC']
            search_data = find_string_by_number(extract_data_list, search_word, data_pos)
            ocrdata.dict_loss_head_data['피보험자'] = search_data
        else:
            search_split = ocr_data['피보험자_LOC']
            search_data = find_string_by_string(extract_data_list, search_word, search_split)
            ocrdata.dict_loss_head_data['피보험자'] = search_data

        search_word = ocr_data['보장기간']
        try:
            if is_number(ocr_data['보장기간_LOC']):
                data_pos = ocr_data['보장기간_LOC']
                search_data = find_string_by_number(extract_data_list, search_word, data_pos)
                ocrdata.dict_loss_head_data['보장기간'] = int(search_data)
        except KeyError as e:
            ocrdata.dict_loss_head_data['보장기간'] = search_word

        search_word = ocr_data['월보장보험료']
        if is_number(ocr_data['월보장보험료_LOC']):
            data_pos = ocr_data['월보장보험료_LOC']
            search_data = find_string_by_number(extract_data_list, search_word, data_pos)
            # ','와 '원' 문자 제거
            search_data = search_data.replace(',', '').replace('원', '').replace('(', '').replace(')', '')
            ocrdata.dict_loss_head_data['월보장보험료'] = int(search_data)
        else:
            data_pos = ocr_data['월보장보험료_LOC']
            search_data = find_string_by_string(extract_data_list, search_word, data_pos)
            search_data = search_data.replace(',', '').replace('원', '').replace('(', '').replace(')', '')
            ocrdata.dict_loss_head_data['월보장보험료'] = int(search_data)

        try:
            search_word = ocr_data['계약일']
            if is_number(ocr_data['계약일_LOC']):
                pass
            else:
                search_split = ocr_data['계약일_LOC']
                search_data = find_string_by_string(extract_data_list, search_word, search_split)
                ocrdata.dict_loss_head_data['계약일'] = search_data
        except KeyError as e:
            pass

        try:
            search_word = ocr_data['만기일']
            if is_number(ocr_data['만기일_LOC']):
                pass
            else:
                search_split = ocr_data['만기일_LOC']
                search_data = find_string_by_string(extract_data_list, search_word, search_split)
                ocrdata.dict_loss_head_data['만기일'] = search_data
        except KeyError as e:
            pass

        try:
            search_word = ocr_data['월적립보험료']
            if is_number(ocr_data['월적립보험료_LOC']):
                data_pos = ocr_data['월적립보험료_LOC']
                search_data = find_string_by_number(extract_data_list, search_word, data_pos)
                # ','와 '원' 문자 제거
                search_data = search_data.replace(',', '').replace('원', '').replace('(', '').replace(')', '')
                ocrdata.dict_loss_head_data['월적립보험료'] = int(search_data)
            else:
                data_pos = ocr_data['월적립보험료_LOC']
                search_data = find_string_by_string(extract_data_list, search_word, data_pos)
                search_data = search_data.replace(',', '').replace('원', '').replace('(', '').replace(')', '')
                ocrdata.dict_loss_head_data['월적립보험료'] = int(search_data)
        except KeyError as e:
            pass

        # === 추가 필드 추출 (템플릿에 정의된 경우에만) ===
        _extract_optional_currency_field(extract_data_list, ocr_data, ocrdata.dict_loss_head_data, '월갱신보험료')
        _extract_optional_currency_field(extract_data_list, ocr_data, ocrdata.dict_loss_head_data, '월납입보험료')
        _extract_optional_currency_field(extract_data_list, ocr_data, ocrdata.dict_loss_head_data, '해약환급금')
        _extract_optional_number_field(extract_data_list, ocr_data, ocrdata.dict_loss_head_data, '갱신증가율')

        # 담보별 세부사항
        try:
            arr_detail_data = ocr_data['세부사항']
            # 분류가 긴 순서대로 정렬
            sorted_arr_detail_data = sorted(arr_detail_data, key=lambda d: -len(d['분류']))
            # extract_data_list의 길이만큼 0으로 채워진 새로운 리스트 생성
            lst_check_use_data = [0 for _ in extract_data_list]
            for detail_data in sorted_arr_detail_data:
                find_detail_data(extract_data_list, lst_check_use_data, ocrdata.dict_detail_data, detail_data)
        except KeyError as e:
            pass

    return ocrdata


_json_cache = {}
_json_cache_lock = threading.Lock()


def _load_json_cached(filepath):
    """JSON 파일을 캐시해서 반환 (디스크 I/O 최소화, 스레드 안전)"""
    if filepath not in _json_cache:
        with _json_cache_lock:
            # double-check locking
            if filepath not in _json_cache:
                with open(filepath, 'r', encoding='utf-8') as f:
                    _json_cache[filepath] = json.load(f)
    return _json_cache[filepath]


def ocr_parsing(extract_data_list):
    if not extract_data_list:
        print('ocr_parsing: extract_data_list is empty')
        return Ocr_Data()

    current_path = os.getcwd()
    jsonpath = os.path.join(current_path, 'ocrdata/insurancelist/list.json')

    try:
        json_data = _load_json_cached(jsonpath)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f'ocr_parsing: list.json load error: {e}')
        return Ocr_Data()

    # 상품명이 extract_data_list에 포함되어 있는 경우 해당 위치 반환
    str_location = ''
    matched_product = ''
    for product in json_data.get("보험", []):
        product_name = product.get("상품명", "")
        for extracted_text in extract_data_list:
            if product_name and product_name in extracted_text:
                str_location = product.get("위치", "")
                matched_product = product_name

    if not str_location:
        print(f'ocr_parsing: no matching product found in OCR text, trying regex fallback')
        try:
            fallback_result = regex_fallback_parse(extract_data_list)
            if _has_meaningful_data(fallback_result):
                return fallback_result
        except Exception as e:
            print(f'regex fallback error: {e}')
        return Ocr_Data()

    try:
        insurance_json_path = os.path.join(current_path, str_location)
        ocr_data = _load_json_cached(insurance_json_path)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f'ocr_parsing: insurance json load error ({str_location}): {e}')
        return Ocr_Data()

    print(f'ocr_parsing: matched product "{matched_product}", template: {str_location}')
    try:
        cls_ocr_data = get_ocr_data(extract_data_list, ocr_data)
        if _has_meaningful_data(cls_ocr_data):
            cls_ocr_data.parsing_method = 'template'
            return cls_ocr_data
        else:
            print(f'ocr_parsing: template produced no meaningful data, trying regex fallback')
    except Exception as e:
        print(f'ocr_parsing: template parsing error: {e}, trying regex fallback')

    # template 실패 시 regex fallback
    try:
        fallback_result = regex_fallback_parse(extract_data_list)
        if _has_meaningful_data(fallback_result):
            return fallback_result
    except Exception as e:
        print(f'regex fallback error: {e}')
    return Ocr_Data()


# ============================================================
# 범용 정규식 fallback 파서
# 템플릿 매칭 실패 시 정규식으로 기본 정보 추출
# ============================================================

# 담보명 → dict_detail_data 경로 매핑
# 순서 중요: 더 구체적인(긴) 키워드를 먼저 매칭하도록 정렬
COVERAGE_KEYWORDS = {
    # === 유사암 (일반암보다 먼저 체크 - "유사암" 포함 키워드 우선) ===
    '진단비->암->유사암': ['유사암', '소액암', '상피내암', '경계성종양', '기타피부암', '갑상선암', '제자리암',
                          '상피내', '대장점막내암', '전립선암', '방광암'],
    # === 사망 ===
    # 주의: "보통약관(상해사망)"은 기본 사망이므로 일반사망에 포함 (상해사망보다 먼저 매칭)
    '사망->일반->일반사망': ['일반사망', '사망보험금', '사망보장', '보통약관(사망)', '사망담보',
                           '사망후유장해', '사망(재해제외)',
                           '보통약관(상해사망)', '보통약관사망',
                           '변액종신', '변액유니버셜종신', '변액사망', '변액보험사망'],
    '사망->질병->질병사망': ['질병사망', '질병으로인한사망'],
    '사망->상해->상해사망': ['상해사망', '상해로사망', '일반상해사망', '교통상해사망',
                           '대중교통상해사망'],
    '사망->재해->재해사망': ['재해사망'],
    # === 상해 ===
    '상해->상해->상해후유장애': ['상해후유장애', '후유장해', '상해후유장해',
                               '일반상해일반후유장해', '일반상해고도후유장해',
                               '일반상해후유장해', '교통상해후유장해', '대중교통후유장해',
                               '기본계약(상해후유장해)', '질병후유장해',
                               '질병80%이상후유장해', '상해80%이상후유장해',
                               '상해(3~100%)', '상해(80%이상)',
                               '후유장해(3~100%)', '후유장해(80%이상)',
                               '상해후유장해(3%이상)', '상해후유장해(80%이상)'],
    '상해->상해->재해상해': ['재해상해', '교통상해', '대중교통상해'],
    # === 암 진단비 ===
    # 2026-05-12 정리: 사용자 정책 "진단의 금액만 진단비 버킷에 들어가야 한다".
    # 암수술 / 암입원 / 항암치료 / 표적항암 / 조혈모세포 등 처치·치료성 담보는 keywords 에서
    # 제거 → unmatched 로 분류되어 case 생성 안 됨. 순수 진단(diagnosis)만 매핑.
    '진단비->암->일반암': ['일반암', '암진단', '특정암진단', '다발성소아암진단',
                          '소아백혈병진단', '16대특정암진단',
                          '3대질환암진단', '일반암진단', '특정암'],
    # === 뇌 ===
    '진단비->뇌->뇌혈관': ['뇌혈관질환', '뇌혈관', '뇌동맥류', '뇌질환',
                          '뇌혈관질환진단', '뇌혈관진단'],
    '진단비->뇌->뇌졸중': ['뇌졸중', '뇌졸중진단'],
    '진단비->뇌->뇌출혈': ['뇌출혈', '뇌출혈진단'],
    # === 심혈관 ===
    '진단비->심혈관->허혈성': ['허혈성심장', '허혈성심질환', '허혈성',
                              '심혈관질환', '심장질환',
                              '허혈성심장질환진단', '허혈성심장질환'],
    '진단비->심혈관->급성심근경색': ['급성심근경색', '심근경색', '급성심근경색진단'],
    # === 실손 의료비 ===
    '실손 의료비->질병->질병 입원 의료비': ['질병입원', '질병 입원', '질병으로입원',
                                          '질병입원의료비', '질병입원비', '질병입원형',
                                          '질병입원일당', '질병입원치료',
                                          '질병으로입원치료'],
    '실손 의료비->질병->질병 통원 의료비': ['질병통원', '질병 통원', '질병으로통원',
                                          '질병통원의료비', '질병통원형',
                                          '질병통원[외래]',
                                          '질병통원치료', '질병으로통원치료',
                                          '질병통원(외래)'],
    '실손 의료비->질병->질병 처방조제비': ['질병처방조제비', '질병처방조제', '질병으로처방조제',
                                          '질병통원(처방)', '질병통원[처방]',
                                          '질병처방', '질병약제비',
                                          '처방조제비', '처방조제', '처방약제비'],
    '실손 의료비->상해->상해 입원 의료비': ['상해입원', '상해 입원', '다쳐서입원',
                                          '상해입원의료비', '상해입원비', '상해입원형',
                                          '상해입원일당', '상해입원치료',
                                          '다쳐서입원치료'],
    '실손 의료비->상해->상해 통원 의료비': ['상해통원', '상해 통원', '다쳐서통원',
                                          '상해통원의료비', '상해통원형',
                                          '상해통원[외래]',
                                          '상해통원치료', '다쳐서통원치료',
                                          '상해통원(외래)'],
    '실손 의료비->상해->상해 처방조제비': ['상해처방조제비', '상해처방조제', '다쳐서처방조제',
                                          '상해통원(처방)', '상해통원[처방]',
                                          '상해처방', '상해약제비'],
    '실손 의료비->비급여->비급여 MR/MRA': ['비급여도수치료', '비급여체외충격파',
                                          '비급여MRI', '비급여MR',
                                          '비급여증식치료', '도수치료·체외충격파',
                                          '도수치료체외충격파증식치료'],
    '실손 의료비->비급여->비급여 주사료': ['비급여주사', '비급여 주사', '비급여주사료'],
    # === 운전자 ===
    '운전자진단비->벌금->대물 벌금': ['벌금', '대물벌금', '벌금(운전자용)'],
    '운전자진단비->벌금->대인 벌금': ['대인벌금'],
    '운전자진단비->합의금->형사 합의 실손비': ['형사합의', '합의금', '형사합의실손비',
                                             '교통사고처리지원금'],
    '운전자진단비->변호사->변호사 선임비': ['변호사선임', '변호사 선임',
                                          '자동차사고변호사선임', '변호사선임비용'],
    # === 기타 ===
    '기타->일상->일상생활배상책임': ['일상생활배상', '일상생활 배상',
                                   '일상생활중배상책임', '일상생활중배상'],
    '기타->가족->가족생활배상책임': ['가족일상생활', '가족배상', '가족생활배상',
                                   '가족일상생활중배상'],

    # === 특수수술 (2026-07-02 확장 — 종합보험 미매칭 담보, 중립 표시 전용) ===
    # ★ 이 path들은 '수술->특수->*' — '진단비->' 아님.
    #   _is_treatment_only 체크는 진단비 path에만 적용되므로 수술 키워드 안전.
    '수술->특수->골절수술비': ['골절수술비'],
    '수술->특수->화상수술비': ['화상수술비'],
    '수술->특수->조혈모세포이식수술비': ['조혈모세포이식수술비', '조혈모세포이식수술'],
    '수술->특수->장기이식수술비': ['장기이식수술비', '장기이식수술'],
    '수술->특수->각막이식수술비': ['각막이식수술비', '각막이식수술'],
    '수술->특수->흉터복원수술비': ['흉터복원수술비', '흉터복원수술'],
    '수술->특수->인공관절수술비': ['인공관절수술비', '인공관절수술'],
    '수술->특수->호흡기수술비': ['호흡기수술비', '호흡기수술'],

    # === 표적항암 (2026-07-02 확장 — 종합보험 미매칭 담보, 중립 표시 전용) ===
    # ★ '처치->표적항암->*' — 기존 '처치->항암->*' 와 별개 sub.
    '처치->표적항암->표적항암약물치료': ['표적항암약물치료비', '표적항암약물치료'],
    '처치->표적항암->표적항암방사선치료': ['표적항암방사선치료비', '표적항암방사선치료'],

    # === 특수입원 (2026-07-02 확장 — 종합보험 미매칭 담보, 중립 표시 전용) ===
    # ★ '입원->특수->*' — 실손 의료비 path 아님.
    #   '일당' 포함 → _is_fixed_benefit_inpatient True지만, 실손 의료비 path가 아니므로 차단 무관.
    # ★ 질병중환자실입원일당(기존 [표준]입원일당 leaf)을 반드시 먼저 체크해야 함.
    #   '중환자실입원일당'이 substring으로 포함되므로 dict 순서상 이 entry가 앞에 와야
    #   first-path-wins 규칙에 의해 정확한 경로로 분기됨.
    '입원->질병->질병중환자실입원일당': ['질병중환자실입원일당'],
    '입원->특수->중환자실입원일당': ['중환자실입원일당'],
    '입원->특수->환경성질환입원일당': ['환경성질환입원일당', '환경성질환입원'],
    '입원->특수->14대질병입원일당': ['14대질병입원일당', '14대질병입원'],
    '입원->특수->여성특정질병입원일당': ['여성특정질병입원일당', '여성특정질병입원'],
    '입원->특수->희귀난치성질환입원일당': ['희귀난치성질환입원일당', '희귀난치성질환입원'],
}


def _parse_korean_amount(text):
    """한글 금액 표기를 원 단위로 변환.
    예: '5천만원'→50000000, '1억원'→100000000, '3백만원'→3000000,
        '10,000만원'→100000000, '1억5천만원'→150000000"""
    text = text.replace(' ', '').replace(',', '')

    # 패턴1: X억Y천Z백만원 (한글 복합)
    m = re.match(r'^(\d+억)?(\d+천)?(\d+백)?(\d+)?만원$', text)
    if m:
        total = 0
        if m.group(1):
            total += int(m.group(1).replace('억', '')) * 100000000
        if m.group(2):
            total += int(m.group(2).replace('천', '')) * 10000000
        if m.group(3):
            total += int(m.group(3).replace('백', '')) * 1000000
        if m.group(4):
            total += int(m.group(4)) * 10000
        return total

    # 패턴2: X억원
    m = re.match(r'^(\d+)억원$', text)
    if m:
        return int(m.group(1)) * 100000000

    # 패턴3: 숫자만원 (예: 10,000만원, 30만원)
    m = re.match(r'^(\d+)만원$', text)
    if m:
        return int(m.group(1)) * 10000

    return 0


def _detect_company(text_lines):
    """보험사 감지 + 생명/손해 구분. (인덱스, 타입) 반환.
    실제 증권 패턴 기반: 메리츠/한화/현대/삼성 등 주요 보험사 우선 매칭."""
    full_text = ' '.join(text_lines)
    # 공백 제거 텍스트 (현대해상: "현 대 해 상" 대응)
    no_space = re.sub(r'\s+', '', full_text)

    # === Phase 1: 전체 이름 정확 매칭 (충돌 방지) ===
    # 손해보험사
    for idx, company in enumerate(LossInsurance.company):
        if company in full_text or company.replace(' ', '') in no_space:
            return idx, 'loss', company
    # 생명보험사
    for idx, company in enumerate(LifeInsurance.company):
        if company in full_text or company.replace(' ', '') in no_space:
            return idx, 'life', company

    # === Phase 2: 보험사 특징적 키워드 매칭 (실제 증권 패턴) ===
    # 현대해상: "hi.co.kr", "하이스타" (글자 분리 대응: no_space에서도 검색)
    if 'hi.co.kr' in full_text or 'hi.co.kr' in no_space or '하이스타' in full_text or '현대해상' in no_space:
        idx = next((i for i, c in enumerate(LossInsurance.company) if '현대해상' in c), -1)
        if idx >= 0:
            return idx, 'loss', LossInsurance.company[idx]
    # 메리츠화재: "1566-7711", "meritzfire", 상품명에 "메리츠"
    if '1566-7711' in full_text or 'meritzfire' in no_space or re.search(r'메리츠\s*(?:화재|걱정없는|실손|알파)', full_text):
        idx = next((i for i, c in enumerate(LossInsurance.company) if '메리츠' in c), -1)
        if idx >= 0:
            return idx, 'loss', LossInsurance.company[idx]
    # 한화생명: "한아름", "한화생명", "1566-8000", "hwgeneralins"
    if re.search(r'한아름|한화\s*생명|한화생명', full_text) or '한아름' in no_space:
        idx = next((i for i, c in enumerate(LifeInsurance.company) if '한화생명' in c), -1)
        if idx >= 0:
            return idx, 'life', LifeInsurance.company[idx]
    # 한화손해: "1566-8000", "hwgeneralins.com"
    if re.search(r'한화\s*손해|한화손해|1566-8000|hwgeneralins', full_text) or 'hwgeneralins' in no_space:
        idx = next((i for i, c in enumerate(LossInsurance.company) if '한화손해' in c), -1)
        if idx >= 0:
            return idx, 'loss', LossInsurance.company[idx]
    # 삼성생명: 상품명에 "퍼스트클래스", "변액유니버셜종신" 등
    if re.search(r'삼성생명|퍼스트클래스|파워변액', no_space):
        idx = next((i for i, c in enumerate(LifeInsurance.company) if '삼성생명' in c), -1)
        if idx >= 0:
            return idx, 'life', LifeInsurance.company[idx]
    # 교보생명: "프리미엄OK", "교보"
    if re.search(r'교보생명|프리미엄OK|교보', no_space):
        idx = next((i for i, c in enumerate(LifeInsurance.company) if '교보생명' in c), -1)
        if idx >= 0:
            return idx, 'life', LifeInsurance.company[idx]
    # 미래에셋생명: "미래에셋", "PCA"
    if re.search(r'미래에셋|PCA', no_space):
        idx = next((i for i, c in enumerate(LifeInsurance.company) if '미래에셋' in c or '푸본현대' in c), -1)
        if idx >= 0:
            return idx, 'life', LifeInsurance.company[idx]

    # === Phase 3: 약칭 매칭 (최후 수단, 3글자 이상만) ===
    for idx, company in enumerate(LossInsurance.company):
        short_name = company.replace('손해', '').replace('화재', '')
        if short_name and len(short_name) >= 3 and (short_name in full_text or short_name in no_space):
            return idx, 'loss', company
    for idx, company in enumerate(LifeInsurance.company):
        short_name = company.replace('생명', '')
        if short_name and len(short_name) >= 3 and (short_name in full_text or short_name in no_space):
            return idx, 'life', company

    # === Phase 4: 회사 미상이나 상품 유형이 명백히 생명보험(변액·종신)인 경우 ===
    # 회사명이 증권에 없어도 변액·종신·유니버셜 상품은 생명보험으로 확정한다.
    # 회사는 추측하지 않고 -1로 두되(정직), type='life'로 잡아 보험료·계약일·담보가
    # 생명보험 경로로 정상 파싱되게 한다(기존엔 'unknown'이라 헤더·데이터 미적재).
    if re.search(r'변액|종신|유니버셜', no_space):
        return -1, 'life', ''

    return -1, 'unknown', ''


def _extract_product_name(text_lines):
    """상품명 추출 - 실제 증권 패턴 대응.
    메리츠: 별도 줄에 상품명 (예: "무배당 메리츠 걱정없는 암보험1404(2종)")
    한화: 첫 줄에 상품명 (예: "무배당 마이라이프 한아름종합보험1606")
    현대: "보험증권" 다음 줄 (예: "무배당실손의료보장보험(Hi1304)")
    """
    # 패턴 1: "상품명" 라벨 뒤의 값 (명 필수 - "본 상품 약관의..." 오탐 방지)
    for line in text_lines:
        m = re.search(r'상품명\s*[:：]?\s+(.+?)(?:\s{2,}|$)', line)
        if m:
            name = m.group(1).strip()
            if 3 <= len(name) <= 50:
                return name

    # 패턴 2: (무)배당/무배당/(무) + 보험 이름
    # 예: "무배당 메리츠 걱정없는 암보험1404(2종)", "(무) 메리츠 실손의료비보험1404"
    # "무배당 마이라이프 한아름종합보험1606", "무배당실손의료보장보험(Hi1304)"
    for line in text_lines:
        # 2a: "무배당..." 패턴
        m = re.search(r'[\(（]?\s*무\s*[\)）]?\s*배당[가-힣A-Za-z0-9\s\(\)（）+]+보험[가-힣A-Za-z0-9\(\)（）]*', line)
        if m:
            name = m.group(0).strip()
            if 5 <= len(name) <= 50:
                return name
        # 2b: "(무) 보험사 상품보험..." 패턴 (무배당의 약어)
        m = re.search(r'[\(（]\s*무\s*[\)）]\s*[가-힣A-Za-z0-9\s]+보험[가-힣A-Za-z0-9\(\)（）]*', line)
        if m:
            name = m.group(0).strip()
            if 5 <= len(name) <= 50:
                return name

    # 패턴 3: "보험증권" 다음 줄에 상품명 (현대해상 등)
    for i, line in enumerate(text_lines):
        if '보험증권' in line.replace(' ', ''):
            if i + 1 < len(text_lines):
                next_line = text_lines[i + 1].strip()
                if '보험' in next_line and 5 <= len(next_line) <= 50:
                    return next_line

    # 패턴 4: 문서 첫 부분에 "보험" 포함 라인 (한화: 첫 줄이 상품명)
    for line in text_lines[:5]:
        stripped = line.strip()
        if '보험' in stripped and 5 <= len(stripped) <= 50 and not any(
            kw in stripped for kw in ['보험증권', '보험계약', '보험업법', '보험기간']
        ):
            return stripped

    # 패턴 5: full-text (no_space) fallback - 글자 분리 PDF 대응
    no_space = re.sub(r'\s+', '', ' '.join(text_lines))
    # "무배당...보험..." 패턴
    m = re.search(r'(?:무배당|[\(（]무[\)）])[가-힣A-Za-z0-9+]+보험[가-힣A-Za-z0-9\(\)（）]*', no_space)
    if m:
        name = m.group(0)
        if 5 <= len(name) <= 50:
            return name

    return ''


def _extract_person_name(text_lines, label_pattern):
    """계약자/피보험자 이름 추출 - 다양한 보험사 형식 대응.
    메리츠(일반): "계약자\\n최윤님" (라벨과 값이 별도 줄)
    메리츠(실손): "보험계약자\\n성명\\n김효준" (라벨→성명→이름)
    한화(일반):   "계약자\\n박진희 (690913 - 2******)" (주민번호 포함)
    한화(실손):   "보험계약자\\n보험계약을 체결하고...사람 : 이춘호" (설명문 안에 이름)
    현대:         "계 약 자 명\\n김행임" (공백이 있는 라벨)

    핵심: "보험계약자 및 보험료납부자가..." 같은 문장에서 오탐 방지.
    """
    compact_label = label_pattern.replace(r'\s*', '').replace(r'\s+', '')
    # 테이블 헤더/설명 등 이름이 아닌 키워드
    NOT_NAMES = {'주민번호', '사망수익자', '기타수익자', '지정대리청구인', '보험기간',
                 '납입기간', '보장기간', '증권번호', '계약번호', '피보험자', '계약자',
                 '서열', '성별', '직업명', '보험사고', '성명', '수익자', '보헙',
                 '적립금의', '본인자유', '관한사항', '납부자가', '관계구분',
                 '보험료납', '가입사항', '체결하고', '사항'}

    def _try_extract_name_from_lines(start_idx):
        """start_idx 이후 최대 3줄에서 이름 추출 시도"""
        for j in range(1, min(4, len(text_lines) - start_idx)):
            next_line = text_lines[start_idx + j].strip()
            next_first_word = re.sub(r'\s+', '', next_line).split('(')[0] if next_line else ''
            # NOT_NAMES 키워드이면 건너뛰기 (성명, 주민번호 등)
            if next_first_word in NOT_NAMES:
                continue
            # "...사람 : 이름 (주민번호)" 패턴 (한화 실손 형식)
            m = re.search(r'사람\s*[:：]\s*([가-힣]{2,5})(?:\s|님|$|[\(（])', next_line)
            if m:
                return m.group(1)
            # 일반 이름 패턴: "이름 (주민번호)" 또는 "이름님"
            m = re.match(r'([가-힣]{2,5})(?:\s|님|$|[\(（])', next_line)
            if m:
                return m.group(1)
        return None

    for i, line in enumerate(text_lines):
        normalized = re.sub(r'\s+', '', line)

        # === 우선순위 0: "보험계약자"/"보험피보험자" 단독 줄 (실손보험 형식) ===
        # "보험" prefix가 붙어서 lookbehind에 걸리는 경우를 별도 처리
        if re.search(r'^[●\s]*보험' + compact_label + r'$', normalized):
            name = _try_extract_name_from_lines(i)
            if name:
                return name

        # === 우선순위 1: 라벨만 단독으로 있는 줄 → 다음 줄에서 이름 (가장 정확) ===
        # "계약자" 단독, "계 약 자 명" 단독, "피보험자(설명문)" 등
        label_only = (
            re.search(r'(?<![가-힣])' + label_pattern + r'\s*$', line) or
            re.search(r'(?<![가-힣])' + compact_label + r'$', normalized) or
            re.search(r'(?<![가-힣])' + label_pattern + r'\s*[\(（]', line)  # 라벨+괄호설명
        )
        if label_only:
            name = _try_extract_name_from_lines(i)
            if name:
                return name

        # === 우선순위 2: 같은 줄에서 추출 (콜론 구분자 필수) ===
        # "계약자: 홍길동" (콜론이 있어야 안전)
        m = re.search(r'(?<![가-힣])' + label_pattern + r'\s*[:：]\s*([가-힣]{2,5})(?:[^가-힣]|$)', line)
        if m:
            return m.group(1)

        # === 우선순위 2.5: 같은 줄에서 추출 (콜론 없이 공백 구분) ===
        # "O 피보험자 송상훈 (730715)" (한화 가입담보내역서 형식)
        m = re.search(r'(?<![가-힣])' + label_pattern + r'\s+([가-힣]{2,5})(?:\s|님|$|[\(（])', line)
        if m:
            candidate = m.group(1)
            if candidate not in NOT_NAMES:
                return candidate

        # === 우선순위 3: 현대해상 공백 라벨 → 다음 줄 ===
        # "계 약 자 명" → 다음줄 "김행임"
        if re.search(r'(?<![가-힣])' + compact_label + r'$', normalized):
            name = _try_extract_name_from_lines(i)
            if name:
                return name

    # === 우선순위 4: full-text (no_space) fallback ===
    # 글자 분리 PDF에서 "계약자이상찬", "피보험자송상훈" 등을 잡음
    no_space = re.sub(r'\s+', '', ' '.join(text_lines))
    # no_space에서 라벨 바로 뒤 2~5글자 한글이 나오면 이름으로 추출
    # 단, 뒤에 바로 비이름 키워드가 이어지면 제외
    m = re.search(compact_label + r'(?:명)?([가-힣]{2,5})(?=[^가-힣]|$)', no_space)
    if m:
        candidate = m.group(1)
        # 이름인지 검증: NOT_NAMES에 없고, 보험 관련 용어가 아닌지 확인
        bad_suffixes = ['보험', '기간', '사항', '납부', '체결', '가입', '수익', '해약',
                        '적립', '관한', '관계', '및보', '금의', '증권', '자유', '정보', '내용', '현황']
        is_bad = candidate in NOT_NAMES or any(candidate.endswith(s) for s in bad_suffixes)
        if not is_bad:
            return candidate

    return ''


def _extract_periods(text_lines):
    """납입기간, 보장기간(세만기), 갱신주기 추출 - 다양한 형식 대응.
    메리츠: "월납 20년간 240회 납입"
    한화:   "100세만기 / 20년납 / 월납 / 자동이체" (계약사항 줄)
    현대:   "1년납" (보험기간 줄), "납 입 기 간\\n1년납" (공백 라벨)
    """
    result = {'납입기간': 0, '보장기간': 0, '갱신주기': 0}

    for i, line in enumerate(text_lines):
        normalized = re.sub(r'\s+', '', line)

        # --- 한화 계약사항 통합 줄 ---
        # "100세만기 / 20년납 / 월납 / 자동이체"
        if '계약사항' in line or '계약사항' in normalized:
            # 다음 줄에 실제 값이 있을 수 있음
            target = line
            if i + 1 < len(text_lines) and '/' in text_lines[i + 1]:
                target = text_lines[i + 1]
            m_pay = re.search(r'(\d+)\s*년\s*납', target)
            m_cov = re.search(r'(\d+)\s*세\s*만기', target)
            if m_pay:
                result['납입기간'] = int(m_pay.group(1))
            if m_cov:
                result['보장기간'] = int(m_cov.group(1))
            if result['납입기간'] > 0:
                continue

        # --- 납입기간 ---
        if result['납입기간'] == 0:
            # "20년납", "20년 납", "월납 20년간" 등
            m = re.search(r'(\d+)\s*년\s*(?:납|간)', line)
            if m:
                val = int(m.group(1))
                if 1 <= val <= MAX_PAYMENT_PERIOD:  # 합리적 범위 체크
                    result['납입기간'] = val
            # "15년 만기" (실손보험: "15년 만기 / 1년갱신 / 월납")
            if result['납입기간'] == 0:
                m = re.search(r'(\d+)\s*년\s*만기', line)
                if m:
                    val = int(m.group(1))
                    if 1 <= val <= MAX_PAYMENT_PERIOD:
                        result['납입기간'] = val
            # 현대: "납 입 기 간" 라벨 → 다음 줄에 "1년납"
            if '납입기간' in normalized and result['납입기간'] == 0:
                if i + 1 < len(text_lines):
                    m = re.search(r'(\d+)\s*년\s*납', text_lines[i + 1])
                    if m:
                        result['납입기간'] = int(m.group(1))

        # --- 보장기간 ---
        if result['보장기간'] == 0:
            # "100세만기"
            m = re.search(r'(\d+)\s*세\s*만기', line)
            if m:
                val = int(m.group(1))
                if 15 <= val <= MAX_WARRANTY_PERIOD_AGE:
                    result['보장기간'] = val
            # "보장기간: 100세"
            if result['보장기간'] == 0:
                m = re.search(r'보장기간\s*[:.]?\s*(\d+)\s*세', line)
                if m:
                    val = int(m.group(1))
                    if 15 <= val <= MAX_WARRANTY_PERIOD_AGE:
                        result['보장기간'] = val
            # 메리츠: "~2029년 08월 14일 24시까지 (15년)" → (N년) 추출
            if result['보장기간'] == 0:
                m = re.search(r'까지\s*[\(（]\s*(\d+)\s*년\s*[\)）]', line)
                if m:
                    val = int(m.group(1))
                    if 1 <= val <= MAX_WARRANTY_PERIOD_YEAR:
                        result['보장기간'] = val
            # 현대 실손: "보장기간은 최대15년입니다", "보장기간은 최대 15년"
            if result['보장기간'] == 0:
                m = re.search(r'보장\s*기간\s*은?\s*(?:최대\s*)?(\d+)\s*년', line)
                if m:
                    val = int(m.group(1))
                    if 1 <= val <= MAX_WARRANTY_PERIOD_YEAR:
                        result['보장기간'] = val
            # 실손/갱신형: "15년 만기", "15년만기" (세가 아닌 년 단위)
            if result['보장기간'] == 0:
                m = re.search(r'(\d+)\s*년\s*만기', line)
                if m:
                    val = int(m.group(1))
                    if 1 <= val <= MAX_WARRANTY_PERIOD_YEAR:
                        result['보장기간'] = val

        # --- 의무납입기간 (미래에셋: "의무납입기간: 144개월") ---
        if result['납입기간'] == 0:
            m = re.search(r'의무\s*납입\s*기간\s*[:：]?\s*(\d+)\s*개월', line)
            if m:
                result['납입기간'] = int(m.group(1)) // 12

        # --- 갱신주기 ---
        if result['갱신주기'] == 0:
            m = re.search(r'(\d+)\s*년\s*갱신', line)
            if m:
                result['갱신주기'] = int(m.group(1))
            # "자동갱신", "매년 자동갱신" → 1년 갱신
            elif re.search(r'매\s*년\s*(?:마다\s*)?(?:자동\s*)?갱신', line):
                result['갱신주기'] = 1

    # === full-text (no_space) fallback ===
    no_space = re.sub(r'\s+', '', ' '.join(text_lines))
    if result['납입기간'] == 0:
        # "20년납", "납입기간20년"
        m = re.search(r'(\d+)년납', no_space)
        if m:
            val = int(m.group(1))
            if 1 <= val <= MAX_PAYMENT_PERIOD:
                result['납입기간'] = val
        if result['납입기간'] == 0:
            m = re.search(r'납입기간[:：]?(\d+)년', no_space)
            if m:
                val = int(m.group(1))
                if 1 <= val <= MAX_PAYMENT_PERIOD:
                    result['납입기간'] = val
        # "의무납입기간:144개월" (미래에셋)
        if result['납입기간'] == 0:
            m = re.search(r'의무납입기간[:：]?(\d+)개월', no_space)
            if m:
                result['납입기간'] = int(m.group(1)) // 12
    if result['보장기간'] == 0:
        m = re.search(r'(\d+)세만기', no_space)
        if m:
            val = int(m.group(1))
            if 15 <= val <= MAX_WARRANTY_PERIOD_AGE:
                result['보장기간'] = val
    if result['보장기간'] == 0:
        # "까지(15년)" (메리츠: 날짜 범위 뒤 괄호)
        m = re.search(r'까지[\(（](\d+)년[\)）]', no_space)
        if m:
            val = int(m.group(1))
            if 1 <= val <= MAX_WARRANTY_PERIOD_YEAR:
                result['보장기간'] = val
    if result['보장기간'] == 0:
        # "보장기간은최대15년" (현대 실손)
        m = re.search(r'보장기간은?(?:최대)?(\d+)년', no_space)
        if m:
            val = int(m.group(1))
            if 1 <= val <= MAX_WARRANTY_PERIOD_YEAR:
                result['보장기간'] = val

    return result


MAX_PREMIUM = 500_000_000  # 5억원 (월 보험료 상한 - 법인/단체보험 고려)
MAX_ASSURANCE_AMOUNT = 100_000_000_000  # 1000억원 (보장금액 상한 - 법인/단체 고액보험)
MAX_PAYMENT_PERIOD = 99  # 납입기간 상한 (년, 2자리까지 허용)
MAX_WARRANTY_PERIOD_YEAR = 99  # 보장기간 상한 (년, 2자리까지 허용)
MAX_WARRANTY_PERIOD_AGE = 120  # 보장기간 상한 (세, 초고령 설계 고려)


def _valid_premium(val):
    """보험료 유효성: 양수이고 5억원 이하"""
    return isinstance(val, (int, float)) and 0 < val <= MAX_PREMIUM


def _valid_amount(val):
    """보장금액 유효성: 양수이고 1000억원 이하"""
    return isinstance(val, (int, float)) and 0 < val <= MAX_ASSURANCE_AMOUNT


def _extract_premiums(text_lines):
    """보장보험료, 적립보험료, 총 보험료, 갱신보장보험료, 주계약보험료, 특약보험료 추출.
    메리츠: "납입보험료(원)\\n61,120" (라벨과 값이 별도 줄)
    한화:   "1회 보험료\\n61,211원 ( 보장보험료: 61,186원  (갱신보장보험료: 30,888원)  /  적립보험료: 25원 )"
    현대:   "보 장 보 험 료\\n105,130원" (공백 있는 라벨, 값 별도 줄)
    """
    result = {'보장보험료': 0, '적립보험료': 0, '월납입보험료': 0,
              '갱신보장보험료': 0, '주계약보험료': 0, '특약보험료': 0}

    for i, line in enumerate(text_lines):
        # 현대해상: 공백 제거 후 매칭 ("보 장 보 험 료" → "보장보험료")
        normalized = re.sub(r'\s+', '', line)

        # --- 한화 통합형: 한 줄에 여러 보험료 ---
        # "61,211원 ( 보장보험료: 61,186원  (갱신보장보험료: 30,888원)  /  적립보험료: 25원 )"
        if '보장보험료' in line and '적립보험료' in line:
            m = re.search(r'([\d,]+)\s*원\s*[\(（]?\s*보장보험료', line)
            if m:
                result['월납입보험료'] = int(m.group(1).replace(',', ''))
            m = re.search(r'보장보험료\s*[:：]?\s*([\d,]+)\s*원', line)
            if m:
                result['보장보험료'] = int(m.group(1).replace(',', ''))
            m = re.search(r'갱신보장보험료\s*[:：]?\s*([\d,]+)\s*원', line)
            if m:
                result['갱신보장보험료'] = int(m.group(1).replace(',', ''))
            m = re.search(r'적립보험료\s*[:：]?\s*([\d,]+)\s*원', line)
            if m:
                result['적립보험료'] = int(m.group(1).replace(',', ''))
            continue

        # --- 보장보험료 (단독 줄) ---
        m = re.search(r'보장\s*보험료\s*(?:\(원\))?\s*[:：]?\s*([\d,]+)\s*원?', line)
        if not m and '보장보험료' in normalized:
            m = re.search(r'보장보험료(?:\(원\))?[:：]?([\d,]+)', normalized)
        if m and result['보장보험료'] == 0:
            result['보장보험료'] = int(m.group(1).replace(',', ''))
            continue

        # --- 적립보험료 (단독 줄) ---
        m = re.search(r'적립\s*보험료\s*(?:\(원\))?\s*[:：]?\s*([\d,]+)\s*원?', line)
        if not m and '적립보험료' in normalized:
            m = re.search(r'적립보험료(?:\(원\))?[:：]?([\d,]+)', normalized)
        if m and result['적립보험료'] == 0:
            result['적립보험료'] = int(m.group(1).replace(',', ''))
            continue

        # --- 합계보험료 (현대: "합 계 보 험 료") ---
        if re.search(r'합계보험료', normalized):
            m = re.search(r'합\s*계\s*보\s*험\s*료\s*[:：]?\s*([\d,]+)\s*원?', line)
            if not m:
                m = re.search(r'합계보험료[:：]?([\d,]+)', normalized)
            if m:
                val = int(m.group(1).replace(',', ''))
                if val > result['월납입보험료']:
                    result['월납입보험료'] = val
                continue

        # --- 1회/월/납입/월납 보험료 ---
        m = re.search(r'(?:1회|월납|월|납입)\s*보험료\s*(?:\(원\))?\s*[:：]?\s*([\d,]+)\s*원?', line)
        if m and result['월납입보험료'] == 0:
            result['월납입보험료'] = int(m.group(1).replace(',', ''))
            continue

        # --- 보험료 합계 (한화 자녀보험: "1회 보험료 합계 : 144,428원") ---
        m = re.search(r'보험료\s*합계\s*[:：]?\s*([\d,]+)\s*원?', line)
        if m and result['월납입보험료'] == 0:
            result['월납입보험료'] = int(m.group(1).replace(',', ''))
            continue

        # --- 라벨만 있고 값은 다음 줄 (메리츠/현대/실손 형식) ---
        # "납입보험료(원)\n61,120" 또는 "보 장 보 험 료\n105,130원"
        # "보험료\n36,380원 (월납/1년갱신/15년납)" (실손보험 형식)
        if i + 1 < len(text_lines):
            next_line = text_lines[i + 1].strip()
            # 값 추출: 줄 시작이 숫자+원 (뒤에 괄호 내용 등 허용)
            next_val_match = re.match(r'^(\d[\d,]*)\s*원', next_line)
            if not next_val_match:
                next_val_match = re.match(r'^(\d[\d,]*)\s*$', next_line)
            if next_val_match:
                val = int(next_val_match.group(1).replace(',', ''))
                if re.search(r'납입\s*보험료', line) or '납입보험료' in normalized:
                    if result['월납입보험료'] == 0:
                        result['월납입보험료'] = val
                elif re.search(r'보장\s*보험료', line) or '보장보험료' in normalized:
                    if result['보장보험료'] == 0:
                        result['보장보험료'] = val
                elif re.search(r'적립\s*보험료', line) or '적립보험료' in normalized:
                    if result['적립보험료'] == 0:
                        result['적립보험료'] = val
                elif re.search(r'합\s*계\s*보\s*험\s*료', line) or '합계보험료' in normalized:
                    if val > result['월납입보험료']:
                        result['월납입보험료'] = val
                elif normalized == '보험료' or re.match(r'^보험료\s*$', line):
                    # "보험료" 단독 라벨 (실손보험: "보험료\n7,231원")
                    if result['월납입보험료'] == 0:
                        result['월납입보험료'] = val

        # --- 주계약 보험료 ---
        m = re.search(r'주\s*계약\s*(?:보험)?료\s*[:：]?\s*([\d,]+)\s*원?', line)
        if m:
            result['주계약보험료'] = int(m.group(1).replace(',', ''))
            continue

        # --- 특약 보험료 ---
        m = re.search(r'특약\s*(?:보험)?료\s*[:：]?\s*([\d,]+)\s*원?', line)
        if m:
            result['특약보험료'] = int(m.group(1).replace(',', ''))
            continue

    # === full-text (no_space) fallback ===
    # 글자 분리 PDF에서 "보장보험료105,130" 등을 잡음
    no_space = re.sub(r'\s+', '', ' '.join(text_lines))
    if result['보장보험료'] == 0:
        m = re.search(r'보장보험료(?:\(원\))?[:：]?(\d[\d,]*)', no_space)
        if m:
            result['보장보험료'] = int(m.group(1).replace(',', ''))
    if result['적립보험료'] == 0:
        m = re.search(r'적립보험료(?:\(원\))?[:：]?(\d[\d,]*)', no_space)
        if m:
            result['적립보험료'] = int(m.group(1).replace(',', ''))
    if result['월납입보험료'] == 0:
        # 합계보험료
        m = re.search(r'합계보험료[:：]?(\d[\d,]*)', no_space)
        if m:
            result['월납입보험료'] = int(m.group(1).replace(',', ''))
    if result['월납입보험료'] == 0:
        # 납입보험료 / 1회보험료 / 월보험료 / 월납보험료
        m = re.search(r'(?:1회|월납|월|납입)보험료(?:\(원\))?[:：]?(\d[\d,]*)', no_space)
        if m:
            result['월납입보험료'] = int(m.group(1).replace(',', ''))
    if result['월납입보험료'] == 0:
        # "보험료합계144,428" (한화 자녀보험)
        m = re.search(r'보험료합계[:：]?(\d[\d,]*)', no_space)
        if m:
            result['월납입보험료'] = int(m.group(1).replace(',', ''))
    if result['월납입보험료'] == 0:
        # "보험료300,000" (미래에셋 등 - 최소 1000원 이상)
        m = re.search(r'(?<!갱신)보험료[:：]?(\d[\d,]*)', no_space)
        if m:
            val = int(m.group(1).replace(',', ''))
            if val >= 1000:
                result['월납입보험료'] = val
    # 갱신보장보험료 (no_space fallback)
    if result['갱신보장보험료'] == 0:
        m = re.search(r'갱신보장보험료[:：]?(\d[\d,]*)', no_space)
        if m:
            result['갱신보장보험료'] = int(m.group(1).replace(',', ''))
    # 주계약보험료 (no_space fallback)
    if result['주계약보험료'] == 0:
        m = re.search(r'주계약(?:보험)?료[:：]?(\d[\d,]*)', no_space)
        if m:
            result['주계약보험료'] = int(m.group(1).replace(',', ''))
    # 특약보험료 (no_space fallback)
    if result['특약보험료'] == 0:
        m = re.search(r'특약(?:보험)?료[:：]?(\d[\d,]*)', no_space)
        if m:
            result['특약보험료'] = int(m.group(1).replace(',', ''))

    # 보장보험료만 있고 월납입보험료 없으면 합산
    if result['보장보험료'] > 0 and result['월납입보험료'] == 0:
        result['월납입보험료'] = result['보장보험료'] + result['적립보험료']

    # 금액 상한 검증 (비현실적 금액 제거)
    for key in result:
        if result[key] > MAX_PREMIUM:
            print(f'_extract_premiums: {key} 비현실적 금액 제거: {result[key]}')
            result[key] = 0

    return result


def _validate_date(year_str, month_str, day_str):
    """날짜 유효성 검증 - 월(1-12), 일(1-31), 연도(1950-2120)"""
    try:
        y, m, d = int(year_str), int(month_str), int(day_str)
        if not (1950 <= y <= 2120 and 1 <= m <= 12 and 1 <= d <= 31):
            return False
        return True
    except (ValueError, TypeError):
        return False


def _format_date(year, month, day):
    """날짜 포맷 (유효성 검증 포함)"""
    if _validate_date(year, month, day):
        return f'{year}.{str(month).zfill(2)}.{str(day).zfill(2)}'
    return ''


def _extract_dates(text_lines):
    """계약일, 만기일 추출 - 다양한 보험사 형식 대응.
    메리츠: "2014년 05월 09일 부터 2077년 05월 09일 24시까지 (63년)"
    한화:   "2016년 08월 23일 ~ 2100년 08월 23일"
    현대:   "2025-03-04     ~     2026-03-04"
    """
    result = {'계약일': '', '만기일': ''}
    # 날짜 요소 정규식 (년/월/일 또는 -/. 구분자)
    date_part = r'(\d{4})\s*[년.\-/]\s*(\d{1,2})\s*[월.\-/]\s*(\d{1,2})\s*일?'

    for i, line in enumerate(text_lines):
        # 패턴 1: 범위 날짜 - "시작 ~ 종료" 또는 "시작 부터 종료 까지"
        # 메리츠: "2009년 09월 30일 16시부터 2080년 09월 30일 16시까지" (시간 포함)
        m = re.search(
            date_part + r'\s*(?:\d{1,2}시\s*)?(?:부터\s*|[~\-–]\s*|부터\s+)' + date_part,
            line
        )
        if m:
            result['계약일'] = _format_date(m.group(1), m.group(2), m.group(3))
            result['만기일'] = _format_date(m.group(4), m.group(5), m.group(6))
            return result

        # 패턴 2: "계약기간" / "보험기간" 라벨이 있는 줄
        if re.search(r'(?:계약|보험)\s*기간', line):
            m = re.search(date_part + r'.*?' + date_part, line)
            if m:
                result['계약일'] = _format_date(m.group(1), m.group(2), m.group(3))
                result['만기일'] = _format_date(m.group(4), m.group(5), m.group(6))
                return result
            # 라벨만 있고 날짜는 다음 줄 (현대해상)
            if i + 1 < len(text_lines):
                next_line = text_lines[i + 1].strip()
                m = re.search(date_part + r'\s*[~\-–]\s*' + date_part, next_line)
                if m:
                    result['계약일'] = _format_date(m.group(1), m.group(2), m.group(3))
                    result['만기일'] = _format_date(m.group(4), m.group(5), m.group(6))
                    return result

        # 패턴 3: "계약일"/"청약일자" 라벨
        if not result['계약일']:
            m = re.search(r'(?:계약일|청약일자)\s*[:：]?\s*' + date_part, line)
            if m:
                result['계약일'] = _format_date(m.group(1), m.group(2), m.group(3))
            # 라벨만 있고 날짜 다음 줄
            elif re.search(r'(?:계약일|청약일자)\s*$', line.strip()) and i + 1 < len(text_lines):
                m = re.search(date_part, text_lines[i + 1])
                if m:
                    result['계약일'] = _format_date(m.group(1), m.group(2), m.group(3))

        # 패턴 4: "만기일" 라벨
        if not result['만기일']:
            m = re.search(r'만기일\s*[:：]?\s*' + date_part, line)
            if m:
                result['만기일'] = _format_date(m.group(1), m.group(2), m.group(3))

    # === full-text (no_space) fallback ===
    # 글자 분리 PDF에서 "2001.07.09" → "2001.07.09" 가 no_space로 연결됨
    if not result['계약일']:
        no_space = re.sub(r'\s+', '', ' '.join(text_lines))
        ns_date = r'(\d{4})[년.\-/](\d{1,2})[월.\-/](\d{1,2})일?'
        # 범위 날짜 (시간 "16시" 등 건너뛰기)
        m = re.search(ns_date + r'(?:\d{1,2}시)?(?:부터|[~\-–])' + ns_date, no_space)
        if m:
            result['계약일'] = _format_date(m.group(1), m.group(2), m.group(3))
            result['만기일'] = _format_date(m.group(4), m.group(5), m.group(6))
        else:
            # 계약일 라벨
            m = re.search(r'(?:계약일|청약일자|계약체결일)[:：]?' + ns_date, no_space)
            if m:
                result['계약일'] = _format_date(m.group(1), m.group(2), m.group(3))
        if not result['만기일']:
            m = re.search(r'만기일[:：]?' + ns_date, no_space)
            if m:
                result['만기일'] = _format_date(m.group(1), m.group(2), m.group(3))

    # === 2자리 연도 fallback (YY.MM.DD 형식) ===
    if not result['계약일']:
        date_part_2y = r'(\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})'

        for line in text_lines:
            # 범위 날짜: "25.03.04 ~ 26.03.04"
            m = re.search(date_part_2y + r'\s*[~\-–]\s*' + date_part_2y, line)
            if m:
                result['계약일'] = _format_date(_expand_2y(m.group(1)), m.group(2), m.group(3))
                result['만기일'] = _format_date(_expand_2y(m.group(4)), m.group(5), m.group(6))
                break

            # 라벨 + 날짜: "계약일 25.03.04"
            if not result['계약일']:
                m = re.search(r'(?:계약일|청약일자)\s*[:：]?\s*' + date_part_2y, line)
                if m:
                    result['계약일'] = _format_date(_expand_2y(m.group(1)), m.group(2), m.group(3))

            if not result['만기일']:
                m = re.search(r'만기일\s*[:：]?\s*' + date_part_2y, line)
                if m:
                    result['만기일'] = _format_date(_expand_2y(m.group(1)), m.group(2), m.group(3))

    return result


def _expand_2y(yy_str):
    """2자리 연도를 4자리로 변환: 00~50 → 2000~2050, 51~99 → 1951~1999"""
    yy = int(yy_str)
    return str(2000 + yy) if yy <= 50 else str(1900 + yy)


def _extract_renewal_info(text_lines):
    """갱신증가율, 월갱신보험료 추출"""
    result = {'갱신증가율': 0, '월갱신보험료': 0}
    for line in text_lines:
        # 갱신증가율: "갱신증가율 3.5%", "갱신 증가 5%"
        m = re.search(r'갱신\s*증가\s*율?\s*[:：]?\s*(\d+(?:\.\d+)?)\s*%', line)
        if m:
            result['갱신증가율'] = float(m.group(1))

        # 월갱신보험료: "갱신보험료 45,000원", "월갱신료: 30,000"
        m = re.search(r'(?:월\s*)?갱신\s*(?:보험)?료\s*[:：]?\s*([\d,]+)\s*원?', line)
        if m:
            result['월갱신보험료'] = int(m.group(1).replace(',', ''))
    return result


def _extract_refund_info(text_lines):
    """해약환급금, 환급유형 추출 - 오탐 방지 강화.
    실제 증권 패턴:
    - 한화: "만기시 만기환급금 지급", "적립보험료: 25원" (적립>0 → 만기환급)
    - 현대: "중도해지 및 만기시에 환급금이 발생하지 않습니다" (순수보장)
    - 메리츠: 적립보험료=0 → 순수보장
    """
    result = {'해약환급금': 0, '환급유형': 0}
    full_text = ' '.join(text_lines)

    for line in text_lines:
        # 해약환급금: "해약환급금: 1,200,000원"
        m = re.search(r'해약\s*환급금\s*[:：]?\s*([\d,]+)\s*원', line)
        if m:
            result['해약환급금'] = int(m.group(1).replace(',', ''))

    # 환급유형 판별 (문맥 기반, 한 줄이 아닌 전체 텍스트로 판단)
    if result['환급유형'] == 0:
        # 순수보장형 판별 (확실한 패턴)
        if re.search(r'순수\s*보장', full_text):
            result['환급유형'] = 4
        elif re.search(r'환급금이?\s*발생하지\s*않', full_text):
            result['환급유형'] = 4
        # 50% 환급
        elif re.search(r'50\s*%\s*환급', full_text):
            result['환급유형'] = 3
        # 만기환급 (명확한 패턴만)
        elif re.search(r'만기\s*(?:시\s*)?만기\s*환급금\s*지급', full_text):
            result['환급유형'] = 2
        elif re.search(r'만기\s*환급(?:금|형)', full_text):
            result['환급유형'] = 2
        # 종신보험 (상품명에 "종신" 포함 시)
        elif re.search(r'종신\s*보험', full_text):
            result['환급유형'] = 1

    return result


def _parse_amount(text):
    """금액 문자열을 정수로 변환. '2,000만원' → 20000000, '144,428원' → 144428"""
    text = text.strip()
    # 만원 단위
    m = re.search(r'([\d,]+)\s*만\s*원', text)
    if m:
        return int(m.group(1).replace(',', '')) * 10000
    # 원 단위
    m = re.search(r'([\d,]+)\s*원', text)
    if m:
        return int(m.group(1).replace(',', ''))
    # 숫자만 있는 경우
    m = re.search(r'([\d,]+)', text)
    if m:
        val = m.group(1).replace(',', '')
        if val:
            return int(val)
    return 0


# 2026-05-12: 진단비 카테고리에 들어가서는 안 되는 처치/치료/입원/약제 류 정규식.
# claude_parser.py 와 동일 — 두 파서에서 동일 룰을 적용해 일관된 결과 보장.
_DIAGNOSIS_TREATMENT_BLOCKLIST = re.compile(
    r'(?:'
    r'수술|치료|항암|입원|일당|통원|처방|조제|약제|주사|방사선|이식'
    r'|화학요법|면역|표적|호르몬|간병|간호|돌봄|수혈|투석|재활|요양'
    r')'
)


def _is_treatment_only(name):
    if not name:
        return False
    no_space = name.replace(' ', '')
    if '진단' in no_space:
        return False  # 진단 명시되면 처치 키워드 있어도 진단으로 간주
    return bool(_DIAGNOSIS_TREATMENT_BLOCKLIST.search(no_space))


# 정액형 입원 음성 토큰 — '일당/급여금/위로금/N일이상'은 정액(fixed-benefit) 입원이지
# 실손 입원의료비(indemnity)가 아니다. 키워드 매칭이 substring 이라 짧은 '질병입원'이
# '질병입원일당'을 실손으로 빨아들이는 오염을 막는 백스톱(claude/text-line 양 파이프라인 공용).
# 보수적 토큰만 — 실손 '입원형'/'입원비용' 오차단 방지(그 둘은 정액 토큰 미포함).
_FIXED_BENEFIT_INPATIENT = re.compile(r'일당|입원급여금|입원위로금|\d+일이상')


def _is_fixed_benefit_inpatient(name):
    """정액형 입원(일당·입원급여금·입원위로금·N일이상) 여부 → 실손 입원 path 거부용."""
    if not name:
        return False
    return bool(_FIXED_BENEFIT_INPATIENT.search(name.replace(' ', '')))


def is_keyword_excluded(text, keyword):
    """text 에서 keyword 가 '(...제외)' / '(...제거)' / '(...빼고)' 같은
    배제 컨텍스트 안에 있으면 True.

    예) "암(4대유사암제외)진단비" 에서 keyword='유사암' → True (그래프에서는 일반암)
        "4대유사암진단비(기타피부암)" 에서 keyword='유사암' → False (진짜 유사암)

    구현: 키워드 등장 위치 좌우 6자 윈도우 안에 "제외/제거/빼고" 가 있으면 배제로 간주.
    공백 제거 후 비교 (PDF 추출이 공백 변동성이 큼).
    """
    if not text or not keyword:
        return False
    no_space = text.replace(' ', '')
    idx = no_space.find(keyword)
    if idx < 0:
        return False
    window = no_space[max(0, idx - 6): idx + len(keyword) + 6]
    return ('제외' in window) or ('제거' in window) or ('빼고' in window)


_EXCLUSION_PAREN_REGEX = re.compile(r'[\(（][^()（）]*(?:제외|제거|빼고)[^()（）]*[\)）]')


def strip_exclusion_parens(text):
    """'X(...제외)Y' / 'X(...제거)Y' / 'X(...빼고)Y' 처럼 배제 컨텍스트 괄호 통째 제거.

    매칭 전 normalization 용도. 배제 키워드를 무시한 뒤 외곽 텍스트로 다시 매칭 가능하게 함.

    예) "암(4대유사암제외)진단비" → "암진단비" → 이후 키워드 매칭에서 "암진단" 매칭 OK → 일반암
        "4대유사암진단비(기타피부암)" → 그대로 (제외 없음)
    """
    if not text:
        return text
    return _EXCLUSION_PAREN_REGEX.sub('', text)


def _match_coverage(text):
    """줄에서 COVERAGE_KEYWORDS 매칭. path 또는 None 반환.
    짧은 줄(담보명 셀)에서만 매칭하도록 길이 제한 적용.
    긴 키워드 우선 매칭 (false positive 방지).

    2026-05-12: 매칭 결과가 '진단비->*' 면 처치/치료성 패턴 차단.
    "암수술비" 같은 처치성 담보가 일반암 진단비에 잘못 매핑되는 일 방지.

    2026-05-13: 매칭된 키워드가 '(...제외)' 같은 배제 컨텍스트 안에 있으면 그 키워드만
    건너뛰고 다음 후보로 진행. 예: "암(4대유사암제외)진단비" 에서 '유사암' 매칭 무시,
    이어서 '암진단' 등 다른 키워드 후보로 평가.
    추가로 strip_exclusion_parens() 로 배제 괄호 자체를 제거한 후 매칭 — '암(...제외)진단비'
    → '암진단비' 처럼 외곽 키워드 매칭이 가능해진다.
    """
    text = strip_exclusion_parens(text)
    no_space = text.replace(' ', '')
    no_space = re.sub(r'[\(（]\s*갱신[용형]?\s*[\)）]', '', no_space)
    no_space = re.sub(r'[\(（]\s*제?\s*\d+\s*차\s*[\)）]', '', no_space)  # (1차)/(제2차) 갱신 회차 표기 제거
    no_space = re.sub(r'갱신형$', '', no_space)
    no_space = re.sub(r'담보$', '', no_space)
    for path, keywords in COVERAGE_KEYWORDS.items():
        # 정액 입원(일당/급여금/N일이상)은 실손 입원의료비 path 가 아님 — 통째로 건너뜀.
        # (substring 매칭상 짧은 '질병입원'이 '질병입원일당'을 잡아 실손 오염시키는 것 차단.)
        if path.startswith('실손 의료비->') and '입원' in path and _is_fixed_benefit_inpatient(no_space):
            continue
        for kw in sorted(keywords, key=len, reverse=True):
            if kw in no_space:
                if is_keyword_excluded(text, kw):
                    continue  # 배제 컨텍스트 — 다음 키워드로
                # 진단비 카테고리는 처치/치료성 명칭 차단
                if path.startswith('진단비->') and _is_treatment_only(text):
                    return None
                return path
    return None


def _find_amount_in_line(text):
    """줄에서 금액을 추출. 한글 금액(5천만원, 1억원 등) 포함."""
    stripped = text.strip().replace(' ', '')

    # 한글 금액: 5천만원, 1억5천만원, 3백만원, 10,000만원 등
    m_kr = re.search(r'(\d[\d,]*억)?(\d천)?(\d백)?(\d[\d,]*)?만원', stripped)
    if m_kr and m_kr.group(0):
        amt = _parse_korean_amount(m_kr.group(0))
        if amt > 0:
            return amt

    # X억원
    m_ok = re.search(r'(\d+)억원', stripped)
    if m_ok:
        return int(m_ok.group(1)) * 100000000

    return 0


def _find_amount_in_line_numeric(text, unit=1):
    """줄에서 순수 숫자 금액 추출 (만원/원 접미사 없이)."""
    stripped = text.strip()

    # 순수 숫자만 있는 줄 (예: "140,000,000", "3,000")
    m = re.match(r'^([\d,]+)$', stripped)
    if m:
        val = int(m.group(1).replace(',', ''))
        if val >= 100:
            return val * unit
    # 숫자로 시작하는 줄 (예: "12,400 03년만기 / 전기납")
    m = re.match(r'^([\d,]+)\s+', stripped)
    if m:
        val = int(m.group(1).replace(',', ''))
        if val >= 100:
            return val * unit
    return 0


def _extract_detail_table(text_lines, ocrdata):
    """가입담보 테이블에서 세부사항 추출 (강화 버전).
    다양한 보험사 PDF 형식을 지원:
    - 한화 한아름: 담보명 → 금액(원) → 보험료 → 기간 → 상태
    - 한화 자녀보험: 담보명 → 설명(여러줄) → 금액(만원) → 날짜 → 기간
    - 메리츠: 담보명 → 기간 → 날짜 → 금액(만원) → 설명
    - 현대해상: 담보명+담보 → 금액(만원) → 기간+설명

    강화점:
    1. 다중 테이블 섹션 대응 (주계약 + 특약이 분리된 PDF)
    2. 담보별 보험료 컬럼 추출
    3. 테이블 헤더 없이도 담보 키워드 매칭으로 추출 (fallback)
    """
    col_header_kws = ['담보명', '가입금액', '보험료', '보험기간', '납입기간',
                      '보험시기', '보험종기', '담보상태', '갱신여부', '보장내용',
                      '보험/납입기간', '납기 및 만기', '보장명', '특약명']
    skip_kws = ['고객콜센터', '발행IP', '※ 상기', '■ 영업보험료', '문의전화',
                '보험계약사항', '전자서명일시', '인쇄일시']

    # === 1단계: 모든 테이블 헤더 클러스터 찾기 (다중 섹션 대응) ===
    table_sections = []
    i = 0
    while i < len(text_lines):
        stripped = text_lines[i].strip()
        if stripped and len(stripped) <= 40 and any(hk in stripped for hk in col_header_kws):
            # 이 위치부터 6줄 안에 컬럼 헤더가 몇 개 있는지
            score = 0
            cluster_end = i
            for j in range(i, min(i + 6, len(text_lines))):
                line_j = text_lines[j].strip()
                if line_j and len(line_j) < 40:
                    for hk in col_header_kws:
                        if hk in line_j:
                            score += 1
                            cluster_end = j
                            break
            if score >= 2:
                # 헤더 텍스트에서 금액 단위 판별
                header_text = ' '.join(text_lines[i:cluster_end + 1]).replace(' ', '')
                if '(만원)' in header_text or '만원)' in header_text:
                    numeric_unit = 10000
                elif '(원)' in header_text:
                    numeric_unit = 1
                else:
                    numeric_unit = 1
                table_sections.append({
                    'start': cluster_end + 1,
                    'unit': numeric_unit
                })
                i = cluster_end + 1
                continue
        i += 1

    # === 2단계: 각 섹션 + 전체 텍스트에서 담보 키워드 매칭 + 금액 추출 ===
    # 섹션이 없는 경우 전체 텍스트를 대상으로 스캔 (fallback)
    if not table_sections:
        table_sections = [{'start': 0, 'unit': 1}]

    matched_lines = set()  # 중복 매칭 방지

    for section in table_sections:
        data_start = section['start']
        numeric_unit = section['unit']

        i = data_start
        while i < len(text_lines):
            stripped = text_lines[i].strip()
            i += 1

            if not stripped:
                continue
            if i - 1 in matched_lines:
                continue

            # 페이지 구분, 주석 건너뛰기
            if stripped.startswith('※') or stripped.startswith('▶') or stripped.startswith('☎'):
                continue
            if re.match(r'^\d+/\d+$', stripped):
                continue
            if any(sk in stripped for sk in skip_kws):
                continue

            # 긴 줄(> 80자)은 설명/보장내용이므로 건너뛰기
            if len(stripped) > 80:
                continue

            # 담보 키워드 매칭
            path = _match_coverage(stripped)
            if not path:
                continue

            matched_lines.add(i - 1)

            # === lookahead: 최대 12줄까지 금액/기간/보험료 수집 ===
            amounts = []  # (금액, 줄인덱스) - 복수 금액 수집 (보장금액 + 보험료)
            lookahead_lines = [stripped]

            for j in range(i, min(i + 12, len(text_lines))):
                next_line = text_lines[j].strip()
                if not next_line:
                    continue

                # 다음 담보 키워드가 짧은 줄에서 나오면 종료
                if len(next_line) <= 80 and _match_coverage(next_line):
                    break

                # 컬럼 헤더 반복이면 종료
                if len(next_line) < 30 and any(hk in next_line for hk in col_header_kws):
                    normalized_next = next_line.replace(' ', '')
                    if any(hk.replace(' ', '') in normalized_next for hk in col_header_kws):
                        break

                lookahead_lines.append(next_line)

            # 금액 추출 - 모든 lookahead 줄에서 금액 수집
            for la_line in lookahead_lines:
                # 한글 금액 (5천만원, 1억원 등)
                amt = _find_amount_in_line(la_line)
                if amt > 0:
                    amounts.append(amt)

            # 한글 금액 못 찾으면 순수 숫자로 시도
            if not amounts:
                for la_line in lookahead_lines[1:]:
                    amt = _find_amount_in_line_numeric(la_line, numeric_unit)
                    if amt > 0:
                        amounts.append(amt)
                        break  # 숫자 금액은 첫 번째만

            # 같은 줄에서 "원" 단위 금액 찾기 (담보명 줄에 금액이 포함된 경우)
            if not amounts:
                m = re.search(r'([\d,]+)\s*원', stripped)
                if m:
                    val = int(m.group(1).replace(',', ''))
                    if val >= 10000:  # 1만원 이상만
                        amounts.append(val)

            if not amounts:
                continue

            # 첫 번째 금액 = 보장금액
            amount = amounts[0]

            # 기간 추출
            combined = ' '.join(lookahead_lines)
            payment_period = ''

            m_pay = re.search(r'(\d+)\s*년\s*납', combined)
            # "세만기"를 먼저 확인, 없으면 "세" 단독
            m_cov = re.search(r'(\d+)\s*세\s*만기', combined)
            if not m_cov:
                m_cov = re.search(r'(\d+)\s*세', combined)
            m_renew = re.search(r'(\d+)\s*년\s*갱신', combined)
            # 숫자 없는 갱신형 표기: "갱신형", "(갱신)", "(갱신형)", "갱신" 단독
            is_renewal_only = (not m_renew) and bool(
                re.search(r'갱신형|[\(（]\s*갱신[형용]?\s*[\)）]|\b갱신\b', combined)
            )
            m_year_mangi = re.search(r'(\d+)\s*년\s*만기', combined)
            m_jongshin = re.search(r'종신', combined)

            if m_pay:
                payment_period = f'{m_pay.group(1)}:1'
            if m_cov:
                payment_period = f'{payment_period}:{m_cov.group(1)}:1'
            elif m_year_mangi:
                payment_period = f'{payment_period}:{m_year_mangi.group(1)}:2'
            elif m_jongshin:
                payment_period = f'{payment_period}:0:4'  # 종신=type 4
            if m_renew:
                payment_period = f'{payment_period}:갱신{m_renew.group(1)}'
            elif is_renewal_only:
                payment_period = f'{payment_period}:갱신1'  # 기본값 1년갱신

            value = f'{payment_period}:{amount}'

            # dict_detail_data에 삽입
            keys = path.split('->')
            try:
                target = ocrdata.dict_detail_data[keys[0]][keys[1]][keys[2]]
                if value not in target:
                    target.append(value)
            except (KeyError, IndexError):
                pass


def _has_meaningful_data(ocrdata):
    """fallback 파싱 결과가 유의미한 데이터를 포함하는지 검증"""
    if not ocrdata:
        return False

    # 보험사 인덱스가 유효하면 의미 있음
    if ocrdata.dict_life_head_data.get('생명보험', -1) >= 0:
        return True
    if ocrdata.dict_loss_head_data.get('손해보험', -1) >= 0:
        return True

    # 상품명이 있으면 의미 있음
    if ocrdata.dict_life_head_data.get('상품명', ''):
        return True
    if ocrdata.dict_loss_head_data.get('상품명', ''):
        return True

    # 보험료가 있으면 의미 있음
    if ocrdata.dict_loss_head_data.get('월보장보험료', 0) > 0:
        return True
    if ocrdata.dict_life_head_data.get('월납입보험료', 0) > 0:
        return True

    return False


def regex_fallback_parse(extract_data_list):
    """범용 정규식 fallback 파서. 템플릿 매칭 실패 시 호출."""
    ocrdata = Ocr_Data()
    ocrdata.parsing_method = 'regex_fallback'

    # 1. 보험사 감지
    company_idx, insurance_type, company_name = _detect_company(extract_data_list)
    print(f'regex_fallback: company={company_name}, type={insurance_type}, idx={company_idx}')

    # 2. 상품명 추출
    product_name = _extract_product_name(extract_data_list)

    # 3. 계약자/피보험자 추출
    contractor = _extract_person_name(extract_data_list, r'계약자[명]?')
    insured = _extract_person_name(extract_data_list, r'(?:주\s*)?피보험자[명]?')

    # 4. 납입기간/보장기간 추출
    periods = _extract_periods(extract_data_list)

    # 5. 보험료 추출
    premiums = _extract_premiums(extract_data_list)

    # 6. 날짜 추출
    dates = _extract_dates(extract_data_list)

    # 7. 갱신 정보 추출
    renewal = _extract_renewal_info(extract_data_list)

    # 8. 환급 정보 추출
    refund = _extract_refund_info(extract_data_list)

    # 9. 보험사 타입에 따라 데이터 채우기
    if insurance_type == 'loss':
        ocrdata.dict_loss_head_data['손해보험'] = company_idx
        ocrdata.dict_loss_head_data['상품명'] = product_name
        ocrdata.dict_loss_head_data['계약자'] = contractor
        ocrdata.dict_loss_head_data['피보험자'] = insured
        ocrdata.dict_loss_head_data['납입기간'] = periods['납입기간']
        ocrdata.dict_loss_head_data['보장기간'] = periods['보장기간']
        ocrdata.dict_loss_head_data['월보장보험료'] = premiums['보장보험료']
        ocrdata.dict_loss_head_data['월적립보험료'] = premiums['적립보험료']
        ocrdata.dict_loss_head_data['월납입보험료'] = premiums['월납입보험료']
        ocrdata.dict_loss_head_data['계약일'] = dates['계약일']
        ocrdata.dict_loss_head_data['만기일'] = dates['만기일']
        ocrdata.dict_loss_head_data['월갱신보험료'] = renewal['월갱신보험료']
        ocrdata.dict_loss_head_data['갱신증가율'] = 0  # 무조건 0% (설계사가 직접 수정)
        ocrdata.dict_loss_head_data['해약환급금'] = refund['해약환급금']
    elif insurance_type == 'life':
        ocrdata.dict_life_head_data['생명보험'] = company_idx
        ocrdata.dict_life_head_data['상품명'] = product_name
        ocrdata.dict_life_head_data['계약자'] = contractor
        ocrdata.dict_life_head_data['피보험자'] = insured
        ocrdata.dict_life_head_data['납입기간'] = periods['납입기간']
        ocrdata.dict_life_head_data['보장기간'] = periods['보장기간']
        ocrdata.dict_life_head_data['월납입보험료'] = premiums['월납입보험료']
        ocrdata.dict_life_head_data['월적립보험료'] = premiums['적립보험료']
        ocrdata.dict_life_head_data['월주계약보험료'] = premiums['주계약보험료']
        ocrdata.dict_life_head_data['월특약보험료'] = premiums['특약보험료']
        ocrdata.dict_life_head_data['계약일'] = dates['계약일']
        ocrdata.dict_life_head_data['갱신증가율'] = 0  # 무조건 0% (설계사가 직접 수정)
        ocrdata.dict_life_head_data['해약환급금'] = refund['해약환급금']
        if refund['환급유형'] > 0:
            ocrdata.dict_life_head_data['월적립보험료종류'] = refund['환급유형'] - 1
    else:
        # 보험사 타입 불명 - 손해보험으로 기본 설정
        ocrdata.dict_loss_head_data['상품명'] = product_name
        ocrdata.dict_loss_head_data['계약자'] = contractor
        ocrdata.dict_loss_head_data['피보험자'] = insured
        ocrdata.dict_loss_head_data['납입기간'] = periods['납입기간']
        ocrdata.dict_loss_head_data['보장기간'] = periods['보장기간']
        ocrdata.dict_loss_head_data['월보장보험료'] = premiums['보장보험료']
        ocrdata.dict_loss_head_data['월적립보험료'] = premiums['적립보험료']
        ocrdata.dict_loss_head_data['월납입보험료'] = premiums['월납입보험료']
        ocrdata.dict_loss_head_data['계약일'] = dates['계약일']
        ocrdata.dict_loss_head_data['만기일'] = dates['만기일']
        ocrdata.dict_loss_head_data['월갱신보험료'] = renewal['월갱신보험료']
        ocrdata.dict_loss_head_data['갱신증가율'] = 0  # 무조건 0% (설계사가 직접 수정)
        ocrdata.dict_loss_head_data['해약환급금'] = refund['해약환급금']
        if refund['환급유형'] > 0:
            ocrdata.dict_loss_head_data['환급유형'] = refund['환급유형']

    # 10. 담보 세부사항 추출
    _extract_detail_table(extract_data_list, ocrdata)

    # 11. 계/피 동일 여부 자동 판별
    if contractor and insured and contractor == insured:
        ocrdata.is_same_insured = True

    # 12. 해약환급금 퍼센트 인덱스 역산
    # 해약환급금퍼센트 인덱스: 0=120%, 1=110%, ..., 12=0% (10% 단위)
    monthly_premium = premiums['월납입보험료']
    payment_years = periods['납입기간']
    if refund['해약환급금'] > 0 and monthly_premium > 0 and payment_years > 0:
        total_paid = monthly_premium * payment_years * 12
        if total_paid > 0:
            percent = refund['해약환급금'] / total_paid * 100
            # 10% 단위로 반올림하여 인덱스 변환 (120%=0, 110%=1, ..., 0%=12)
            percent_rounded = round(percent / 10) * 10
            percent_rounded = min(120, max(0, percent_rounded))
            ocrdata.refund_percent_index = (120 - percent_rounded) // 10

    # 13. 갱신보장보험료가 있으면 손해보험 월갱신보험료에 매핑
    if insurance_type == 'loss' and premiums.get('갱신보장보험료', 0) > 0:
        if ocrdata.dict_loss_head_data.get('월갱신보험료', 0) == 0:
            ocrdata.dict_loss_head_data['월갱신보험료'] = premiums['갱신보장보험료']

    print(f'regex_fallback: product={product_name}, premium={premiums["월납입보험료"]}, '
          f'contractor={contractor}, insured={insured}, '
          f'is_same={ocrdata.is_same_insured}, refund_pct_idx={ocrdata.refund_percent_index}')

    return ocrdata
