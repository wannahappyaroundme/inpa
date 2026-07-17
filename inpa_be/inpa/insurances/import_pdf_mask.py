import re
import unicodedata
from collections import Counter

from inpa.core.ocr.ocrdata import (
    LIFE_COMPANY_ALIASES, LOSS_COMPANY_ALIASES,
)
from inpa.core.ocr.ocrparsing import COVERAGE_KEYWORDS

from .import_contract import (
    COVERAGE_MARKERS,
    PDFImportError,
    PSEUDONYMIZATION_CATEGORIES,
    PSEUDONYMIZATION_CATEGORY_TOKENS,
    PseudonymizedDocument,
)


_INVISIBLE_OCR_SEPARATORS = frozenset({'\u200b', '\u200c', '\u200d', '\ufeff'})


def _normalize_ocr_text(value):
    form = (
        'NFKC'
        if any('\u3130' <= character <= '\u318f' for character in value)
        else 'NFC'
    )
    normalized = unicodedata.normalize(form, value)
    return ''.join(
        ' '
        if (character in _INVISIBLE_OCR_SEPARATORS
            or unicodedata.category(character) in {'Cf', 'Zs'})
        else character
        for character in normalized
    )


_DASHES = r'[-‐‑‒–—―−－]'
_RRN_PATTERN = (
    r'(?<![0-9*])(?:'
    r'[0-9]{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12][0-9]|3[01])'
    rf'[ \t]*{_DASHES}?[ \t]*[1-8][0-9]{{6}}'
    rf'|[0-9*]{{6}}(?:[ \t]*{_DASHES}[ \t]*|[ \t]+)[0-9*]{{7}}'
    r')(?![0-9*])'
)
_PHONE_SEPARATOR = rf'(?:[ \t]*(?:{_DASHES}|\.)[ \t]*|[ \t]+)'
_OPTIONAL_PHONE_SEPARATOR = rf'(?:{_PHONE_SEPARATOR})?'
_PHONE_GROUP = r'[0-9*]'
_COUNTRY_PHONE_PREFIX = (
    r'\+82'
    rf'{_OPTIONAL_PHONE_SEPARATOR}'
    r'(?:\([ \t]*0[ \t]*\)[ \t]*|0)?'
)
_PHONE_PATTERN = (
    r'(?<![0-9*+])'
    r'(?:'
    r'(?:01[016789]|02|0(?:3[1-3]|4[1-4]|5[1-5]|6[1-4])|070)'
    rf'{_OPTIONAL_PHONE_SEPARATOR}{_PHONE_GROUP}{{3,4}}'
    rf'{_OPTIONAL_PHONE_SEPARATOR}{_PHONE_GROUP}{{4}}'
    r'|050[2-8]'
    rf'{_OPTIONAL_PHONE_SEPARATOR}{_PHONE_GROUP}{{3,4}}'
    rf'{_OPTIONAL_PHONE_SEPARATOR}{_PHONE_GROUP}{{4}}'
    rf'|{_COUNTRY_PHONE_PREFIX}'
    r'(?:1[016789]|2|(?:3[1-3]|4[1-4]|5[1-5]|6[1-4])|70)'
    rf'{_OPTIONAL_PHONE_SEPARATOR}{_PHONE_GROUP}{{3,4}}'
    rf'{_OPTIONAL_PHONE_SEPARATOR}{_PHONE_GROUP}{{4}}'
    rf'|{_COUNTRY_PHONE_PREFIX}50[2-8]'
    rf'{_OPTIONAL_PHONE_SEPARATOR}{_PHONE_GROUP}{{3,4}}'
    rf'{_OPTIONAL_PHONE_SEPARATOR}{_PHONE_GROUP}{{4}}'
    r')'
    r'(?![0-9*])'
)
_EMAIL_PATTERN = (
    r"(?<![A-Za-z0-9.!#$%&'*+/=?^_`{|}~-])"
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@"
    r'(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.){1,10}'
    r'[A-Za-z]{2,63}'
    r"(?![A-Za-z0-9.!#$%&'*+/=?^_`{|}~-])"
)

_RRN_RE = re.compile(_RRN_PATTERN)
_PHONE_RE = re.compile(_PHONE_PATTERN)
_EMAIL_RE = re.compile(_EMAIL_PATTERN)


def _spaced(value):
    return r'[ \t]*'.join(re.escape(character) for character in value)


def _alternatives(*values):
    return '(?:' + '|'.join(_spaced(value) for value in values) + ')'


_NAME_WORD = _alternatives('성명', '이름')
_ROLE_NAME_WORD = _alternatives('성명', '이름', '명')
_CUSTOMER_ROLE_WORDS = (
    '보험계약자', '계약자', '피보험자', '보험수익자',
    '수익자', '가입자', '고객', '대표자',
)
_PLANNER_ROLE_WORDS = (
    '보험설계사', '모집담당자', '모집자', '모집인',
    '담당설계사', '담당자', '설계사',
)
_CUSTOMER_ROLE = _alternatives(*_CUSTOMER_ROLE_WORDS)
_PLANNER_ROLE = _alternatives(*_PLANNER_ROLE_WORDS)
_ROLE_SENTENCE_RESERVED_PREFIX = _alternatives(
    '보장', '보험', '계약', '가입', '담보', '특약', '진단', '수술',
    '입원', '만기', '납입', '갱신', '안내', '사망', '지급', '청약',
    '해지', '분석', '수익금', '변경', '확인', '서명', '동의', '설명',
    '고지', '제공', '등록', '작성', '선택', '입력', '기재', '해당',
    '기준', '경우', '내용', '사항', '정보', '관계', '구분', '및', '또는',
    '본인', '지정', '모집', '수수료', '배우자', '자녀', '가족',
    '법정', '상속', '동일', '인당', '연령', '나이', '직업', '급수',
    '배당', '배당금', '권리', '조건',
)
_ROLE_STRUCTURED_FIELD_PREFIX = _alternatives(
    '성명', '이름', '주소', '거주지', '소재지', '주민', '생년', '출생',
    '연락', '전화', '휴대', '이메일', '전자우편',
)
_ROLE_PARTICLE_PREFIX = _alternatives(
    '에게는', '에게', '에는', '은', '는', '이', '가', '을', '를',
    '와', '과', '의', '도',
)
_ROLE_VALUE_METADATA_PREFIX = _alternatives(
    '변경', '정보', '에게는', '에게', '에는', '은', '는', '이', '가',
    '을', '를', '와', '과', '의', '도',
)
_SAFE_ROLE_SENTENCES = frozenset({
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
})
_STRONG_BOUNDARY = r'(?=[ \t]*(?:[:：]|$)|[ \t]+)'
_ROLE_NON_NAME_START = (
    r'(?:' + _ROLE_SENTENCE_RESERVED_PREFIX
    + r'|' + _ROLE_STRUCTURED_FIELD_PREFIX
    + r'|' + _ROLE_PARTICLE_PREFIX + r')'
)
_ROLE_SPACE_NAME_BOUNDARY = (
    r'(?=[ \t]+'
    r'(?!' + _ROLE_NON_NAME_START + r')'
    r'(?:[가-힣][ \t]*){2,8}'
    r'(?=$|[ \t]*(?:\(|\[|\{|/|,|:|：)))'
)
_ROLE_BOUNDARY = (
    r'(?:(?=[ \t]*(?:[:：]|$))|' + _ROLE_SPACE_NAME_BOUNDARY + r')'
)
_LABEL_WRAPPER = (
    r'[ \t]*[\(（\[\{][ \t]*'
    r'(?:(?i:TEST|NO\.?)|번호|코드)'
    r'[ \t]*[\)）\]\}]'
)
_IDENTIFIER_BOUNDARY = (
    r'(?:' + _LABEL_WRAPPER + r'|' + _STRONG_BOUNDARY + r')'
)

_LABEL_PATTERNS = (
    ('recruiter_id',
     _alternatives('모집자번호', '모집인번호', '모집인등록번호')
     + _IDENTIFIER_BOUNDARY),
    ('planner_id',
     _alternatives('설계사번호', '담당자번호', '사원번호')
     + _IDENTIFIER_BOUNDARY),
    ('contract_id',
     _alternatives('보험계약번호', '계약번호', '계약No', '계약NO')
     + _IDENTIFIER_BOUNDARY),
    ('policy_id',
     _alternatives('보험증권번호', '증권번호', '증권No', '증권NO')
     + _IDENTIFIER_BOUNDARY),
    ('customer_id',
     _alternatives('고객번호', '고객No', '고객NO')
     + _IDENTIFIER_BOUNDARY),
    ('certificate_id',
     _alternatives('가입증서번호', '증서번호', '증서No', '증서NO')
     + _IDENTIFIER_BOUNDARY),
    ('application_id',
     _alternatives('보험청약번호', '청약번호', '청약No', '청약NO')
     + _IDENTIFIER_BOUNDARY),
    ('license_id',
     _alternatives('고유번호', '등록번호', '자격번호', '면허번호')
     + _IDENTIFIER_BOUNDARY),
    ('business_id',
     _alternatives('사업자등록번호', '사업자번호')
     + _IDENTIFIER_BOUNDARY),
    ('account_id',
     _alternatives('계좌번호', '은행계좌', '출금계좌')
     + _IDENTIFIER_BOUNDARY),
    ('card_id',
     _alternatives('카드번호') + _IDENTIFIER_BOUNDARY),
    ('birth_date',
     _alternatives('생년월일', '출생일', '생일') + _STRONG_BOUNDARY),
    ('rrn',
     _alternatives('주민등록번호', '주민번호') + _STRONG_BOUNDARY),
    ('phone',
     _alternatives('휴대전화번호', '휴대폰번호', '전화번호',
                   '연락처', '휴대전화', '휴대폰', '전화')
     + _STRONG_BOUNDARY),
    ('email',
     _alternatives('이메일주소', '전자우편', '이메일', '메일')
     + _STRONG_BOUNDARY),
    ('address',
     r'(?:(?:' + _CUSTOMER_ROLE + '|' + _alternatives('자택', '직장')
     + r')[ \t]*)?'
     + _alternatives('주소', '거주지', '소재지') + _STRONG_BOUNDARY),
    ('planner_name',
     r'(?:' + _PLANNER_ROLE + r'[ \t]*' + _ROLE_NAME_WORD + r')'
     + _STRONG_BOUNDARY + r'|' + _PLANNER_ROLE + _ROLE_BOUNDARY),
    ('customer_name',
     r'(?:' + _CUSTOMER_ROLE + r'[ \t]*' + _ROLE_NAME_WORD
     + r'|' + _NAME_WORD + r')'
     + _STRONG_BOUNDARY + r'|' + _CUSTOMER_ROLE + _ROLE_BOUNDARY),
)
_LABEL_RE = re.compile('|'.join(
    f'(?P<{category}>(?<![\[가-힣A-Za-z0-9])(?:{pattern}))'
    for category, pattern in _LABEL_PATTERNS
))

