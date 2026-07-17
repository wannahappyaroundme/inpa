from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from django.test import SimpleTestCase

from .import_contract import COVERAGE_MARKERS, PDFImportError
from .import_pdf_mask import (
    DocumentPseudonymizer,
    assert_pseudonymized_pages_safe,
    contains_probable_direct_identifier,
    mask_page_lines,
    pseudonymize_page_lines,
)


class LinearPDFMaskTests(SimpleTestCase):
    def test_unlabeled_standalone_identity_is_masked_conservatively(self):
        synthetic_name = '김가온'
        synthetic_address = '테스트광역시 가림구 보호로 123'
        coverage_lines = (
            '유사암진단비',
            '백혈병진단비',
            '상해후유장해진단비',
        )

        result = pseudonymize_page_lines((
            (synthetic_name, synthetic_address, *coverage_lines),
        ))

        flattened = '\n'.join(result.pages[0])
        self.assertNotIn(synthetic_name, flattened)
        self.assertNotIn(synthetic_address, flattened)
        self.assertEqual(result.pages[0][0], '[고객_1]')
        self.assertEqual(result.pages[0][1], '[주소_1]')
        self.assertEqual(result.pages[0][2:], coverage_lines)
        for raw_value in (synthetic_name, synthetic_address):
            with self.subTest(raw_value_kind=len(raw_value)):
                with self.assertRaises(PDFImportError):
                    assert_pseudonymized_pages_safe(((raw_value,),))

    def test_unlabeled_three_syllable_names_do_not_depend_on_surname_allowlist(self):
        synthetic_names = (
            '엄가온', '류하람', '차다온', '주가온', '구하람',
            '김가형', '류하율', '차은비', '주다금',
            '한도윤', '김유지', '이정상', '최장기', '고주민',
        )

        result = pseudonymize_page_lines((synthetic_names,))
        serialized = repr(result.pages)

        for index, raw_name in enumerate(synthetic_names, start=1):
            with self.subTest(index=index):
                self.assertNotIn(raw_name, serialized)
                self.assertIn(f'[고객_{index}]', serialized)
                with self.assertRaises(PDFImportError):
                    assert_pseudonymized_pages_safe(((raw_name,),))
        self.assertTrue(result.residual_scan_passed)

    def test_ambiguous_unlabeled_identity_is_quarantined(self):
        synthetic_ambiguous_value = '김가온 부가표기'

        result = pseudonymize_page_lines(((
            synthetic_ambiguous_value,
            '일반암진단비 3,000만원',
        ),))

        self.assertEqual(result.pages[0][0], '')
        self.assertEqual(result.quarantined_line_count, 1)
        self.assertNotIn(synthetic_ambiguous_value, repr(result.pages))

    def test_low_confidence_standalone_variants_are_quarantined(self):
        synthetic_variants = (
            '김솔',
            '엄솔',
            '한도',
            '남궁가온',
            '류가온별',
            '가온동 123-4',
            '테스트광역시 가림구 보호로',
            '테스트광역시 가림구 보호리',
        )

        for synthetic_value in synthetic_variants:
            with self.subTest(shape=len(synthetic_value)):
                result = pseudonymize_page_lines(((
                    synthetic_value,
                    '일반암진단비 3,000만원',
                ),))
                self.assertEqual(result.pages[0][0], '')
                self.assertEqual(result.quarantined_line_count, 1)
                self.assertNotIn(synthetic_value, repr(result.pages))

    def test_short_korean_insurance_terms_are_not_blanket_blocked(self):
        coverage_lines = (
            '보험',
            '입원비',
            '정액형',
            '일반암',
            '유사암',
            '소액암',
            '특정암',
            '암진단비',
            '질병수술비',
            '이전계약',
            '장기보험료',
            '상해사망',
            '보험기간',
            '납입기간',
            '보장기간',
            '뇌졸중',
            '골절비',
            '화상비',
            '벌금',
            '상해',
            '질병',
            '수술',
            '입원',
            '무배당',
            '고객센터',
            '적립금',
            '환급금',
            '간병비',
            '치매비',
            '교통비',
            '응급실',
            '간병인',
            '중환자실',
            '표적항암',
            '생활비',
            '위로금',
            '보험료',
        )

        result = pseudonymize_page_lines((coverage_lines,))

        self.assertEqual(result.pages, (coverage_lines,))
        self.assertTrue(assert_pseudonymized_pages_safe((coverage_lines,)))

    def test_exact_coverage_markers_survive_pseudonymization(self):
        result = pseudonymize_page_lines((COVERAGE_MARKERS,))

        self.assertEqual(result.pages, (COVERAGE_MARKERS,))
        self.assertTrue(assert_pseudonymized_pages_safe((COVERAGE_MARKERS,)))

    def test_compound_coverage_markers_survive_as_standalone_table_cells(self):
        coverage_terms = ('사망보험금', '상해수술비', '입원일당', '후유장해')

        result = pseudonymize_page_lines((coverage_terms,))

        self.assertEqual(result.pages, (coverage_terms,))
        self.assertTrue(assert_pseudonymized_pages_safe((coverage_terms,)))

    def test_mixed_identity_and_analysis_signals_fail_closed(self):
        synthetic_mixed_lines = (
            '김솔 3,000만원',
            '남궁가온 일반암진단비 3,000만원',
            '한도윤 일반암진단비 3,000만원',
            '김유지 보험료 30,000원',
            '일반암진단비 엄가온 3,000만원',
            '가입금액 3,000만원 엄가온',
            '엄 가온',
            '엄 가온 일반암진단비 3,000만원',
            '탁솔 보험료 30,000원',
            '일반암진단비 탁가온별 3,000만원',
            '가입금액 3,000만원 탁 가온',
            '탁보장 일반암진단비 3,000만원',
            '일반암진단비 석한도 3,000만원',
            '석정상 보험료 30,000원',
            '탁유지 일반암진단비 3,000만원',
            '도안내 보험료 30,000원',
            '복정보 일반암진단비 3,000만원',
            '탁보험금 보험료 30,000원',
            '보험료 30,000원 탁보험금',
            '탁진단비 일반암진단비 3,000만원',
            '남궁가온별빛 보험료 30,000원',
            '황보하늘사랑 일반암진단비 3,000만원',
            '탁가온하늘별빛 보험료 30,000원',
            '테스트광역시 가림구 보호로 123 보험료 30,000원',
        )

        for synthetic_line in synthetic_mixed_lines:
            with self.subTest(shape=len(synthetic_line)):
                result = pseudonymize_page_lines(((synthetic_line,),))
                self.assertEqual(result.pages, (('',),))
                self.assertEqual(result.quarantined_line_count, 1)
                self.assertEqual(
                    result.analysis_signal_quarantined_line_count,
                    0 if synthetic_line == '엄 가온' else 1,
                )
                self.assertNotIn(synthetic_line, repr(result.pages))

    def test_ambiguous_standalone_insurance_copy_is_quarantined(self):
        synthetic_value = '안내'

        result = pseudonymize_page_lines(((
            synthetic_value,
            '일반암진단비 3,000만원',
        ),))

        self.assertEqual(result.pages[0][0], '')
        self.assertEqual(result.quarantined_line_count, 1)
        self.assertNotIn(synthetic_value, repr(result.pages))

    def test_additional_unlabeled_name_variants_are_quarantined(self):
        synthetic_variants = (
            '김 가온',
            '김가온별',
            '김가온별빛',
            'ALEX MORGAN KIM',
            '김 가온 보험료 30,000원',
            '남궁가온별빛',
            '황보하늘사랑',
            '제갈푸른하늘',
            '남궁 가온별빛',
            '탁 솔',
            '탁 가온별',
            '탁 가온하람',
            '남궁 가온',
            '남궁 가온별',
            '탁가온하늘별빛',
            '탁 가온하늘별빛',
        )

        for synthetic_value in synthetic_variants:
            with self.subTest(shape=len(synthetic_value)):
                result = pseudonymize_page_lines(((synthetic_value,),))
                self.assertEqual(result.pages, (('',),))
                self.assertEqual(result.quarantined_line_count, 1)
                self.assertNotIn(synthetic_value, repr(result.pages))

    def test_spaced_short_coverage_terms_remain_analysis_evidence(self):
        coverage_lines = (
            '상해 수술비 100만원',
            '질병 수술비 100만원',
            '실손 의료비 5,000만원',
            '상해 사망 1억원',
            '질병 입원비 5,000만원',
            '뇌 혈관 진단비 1,000만원',
        )

        result = pseudonymize_page_lines((coverage_lines,))

        self.assertEqual(result.pages, (coverage_lines,))
        self.assertEqual(result.quarantined_line_count, 0)

    def test_identity_remaining_after_global_alias_is_quarantined(self):
        synthetic_lines = (
            '010-2468-1357 김가온',
            'private@example.com 김가온',
            '800101-1234567 남궁가온',
            '[고객_1] 탁가온별',
            '010-2468-1357 담당 김가온',
            'private@example.com 담당 김가온',
            '800101-1234567 문의 남궁가온',
            '[전화_1] 담당 탁가온별',
        )

        for synthetic_line in synthetic_lines:
            with self.subTest(shape=len(synthetic_line)):
                result = pseudonymize_page_lines(((synthetic_line,),))
                self.assertEqual(result.pages, (('',),))
                self.assertEqual(result.quarantined_line_count, 1)
                self.assertNotIn(synthetic_line, repr(result.pages))

    def test_name_with_relationship_metadata_is_quarantined(self):
        synthetic_lines = (
            '탁솔 본인',
            '탁가온별 본인',
            '탁가온하람 남 본인',
            '남궁가온별빛 남 본인',
            '010-2468-1357 탁가온별 본인',
            '[고객_1] 남궁가온별빛 본인',
            '궉 솔',
            '궉 가온',
            '궉 가온별',
            '궉 가온하람',
            '궉 솔 보험료 30,000원',
        )

        for synthetic_line in synthetic_lines:
            with self.subTest(shape=len(synthetic_line)):
                result = pseudonymize_page_lines(((synthetic_line,),))
                self.assertEqual(result.pages, (('',),))
                self.assertEqual(result.quarantined_line_count, 1)
                self.assertNotIn(synthetic_line, repr(result.pages))

    def test_ocr_delimited_unlabeled_names_are_quarantined(self):
        synthetic_lines = (
            '김·솔', '김.솔', '김-솔', '궉·솔', '남궁·가온',
            '김·가·온', '김 · 가온', '남궁-가-온',
            '김·솔 본인', '궉·솔 본인', '김·솔 관계', '담당 김·솔',
            '010-2468-1357 보험료 김·솔',
            '[전화_1] 보험료 궉·솔',
        )

        for synthetic_line in synthetic_lines:
            with self.subTest(shape=len(synthetic_line)):
                result = pseudonymize_page_lines(((synthetic_line,),))
                self.assertEqual(result.pages, (('',),))
                self.assertEqual(result.quarantined_line_count, 1)
                self.assertNotIn(synthetic_line, repr(result.pages))

    def test_contextual_korean_and_english_names_are_quarantined(self):
        synthetic_lines = (
            '(김가온)', '[김가온]', '김가온(본인)', '김가온, 본인',
            '담당 김가온', '김\u00a0가온',
            '탁솔 형제', '탁솔 모', '탁솔 부', '탁가온별 형제',
            '남궁가온 모', '김·가온 모', '김-가온 형제', '김가 온별',
            '담당 ALEX MORGAN KIM', '본인 ALEX MORGAN KIM',
            '(ALEX MORGAN KIM)', '[ALEX MORGAN KIM]',
        )

        for synthetic_line in synthetic_lines:
            with self.subTest(shape=len(synthetic_line)):
                result = pseudonymize_page_lines(((synthetic_line,),))
                self.assertEqual(result.pages, (('',),))
                self.assertEqual(result.quarantined_line_count, 1)
                self.assertNotIn(synthetic_line, repr(result.pages))

    def test_ambiguous_product_keyword_is_private_unless_product_shaped(self):
        private_lines = (
            '한아름', '010-2468-1357 한아름', '[전화_1] 한아름',
            '한아름 본인',
        )
        for private_line in private_lines:
            with self.subTest(shape=len(private_line)):
                result = pseudonymize_page_lines(((private_line,),))
                self.assertNotIn(private_line, repr(result.pages))

        product_lines = (
            '한아름보험', '한아름종합보험', '한아름건강보험',
            '한아름종합보험 보험료 30,000원',
        )
        result = pseudonymize_page_lines((product_lines,))
        self.assertEqual(result.pages, (product_lines,))

    def test_insurance_morphemes_do_not_make_person_shaped_values_safe(self):
        private_lines = (
            '탁보험암', '탁진단암', '탁상해암', '김암보험', '김암진단',
            '보험암탁', '진단암탁', '상해암탁', '암보험탁', '암진단탁',
            '장해진 보험료', '장해진보험료 30,000원', '진단희 보험료',
            '고도암', '진단암', '상해암', '장해암',
            '고도암 보험료 30,000원', '진단암 가입금액 1,000만원',
            '상해암 진단비 1,000만원', '진단암비', '상해암비',
            '장해암금', '고도암종',
            '탁보험암 본인', '탁상해암 모', '김암보험 형제',
            '보험암탁 본인', '진단암탁 모', '상해암탁 형제',
            '탁보험암 보험료 30,000원',
            '보험암탁 보험료 30,000원', '진단암탁 가입금액 1,000만원',
            '김상해 보험료', '김상해보험료 30,000원',
            '이상해 보험료', '이상해보험료 30,000원',
            '김진단 보험료', '이상 보험료 30,000원',
            '이하 가입금액 1,000만원', '1 이상 보험료 30,000원',
            '2 이하 가입금액 1,000만원',
        )

        for private_line in private_lines:
            with self.subTest(shape=len(private_line)):
                result = pseudonymize_page_lines(((private_line,),))
                self.assertNotIn(private_line, repr(result.pages))
                self.assertTrue(
                    result.pages == (('',),)
                    or '[고객_1]' in result.pages[0][0]
                )

    def test_colon_and_relationship_english_names_are_quarantined(self):
        private_lines = (
            '담당: ALEX MORGAN KIM', '담당：ALEX MORGAN KIM',
            '본인 : ALEX MORGAN KIM', '본인 ALEX MORGAN KIM 관계',
            '담당 - ALEX MORGAN KIM', '본인 ALEX MORGAN KIM, 관계',
            '담당: 김가온', '담당：김가온', '본인 : 김가온',
            '담당 김/가온', '김|가온',
            'ALEX·MORGAN·KIM', 'ALEX.MORGAN.KIM',
            'ALEX/MORGAN/KIM', 'ALEX-MORGAN-KIM',
            'KIM, ALEX MORGAN', 'KIM,ALEX,MORGAN',
            'ALEX-KIM', 'ALEX/KIM', 'ALEX.KIM',
            '담당 / ALEX MORGAN KIM', '담당 | ALEX MORGAN KIM',
            '본인 ALEX MORGAN KIM / 관계',
        )

        for private_line in private_lines:
            with self.subTest(shape=len(private_line)):
                result = pseudonymize_page_lines(((private_line,),))
                self.assertEqual(result.pages, (('',),))
                self.assertEqual(result.quarantined_line_count, 1)

    def test_common_insurance_product_types_are_preserved(self):
        product_lines = (
            '건강보험', '어린이보험', '종신보험', '연금보험', '정기보험',
            '운전자보험', '치아보험', '간병보험', '태아보험', '화재보험',
            '자동차보험', '변액보험', '유병자보험', '여행자보험',
            '펫보험', '저축보험', '저축성보험', '연금저축보험', '단체보험',
            '해상보험', '보증보험', '신용보험', '재산보험', '상조보험',
            '실버보험', '치매보험', '주택화재보험', '가정종합보험',
            '보장성보험', '무해지보험', '무배당보험', '간편보험',
            '간편심사보험', '유병력자보험',
        )

        result = pseudonymize_page_lines((product_lines,))

        self.assertEqual(result.pages, (product_lines,))
        self.assertEqual(result.quarantined_line_count, 0)

    def test_relationship_context_overrides_insurance_word_ambiguity(self):
        private_lines = (
            '상해 본인', '상해 모', '질병 본인', '수술 본인', '입원 본인',
            '벌금 본인', '실손 본인', '교보 본인', '라이나 본인',
            '(상해)', '상해, 본인', '(상해) 보험료 30,000원',
            '[상해] 가입금액 1,000만원',
        )

        for private_line in private_lines:
            with self.subTest(shape=len(private_line)):
                result = pseudonymize_page_lines(((private_line,),))
                self.assertEqual(result.pages, (('',),))
                self.assertEqual(result.quarantined_line_count, 1)

    def test_unicode_variant_names_are_quarantined(self):
        private_lines = (
            '김\u200b가온', '김\u2009가온', '담당 김\u200b가온',
            '김가온', 'ㄱㅣㅁㄱㅏㅇㅗㄴ',
            '김\u2060가온', '김\u00ad가온',
        )

        for private_line in private_lines:
            with self.subTest(shape=len(private_line)):
                result = pseudonymize_page_lines(((private_line,),))
                self.assertNotIn(private_line, repr(result.pages))
                self.assertTrue(
                    result.pages == (('',),)
                    or '[고객_1]' in result.pages[0][0]
                )

    def test_short_carrier_alias_after_identifier_is_quarantined(self):
        private_lines = (
            '010-2468-1357 동양', 'private@example.com 교보',
            '010-2468-1357 라이나', 'private@example.com 라이나',
            '010-2468-1357 에이스',
        )

        for private_line in private_lines:
            with self.subTest(shape=len(private_line)):
                result = pseudonymize_page_lines(((private_line,),))
                self.assertEqual(result.pages, (('',),))
                self.assertEqual(result.quarantined_line_count, 1)

    def test_parenthesized_policy_structure_is_preserved(self):
        insurance_lines = (
            '(무배당) 건강보험', '(주계약) 사망보험금 1억원',
            '(무배당)', '(주계약)',
        )

        result = pseudonymize_page_lines((insurance_lines,))

        self.assertEqual(result.pages, (insurance_lines,))
        self.assertEqual(result.quarantined_line_count, 0)

    def test_spaced_numeric_threshold_conditions_are_preserved(self):
        insurance_lines = (
            '10% 이상 보험료 30,000원', '10％ 이상 진단비 1,000만원',
            '80세 이상 보험기간', '1일 이상 입원비 5만원',
            '3년 이상 보장기간', '10만원 이상 가입금액',
            '180일 이상 입원비 5만원',
        )

        result = pseudonymize_page_lines((insurance_lines,))

        self.assertEqual(result.pages, (insurance_lines,))
        self.assertEqual(result.quarantined_line_count, 0)

    def test_canonical_carriers_and_policy_structure_cells_are_preserved(self):
        insurance_lines = (
            '한화생명', '신한라이프', '동양생명', '한화손해보험',
            '교보', '동양',
            '한화생명 보험료 30,000원',
            '신한라이프 일반암진단비 3,000만원',
            '만기보험금', '해약환급금', '납입면제', '면책기간',
            '감액기간', '보장개시일', '계약상태', '실효일자',
            '부활일자', '중도인출', '적립보험료', '위험보험료',
            '특약보험금', '만기환급금', '기본보험금',
            '보장보험료: 61,186원', '주계약보험료 55,000원',
            '특약보험료 12,000원', '납입보험료(원)',
            '해지환급금 1,234,567원', '보 장 보 험 료',
        )

        result = pseudonymize_page_lines((insurance_lines,))

        self.assertEqual(result.pages, (insurance_lines,))
        self.assertEqual(result.quarantined_line_count, 0)

    def test_normalization_and_standard_tree_vocabulary_is_preserved(self):
        from inpa.analysis.management.commands.seed_normalization import (
            NORMALIZATION_V0,
            STANDARD_TREE,
        )

        raw_names = {raw_name for _company, raw_name, _leaf in NORMALIZATION_V0}
        standard_leaves = {
            detail_name
            for _category, _insurance_type, subcategories in STANDARD_TREE
            for _subcategory, details in subcategories
            for detail_name, _amount in details
        }
        coverage_lines = tuple(
            f'{name} 1,000만원'
            for name in sorted(raw_names | standard_leaves)
        )

        result = pseudonymize_page_lines((coverage_lines,))

        self.assertEqual(result.pages, (coverage_lines,))
        self.assertEqual(result.quarantined_line_count, 0)

    def test_korean_and_english_insurance_names_remain_unchanged(self):
        insurance_lines = (
            '무배당 건강보장보험',
            '일반암진단비 3,000만원',
            'GLOBAL HEALTH INSURANCE',
            'CANCER DIAGNOSIS BENEFIT',
            'HANWHA LIFE',
        )

        result = pseudonymize_page_lines((insurance_lines,))

        self.assertEqual(result.pages, (insurance_lines,))
        self.assertTrue(assert_pseudonymized_pages_safe((insurance_lines,)))

    def test_document_local_aliases_are_consistent_across_pages(self):
        customer = '테스트고객경계'
        phone_formats = ('010-2468-1357', '010 2468 1357')
        identifier_formats = (
            'TEST-POLICY-12345',
            'TEST POLICY 12345',
        )
        pages = (
            (
                f'계약자 성명: {customer}',
                f'연락처: {phone_formats[0]}',
                f'증권번호: {identifier_formats[0]}',
            ),
            (
                '계약자 성명',
                '',
                customer,
                f'연락처 {phone_formats[1]}',
                f'증권번호 {identifier_formats[1]}',
            ),
        )

        result = pseudonymize_page_lines(pages)
        serialized = repr(result)

        for sentinel in (customer, *phone_formats, *identifier_formats):
            self.assertNotIn(sentinel, serialized)
        self.assertEqual(serialized.count('[고객_1]'), 2)
        self.assertEqual(serialized.count('[전화_1]'), 2)
        self.assertEqual(serialized.count('[증권번호_1]'), 2)
        self.assertTrue(result.residual_scan_passed)
        self.assertFalse(hasattr(result, 'source_map'))
        self.assertFalse(hasattr(result, 'maps'))

        pseudonymizer = DocumentPseudonymizer()
        pseudonymizer.pseudonymize(pages)
        self.assertNotIn(customer, repr(pseudonymizer))

    def test_expanded_identity_labels_use_category_specific_aliases(self):
        sentinels = {
            '계약번호': 'TEST-CONTRACT-1001',
            '증권번호': 'TEST-POLICY-1002',
            '고객번호': 'TEST-CUSTOMER-1003',
            '증서번호': 'TEST-CERT-1004',
            '청약번호': 'TEST-APPLICATION-1005',
            '설계사번호': 'TEST-PLANNER-1006',
            '모집자번호': 'TEST-RECRUITER-1007',
            '등록번호': 'TEST-LICENSE-1008',
            '생년월일': '1988.04.03',
            '주소': '테스트시 보장구 안심로 10',
        }
        pages = ((
            *(f'{label}: {value}' for label, value in sentinels.items()),
            '모집자: 테스트설계사(고유번호: TEST-UNIQUE-1009)',
            '대표자: 테스트대표',
            '일반암진단비(갱신형) 가입금액 3,000만원 '
            '보험료 12,600원 20년납 100세만기',
        ),)

        result = pseudonymize_page_lines(pages)
        flattened = '\n'.join(result.pages[0])

        for sentinel in (*sentinels.values(), '테스트설계사',
                         'TEST-UNIQUE-1009', '테스트대표'):
            self.assertNotIn(sentinel, flattened)
        for token in (
                '[계약번호_1]', '[증권번호_1]', '[고객번호_1]',
                '[증서번호_1]', '[청약번호_1]', '[설계사번호_1]',
                '[모집자번호_1]', '[등록번호_1]', '[생년월일_1]',
                '[주소_1]', '[설계사_1]', '[고객_1]'):
            self.assertIn(token, flattened)
        self.assertIn(
            '일반암진단비(갱신형) 가입금액 3,000만원 '
            '보험료 12,600원 20년납 100세만기',
            flattened,
        )

    def test_identifier_field_wrappers_are_masked_and_residual_blocked(self):
        cases = (
            ('계약번호(번호)privatecode', '계약번호(번호)[계약번호_1]'),
            ('계약번호（번호）privatecode', '계약번호（번호）[계약번호_1]'),
            ('계약번호[번호]privatecode', '계약번호[번호][계약번호_1]'),
            ('계약번호{번호}: privatecode', '계약번호{번호}: [계약번호_1]'),
            ('설계사번호（TEST）abc123', '설계사번호（TEST）[설계사번호_1]'),
            ('증권번호{NO.}policycode', '증권번호{NO.}[증권번호_1]'),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                result = pseudonymize_page_lines(((source,),))
                self.assertEqual(result.pages, ((expected,),))
                self.assertNotIn('privatecode', repr(result))
                self.assertNotIn('abc123', repr(result))
                self.assertNotIn('policycode', repr(result))
                with self.assertRaises(PDFImportError):
                    assert_pseudonymized_pages_safe(((source,),))

    def test_concurrent_documents_do_not_share_alias_maps_or_counters(self):
        pages = [
            ((f'계약자 성명: 테스트고객{number}',),)
            for number in range(12)
        ]

        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(pseudonymize_page_lines, pages))

        self.assertTrue(all(
            result.pages == (('계약자 성명: [고객_1]',),)
            for result in results
        ))
        for number, result in enumerate(results):
            self.assertNotIn(f'테스트고객{number}', repr(result))

    def test_independent_residual_scan_fails_with_safe_code_only(self):
        sentinel = 'TEST-UNMASKED-45678'

        with self.assertRaises(PDFImportError) as caught:
            assert_pseudonymized_pages_safe(((f'계약번호: {sentinel}',),))

        self.assertEqual(caught.exception.code, 'PII_REDACTION_UNCERTAIN')
        self.assertNotIn(sentinel, str(caught.exception))

    def test_every_person_role_supports_space_colon_and_page_boundary(self):
        role_families = {
            '고객': (
                '보험계약자', '계약자', '피보험자', '보험수익자',
                '수익자', '가입자', '고객', '대표자',
            ),
            '설계사': (
                '보험설계사', '모집담당자', '모집자', '모집인',
                '담당설계사', '담당자', '설계사',
            ),
        }

        for token_name, roles in role_families.items():
            for role in roles:
                sentinel = '테스트가나다'
                pages = (
                    (f'{role} {sentinel}', f'{role}: {sentinel}', role, ''),
                    ('', sentinel),
                )
                with self.subTest(role=role):
                    result = pseudonymize_page_lines(pages)
                    serialized = repr(result)
                    self.assertNotIn(sentinel, serialized)
                    self.assertEqual(
                        serialized.count(f'[{token_name}_1]'), 3)
                    with self.assertRaises(PDFImportError):
                        assert_pseudonymized_pages_safe(
                            ((f'{role} {sentinel}',),))

    def test_all_role_rows_mask_korean_latin_and_adjacent_birth_dates(self):
        role_families = {
            '고객': (
                '보험계약자', '계약자', '피보험자', '보험수익자',
                '수익자', '가입자', '고객', '대표자',
            ),
            '설계사': (
                '보험설계사', '모집담당자', '모집자', '모집인',
                '담당설계사', '담당자', '설계사',
            ),
        }

        for token_name, roles in role_families.items():
            for role in roles:
                pages = (
                    (
                        f'{role} 테스트홍길동 1980.01.01',
                        f'{role} ALEX KIM',
                        role,
                        '',
                    ),
                    ('', '김'),
                )
                with self.subTest(role=role):
                    result = pseudonymize_page_lines(pages)
                    flattened = '\n'.join(
                        line for page in result.pages for line in page)
                    self.assertNotIn('테스트홍길동', flattened)
                    self.assertNotIn('ALEX KIM', flattened)
                    self.assertNotIn('1980.01.01', flattened)
                    self.assertEqual(
                        result.pages[0][0],
                        f'{role} [{token_name}_1] [생년월일_1]',
                    )
                    self.assertEqual(
                        result.pages[0][1], f'{role} [{token_name}_2]')
                    self.assertEqual(result.pages[1][1], f'[{token_name}_3]')

    def test_role_rows_mask_identity_prefix_before_structured_table_columns(self):
        sentinels = (
            '테스트홍길동',
            'ALEX KIM',
            'TEST-STAFF-4102',
            '010-2468-1357',
            '1980.01.01',
        )
        pages = ((
            f'계약자 {sentinels[0]} {sentinels[4]} 남 본인',
            f'모집인 {sentinels[1]} '
            f'사원번호: {sentinels[2]} 연락처: {sentinels[3]}',
        ),)

        result = pseudonymize_page_lines(pages)
        flattened = '\n'.join(result.pages[0])

        for sentinel in sentinels:
            self.assertNotIn(sentinel, flattened)
        self.assertIn('계약자 [고객_1] [생년월일_1] 남 본인', flattened)
        self.assertIn('모집인 [설계사_1]', flattened)
        self.assertIn('사원번호: [설계사번호_1]', flattened)
        self.assertIn('연락처: [전화_1]', flattened)

    def test_cross_line_role_header_masks_identity_prefix_and_global_contact(self):
        pages = ((
            '계약자 성명',
            '테스트김 010-1357-2468 본인',
        ),)

        result = pseudonymize_page_lines(pages)

        self.assertEqual(result.pages, ((
            '계약자 성명',
            '[고객_1] [전화_1] 본인',
        ),))

    def test_role_domain_sentences_are_preserved_but_appended_name_is_rejected(self):
        safe = (
            '피보험자 본인 사망 시 보험금 지급',
            '계약자 및 피보험자의 관계 확인',
            '수익자 지정 및 변경 안내',
            '설계사 모집 수수료 안내',
            '피보험자 1인당 가입금액 1,000만원',
        )

        result = pseudonymize_page_lines((safe,))

        self.assertEqual(result.pages, (safe,))
        with self.assertRaises(PDFImportError) as caught:
            assert_pseudonymized_pages_safe(
                (('계약자는 보장내용을 확인합니다. 테스트홍길동',),))
        self.assertEqual(caught.exception.code, 'PII_REDACTION_UNCERTAIN')

    def test_preceding_parenthesized_roles_and_role_name_labels_are_masked(self):
        cases = (
            ('홍길동(계약자)', '[고객_1](계약자)', '홍길동'),
            ('보험계약자명: 홍길동', '보험계약자명: [고객_1]', '홍길동'),
            ('피보험자명 홍길동', '피보험자명 [고객_1]', '홍길동'),
            ('모집인명: 김인파', '모집인명: [설계사_1]', '김인파'),
        )

        for source, expected, private_value in cases:
            with self.subTest(source=source):
                result = pseudonymize_page_lines(((source,),))
                self.assertEqual(result.pages, ((expected,),))
                self.assertNotIn(private_value, repr(result))
                with self.assertRaises(PDFImportError) as caught:
                    assert_pseudonymized_pages_safe(((source,),))
                self.assertEqual(
                    caught.exception.code, 'PII_REDACTION_UNCERTAIN')

    def test_role_field_wrappers_and_cross_line_preceding_role_are_safe(self):
        cases = (
            ('계약자 (성명) 테스트홍길동', '계약자 (성명) [고객_1]'),
            ('계약자(이름): 테스트홍길동', '계약자(이름): [고객_1]'),
            ('모집인 (명) 테스트김', '모집인 (명) [설계사_1]'),
            ('계약자（성명）테스트홍길동', '계약자（성명）[고객_1]'),
            ('계약자 [성명] 테스트홍길동', '계약자 [성명] [고객_1]'),
            ('계약자{성명}: 테스트홍길동', '계약자{성명}: [고객_1]'),
            ('계약자(성 명): 테스트홍길동', '계약자(성 명): [고객_1]'),
            ('계약자 ( 이름 ) 테스트홍길동', '계약자 ( 이름 ) [고객_1]'),
            ('담당설계사(성명) 테스트김', '담당설계사(성명) [설계사_1]'),
            ('테스트홍길동（계약자）', '[고객_1]（계약자）'),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                result = pseudonymize_page_lines(((source,),))
                self.assertEqual(result.pages, ((expected,),))
                self.assertNotIn('테스트', repr(result))
                with self.assertRaises(PDFImportError):
                    assert_pseudonymized_pages_safe(((source,),))

        cross_line = (('테스트홍길동', '(계약자)'),)
        result = pseudonymize_page_lines(cross_line)
        self.assertNotIn('테스트홍길동', repr(result))
        self.assertEqual(result.quarantined_line_count, 2)
        with self.assertRaises(PDFImportError):
            assert_pseudonymized_pages_safe(cross_line)

    def test_role_insurance_descriptions_are_preserved_without_aliasing(self):
        lines = (
            '피보험자 연령 기준 15세 이상',
            '피보험자 직업급수 1급',
            '계약자 배당금 지급 안내',
            '계약자 권리 안내',
            '피보험자 조건 확인',
        )

        result = pseudonymize_page_lines((lines,))

        self.assertEqual(result.pages, (lines,))
        self.assertEqual(result.category_counts, ())
        self.assertTrue(assert_pseudonymized_pages_safe((lines,)))

    def test_labeled_alias_with_domain_suffix_remains_safe(self):
        lines = (
            '주민번호: [주민번호_1] 확인',
            '연락처: [전화_1] 등록 정보',
            '계약자: [고객_1] 관계 확인',
        )

        self.assertTrue(assert_pseudonymized_pages_safe((lines,)))

    def test_existing_alias_chains_are_idempotent_during_safety_recheck(self):
        lines = (
            '계약자: [고객_1] 관계 확인',
            '주민번호: [주민번호_1] 확인',
            '연락처: [전화_1] 등록 정보',
        )

        result = pseudonymize_page_lines((lines,))

        self.assertEqual(result.pages, (lines,))
        self.assertEqual(result.category_counts, (
            ('customer_name', 1), ('rrn', 1), ('phone', 1),
        ))

    def test_unresolved_identity_only_table_row_is_redacted_as_one_safe_value(self):
        sentinels = ('테스트장기이름', 'TEST-CODE-2002')
        pages = ((
            '모집인 성명 등록번호',
            f'{sentinels[0]} 추가 열 {sentinels[1]}',
        ),)

        result = pseudonymize_page_lines(pages)
        serialized = repr(result.pages)

        for sentinel in sentinels:
            self.assertNotIn(sentinel, serialized)
        self.assertIn(result.pages[0][1], ('', '[등록번호_1]'))

    def test_unresolved_identity_and_analysis_line_is_quarantined_with_coordinates(self):
        private_value = '테스트홍길동'
        source = f'계약자 {private_value} 추가정보 일반암진단비 3,000만원'

        result = pseudonymize_page_lines(((source, '다음 줄 안내'),))

        self.assertEqual(result.pages, (('', '다음 줄 안내'),))
        self.assertEqual(result.quarantined_line_count, 1)
        self.assertEqual(result.quarantined_line_ids, ('p01-l001',))
        self.assertEqual(
            result.analysis_signal_quarantined_line_count, 1)
        self.assertEqual(
            result.analysis_signal_quarantined_line_ids,
            ('p01-l001',),
        )
        self.assertNotIn(private_value, repr(result))

    def test_identity_line_quarantine_preserves_page_and_line_positions(self):
        pages = (
            ('계약자 성명', '테스트가나다 추가 열', '일반 안내'),
            ('모집인 등록번호', 'TEST-PRIVATE-3003', '기타 안내'),
        )

        result = pseudonymize_page_lines(pages)

        self.assertEqual(
            [len(page) for page in result.pages],
            [len(page) for page in pages],
        )
        self.assertEqual(result.pages[0][1], '')
        self.assertEqual(result.pages[1][1], '')
        self.assertGreaterEqual(result.quarantined_line_count, 2)

    def test_concurrent_quarantine_counts_and_alias_state_are_document_local(self):
        documents = tuple(
            (( '계약자 성명', f'테스트고객{number} 추가 열'),)
            for number in range(8)
        )

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(pseudonymize_page_lines, documents))

        self.assertTrue(all(
            result.quarantined_line_count >= 1 for result in results))
        self.assertTrue(all(
            result.pages[0][1] == '' for result in results))

    def test_bounded_role_fields_anywhere_mask_prefix_metadata_and_birth(self):
        role_families = {
            '고객': (
                '보험계약자', '계약자', '피보험자', '보험수익자',
                '수익자', '가입자', '고객', '대표자',
            ),
            '설계사': (
                '보험설계사', '모집담당자', '모집자', '모집인',
                '담당설계사', '담당자', '설계사',
            ),
        }

        for token_name, roles in role_families.items():
            for role in roles:
                cases = (
                    (
                        f'구분 {role} 테스트홍길동 1980.01.01',
                        f'구분 {role} [{token_name}_1] [생년월일_1]',
                    ),
                    (
                        f'{role} 변경 테스트홍길동',
                        f'{role} 변경 [{token_name}_1]',
                    ),
                    (
                        f'{role} 정보 테스트홍길동',
                        f'{role} 정보 [{token_name}_1]',
                    ),
                    (
                        f'{role} 는 테스트홍길동',
                        f'{role} 는 [{token_name}_1]',
                    ),
                )
                for source, expected in cases:
                    with self.subTest(role=role, source=source):
                        result = pseudonymize_page_lines(((source,),))
                        self.assertEqual(result.pages, ((expected,),))

    def test_independent_role_invariant_rejects_raw_tail_anywhere(self):
        unsafe = (
            '구분 계약자 테스트홍길동 1980.01.01',
            '표1 모집자 ALEX KIM',
            '계약자 변경 테스트홍길동',
            '계약자 정보 테스트홍길동',
            '계약자 는 테스트홍길동',
            '앞열 피보험자 UNKNOWN / 1980.01.01',
        )
        safe = (
            '구분 계약자 [고객_1] [생년월일_1]',
            '계약자 변경 [고객_1]',
            '계약자 정보 [고객_1]',
            '계약자 는 [고객_1]',
            '계약자 성명: [고객_1]',
        )

        for line in unsafe:
            with self.subTest(line=line):
                with self.assertRaises(PDFImportError) as caught:
                    assert_pseudonymized_pages_safe(((line,),))
                self.assertEqual(
                    caught.exception.code, 'PII_REDACTION_UNCERTAIN')
        self.assertTrue(assert_pseudonymized_pages_safe((safe,)))

    def test_attached_role_particles_mask_bounded_names_anywhere(self):
        role_families = {
            '고객': (
                '보험계약자', '계약자', '피보험자', '보험수익자',
                '수익자', '가입자', '고객', '대표자',
            ),
            '설계사': (
                '보험설계사', '모집담당자', '모집자', '모집인',
                '담당설계사', '담당자', '설계사',
            ),
        }
        particles = (
            '에게는', '에게', '에는', '은', '는', '이', '가',
            '을', '를', '와', '과', '의', '도',
        )

        for token_name, roles in role_families.items():
            for role in roles:
                for particle in particles:
                    cases = (
                        (
                            f'구분 {role}{particle} 테스트홍길동',
                            f'구분 {role}{particle} [{token_name}_1]',
                        ),
                        (
                            f'구분 {role} {particle} 테스트홍길동',
                            f'구분 {role} {particle} [{token_name}_1]',
                        ),
                    )
                    for source, expected in cases:
                        with self.subTest(
                                role=role, particle=particle, source=source):
                            result = pseudonymize_page_lines(((source,),))
                            self.assertEqual(result.pages, ((expected,),))

    def test_role_parentheses_mask_names_and_reject_uncertain_values(self):
        mask_cases = (
            ('계약자(테스트홍길동)', '계약자([고객_1])'),
            ('구분 피보험자 (테스트홍길동)',
             '구분 피보험자 ([고객_1])'),
            ('모집자: (ALEX KIM)', '모집자: ([설계사_1])'),
            ('계약자의(테스트홍길동)', '계약자의([고객_1])'),
        )
        uncertain = (
            '계약자(테스트홍길동 / 기타)',
            '구분 피보험자의 UNKNOWN / 1980.01.01',
            '모집자에게 ALEX KIM 추가값',
            '계약자는 [고객_1] 테스트홍길동',
        )
        safe = (
            '계약자([고객_1])',
            '구분 피보험자는 [고객_1]',
            '모집자에게 [설계사_1]',
            '계약자의([고객_1])',
        )

        for source, expected in mask_cases:
            with self.subTest(source=source):
                try:
                    result = pseudonymize_page_lines(((source,),))
                except PDFImportError as error:
                    self.fail(
                        'bounded parenthesized role name was rejected: '
                        f'{error.code}')
                self.assertEqual(result.pages, ((expected,),))
        for line in uncertain:
            with self.subTest(line=line):
                with self.assertRaises(PDFImportError) as caught:
                    assert_pseudonymized_pages_safe(((line,),))
                self.assertEqual(
                    caught.exception.code, 'PII_REDACTION_UNCERTAIN')
        self.assertTrue(assert_pseudonymized_pages_safe((safe,)))

    def test_role_sentence_allowlist_requires_the_complete_normalized_line(self):
        anchors = (
            '계약자에게는 보장내용을 안내합니다.',
            '계약자는 보장내용을 확인합니다.',
            '피보험자에게는 보험금 지급내용을 안내합니다.',
        )

        for anchor in anchors:
            with self.subTest(anchor=anchor):
                spaced = f'  {anchor}  '
                self.assertEqual(
                    pseudonymize_page_lines(((spaced,),)).pages,
                    ((spaced,),),
                )
                with self.assertRaises(PDFImportError) as caught:
                    assert_pseudonymized_pages_safe(
                        ((f'{anchor} 테스트홍길동',),))
                self.assertEqual(
                    caught.exception.code, 'PII_REDACTION_UNCERTAIN')

    def test_uncertain_role_bound_values_fail_closed_independently(self):
        uncertain = (
            '계약자 테스트홍길동 1980.01.01 추가값',
            '설계사 ALEX KIM / UNKNOWN 123',
            '계약자 테스트홍길동 남',
            '피보험자 테스트홍길동 본인',
            '설계사 ALEX KIM 고객번호 TEST-CUSTOMER-31',
        )

        for line in uncertain:
            with self.subTest(line=line):
                with self.assertRaises(PDFImportError) as caught:
                    assert_pseudonymized_pages_safe(((line,),))
                self.assertEqual(
                    caught.exception.code, 'PII_REDACTION_UNCERTAIN')

    def test_role_rows_mask_mixed_script_and_name_punctuation(self):
        names = ('ANNA김', '김·민준', '김-민준')

        result = pseudonymize_page_lines((tuple(
            f'계약자 {name}' for name in names
        ),))
        serialized = repr(result)

        for number, name in enumerate(names, start=1):
            self.assertNotIn(name, serialized)
            self.assertIn(f'[고객_{number}]', serialized)

    def test_role_words_in_sentences_and_coverage_copy_are_preserved(self):
        lines = (
            '계약자에게는 보장내용을 안내합니다.',
            '계약자는 보장내용을 확인합니다.',
            '피보험자에게는 보험금 지급내용을 안내합니다.',
            '계약자 는 보장내용을 확인합니다.',
            '계약자 변경 시 안내',
            '계약자 보장내용 안내',
            '피보험자 사망 일반사망보험금 3,000만원',
            '가입자 만기 수익금 1,000만원',
            '설계사 확인 후 서명',
            '설계사 보장분석 안내',
        )

        result = pseudonymize_page_lines((lines,))

        self.assertEqual(result.pages, (lines,))
        self.assertTrue(result.residual_scan_passed)

    def test_role_insurance_golden_lines_remain_coverage_candidates(self):
        lines = (
            '피보험자 연령 기준 15세 이상 가입금액 100만원',
            '피보험자 직업급수 1급 가입금액 200만원',
            '계약자 배당금 지급 안내 가입금액 300만원',
            '계약자 권리 안내 가입금액 400만원',
            '피보험자 조건 안내 가입금액 500만원',
        )

        result = pseudonymize_page_lines((lines,))

        self.assertEqual(result.pages, (lines,))
        self.assertEqual(result.category_counts, ())

    def test_global_korean_phone_families_and_pdf_separators_are_aliased(self):
        phones = (
            '010-1234-5678', '011 123 4567', '02–1234–5678',
            '031‑123‑4567', '032-1234-5678', '033.1234.5678',
            '041-123-4567', '042-1234-5678', '043 123 4567',
            '044−1234−5678', '051 123 4567', '052-123-4567',
            '053-1234-5678', '054.123.4567', '055-1234-5678',
            '061－123－4567', '062-1234-5678', '063 123 4567',
            '064-1234-5678', '070-1234-5678',
            '0502-123-4567', '0508–1234–5678',
        )

        result = pseudonymize_page_lines((phones,))
        serialized = repr(result)

        for number, phone in enumerate(phones, start=1):
            self.assertNotIn(phone, serialized)
            self.assertIn(f'[전화_{number}]', serialized)
            self.assertTrue(contains_probable_direct_identifier(phone))
        self.assertEqual(dict(result.category_counts)['phone'], len(phones))

    def test_partial_and_country_prefix_phones_share_domestic_aliases(self):
        equivalent_pairs = (
            ('010-****-5678', '+82 10 **** 5678'),
            ('010-1234-****', '+82–10–1234–****'),
            ('02-1234-5678', '+82-2-1234-5678'),
        )
        phones = tuple(
            phone for pair in equivalent_pairs for phone in pair
        )

        result = pseudonymize_page_lines((phones,))
        serialized = repr(result)

        for number, pair in enumerate(equivalent_pairs, start=1):
            for phone in pair:
                self.assertNotIn(phone, serialized)
                self.assertTrue(contains_probable_direct_identifier(phone))
            self.assertEqual(serialized.count(f'[전화_{number}]'), 2)
        self.assertEqual(dict(result.category_counts)['phone'], len(phones))

    def test_country_prefix_trunk_zero_variants_share_domestic_aliases(self):
        equivalent_groups = (
            (
                '010-1234-5678',
                '+82 (0)10-1234-5678',
                '+82-010-1234-5678',
                '+82 – ( 0 ) 10 1234 5678',
            ),
            (
                '010-****-5678',
                '+82 (0)10-****-5678',
                '+82－010－****－5678',
            ),
            (
                '02-1234-5678',
                '+82 (0)2-1234-5678',
                '+82-02-1234-5678',
            ),
        )
        phones = tuple(
            phone for group in equivalent_groups for phone in group
        )

        result = pseudonymize_page_lines((phones,))
        serialized = repr(result)

        for number, group in enumerate(equivalent_groups, start=1):
            for phone in group:
                self.assertNotIn(phone, serialized)
                self.assertTrue(contains_probable_direct_identifier(phone))
                with self.assertRaises(PDFImportError):
                    assert_pseudonymized_pages_safe(((phone,),))
            self.assertEqual(serialized.count(f'[전화_{number}]'), len(group))

    def test_country_prefix_residual_uses_digit_star_count_not_layout(self):
        irregular = (
            '+82 ( 0 ) 1 0 1 2 3 4 5 6 7 8',
            '+82 / 10 / **** / 5678',
        )
        harmless = '환급률 +82% 기준금액 82만원'

        for phone in irregular:
            with self.subTest(phone=phone):
                self.assertTrue(contains_probable_direct_identifier(phone))
                with self.assertRaises(PDFImportError) as caught:
                    assert_pseudonymized_pages_safe(((phone,),))
                self.assertEqual(
                    caught.exception.code, 'PII_REDACTION_UNCERTAIN')
        self.assertFalse(contains_probable_direct_identifier(harmless))
        self.assertEqual(
            pseudonymize_page_lines(((harmless,),)).pages,
            ((harmless,),),
        )

    def test_insurance_numbers_are_not_false_positive_phones(self):
        line = (
            '가입금액 3,000만원 10년납 100세만기 '
            '보험사 대표번호 1588-1234 고객센터 080-123-4567 '
            '증권번호 TEST-2026-010-123456'
        )

        result = pseudonymize_page_lines(((line,),))

        self.assertEqual(
            result.pages,
            ((line.replace(
                'TEST-2026-010-123456', '[증권번호_1]'),),),
        )
        self.assertNotIn('[전화_', result.pages[0][0])
        self.assertFalse(contains_probable_direct_identifier(line))

    def test_bounded_identifier_label_wrappers_are_supported(self):
        cases = (
            ('계약번호', 'TEST-CONTRACT-21', '계약번호'),
            ('증권번호', 'TEST-POLICY-22', '증권번호'),
            ('고객번호', 'TEST-CUSTOMER-23', '고객번호'),
            ('설계사번호', 'TEST-PLANNER-24', '설계사번호'),
            ('모집자번호', 'TEST-RECRUITER-25', '모집자번호'),
            ('등록번호', 'TEST-LICENSE-26', '등록번호'),
        )
        wrappers = ('(TEST)', '(No.)')

        for label, sentinel, token_name in cases:
            for wrapper in wrappers:
                line = f'{label}{wrapper}: {sentinel}'
                with self.subTest(label=label, wrapper=wrapper):
                    result = pseudonymize_page_lines(((line,),))
                    self.assertNotIn(sentinel, repr(result))
                    self.assertIn(
                        f'{label}{wrapper}: [{token_name}_1]',
                        result.pages[0][0],
                    )
                    with self.assertRaises(PDFImportError):
                        assert_pseudonymized_pages_safe(((line,),))

    def test_unapproved_wrappers_in_coverage_names_are_preserved(self):
        lines = (
            '계약번호(갱신형)특약 100만원',
            '고유번호(보장형)진단비 300만원',
        )

        result = pseudonymize_page_lines((lines,))

        self.assertEqual(result.pages, (lines,))

    def test_korean_name_ocr_spacing_reuses_alias_without_merging_names(self):
        pages = ((
            '계약자 성명: 테스트가나다',
            '피보험자 성명: 테 스 트 가 나 다',
            '수익자 성명: 테스트가다나',
        ),)

        result = pseudonymize_page_lines(pages)

        self.assertEqual(result.pages[0][0], '계약자 성명: [고객_1]')
        self.assertEqual(result.pages[0][1], '피보험자 성명: [고객_1]')
        self.assertEqual(result.pages[0][2], '수익자 성명: [고객_2]')

    def test_same_line_labels_and_global_identity_sentinels_are_masked(self):
        sentinels = (
            '홍길동',
            '서울특별시 강남구 테헤란로 123',
            '010-9876-5432',
            '901231-1234567',
            'planner.customer@example.com',
        )
        pages = ((
            f'계약자 성명: {sentinels[0]}',
            f'자택 주소 {sentinels[1]}',
            f'연락처 {sentinels[2]} 주민번호 {sentinels[3]}',
            f'전자우편 {sentinels[4]}',
        ),)

        masked = mask_page_lines(pages)
        serialized = '\n'.join(masked[0])

        for sentinel in sentinels:
            self.assertNotIn(sentinel, serialized)
        self.assertIn('계약자 성명: [고객_1]', serialized)
        self.assertIn('자택 주소 [주소_1]', serialized)
        self.assertIn('[전화_1]', serialized)
        self.assertIn('[주민번호_1]', serialized)
        self.assertIn('[이메일_1]', serialized)

    def test_full_and_partially_redacted_resident_ids_are_all_masked(self):
        resident_ids = (
            '901231-1******',
            '901231-*******',
            '9012311234567',
            '901231 1234567',
            '901231 - 1******',
            '90****-1******',
        )

        masked = mask_page_lines(((
            ' / '.join(resident_ids),
        ),))
        serialized = masked[0][0]

        for resident_id in resident_ids:
            self.assertNotIn(resident_id, serialized)
        self.assertEqual(serialized.count('[주민번호_'), len(resident_ids))

    def test_unicode_pdf_dash_resident_ids_are_all_masked(self):
        resident_ids = (
            '901231–1******',
            '901231 – 1******',
            '901231‑1******',
            '901231－1******',
        )

        masked = mask_page_lines(((' / '.join(resident_ids),),))
        serialized = masked[0][0]

        for resident_id in resident_ids:
            self.assertNotIn(resident_id, serialized)
        self.assertEqual(serialized.count('[주민번호_1]'), len(resident_ids))

    def test_label_state_crosses_arbitrary_blanks_and_page_boundaries(self):
        raw_name = '박경계'
        raw_address = '부산광역시 해운대구 센텀로 45 101동 202호'
        pages = (
            ('피보험자 성명', '', '', ''),
            ('', '', raw_name, '계약자 주소'),
            ('', '', '', raw_address, '일반암진단비 3,000만원'),
        )

        masked = mask_page_lines(pages)
        flattened = '\n'.join(line for page in masked for line in page)

        self.assertNotIn(raw_name, flattened)
        self.assertNotIn(raw_address, flattened)
        self.assertEqual(masked[1][2], '[고객_1]')
        self.assertEqual(masked[2][3], '[주소_1]')
        self.assertEqual(masked[2][4], '일반암진단비 3,000만원')
        self.assertEqual(
            [len(page) for page in masked], [len(page) for page in pages])

    def test_role_only_identity_labels_mask_same_line_and_remote_names(self):
        pages = ((
            '계 약 자: 김같은줄',
            '보 험 수 익 자',
            '',
            '이먼줄',
        ),)

        masked = mask_page_lines(pages)
        serialized = '\n'.join(masked[0])

        self.assertNotIn('김같은줄', serialized)
        self.assertNotIn('이먼줄', serialized)
        self.assertEqual(masked[0][0], '계 약 자: [고객_1]')
        self.assertEqual(masked[0][3], '[고객_2]')

    def test_role_word_inside_a_sentence_does_not_start_mask_state(self):
        sentence = '계약자에게는 보장내용을 안내합니다.'
        coverage = '일반암진단비 3,000만원'

        masked = mask_page_lines(((sentence, coverage),))

        self.assertEqual(masked, ((sentence, coverage),))

    def test_coverage_amounts_and_periods_are_preserved(self):
        coverage = (
            '테스트손해보험 무배당 건강보장보험 '
            '일반암진단비(갱신형) 가입금액 3,000만원 '
            '보험료 12,600원 20년납입 100세만기'
        )

        masked = mask_page_lines(((coverage,),))

        self.assertEqual(masked, ((coverage,),))

    def test_new_complete_label_clears_an_unresolved_prior_label(self):
        coverage = '일반암진단비 3,000만원'
        pages = ((
            '피보험자 성명',
            '주소 서울특별시 강남구 테헤란로 123',
            coverage,
        ),)

        masked = mask_page_lines(pages)

        self.assertEqual(masked[0][1], '주소 [주소_1]')
        self.assertEqual(masked[0][2], coverage)

    def test_500000_digit_non_pii_line_completes_without_change(self):
        non_pii = '9' * 500_000

        masked = mask_page_lines(((non_pii,),))

        self.assertEqual(masked, ((non_pii,),))

    def test_new_pipeline_never_calls_legacy_identity_masker(self):
        with mock.patch(
                'inpa.core.ocr.pii_mask._strip_identity',
                side_effect=AssertionError('legacy masker called')) as legacy:
            masked = mask_page_lines((('계약자 성명 홍길동',),))

        legacy.assert_not_called()
        self.assertEqual(masked, (('계약자 성명 [고객_1]',),))