_ROLE_ROW_RE = re.compile(
    r'^(?P<leading>.*?)'
    r'(?<![가-힣A-Za-z0-9])'
    r'(?:(?P<customer_role>' + _CUSTOMER_ROLE + r')'
    r'|(?P<planner_role>' + _PLANNER_ROLE + r'))'
    r'(?P<tail>.+)$'
)
_ROLE_PAREN_TAIL_RE = re.compile(
    r'^(?P<particle>[ \t]*(?:' + _ROLE_PARTICLE_PREFIX + r'))?'
    r'(?P<open>[ \t]*(?:[:：][ \t]*)?[\(（\[\{][ \t]*)'
    r'(?P<value>[^()（）\[\]{}]*)'
    r'(?P<close>[ \t]*[\)）\]\}][ \t]*)$'
)
_ROLE_SEPARATED_TAIL_RE = re.compile(
    r'^(?P<particle>[ \t]*(?:' + _ROLE_PARTICLE_PREFIX + r'))?'
    r'(?P<separator>(?:[ \t]*[:：][ \t]*|[ \t]+'
    r'|(?=[\(（\[\{])))'
    r'(?P<value>.+)$'
)
_PRECEDING_ROLE_VALUE_RE = re.compile(
    r'^(?P<leading>[ \t]*)'
    r'(?P<value>.+?)'
    r'(?P<open>[ \t]*[\(（\[\{][ \t]*)'
    r'(?:(?P<customer_role>' + _CUSTOMER_ROLE + r')'
    r'|(?P<planner_role>' + _PLANNER_ROLE + r'))'
    r'(?P<close>[ \t]*[\)）\]\}][ \t]*)$'
)
_ROLE_FIELD_WRAPPER_RE = re.compile(
    r'^(?P<prefix>[ \t]*[\(（\[\{][ \t]*'
    r'(?:' + _ROLE_NAME_WORD + r')'
    r'[ \t]*[\)）\]\}][ \t]*(?:[:：][ \t]*)?)'
    r'(?P<value>.+)$'
)
_IDENTIFIER_FIELD_WRAPPER_RE = re.compile(
    r'^(?P<prefix>' + _LABEL_WRAPPER + r')(?P<value>.*)$'
)
_ROLE_ONLY_WRAPPER_RE = re.compile(
    r'^[ \t]*[\(（\[\{][ \t]*'
    r'(?:(?P<customer_role>' + _CUSTOMER_ROLE + r')'
    r'|(?P<planner_role>' + _PLANNER_ROLE + r'))'
    r'[ \t]*[\)）\]\}][ \t]*$'
)
_ROLE_STRUCTURED_VALUE_RE = re.compile(
    r'^' + _ROLE_STRUCTURED_FIELD_PREFIX
)
_ROLE_METADATA_VALUE_RE = re.compile(
    r'^(?P<prefix>(?:(?:' + _ROLE_VALUE_METADATA_PREFIX
    + r')[ \t]+)+)(?P<value>.+)$'
)
_BIRTH_DATE_PATTERN = (
    r'(?:'
    r'(?:19|20)[0-9]{2}'
    r'(?:[./-](?:0?[1-9]|1[0-2])'
    r'[./-](?:0?[1-9]|[12][0-9]|3[01])'
    r'|[ \t]*년[ \t]*(?:0?[1-9]|1[0-2])[ \t]*월'
    r'[ \t]*(?:0?[1-9]|[12][0-9]|3[01])[ \t]*일'
    r'|[0-9]{4})'
    r')'
)
_ROLE_TABLE_REMAINDER_RE = re.compile(
    r'^(?:'
    + _BIRTH_DATE_PATTERN
    + r'|[0-9*+/|,;]'
    + r'|남(?:[ \t]|$)|여(?:[ \t]|$)|본인(?:[ \t]|$)'
    + r'|배우자(?:[ \t]|$)|자녀(?:[ \t]|$)|가족(?:[ \t]|$)'
    + r'|법정상속인(?:[ \t]|$)|관계(?:[ \t:：]|$)'
    + r'|성[ \t]*명(?:[ \t:：]|$)|이[ \t]*름(?:[ \t:：]|$)'
    + r'|생[ \t]*년[ \t]*월[ \t]*일(?:[ \t:：]|$)'
    + r'|주[ \t]*민(?:등[ \t]*록)?번[ \t]*호(?:[ \t:：]|$)'
    + r'|연[ \t]*락[ \t]*처(?:[ \t:：]|$)'
    + r'|전[ \t]*화(?:번[ \t]*호)?(?:[ \t:：]|$)'
    + r'|휴[ \t]*대(?:전[ \t]*화|폰)(?:번[ \t]*호)?(?:[ \t:：]|$)'
    + r'|사[ \t]*원[ \t]*번[ \t]*호(?:[ \t:：]|$)'
    + r'|고[ \t]*객[ \t]*번[ \t]*호(?:[ \t:：]|$)'
    + r'|등[ \t]*록[ \t]*번[ \t]*호(?:[ \t:：]|$)'
    + r')'
)
_ROLE_VALUE_RE = re.compile(
    r'^(?P<name>.+?)'
    r'(?:(?P<birth_prefix>[ \t,(/]+)'
    r'(?P<birth>' + _BIRTH_DATE_PATTERN + r')'
    r'(?P<birth_suffix>[)]?))?$'
)
_PERSON_NAME_RE = re.compile(
    r'^[가-힣A-Za-z]'
    r'(?:[가-힣A-Za-z]'
    r"|[.'·ㆍ-](?=[가-힣A-Za-z])"
    r'|[ \t]+(?=[가-힣A-Za-z]))*$'
)


def split_role_identity_field_wrapper(value):
    """Split only a bounded (성명)/(이름)/(명) OCR-style wrapper."""
    match = _ROLE_FIELD_WRAPPER_RE.fullmatch(value)
    if match is None:
        return '', value
    return match.group('prefix'), match.group('value')


def split_identifier_field_wrapper(value):
    """Split only a bounded identifier (번호)/(TEST)/(NO) wrapper."""
    match = _IDENTIFIER_FIELD_WRAPPER_RE.fullmatch(value)
    if match is None:
        return '', value
    return match.group('prefix'), match.group('value')

_CATEGORY_TOKEN = dict(PSEUDONYMIZATION_CATEGORY_TOKENS)

_FIELD_PREFIX_RE = re.compile(
    r'(?P<prefix>[ \t]*(?:[:：][ \t]*)?)(?P<body>.*)', re.DOTALL)
_TRAILING_WRAPPER_RE = re.compile(r'(?P<value>.*?)(?P<suffix>[ \t()\[\]{},/|;]*)$')
_IDENTIFIER_NORMALIZER_RE = re.compile(r'[^0-9A-Za-z가-힣*]+')
_ANALYSIS_SIGNAL_RE = re.compile(
    r'(?:보험사|회사명|상품명|보험종류|보험료|'
    r'담보명|보장명|특약명|담보|특약|가입금액|'
    r'보장내용|보험금|진단비|수술비|입원비|'
    r'일당|치료비|납입기간|보장기간|보험기간|'
    r'납입|만기|비갱신|갱신)'
)
_ANALYSIS_AMOUNT_RE = re.compile(
    r'[0-9][0-9,]{0,24}(?:\.[0-9]{1,4})?[ \t]*'
    r'(?:억|천|백)?[ \t]*만?[ \t]*원'
)
_STANDALONE_PERSON_ROLE_WORDS = frozenset(
    _CUSTOMER_ROLE_WORDS + _PLANNER_ROLE_WORDS)
_KNOWN_COVERAGE_WORDS = frozenset(
    word
    for path, aliases in COVERAGE_KEYWORDS.items()
    for word in (*path.split('->'), *aliases)
    if re.fullmatch(r'[가-힣]{2,40}', word)
).union({'실손', '의료비', '혈관', '백혈병'})
_KNOWN_INSURANCE_CARRIER_NAMES = frozenset(
    alias.replace(' ', '')
    for aliases in (
        *LOSS_COMPANY_ALIASES.values(),
        *LIFE_COMPANY_ALIASES.values(),
    )
    for alias in aliases
    if re.fullmatch(r'[가-힣A-Za-z0-9]{2,40}', alias.replace(' ', ''))
)
_STANDALONE_INSURANCE_EXACT_SAFE_WORDS = frozenset({
    '일반암', '유사암', '소액암', '고액암', '특정암',
    '보험', '입원비', '정액형', '암진단비', '질병수술비',
    '이전계약', '장기보험료', '환급률', '후유장해',
    '뇌졸중', '골절비', '화상비',
    '무배당', '주계약', '보험사', '대표번호', '고객센터', '고유번호', '보험료', '월보험료',
    '번호',
    '갱신형', '보장형', '기준금액',
    '연락처', '휴대전화', '휴대폰', '전자우편', '성명', '이름',
    '회사명', '상품명', '보험종류', '계약', '담보', '특약', '납입', '만기', '비갱신', '갱신',
    '상해사망', '보험기간', '납입기간', '보장기간',
    '적립금', '환급금', '간병비', '치매비', '교통비', '응급실',
    '간병인', '중환자실', '표적항암', '생활비', '위로금',
    '만원', '억원', '천원', '백만원', '천만원',
    '년납', '년납입', '개월납', '개월납입', '세만기', '년만기',
    '만기보험금', '해약환급금', '납입면제', '면책기간', '감액기간',
    '보장개시일', '계약상태', '실효일자', '부활일자', '중도인출',
    '적립보험료', '위험보험료', '특약보험금', '만기환급금',
    '기본보험금', '월납입보험료', '월주계약보험료', '월특약보험료',
    '월적립보험료', '월보장보험료', '월갱신보험료', '갱신증가율',
    '환급유형', '갱신특약만기일',
    '페이지', '한아름보험', '한아름종합보험', '한아름건강보험',
    '건강보험', '어린이보험', '종신보험', '연금보험', '정기보험',
    '운전자보험', '치아보험', '간병보험', '태아보험', '화재보험',
    '자동차보험', '변액보험', '유병자보험', '여행자보험',
    '펫보험', '저축보험', '저축성보험', '연금저축보험', '단체보험',
    '해상보험', '보증보험', '신용보험', '재산보험', '상조보험',
    '실버보험', '치매보험', '주택화재보험', '가정종합보험',
    '보장성보험', '무해지보험', '무배당보험', '간편보험',
    '간편심사보험', '유병력자보험',
    '보장보험료', '주계약보험료', '특약보험료', '납입보험료',
    '해지환급금',
}).union(
    _KNOWN_INSURANCE_CARRIER_NAMES,
    COVERAGE_MARKERS,
    (token for _category, token in PSEUDONYMIZATION_CATEGORY_TOKENS),
)
_COMPOUND_KOREAN_FAMILY_NAMES = (
    '남궁', '황보', '제갈', '선우', '독고', '서문', '동방', '사공',
)
_KOREAN_FAMILY_NAMES = frozenset(
    '김이박최정강조윤장임한오서신권황안송전홍유고문양손배백허남심노'
    '엄류차주구우민진지채원천방공현함변염여추도소석선설마길연위표명기반왕금옥'
    '육인맹제모탁국어은편용예봉경부사복태목형두감음빈동온호범좌팽승간상시갈가계'
)
_STANDALONE_NAME_RE = re.compile(r'^[가-힣]{2,5}$')
_DELIMITED_KOREAN_NAME_RE = re.compile(
    r'(?<![가-힣])(?P<name>[가-힣]{1,2}'
    r'(?:[ \t]*[.·ㆍ/|\-][ \t]*[가-힣]{1,6}){1,3})(?![가-힣])')
_KOREAN_NAME_PART_RE = re.compile(r'^[가-힣]{1,6}$')
_IDENTITY_METADATA_WORDS = frozenset({
    '본인', '남', '여', '관계', '배우자', '자녀', '가족', '법정상속인',
    '부', '모', '부모', '형제', '자매', '형제자매', '친족', '동거인',
    '기타', '조부', '조모', '손자', '손녀',
})
_IDENTITY_CONTEXT_PREFIX_WORDS = frozenset({'담당', '문의', '본인'})
_WRAPPED_STRUCTURAL_SAFE_WORDS = (
    _STANDALONE_PERSON_ROLE_WORDS
    | {'번호', '성명', '이름', '명', '무배당', '주계약'}
)
_PERSON_PREFIX_ANALYSIS_MARKERS = (
    '가입금액', '보험료', '진단비', '수술비', '입원비', '치료비',
    '보험금', '담보', '특약',
)
_ENGLISH_WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'\-]*$")
_ENGLISH_IDENTITY_SAFE_SIGNAL_RE = re.compile(
    r'^(?:INSURANCE|ASSURANCE|POLICY|PREMIUM|BENEFIT|COVERAGE|'
    r'RIDER|PLAN|PRODUCT|COMPANY|CORP|CORPORATION|INC|LTD|LIFE|'
    r'MUTUAL|FINANCIAL|CASUALTY|ANNUITY)$',
    re.IGNORECASE,
)
_STANDALONE_INSURANCE_TERM_RE = re.compile(
    r'(?:보험|보장|담보|특약|계약|가입|진단|수술|입원|'
    r'치료|사망|후유|장해|질환|질병|상해|재해|실손|'
    r'의료|혈압|만기|납입|갱신|지급|면책|정액|'
    r'고객|이름|성명|안내|정보|내용|사항|관계|구분|본인|'
    r'주소|거주지|소재지|주민|생년|출생|연락처|전화|'
    r'휴대전화|휴대폰|이메일|전자우편|'
    r'배우자|자녀|가족|직업|급수|연령|나이|권리|조건|'
    r'서명|동의|설명|고지|제공|등록|작성|선택|입력|'
    r'기재|해당|기준|경우|정상|유지|한도|최초|손해|장기)'
)
_INSURANCE_MORPHEME_RE = re.compile(
    r'(?:일반|유사|소액|특정|갑상선|대장|고도|암|뇌|심근|심장|질병|상해|'
    r'재해|후유|장해|진단|급여금?|수술|입원|통원|일당|실손|의료|비급여|'
    r'주사|도수|체외|충격파|증식|방사선|약물|촬영|MRI|MRA|'
    r'벌금|형사|합의|변호사|선임|'
    r'배상|책임|사망|항암|치료|골절|화상|이식|중환자|환경성|희귀|'
    r'질환|종합|보험)'
)
_INSURANCE_MORPHEME_RESIDUAL_RE = re.compile(
    r'^(?:(?:일이상|경계성|제외|포함|이상|이하|비|금|료|종|일|등)'
    r'|[0-9%％~～()（）·/.,\-])*$'
)
_ANALYSIS_FRAGMENT_SAFE_WORDS = frozenset({
    '일이상', '갑상선', '급여', '급여통원', '경계성',
    '특정', '소액', '종수술', '촬영료', '비급여', '실손', '통원', '등',
})
_STANDALONE_ADDRESS_RE = re.compile(
    r'^(?=.{6,160}$)(?=.*[0-9])'
    r'(?=.*(?:특별시|광역시|특별자치시|특별자치도|'
    r'[가-힣]{1,12}(?:시|군|구|읍|면|동|리))(?=[ \t]))'
    r'(?=.*(?:[가-힣A-Za-z0-9]{1,20}'
    r'(?:대로|번길|로|길)[ \t]+[0-9]))'
    r'[가-힣A-Za-z0-9 \t,./()\-]+$'
)
_ADDRESS_ALLOWED_RE = re.compile(r'^[가-힣A-Za-z0-9 \t,./()\-]{6,160}$')
_ADDRESS_HIGH_UNIT_RE = re.compile(
    r'^[가-힣]{1,16}(?:도|시|군|구|읍|면)$')
_ADDRESS_LOCAL_UNIT_RE = re.compile(r'^[가-힣]{1,16}(?:동|리)$')
_ADDRESS_ROAD_UNIT_RE = re.compile(
    r'^[가-힣A-Za-z0-9]{1,24}(?:대로|번길|로|길)$')
_ADDRESS_LOT_NUMBER_RE = re.compile(
    r'^(?:산[ \t]*)?[0-9]{1,6}(?:-[0-9]{1,6})?(?:번지)?$')


def _is_standalone_insurance_structure(
        value, *, allow_two_syllable_coverage=False):
    if value in _STANDALONE_INSURANCE_EXACT_SAFE_WORDS:
        return True
    if (value in _KNOWN_COVERAGE_WORDS
            and (len(value) >= 3 or allow_two_syllable_coverage)):
        return True
    for marker in _PERSON_PREFIX_ANALYSIS_MARKERS:
        if not value.endswith(marker):
            continue
        prefix = value[:-len(marker)]
        if (3 <= len(prefix) <= 4
                and re.fullmatch(r'[가-힣]{3,4}', prefix)
                and _is_bounded_family_korean_name(prefix)
                and prefix not in _KNOWN_COVERAGE_WORDS
                and prefix not in _STANDALONE_INSURANCE_EXACT_SAFE_WORDS):
            return False
    morpheme_matches = tuple(_INSURANCE_MORPHEME_RE.finditer(value))
    if ((len(value) >= 5
            or (len(value) == 4
                and not _is_bounded_family_korean_name(value)))
            and morpheme_matches
            and morpheme_matches[0].start() == 0
            and len({match.group(0) for match in morpheme_matches}) >= 2):
        residual_parts = []
        cursor = 0
        for match in morpheme_matches:
            residual_parts.append(value[cursor:match.start()])
            cursor = match.end()
        residual_parts.append(value[cursor:])
        residual = re.sub(r'[ \t]+', '', ''.join(residual_parts))
        if _INSURANCE_MORPHEME_RESIDUAL_RE.fullmatch(residual):
            return True
    for marker in COVERAGE_MARKERS:
        if not value.endswith(marker):
            continue
        prefix = value[:-len(marker)]
        if prefix in _KNOWN_COVERAGE_WORDS:
            return True
    return False


def _is_ocr_spaced_insurance_structure(value):
    if re.fullmatch(r'[가-힣]+(?:[ \t]+[가-힣]+)+', value) is None:
        return False
    parts = tuple(re.split(r'[ \t]+', value))
    collapsed = re.sub(r'[ \t]+', '', value)
    if all(len(part) == 1 for part in parts):
        return _is_standalone_insurance_structure(
            collapsed, allow_two_syllable_coverage=True)
    return all(
        _is_standalone_insurance_structure(
            part, allow_two_syllable_coverage=True)
        for part in parts
    )


def _is_bounded_compound_korean_name(value):
    return any(
        value.startswith(family_name)
        and 1 <= len(value) - len(family_name) <= 6
        and re.fullmatch(r'[가-힣]{3,8}', value) is not None
        for family_name in _COMPOUND_KOREAN_FAMILY_NAMES
    )


def _is_bounded_family_korean_name(value):
    return bool(
        re.fullmatch(r'[가-힣]{2,8}', value) is not None
        and (
            value[0] in _KOREAN_FAMILY_NAMES
            or _is_bounded_compound_korean_name(value)
        )
    )


def _is_possible_unlabeled_korean_name_token(value):
    if ((_STANDALONE_NAME_RE.fullmatch(value) is None
            and not _is_bounded_family_korean_name(value))
            or value in _STANDALONE_PERSON_ROLE_WORDS
            or _is_standalone_insurance_structure(
                value, allow_two_syllable_coverage=True)):
        return False
    return True


def _is_possible_delimited_korean_name(value):
    match = _DELIMITED_KOREAN_NAME_RE.fullmatch(value)
    if match is None:
        return False
    normalized = re.sub(r'[ \t.·ㆍ/|\-]', '', match.group('name'))
    return _is_possible_unlabeled_korean_name_token(normalized)


def _contains_possible_delimited_korean_name(value):
    has_analysis_signal = bool(
        _ANALYSIS_SIGNAL_RE.search(value) or _ANALYSIS_AMOUNT_RE.search(value)
    )
    for match in _DELIMITED_KOREAN_NAME_RE.finditer(value):
        candidate = match.group('name')
        collapsed = re.sub(r'[ \t.·ㆍ/|\-]+', '', candidate)
        if (has_analysis_signal
                and _is_standalone_insurance_structure(
                    collapsed, allow_two_syllable_coverage=True)):
            continue
        if _is_possible_delimited_korean_name(candidate):
            return True
    return False


def _is_safe_analysis_fragment(match, value):
    token = match.group(0)
    if token in _ANALYSIS_FRAGMENT_SAFE_WORDS:
        return True
    threshold = next(
        (word for word in ('이상', '이하') if token.startswith(word)),
        None,
    )
    if threshold is None:
        return False
    numeric_context = value[max(0, match.start() - 8):match.start()]
    if re.search(
            r'(?:[%％]|세|일|년|개월|만원|원)[ \t]*$',
            numeric_context) is None:
        return False
    remainder = token[len(threshold):]
    return not remainder or _is_standalone_insurance_structure(
        remainder, allow_two_syllable_coverage=True)


def _contains_delimited_english_name(value):
    stripped = value.strip()
    if (re.fullmatch(r"[A-Za-z][A-Za-z' ,.·/|\-]{2,160}", stripped)
            is None
            or re.search(r'[,，.·/|\-]', stripped) is None):
        return False
    words = tuple(re.findall(r"[A-Za-z][A-Za-z']{1,30}", stripped))
    if not 2 <= len(words) <= 6:
        return False
    return not any(
        _ENGLISH_IDENTITY_SAFE_SIGNAL_RE.fullmatch(word)
        for word in words
    )


def _contains_contextual_unlabeled_name(value):
    if (_contains_possible_delimited_korean_name(value)
            or _contains_delimited_english_name(value)):
        return True

    has_analysis_signal = bool(
        _ANALYSIS_SIGNAL_RE.search(value) or _ANALYSIS_AMOUNT_RE.search(value)
    )
    for candidate in re.findall(
            r'[\(（\[\{][ \t]*([가-힣]{2,8})[ \t]*[\)）\]\}]',
            value):
        if candidate in _WRAPPED_STRUCTURAL_SAFE_WORDS:
            continue
        if (has_analysis_signal
                and (
                    candidate in _ANALYSIS_FRAGMENT_SAFE_WORDS
                    or candidate in {
                        '벌금', '일반암', '유사암', '소액암', '특정암',
                        '갱신형', '보장형',
                    }
                    or (len(candidate) >= 4
                        and _is_standalone_insurance_structure(
                        candidate, allow_two_syllable_coverage=True)
                    )
                )):
            continue
        return True

    prefix_pattern = '|'.join(
        re.escape(word) for word in _IDENTITY_CONTEXT_PREFIX_WORDS)
    prefix_match = re.search(
        rf'(?<![가-힣])(?:{prefix_pattern})'
        r'(?:[ \t]*[:：/|\-][ \t]*|[ \t]+)'
        r'(?P<value>[가-힣]{1,2}(?:[ \t]+[가-힣]{1,6})?'
        r'|[가-힣]{2,8})(?![가-힣])',
        value,
    )
    if prefix_match is not None:
        return True

    metadata_pattern = '|'.join(
        re.escape(word) for word in _IDENTITY_METADATA_WORDS)
    metadata_non_gender_pattern = '|'.join(
        re.escape(word)
        for word in _IDENTITY_METADATA_WORDS
        if word not in {'남', '여'}
    )
    suffix_match = re.search(
        r'(?<![가-힣])(?P<value>[가-힣]{2,8})'
        r'(?:'
        rf'[ \t]*(?:[,，]|[\(（])?[ \t]*(?:{metadata_non_gender_pattern})'
        r'|[ \t,，\(（]+(?:남|여)'
        r')'
        r'(?:[ \t]*[\)）])?(?![가-힣])',
        value,
    )
    if suffix_match is not None:
        return True

    nbsp_match = re.search(
        r'(?<![가-힣])(?P<family>[가-힣]{1,2})\u00a0+'
        r'(?P<given>[가-힣]{1,6})(?![가-힣])',
        value,
    )
    if (nbsp_match is not None
            and _is_possible_unlabeled_korean_name_token(
                nbsp_match.group('family') + nbsp_match.group('given'))):
        return True

    wrapped_english = re.search(
        r'[\(（\[\{][ \t]*(?P<value>'
        r"[A-Za-z][A-Za-z .·\-']{1,79})[ \t]*[\)）\]\}]",
        value,
    )
    if (wrapped_english is not None
            and _has_ambiguous_english_name_prefix(
                wrapped_english.group('value').strip())):
        return True

    english_prefix = re.search(
        rf'(?<![가-힣])(?:{prefix_pattern})'
        r'(?:[ \t]*[:：/|\-][ \t]*|[ \t]+)'
        r"(?P<value>[A-Za-z][A-Za-z .·\-']{1,79}?)"
        rf'(?:[ \t]*[,，/|]?[ \t]+(?:{metadata_pattern}))?[ \t]*$',
        value,
    )
    return bool(
        english_prefix is not None
        and _has_ambiguous_english_name_prefix(
            english_prefix.group('value').strip())
    )


def _contains_possible_unlabeled_korean_name(value):
    if _contains_possible_delimited_korean_name(value):
        return True
    has_analysis_signal = bool(
        _ANALYSIS_SIGNAL_RE.search(value) or _ANALYSIS_AMOUNT_RE.search(value)
    )
    token_matches = tuple(re.finditer(
        r'(?<![가-힣])[가-힣]{2,8}(?![가-힣])', value))
    if any(
            _is_possible_unlabeled_korean_name_token(match.group(0))
            and not (
                has_analysis_signal
                and _is_safe_analysis_fragment(match, value)
            )
            for match in token_matches):
        return True
    # A one-syllable surname cannot safely depend on a finite surname list.
    # Join the bounded OCR-spaced shape, but retain known insurance phrases.
    for family_name, given_name in re.findall(
            r'(?<![가-힣])([가-힣])[ \t]+([가-힣]{1,6})(?![가-힣])',
            value):
        if (has_analysis_signal
                and family_name in {'세', '일', '년', '원'}
                and given_name in {'이상', '이하'}):
            continue
        if _is_standalone_insurance_structure(
                given_name, allow_two_syllable_coverage=True):
            continue
        joined = family_name + given_name
        if (2 <= len(joined) <= 8
                and joined not in _STANDALONE_PERSON_ROLE_WORDS
                and not _is_standalone_insurance_structure(
                    joined, allow_two_syllable_coverage=True)):
            return True
    return False


def _is_conservative_standalone_name(value):
    if (_STANDALONE_NAME_RE.fullmatch(value) is None
            or value in _STANDALONE_PERSON_ROLE_WORDS
            or _is_standalone_insurance_structure(
                value, allow_two_syllable_coverage=True)):
        return False
    return len(value) == 3


def _leading_korean_name_candidate(value):
    """Return a bounded Korean name after normalizing surname whitespace."""
    parts = re.split(r'[ \t]+', value)
    first = parts[0]
    if (first in _STANDALONE_PERSON_ROLE_WORDS
            or _STANDALONE_INSURANCE_TERM_RE.fullmatch(first)):
        return None, 0
    if _is_conservative_standalone_name(first):
        return first, 1
    if len(parts) < 2 or _KOREAN_NAME_PART_RE.fullmatch(parts[1]) is None:
        return None, 0
    if _is_standalone_insurance_structure(
            parts[1], allow_two_syllable_coverage=True):
        return None, 0
    normalized = first + parts[1]
    if (((len(first) == 1 and re.fullmatch(r'[가-힣]', first))
            or _is_bounded_family_korean_name(normalized))
            and _is_possible_unlabeled_korean_name_token(normalized)):
        return normalized, 2
    return None, 0


def _has_ambiguous_english_name_prefix(value):
    """Fail closed for multiword Latin identity shapes without safe context."""
    words = []
    for part in re.split(r'[ \t]+', value):
        if _ENGLISH_WORD_RE.fullmatch(part) is None:
            break
        words.append(part)
    if len(words) < 2:
        return False
    return not any(
        _ENGLISH_IDENTITY_SAFE_SIGNAL_RE.fullmatch(word)
        for word in words
    )


def _looks_like_standalone_address(value):
    if _ADDRESS_ALLOWED_RE.fullmatch(value) is None:
        return False
    tokens = tuple(re.split(r'[ \t]+', value))
    high_units = sum(
        _ADDRESS_HIGH_UNIT_RE.fullmatch(token) is not None
        for token in tokens
    )
    has_local_unit = any(
        _ADDRESS_LOCAL_UNIT_RE.fullmatch(token) is not None
        for token in tokens
    )
    has_road_unit = any(
        _ADDRESS_ROAD_UNIT_RE.fullmatch(token) is not None
        for token in tokens
    )
    has_lot_number = any(
        _ADDRESS_LOT_NUMBER_RE.fullmatch(token) is not None
        for token in tokens
    )
    return bool(
        (high_units >= 1 and (has_road_unit or has_local_unit))
        or (has_local_unit and has_lot_number)
    )


def _is_bounded_person_name(value):
    if _PERSON_NAME_RE.fullmatch(value) is None:
        return False
    letters = tuple(
        character for character in value
        if ('가' <= character <= '힣'
            or 'A' <= character <= 'Z'
            or 'a' <= character <= 'z')
    )
    has_hangul = any('가' <= character <= '힣' for character in letters)
    has_latin = any(
        'A' <= character <= 'Z' or 'a' <= character <= 'z'
        for character in letters
    )
    word_count = len(re.split(r'[ \t]+', value))
    if has_hangul and not has_latin:
        return 1 <= len(letters) <= 8
    if has_latin and not has_hangul:
        return len(letters) <= 80 and word_count <= 6
    return 2 <= len(letters) <= 40 and word_count <= 6


def is_bounded_person_name(value):
    """Shared conservative person-shape predicate; returns no source data."""
    return _is_bounded_person_name(value)


def _role_identity_prefix(value):
    """Find a bounded person prefix only before a structured table column."""
    if re.match(_ROLE_NON_NAME_START, value.strip()):
        return None
    for boundary in re.finditer(r'[ \t]+', value):
        candidate = value[:boundary.start()].strip()
        remainder = value[boundary.end():]
        if (candidate
                and _is_bounded_person_name(candidate)
                and _ROLE_TABLE_REMAINDER_RE.match(remainder)):
            return candidate, value[boundary.start():]
    return None


def is_bounded_role_identity_value(value):
    """Recognize a person value alone or before birth/table metadata."""
    stripped = value.strip()
    return bool(
        _is_bounded_person_name(stripped)
        or _role_identity_prefix(stripped) is not None
    )


def _is_explicit_safe_role_sentence(line):
    return ' '.join(line.split()) in _SAFE_ROLE_SENTENCES


def _is_structural_safe_role_copy(line):
    """Recognize role words used as insurance prose, not identity fields."""
    if any(mark in line for mark in ('.', '!', '?', '。')):
        return False
    matches = list(_ROLE_ROW_RE.finditer(line))
    if not matches:
        return False
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
        tail = match.group('tail')[:end - match.start()]
        separated = _ROLE_PAREN_TAIL_RE.fullmatch(tail)
        if separated is None:
            separated = _ROLE_SEPARATED_TAIL_RE.fullmatch(tail)
        if separated is None:
            return False
        value = separated.group('value').strip()
        if not value:
            continue
        if (_ROLE_STRUCTURED_VALUE_RE.match(value)
                or _ROLE_METADATA_VALUE_RE.fullmatch(value)):
            return False
        if (not re.match(_ROLE_SENTENCE_RESERVED_PREFIX, value)
                and value[0] not in '0123456789*+'):
            return False
    return True


class DocumentPseudonymizer:
    """Own one document's short-lived alias state inside the PDF child."""

    def __init__(self):
        self._value_aliases = {
            category: {} for category in PSEUDONYMIZATION_CATEGORIES
        }
        self._occurrence_counts = Counter()

    def __repr__(self):
        return '<DocumentPseudonymizer private>'

    @staticmethod
    def _normalize(category, value):
        if category in {'phone', 'rrn'}:
            normalized = ''.join(
                character for character in value
                if character.isdigit() or character == '*'
            )
            if category == 'phone' and value.lstrip().startswith('+82'):
                local_units = normalized[2:]
                if local_units.startswith('0'):
                    local_units = local_units[1:]
                normalized = f'0{local_units}'
        elif category == 'email':
            normalized = value.strip().casefold()
        elif category in {'customer_name', 'planner_name'}:
            collapsed = ' '.join(value.split())
            if re.fullmatch(r'(?:[가-힣][ \t]*){2,8}', value.strip()):
                normalized = re.sub(r'[ \t]+', '', value).casefold()
            else:
                normalized = collapsed.casefold()
        elif category in {
                'contract_id', 'policy_id', 'customer_id',
                'certificate_id', 'application_id', 'planner_id',
                'recruiter_id', 'license_id', 'account_id', 'card_id',
                'business_id'}:
            normalized = _IDENTIFIER_NORMALIZER_RE.sub(
                '', value).casefold()
        else:
            normalized = ' '.join(value.split()).casefold()
        return normalized or ' '.join(value.split()).casefold()

    def _alias(self, category, source_value):
        normalized = self._normalize(category, source_value)
        aliases = self._value_aliases[category]
        alias = aliases.get(normalized)
        if alias is None:
            alias = f'[{_CATEGORY_TOKEN[category]}_{len(aliases) + 1}]'
            aliases[normalized] = alias
        self._occurrence_counts[category] += 1
        return alias

    def _replace_globals(self, line):
        if '@' in line:
            line = _EMAIL_RE.sub(
                lambda match: self._alias('email', match.group(0)), line)
        line = _RRN_RE.sub(
            lambda match: self._alias('rrn', match.group(0)), line)
        if '0' in line or '+82' in line:
            line = _PHONE_RE.sub(
                lambda match: self._alias('phone', match.group(0)), line)
        return line

    def _replace_role_value(self, category, value):
        leading_length = len(value) - len(value.lstrip(' \t'))
        trailing_length = len(value) - len(value.rstrip(' \t'))
        leading = value[:leading_length]
        trailing = value[len(value) - trailing_length:] if trailing_length else ''
        value_end = len(value) - trailing_length if trailing_length else len(value)
        core = value[leading_length:value_end]
        metadata_prefix = ''
        metadata_match = _ROLE_METADATA_VALUE_RE.fullmatch(core)
        if metadata_match is not None:
            metadata_prefix = metadata_match.group('prefix')
            core = metadata_match.group('value')
        value_match = _ROLE_VALUE_RE.fullmatch(core)
        if (value_match is not None
                and _is_bounded_person_name(value_match.group('name'))):
            replacement = (
                metadata_prefix
                + self._alias(category, value_match.group('name'))
            )
            birth = value_match.group('birth')
            if birth is not None:
                replacement += (
                    value_match.group('birth_prefix')
                    + self._alias('birth_date', birth)
                    + value_match.group('birth_suffix')
                )
        else:
            identity_prefix = _role_identity_prefix(core)
            if identity_prefix is None:
                return None
            name, remainder = identity_prefix
            replacement = metadata_prefix + self._alias(category, name)
            birth_match = re.match(
                r'(?P<spacing>[ \t]+)(?P<birth>'
                + _BIRTH_DATE_PATTERN
                + r')(?P<rest>.*)$',
                remainder,
            )
            if birth_match is not None:
                replacement += (
                    birth_match.group('spacing')
                    + self._alias('birth_date', birth_match.group('birth'))
                    + birth_match.group('rest')
                )
            else:
                replacement += remainder
        return f'{leading}{replacement}{trailing}'

    def _replace_role_row(self, line):
        role_match = _ROLE_ROW_RE.fullmatch(line)
        if role_match is None:
            return None

        tail = role_match.group('tail')
        tail_match = _ROLE_PAREN_TAIL_RE.fullmatch(tail)
        is_parenthesized = tail_match is not None
        if tail_match is None:
            tail_match = _ROLE_SEPARATED_TAIL_RE.fullmatch(tail)
        if tail_match is None:
            return None

        value = tail_match.group('value')
        field_wrapper, value = split_role_identity_field_wrapper(value)
        if (not is_parenthesized
                and _ROLE_STRUCTURED_VALUE_RE.match(value)):
            return None

        category = (
            'customer_name'
            if role_match.group('customer_role') is not None
            else 'planner_name'
        )
        masked_value = self._replace_role_value(category, value)
        if masked_value is None:
            return None
        masked_value = field_wrapper + masked_value
        role = (
            role_match.group('customer_role')
            or role_match.group('planner_role')
        )
        particle = tail_match.group('particle') or ''
        if is_parenthesized:
            masked_tail = (
                particle
                + tail_match.group('open')
                + masked_value
                + tail_match.group('close')
            )
        else:
            masked_tail = (
                particle
                + tail_match.group('separator')
                + masked_value
            )
        return (
            role_match.group('leading')
            + role
            + masked_tail
        )

    def _replace_preceding_role_value(self, line):
        match = _PRECEDING_ROLE_VALUE_RE.fullmatch(line)
        if match is None:
            return None
        value = match.group('value')
        if _segment_is_empty_or_alias(value) is True:
            return line
        if not _is_bounded_person_name(value.strip()):
            return None
        category = (
            'customer_name'
            if match.group('customer_role') is not None
            else 'planner_name'
        )
        return (
            match.group('leading')
            + self._alias(category, value.strip())
            + match.group('open')
            + (match.group('customer_role') or match.group('planner_role'))
            + match.group('close')
        )

    def _replace_labeled_segment(self, category, segment):
        if _segment_is_empty_or_alias(segment) is True:
            return segment, True
        field_match = _FIELD_PREFIX_RE.fullmatch(segment)
        if field_match is None:
            return segment, False
        body = field_match.group('body')
        wrapper_match = _TRAILING_WRAPPER_RE.fullmatch(body)
        value = wrapper_match.group('value') if wrapper_match else body
        suffix = wrapper_match.group('suffix') if wrapper_match else ''
        if not value.strip():
            return segment, False
        direct_pattern = {
            'rrn': _RRN_RE,
            'phone': _PHONE_RE,
            'email': _EMAIL_RE,
        }.get(category)
        if direct_pattern is not None and direct_pattern.search(value):
            replaced = direct_pattern.sub(
                lambda match: self._alias(category, match.group(0)), value)
            return (
                f'{field_match.group("prefix")}{replaced}{suffix}',
                True,
            )
        alias = self._alias(category, value)
        return f'{field_match.group("prefix")}{alias}{suffix}', True

    def _replace_pending_line(self, category, line):
        if _segment_is_empty_or_alias(line) is True:
            return line
        leading_length = len(line) - len(line.lstrip())
        trailing_length = len(line) - len(line.rstrip())
        leading = line[:leading_length]
        trailing = line[len(line) - trailing_length:] if trailing_length else ''
        value_end = len(line) - trailing_length if trailing_length else len(line)
        value = line[leading_length:value_end]
        if category in {'customer_name', 'planner_name'}:
            masked_value = self._replace_role_value(category, value)
            if masked_value is None:
                return line
            return self._replace_globals(
                f'{leading}{masked_value}{trailing}')
        return f'{leading}{self._alias(category, value)}{trailing}'

    def _replace_followup_labels(self, line):
        matches = [
            match for match in _LABEL_RE.finditer(line)
            if match.lastgroup not in {'customer_name', 'planner_name'}
        ]
        if not matches:
            return self._replace_globals(line), None
        parts = []
        cursor = 0
        next_pending = None
        for index, label_match in enumerate(matches):
            value_end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(line)
            )
            parts.append(self._replace_globals(
                line[cursor:label_match.end()]))
            masked_value, consumed = self._replace_labeled_segment(
                label_match.lastgroup,
                line[label_match.end():value_end],
            )
            parts.append(masked_value)
            next_pending = None if consumed else label_match.lastgroup
            cursor = value_end
        return self._replace_globals(''.join(parts)), next_pending

    def _pseudonymize_line(
            self, line, pending_category, *, detect_unlabeled):
        if (detect_unlabeled
                and any('\u3130' <= character <= '\u318f'
                        for character in line)):
            return (
                _UNCERTAIN_ANALYSIS_IDENTITY_SENTINEL
                if _line_has_analysis_signal(line)
                else _UNCERTAIN_IDENTITY_SENTINEL,
                None,
            )
        line = _normalize_ocr_text(line)
        preceding_role = self._replace_preceding_role_value(line)
        if preceding_role is not None:
            return self._replace_globals(preceding_role), None
        if (_is_explicit_safe_role_sentence(line)
                or _is_structural_safe_role_copy(line)):
            return self._replace_globals(line), None

        role_row = self._replace_role_row(line)
        if role_row is not None:
            return self._replace_followup_labels(role_row)

        matches = list(_LABEL_RE.finditer(line))
        if pending_category is not None and line.strip():
            if not matches:
                return self._replace_pending_line(pending_category, line), None
            pending_category = None

        if not matches:
            if not detect_unlabeled:
                return self._replace_globals(line), pending_category
            globally_masked = self._replace_globals(line)
            if _PSEUDONYM_ALIAS_CAPTURE_RE.search(globally_masked):
                residual_probe = _PSEUDONYM_ALIAS_CAPTURE_RE.sub(
                    ' ', globally_masked).strip()
                ambiguous_short_carrier = bool(
                    re.fullmatch(r'[가-힣]{2,3}', residual_probe)
                    and residual_probe in _KNOWN_INSURANCE_CARRIER_NAMES
                )
                if (residual_probe
                        and (
                            ambiguous_short_carrier
                            or
                            _contains_possible_unlabeled_korean_name(
                                residual_probe)
                            or _standalone_identity_state(
                                residual_probe) is not None
                        )):
                    return (
                        _UNCERTAIN_ANALYSIS_IDENTITY_SENTINEL
                        if _line_has_analysis_signal(line)
                        else _UNCERTAIN_IDENTITY_SENTINEL,
                        None,
                    )
            standalone_state = _standalone_identity_state(globally_masked)
            if standalone_state == 'ambiguous':
                # Drop the raw value immediately. The bounded quarantine pass
                # removes this private sentinel and records source coordinates
                # before any external AI payload is built.
                return (
                    _UNCERTAIN_ANALYSIS_IDENTITY_SENTINEL
                    if _line_has_analysis_signal(line)
                    else _UNCERTAIN_IDENTITY_SENTINEL,
                    None,
                )
            if standalone_state is not None:
                leading_length = len(line) - len(line.lstrip())
                trailing_length = len(line) - len(line.rstrip())
                leading = line[:leading_length]
                trailing = (
                    line[len(line) - trailing_length:]
                    if trailing_length else ''
                )
                return (
                    leading
                    + self._alias(standalone_state, globally_masked.strip())
                    + trailing,
                    None,
                )
            return globally_masked, pending_category

        parts = []
        cursor = 0
        next_pending = None
        for index, label_match in enumerate(matches):
            value_end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(line)
            )
            parts.append(self._replace_globals(line[cursor:label_match.end()]))
            masked_value, consumed = self._replace_labeled_segment(
                label_match.lastgroup,
                line[label_match.end():value_end],
            )
            parts.append(masked_value)
            next_pending = None if consumed else label_match.lastgroup
            cursor = value_end
        return ''.join(parts), next_pending

    def _pseudonymize_pass(
            self, page_source_lines, *, detect_unlabeled):
        pseudonymized_pages = []
        pending_category = None
        for page_lines in page_source_lines:
            pseudonymized_page = []
            for source_line in page_lines:
                pseudonymized_line, pending_category = self._pseudonymize_line(
                    source_line,
                    pending_category,
                    detect_unlabeled=detect_unlabeled,
                )
                pseudonymized_page.append(pseudonymized_line)
            pseudonymized_pages.append(tuple(pseudonymized_page))
        return tuple(pseudonymized_pages)

    def pseudonymize(self, page_source_lines):
        # A bounded second identity pass handles nested/table label chains
        # created by PDF layout flattening. Existing aliases are idempotent.
        pages = self._pseudonymize_pass(
            page_source_lines, detect_unlabeled=True)
        pages = self._pseudonymize_pass(pages, detect_unlabeled=False)
        (
            pages,
            quarantined_line_ids,
            analysis_signal_quarantined_line_ids,
        ) = _quarantine_uncertain_identity_lines(pages)
        pages, category_counts = _compact_pseudonym_aliases(pages)
        assert_pseudonymized_pages_safe(pages)
        return PseudonymizedDocument(
            pages=pages,
            category_counts=category_counts,
            residual_scan_passed=True,
            quarantined_line_count=len(quarantined_line_ids),
            quarantined_line_ids=quarantined_line_ids,
            analysis_signal_quarantined_line_count=len(
                analysis_signal_quarantined_line_ids),
            analysis_signal_quarantined_line_ids=(
                analysis_signal_quarantined_line_ids),
        )


# These patterns intentionally form a separate post-transform pass. A defect in
# the alias replacement cannot turn the scanner result into a matched excerpt.
_RESIDUAL_RRN_RE = re.compile(_RRN_PATTERN)
_RESIDUAL_EMAIL_RE = re.compile(_EMAIL_PATTERN)
_RESIDUAL_PHONE_SEPARATOR = (
    r'(?:[ \t]*(?:[-‐‑‒–—―−－]|\.)[ \t]*|[ \t]+)?'
)
_RESIDUAL_PHONE_CANDIDATE_RE = re.compile(
    r'(?<![0-9*+])(?:\+82'
    rf'{_RESIDUAL_PHONE_SEPARATOR}[0-9*]{{1,4}}'
    r'|0[0-9*]{1,3})'
    rf'{_RESIDUAL_PHONE_SEPARATOR}[0-9*]{{3,4}}'
    rf'{_RESIDUAL_PHONE_SEPARATOR}[0-9*]{{4}}(?![0-9*])'
)
_RESIDUAL_COUNTRY_SEQUENCE_RE = re.compile(
    r'(?<![0-9*+])\+82'
    r'(?P<body>(?:(?:[ \t()/.\-‐‑‒–—―−－]*)[0-9*]){8,32})'
)
_RESIDUAL_ROLE_PARTICLE_PATTERN = (
    r'(?:에[ \t]*게[ \t]*는|에[ \t]*게|에[ \t]*는|'
    r'은|는|이|가|을|를|와|과|의|도)'
)
_RESIDUAL_ROLE_FIELD_RE = re.compile(
    r'(?<![가-힣A-Za-z0-9])(?:'
    + _alternatives(
        '보험계약자', '계약자', '피보험자', '보험수익자',
        '수익자', '가입자', '고객', '대표자', '보험설계사',
        '모집담당자', '모집자', '모집인', '담당설계사',
        '담당자', '설계사',
    )
    + r')(?P<suffix>(?:'
    + r'(?:(?:[ \t]*' + _RESIDUAL_ROLE_PARTICLE_PATTERN + r')?'
    + r'(?:[ \t]*[:：][ \t]*|[ \t]+))'
    + r'|(?:(?:[ \t]*' + _RESIDUAL_ROLE_PARTICLE_PATTERN + r')?'
    + r'[ \t]*[\(（\[\{][ \t]*)'
    + r'))'
)
_RESIDUAL_ROLE_METADATA_RE = re.compile(
    r'^(?:(?:변[ \t]*경|정[ \t]*보|에[ \t]*게[ \t]*는|'
    r'에[ \t]*게|에[ \t]*는|은|는|이|가|을|를|와|과|의|도)'
    r'[ \t]+)+'
)
_RESIDUAL_ROLE_STRUCTURED_RE = re.compile(
    r'^(?:성[ \t]*명|이[ \t]*름|주[ \t]*소|거[ \t]*주[ \t]*지|'
    r'소[ \t]*재[ \t]*지|주[ \t]*민(?:등[ \t]*록)?번[ \t]*호|'
    r'생[ \t]*년[ \t]*월[ \t]*일|출[ \t]*생[ \t]*일|'
    r'연[ \t]*락[ \t]*처|전[ \t]*화(?:번[ \t]*호)?|'
    r'휴[ \t]*대(?:전[ \t]*화|폰)(?:번[ \t]*호)?|'
    r'이[ \t]*메[ \t]*일(?:주[ \t]*소)?|'
    r'전[ \t]*자[ \t]*우[ \t]*편)'
    r'[ \t]*(?:[:：][ \t]*)?(?P<value>.*)$'
)
_RESIDUAL_LABEL_RE = re.compile(
    r'(?<![\[가-힣A-Za-z0-9])(?:'
    + '|'.join(pattern for _category, pattern in _LABEL_PATTERNS)
    + r')'
)
_TOKEN_PATTERN = (
    r'\[(?:' + '|'.join(re.escape(value) for value in _CATEGORY_TOKEN.values())
    + r')_[1-9][0-9]*\]'
)
_TOKEN_CATEGORY = {
    token: category for category, token in _CATEGORY_TOKEN.items()
}
_PSEUDONYM_ALIAS_CAPTURE_RE = re.compile(
    r'\[(?P<token>'
    + '|'.join(re.escape(token) for token in _TOKEN_CATEGORY)
    + r')_(?P<index>[1-9][0-9]*)\]'
)
_UNCERTAIN_IDENTITY_SENTINEL = '[INPA_UNCERTAIN_IDENTITY]'
_UNCERTAIN_ANALYSIS_IDENTITY_SENTINEL = (
    '[INPA_UNCERTAIN_ANALYSIS_IDENTITY]')
_UNCERTAIN_IDENTITY_SENTINELS = frozenset({
    _UNCERTAIN_IDENTITY_SENTINEL,
    _UNCERTAIN_ANALYSIS_IDENTITY_SENTINEL,
})
_ALIAS_ONLY_RE = re.compile(
    r'^[ \t:：()（）{}\[\],/|;.-]*(?:' + _TOKEN_PATTERN
    + r'[ \t:：()（）{}\[\],/|;.-]*)+$'
)


def _standalone_identity_state(line):
    """Classify only high-confidence unlabeled identity-shaped lines."""
    value = line.strip()
    if not value or _ALIAS_ONLY_RE.fullmatch(value):
        return None
    if (_is_explicit_safe_role_sentence(value)
            or _is_structural_safe_role_copy(value)):
        return None
    if _is_ocr_spaced_insurance_structure(value):
        return None
    has_analysis_signal = _line_has_analysis_signal(value)
    if _contains_contextual_unlabeled_name(value):
        return 'ambiguous'
    if (_is_bounded_compound_korean_name(value)
            and not _is_standalone_insurance_structure(value)):
        return 'ambiguous'
    if (len(value) > 5
            and _is_bounded_family_korean_name(value)
            and not _is_standalone_insurance_structure(value)):
        return 'ambiguous'
    if (_STANDALONE_NAME_RE.fullmatch(value) is not None
            and value not in _STANDALONE_PERSON_ROLE_WORDS):
        if _is_standalone_insurance_structure(
                value, allow_two_syllable_coverage=True):
            return None
        # A standalone three-syllable Korean name cannot safely depend on a
        # finite surname allowlist. Alias the common shape; fail closed for
        # shorter/longer shapes that are also plausible names.
        return 'customer_name' if len(value) == 3 else 'ambiguous'
    name_parts = re.split(r'[ \t]+', value)
    if (has_analysis_signal
            and _contains_possible_unlabeled_korean_name(value)):
        return 'ambiguous'
    if (len(name_parts) > 1
            and name_parts[1] in _IDENTITY_METADATA_WORDS
            and _is_possible_unlabeled_korean_name_token(name_parts[0])):
        return 'ambiguous'
    name_candidate, consumed_parts = _leading_korean_name_candidate(value)
    # A bounded identity-shaped leading column must be resolved before an
    # amount or coverage marker can make the remaining insurance facts safe.
    if name_candidate is not None:
        if (consumed_parts > 1
                or len(name_parts) > consumed_parts
                or len(name_candidate) != 3):
            return 'ambiguous'
        return 'customer_name'
    if _has_ambiguous_english_name_prefix(value):
        return 'ambiguous'
    if _STANDALONE_ADDRESS_RE.fullmatch(value):
        return 'ambiguous' if has_analysis_signal else 'address'
    if _looks_like_standalone_address(value):
        return 'ambiguous'
    # Only after identity-shaped prefixes and address ranges are excluded may
    # short Korean insurance terms and analysis signals pass unchanged.
    if (has_analysis_signal
            or _STANDALONE_INSURANCE_TERM_RE.search(value) is not None):
        return None
    return None
_ALIAS_PREFIX_RE = re.compile(
    r'^[ \t:：()（）{}\[\],/|;.-]*(?:' + _TOKEN_PATTERN + r')'
)
_APPENDED_ROLE_NAME_RE = re.compile(
    r'[.!?。][ \t]*(?P<name>'
    r'(?:[가-힣][ .·ㆍ\-\'\t]*){2,8}'
    r'|[A-Za-z][A-Za-z .·\-\']{1,79}'
    r')[ \t]*$'
)


def contains_probable_direct_identifier(text):
    """Return only a boolean; never expose the matched value or context."""
    return bool(
        _RESIDUAL_RRN_RE.search(text)
        or (('0' in text or '+82' in text)
            and _contains_residual_phone(text))
        or ('@' in text and _RESIDUAL_EMAIL_RE.search(text))
    )


def _is_korean_phone_units(units):
    if units.startswith(('010', '011', '016', '017', '018', '019')):
        return len(units) in (10, 11)
    if units.startswith('02'):
        return len(units) in (9, 10)
    if units[:3] in {
            '031', '032', '033', '041', '042', '043', '044',
            '051', '052', '053', '054', '055', '061', '062',
            '063', '064', '070'}:
        return len(units) in (10, 11)
    if units[:4] in {
            '0502', '0503', '0504', '0505', '0506', '0507', '0508'}:
        return len(units) in (11, 12)
    return False


def _contains_residual_phone(text):
    if _RESIDUAL_COUNTRY_SEQUENCE_RE.search(text):
        return True
    for match in _RESIDUAL_PHONE_CANDIDATE_RE.finditer(text):
        units = ''.join(
            character for character in match.group(0)
            if character.isdigit() or character == '*'
        )
        if match.group(0).lstrip().startswith('+82'):
            units = f'0{units[2:]}'
        if _is_korean_phone_units(units):
            return True
    return False


def _residual_role_tail_is_safe(tail):
    value = tail.strip()
    if not value:
        return True
    _field_wrapper, value = split_role_identity_field_wrapper(value)
    value = value.strip()
    if not value:
        return False
    if _ALIAS_ONLY_RE.fullmatch(value):
        return True

    metadata_match = _RESIDUAL_ROLE_METADATA_RE.match(value)
    if metadata_match is not None:
        value = value[metadata_match.end():].strip()
        return _ALIAS_ONLY_RE.fullmatch(value) is not None

    structured_match = _RESIDUAL_ROLE_STRUCTURED_RE.fullmatch(value)
    if structured_match is not None:
        structured_value = structured_match.group('value').strip()
        return (
            not structured_value
            or _ALIAS_ONLY_RE.fullmatch(structured_value) is not None
        )
    alias = _ALIAS_PREFIX_RE.match(value)
    if alias is not None:
        alias_chain_state = _alias_chain_is_safe(value)
        if alias_chain_state is True:
            return True
        remainder = value[alias.end():].strip(' \t:：(){}[],/|;.-')
        if _role_identity_prefix(remainder) is not None:
            return False
        if (_is_bounded_person_name(remainder)
                and not re.match(_ROLE_NON_NAME_START, remainder)):
            return False
        return True
    if _APPENDED_ROLE_NAME_RE.search(value):
        return False
    if re.match(_ROLE_NON_NAME_START, value):
        return True
    if value[0].isdigit() or value[0] in '*+':
        return True
    if _role_identity_prefix(value) is not None:
        return False
    if (_is_bounded_person_name(value)
            and not re.match(_ROLE_NON_NAME_START, value)):
        return False
    if _residual_alias_label_chain_is_safe(value):
        return True
    # The role word is ordinary insurance prose unless a preceding branch
    # proves a raw identity-shaped value. Direct and labeled identifiers are
    # still checked independently for every line.
    return True


def _contains_residual_role_value(line):
    preceding_role = _PRECEDING_ROLE_VALUE_RE.fullmatch(line)
    if preceding_role is not None:
        value = preceding_role.group('value').strip()
        if (_segment_is_empty_or_alias(value) is not True
                and _is_bounded_person_name(value)):
            return True
    if (_is_explicit_safe_role_sentence(line)
            or _is_structural_safe_role_copy(line)):
        return False
    matches = list(_RESIDUAL_ROLE_FIELD_RE.finditer(line))
    for index, role_match in enumerate(matches):
        value_end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(line)
        )
        if not _residual_role_tail_is_safe(
                line[role_match.end():value_end]):
            return True
    return False


def _segment_is_empty_or_alias(segment):
    if not segment.strip(' \t:：()（）{}[],/|;.-'):
        return None
    return _alias_chain_is_safe(segment)


def _alias_chain_is_safe(value):
    remainder = value
    consumed = False
    between_alias_separators = ' \t:：()（）{},/|;.-'
    while True:
        alias = _ALIAS_PREFIX_RE.match(remainder)
        if alias is None:
            break
        consumed = True
        remainder = remainder[alias.end():]
        # Keep square brackets intact so another alias can be recognized.
        stripped = remainder.strip(between_alias_separators)
        if not stripped:
            return True
        remainder = stripped
    return bool(consumed and re.match(_ROLE_NON_NAME_START, remainder))


def _line_has_analysis_signal(line):
    return bool(_ANALYSIS_SIGNAL_RE.search(line) or _ANALYSIS_AMOUNT_RE.search(line))


def _contains_probable_role_identity_prefix(line):
    if (_is_explicit_safe_role_sentence(line)
            or _is_structural_safe_role_copy(line)):
        return False
    role = _ROLE_ROW_RE.fullmatch(line)
    if role is None:
        return False
    tail = role.group('tail')
    separated = _ROLE_PAREN_TAIL_RE.fullmatch(tail)
    if separated is None:
        separated = _ROLE_SEPARATED_TAIL_RE.fullmatch(tail)
    if separated is None:
        return False
    value = separated.group('value').strip()
    _field_wrapper, value = split_role_identity_field_wrapper(value)
    value = value.strip()
    metadata = _ROLE_METADATA_VALUE_RE.fullmatch(value)
    if metadata is not None:
        value = metadata.group('value').strip()
    if (not value
            or _ROLE_STRUCTURED_VALUE_RE.match(value)
            or re.match(_ROLE_SENTENCE_RESERVED_PREFIX, value)
            or _ALIAS_PREFIX_RE.match(value)):
        return False
    first = re.split(r'[ \t:：()\[\]{},;/|]+', value, maxsplit=1)[0]
    return bool(first and _is_bounded_person_name(first))


def _identity_line_state(line, pending_category):
    """Return (unresolved identity, next pending category) without excerpts."""
    matches = list(_LABEL_RE.finditer(line))
    unresolved = bool(
        contains_probable_direct_identifier(line)
        or _contains_residual_role_value(line)
        or _contains_probable_role_identity_prefix(line)
        or line in _UNCERTAIN_IDENTITY_SENTINELS
    )

    if pending_category is not None and line.strip():
        if not matches and _segment_is_empty_or_alias(line.strip()) is not True:
            unresolved = True
        pending_category = None

    next_pending = None
    for index, match in enumerate(matches):
        value_end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(line)
        )
        state = _segment_is_empty_or_alias(line[match.end():value_end])
        if state is False:
            unresolved = True
        next_pending = match.lastgroup if state is None else None
    return unresolved, next_pending


def _quarantine_uncertain_identity_lines(pages):
    mutable = [list(page) for page in pages]
    quarantined = set()
    analysis_quarantined = set()
    pending_category = None
    pending_position = None

    for page_index, page in enumerate(mutable):
        previous_position = None
        previous_line = None
        for line_index, line in enumerate(page):
            if (_ROLE_ONLY_WRAPPER_RE.fullmatch(line)
                    and previous_position is not None
                    and _segment_is_empty_or_alias(previous_line) is not True
                    and _is_bounded_person_name(previous_line.strip())):
                current_position = (page_index, line_index)
                for position in (previous_position, current_position):
                    mutable[position[0]][position[1]] = ''
                    quarantined.add(position)
                if (_line_has_analysis_signal(previous_line)
                        or _line_has_analysis_signal(line)):
                    analysis_quarantined.update(
                        (previous_position, current_position))
                pending_category = None
                pending_position = None
                previous_position = None
                previous_line = None
                continue
            unresolved, next_pending = _identity_line_state(
                line, pending_category)
            if unresolved:
                current_position = (page_index, line_index)
                if (_line_has_analysis_signal(line)
                        or line == _UNCERTAIN_ANALYSIS_IDENTITY_SENTINEL):
                    analysis_quarantined.add(current_position)
                positions = [(page_index, line_index)]
                if pending_position is not None:
                    positions.append(pending_position)
                for position in positions:
                    mutable[position[0]][position[1]] = ''
                    quarantined.add(position)
                pending_category = None
                pending_position = None
                previous_position = None
                previous_line = None
                continue
            if next_pending is not None:
                pending_category = next_pending
                pending_position = (page_index, line_index)
            elif line.strip():
                pending_category = None
                pending_position = None
            if line.strip():
                previous_position = (page_index, line_index)
                previous_line = line
            else:
                previous_position = None
                previous_line = None

    if pending_position is not None:
        mutable[pending_position[0]][pending_position[1]] = ''
        quarantined.add(pending_position)

    def line_id(position):
        page_index, line_index = position
        return f'p{page_index + 1:02d}-l{line_index + 1:03d}'

    return (
        tuple(tuple(page) for page in mutable),
        tuple(line_id(position) for position in sorted(quarantined)),
        tuple(
            line_id(position)
            for position in sorted(analysis_quarantined)
        ),
    )


def _compact_pseudonym_aliases(pages):
    index_maps = {category: {} for category in PSEUDONYMIZATION_CATEGORIES}
    occurrence_counts = Counter()

    def replace(match):
        category = _TOKEN_CATEGORY[match.group('token')]
        old_index = match.group('index')
        mapping = index_maps[category]
        if old_index not in mapping:
            mapping[old_index] = len(mapping) + 1
        occurrence_counts[category] += 1
        return f'[{_CATEGORY_TOKEN[category]}_{mapping[old_index]}]'

    compacted = tuple(tuple(
        _PSEUDONYM_ALIAS_CAPTURE_RE.sub(replace, line)
        for line in page
    ) for page in pages)
    counts = tuple(
        (category, occurrence_counts[category])
        for category in PSEUDONYMIZATION_CATEGORIES
        if occurrence_counts[category]
    )
    return compacted, counts


def _residual_alias_label_chain_is_safe(value):
    matches = list(_RESIDUAL_LABEL_RE.finditer(value))
    if not matches:
        return False

    cursor = 0
    for match in matches:
        if _segment_is_empty_or_alias(value[cursor:match.start()]) is False:
            return False
        cursor = match.end()
    return _segment_is_empty_or_alias(value[cursor:]) is not False


def assert_pseudonymized_pages_safe(pages):
    """Fail closed without returning a match, value, line, or page."""
    pending_label = False
    for page_lines in pages:
        previous_line = None
        for line in page_lines:
            if _standalone_identity_state(line) is not None:
                raise PDFImportError('PII_REDACTION_UNCERTAIN')
            if (_ROLE_ONLY_WRAPPER_RE.fullmatch(line)
                    and previous_line is not None
                    and _segment_is_empty_or_alias(previous_line) is not True
                    and _is_bounded_person_name(previous_line.strip())):
                raise PDFImportError('PII_REDACTION_UNCERTAIN')
            if contains_probable_direct_identifier(line):
                raise PDFImportError('PII_REDACTION_UNCERTAIN')
            if _contains_residual_role_value(line):
                raise PDFImportError('PII_REDACTION_UNCERTAIN')

            if (_is_explicit_safe_role_sentence(line)
                    or _is_structural_safe_role_copy(line)):
                pending_label = False
                previous_line = None
                continue

            matches = list(_RESIDUAL_LABEL_RE.finditer(line))
            if pending_label and line.strip():
                if (not matches
                        and _segment_is_empty_or_alias(line.strip()) is not True):
                    raise PDFImportError('PII_REDACTION_UNCERTAIN')
                pending_label = False

            if not matches:
                previous_line = line if line.strip() else None
                continue

            pending_label = False
            for index, match in enumerate(matches):
                value_end = (
                    matches[index + 1].start()
                    if index + 1 < len(matches)
                    else len(line)
                )
                state = _segment_is_empty_or_alias(
                    line[match.end():value_end])
                if state is False:
                    raise PDFImportError('PII_REDACTION_UNCERTAIN')
                pending_label = state is None
            previous_line = line if line.strip() else None
    return True


def pseudonymize_page_lines(page_source_lines):
    return DocumentPseudonymizer().pseudonymize(page_source_lines)


def mask_page_lines(page_source_lines):
    """Compatibility facade returning only safe document-local alias pages."""
    return pseudonymize_page_lines(page_source_lines).pages
