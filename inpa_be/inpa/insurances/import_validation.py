import copy
import re
from dataclasses import asdict, dataclass, is_dataclass
from decimal import Decimal, InvalidOperation

from inpa.analysis.management.commands.seed_normalization import STANDARD_TREE
from inpa.core.ocr.ocrdata import LifeInsurance, LossInsurance
from inpa.core.ocr.ocrparsing import is_ambiguous_coverage_name

from .date_utils import parse_insurance_date


STANDARD_COVERAGE_PATHS = frozenset(
    (category, subcategory, detail_name)
    for category, _insurance_type, subcategories in STANDARD_TREE
    for subcategory, details in subcategories
    for detail_name, _chart_based_amount in details
)
CARRIER_CODE_BY_NAME = {
    re.sub(r'\s+', '', name).lower(): index
    for index, name in enumerate(LossInsurance.company)
}
CARRIER_CODE_BY_NAME.update({
    re.sub(r'\s+', '', name).lower(): 200 + index
    for index, name in enumerate(LifeInsurance.company)
})
ALLOWED_CARRIER_CODES = frozenset(CARRIER_CODE_BY_NAME.values())


def sanitize_force_manual_carrier_codes(value):
    """Return only canonical, non-boolean carrier integers from JSON state."""
    if not isinstance(value, list):
        return []
    return sorted({
        code for code in value
        if type(code) is int and code in ALLOWED_CARRIER_CODES
    })


_INVALID_CODES = {
    'CONTRACT_AFTER_EXPIRY', 'INVALID_DATE', 'NEGATIVE_AMOUNT',
    'NEGATIVE_PREMIUM', 'INVALID_PERIOD',
    'INVALID_RENEWAL_PAYMENT_COMBINATION', 'DUPLICATE_ROW_ID',
    'UNKNOWN_SOURCE_CANDIDATE', 'INVALID_ROW_ID', 'RAW_NAME_REQUIRED',
    'PERIOD_UNIT_REQUIRED', 'PERIOD_VALUE_REQUIRED',
    'LIFETIME_PERIOD_HAS_VALUE', 'RENEWAL_FLAG_REQUIRED',
    'PAYMENT_PERIOD_EXCEEDS_WARRANTY',
    'INSURANCE_TYPE_REQUIRED',
    'CONTRACT_DATE_REQUIRED_FOR_AGE_PERIOD',
}
_NO_EVIDENCE_CODES = {
    'EVIDENCE_LINE_NOT_FOUND', 'RAW_NAME_EVIDENCE_MISMATCH',
    'AMOUNT_EVIDENCE_MISMATCH', 'PREMIUM_EVIDENCE_MISMATCH',
    'DATE_EVIDENCE_MISMATCH', 'TEXT_EVIDENCE_MISMATCH',
    'EVIDENCE_CANDIDATE_MISMATCH', 'AMOUNT_ROLE_AMBIGUOUS',
}
MANUAL_COVERAGE_FIELDS = (
    'raw_name', 'assurance_amount', 'premium', 'is_renewal',
    'renewal_period', 'payment_period', 'payment_period_unit',
    'warranty_period', 'warranty_period_unit', 'standard_category',
    'standard_subcategory', 'standard_detail_name', 'disposition',
    'exclusion_reason', 'duplicate_of_row_id',
)
_MANUAL_COVERAGE_FIELD_SET = frozenset(MANUAL_COVERAGE_FIELDS)
_CONFIRMABLE_REVIEW_CODES = frozenset({'CARRIER_MANUAL_REVIEW'})
_EXCLUDED_ROW_INTEGRITY_CODES = frozenset({
    'INVALID_ROW_ID', 'DUPLICATE_ROW_ID', 'UNKNOWN_SOURCE_CANDIDATE',
    'DUPLICATE_SOURCE_ROW', 'EXCLUSION_REASON_REQUIRED',
})
_STANDARD_MAPPING_FIELDS = frozenset({
    'standard_category', 'standard_subcategory', 'standard_detail_name',
})
_DOSU_DETAIL = '실손비급여도수치료'
_MRI_DETAIL = '실손비급여MRI'


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    state: str
    scope: str
    row_id: str | None = None
    field: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    draft: dict
    issues: tuple[ValidationIssue, ...]
    summary: dict


def _plain(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    return {
        key: getattr(value, key)
        for key in value.__annotations__
    }


def _compact_text(value):
    return re.sub(r'\s+', '', str(value or '')).lower()


def _standard_mapping_contradicts_name(raw_name, detail_name):
    compact = _compact_text(raw_name).upper()
    is_dosu = any(token in compact for token in (
        '도수치료', '도수·체외충격파·증식치료',
    ))
    is_mri = 'MRI' in compact or 'MRA' in compact
    if is_dosu:
        return detail_name != _DOSU_DETAIL
    if is_mri:
        return detail_name != _MRI_DETAIL
    return False


def _line_texts(line_ids, lines_by_id):
    if (not isinstance(line_ids, list)
            or not line_ids
            or any(line_id not in lines_by_id for line_id in line_ids)):
        return None
    return [lines_by_id[line_id]['text_masked'] for line_id in line_ids]


def _decimal_number(value):
    try:
        return Decimal(value.replace(',', ''))
    except (AttributeError, InvalidOperation):
        return None


_MONEY_PATTERN = re.compile(
    r'(?P<eok_sign>[+-]?)(?P<eok>\d+(?:,\d{3})*(?:\.\d+)?)억(?:원)?'
    r'(?:\s*(?P<tail>\d+(?:,\d{3})*(?:\.\d+)?)'
    r'(?P<tail_unit>천만원|백만원|만원|천원|원))?'
    r'|(?P<simple>[+-]?\d+(?:,\d{3})*(?:\.\d+)?)'
    r'(?P<simple_unit>천만원|백만원|만원|천원|원)'
)
_MONEY_MULTIPLIER = {
    '천만원': Decimal('10000000'),
    '백만원': Decimal('1000000'),
    '만원': Decimal('10000'),
    '천원': Decimal('1000'),
    '원': Decimal('1'),
}
_MONEY_LABEL_ROLE = {
    '보험가입금액': 'assurance',
    '가입금액': 'assurance',
    '보장금액': 'assurance',
    '보장한도': 'assurance',
    '보장액': 'assurance',
    '한도액': 'assurance',
    '월납입보험료': 'premium',
    '월보험료': 'premium',
    '납입보험료': 'premium',
    '보험료': 'premium',
}
_MONEY_LABEL_PATTERN = re.compile('|'.join(
    sorted(_MONEY_LABEL_ROLE, key=len, reverse=True)))


def _money_mentions(text):
    compact = re.sub(r'\s+', '', text)
    mentions = []
    for match in _MONEY_PATTERN.finditer(compact):
        if match.group('eok') is not None:
            eok = _decimal_number(match.group('eok'))
            if eok is None:
                continue
            total = eok * Decimal('100000000')
            if match.group('tail') is not None:
                tail = _decimal_number(match.group('tail'))
                if tail is None:
                    continue
                total += tail * _MONEY_MULTIPLIER[match.group('tail_unit')]
            if match.group('eok_sign') == '-':
                total = -total
        else:
            number = _decimal_number(match.group('simple'))
            if number is None:
                continue
            total = number * _MONEY_MULTIPLIER[match.group('simple_unit')]
        if total == total.to_integral_value():
            mentions.append((match.start(), match.end(), int(total)))
    return mentions


def _date(value):
    return parse_insurance_date(value)


def _dates_in_text(text):
    patterns = (
        r'(?<!\d)(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*'
        r'(\d{1,2})(?!\d)',
        r'(?<!\d)(\d{4})\s*년\s*(\d{1,2})\s*월\s*'
        r'(\d{1,2})\s*일(?!\d)',
    )
    found = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            parsed = parse_insurance_date('.'.join(match.groups()))
            if parsed is not None:
                found.add(parsed)
    return found


def _date_in_evidence(value, texts):
    if texts is None or not isinstance(value, str):
        return False
    expected = _date(value)
    return expected is not None and any(
        expected in _dates_in_text(text) for text in texts)


def _text_in_evidence(value, texts):
    if texts is None or not isinstance(value, str):
        return False
    normalized = _compact_text(value)
    return bool(normalized) and any(
        normalized in _compact_text(text) for text in texts)


def _money_evidence_inventory(texts):
    labeled_values = {'assurance': [], 'premium': []}
    unlabeled_mentions = []
    seen_label_roles = set()
    for text in texts:
        compact = re.sub(r'\s+', '', text)
        mentions = _money_mentions(text)
        labels = list(_MONEY_LABEL_PATTERN.finditer(compact))
        if not labels:
            unlabeled_mentions.extend(
                mention_value for _start, _end, mention_value in mentions)
            continue
        seen_label_roles.update(
            _MONEY_LABEL_ROLE[label.group(0)] for label in labels)
        assigned_mentions = set()
        for index, label in enumerate(labels):
            segment_end = (
                labels[index + 1].start()
                if index + 1 < len(labels) else len(compact)
            )
            for mention_index, (start, _end, mention_value) in enumerate(
                    mentions):
                if not label.end() <= start < segment_end:
                    continue
                assigned_mentions.add(mention_index)
                labeled_values[_MONEY_LABEL_ROLE[label.group(0)]].append(
                    mention_value)
        unlabeled_mentions.extend(
            mention_value
            for mention_index, (_start, _end, mention_value) in enumerate(
                mentions)
            if mention_index not in assigned_mentions
        )
    return labeled_values, unlabeled_mentions, seen_label_roles


def _money_in_evidence(value, texts, *, role):
    if texts is None or type(value) is not int:
        return False
    labeled, unlabeled, seen_roles = _money_evidence_inventory(texts)
    if labeled[role]:
        return value in labeled[role]
    if seen_roles:
        other_role = 'premium' if role == 'assurance' else 'assurance'
        return (
            role not in seen_roles
            and other_role in seen_roles
            and len(unlabeled) == 1
            and value == unlabeled[0]
        )
    return len(unlabeled) == 1 and value == unlabeled[0]


def _row_money_evidence(assurance_amount, premium, texts):
    """Allocate each evidence occurrence to at most one populated row field."""
    supported = {'assurance': assurance_amount is None, 'premium': premium is None}
    if texts is None:
        return supported, False

    labeled, unlabeled, seen_roles = _money_evidence_inventory(texts)
    values = {'assurance': assurance_amount, 'premium': premium}
    unresolved_roles = []
    for role, value in values.items():
        if value is None:
            continue
        if role in seen_roles:
            supported[role] = value in labeled[role]
        else:
            unresolved_roles.append(role)

    if len(unresolved_roles) == 1:
        role = unresolved_roles[0]
        supported[role] = (
            len(unlabeled) == 1 and values[role] == unlabeled[0])
        return supported, False
    if len(unresolved_roles) > 1:
        for role in unresolved_roles:
            supported[role] = False
        return supported, bool(unlabeled)
    return supported, False


def _carrier_kind(carrier_name):
    normalized = _compact_text(carrier_name)
    if normalized == '우체국보험':
        return 'loss'
    if normalized.endswith(('생명', '라이프')):
        return 'life'
    if normalized.endswith(('화재', '해상', '손해', '손보')):
        return 'loss'
    return None


def _product_kind(product_name):
    normalized = _compact_text(product_name)
    if any(keyword in normalized for keyword in (
            '자동차보험', '운전자보험', '화재보험', '실손보험')):
        return 'loss'
    if any(keyword in normalized for keyword in (
            '종신보험', '변액보험', '연금보험')):
        return 'life'
    return None


def _row_state(row, codes, *, manual_fields):
    if any(code in _INVALID_CODES for code in codes):
        return 'invalid'
    if any(code in _NO_EVIDENCE_CODES for code in codes):
        return 'no_evidence'
    if 'STANDARD_MAPPING_REQUIRED' in codes:
        return 'unmatched'
    if 'STANDARD_MAPPING_INVALID' in codes:
        return 'unmatched'
    if row.get('disposition') == 'unmatched':
        return 'unmatched'
    if codes:
        return 'needs_review'
    if manual_fields:
        return 'manual'
    if row.get('disposition') == 'intentionally_excluded':
        return 'needs_review'
    return 'review_ready'


def _trusted_row_review_metadata(row, *, allow_manual):
    if not allow_manual:
        row.pop('manual_fields', None)
        row.pop('confirmed_review_codes', None)
        row.pop('_review_previous', None)
        return frozenset()

    raw_manual_fields = row.get('manual_fields')
    if not isinstance(raw_manual_fields, list):
        raw_manual_fields = []
    manual_fields = frozenset(
        field for field in raw_manual_fields
        if field in _MANUAL_COVERAGE_FIELD_SET
    )
    if manual_fields:
        row['manual_fields'] = [
            field for field in MANUAL_COVERAGE_FIELDS
            if field in manual_fields
        ]
    else:
        row.pop('manual_fields', None)

    raw_confirmed_codes = row.get('confirmed_review_codes')
    if not isinstance(raw_confirmed_codes, list):
        raw_confirmed_codes = []
    confirmed_codes = [
        code for code in raw_confirmed_codes
        if code in _CONFIRMABLE_REVIEW_CODES
    ]
    if confirmed_codes:
        row['confirmed_review_codes'] = list(dict.fromkeys(confirmed_codes))
    else:
        row.pop('confirmed_review_codes', None)
    return manual_fields


def _is_server_approved_exclusion(row, manual_fields=None):
    if row.get('disposition') != 'intentionally_excluded':
        return False
    trusted = set(
        manual_fields
        if manual_fields is not None else row.get('manual_fields') or [])
    required = {'disposition', 'exclusion_reason'}
    if row.get('duplicate_of_row_id') is not None:
        required.add('duplicate_of_row_id')
    return required.issubset(trusted)


def apply_force_manual_review(validation, *, required):
    """Reapply the worker-snapshotted carrier review requirement per row."""
    draft = validation.draft
    summary = dict(validation.summary)
    if not required:
        return draft, summary

    validation_payload = draft.setdefault('validation', {})
    existing_issues = validation_payload.setdefault('issues', [])
    for row in draft.get('coverage_rows') or []:
        if _is_server_approved_exclusion(row):
            continue
        confirmed_codes = row.get('confirmed_review_codes')
        if (isinstance(confirmed_codes, list)
                and 'CARRIER_MANUAL_REVIEW' in confirmed_codes):
            continue
        reasons = row.setdefault('review_reason_codes', [])
        if 'CARRIER_MANUAL_REVIEW' not in reasons:
            reasons.append('CARRIER_MANUAL_REVIEW')
        row['state'] = 'needs_review'
        issue = {
            'code': 'CARRIER_MANUAL_REVIEW',
            'state': 'needs_review',
            'scope': 'coverage',
            'row_id': row.get('row_id'),
            'field': 'company_code',
        }
        if issue not in existing_issues:
            existing_issues.append(issue)

    resolved_states = {'review_ready', 'manual'}
    unresolved = sum(
        row.get('state') not in resolved_states
        for row in draft.get('coverage_rows') or [])
    unresolved += sum(
        field.get('state') not in resolved_states
        for field in (draft.get('policy') or {}).values()
        if isinstance(field, dict))
    validation_payload['unresolved_count'] = unresolved
    summary['unresolved_count'] = unresolved
    summary['issue_count'] = len(existing_issues)
    return draft, summary


def validate_draft(lines, candidates, provider_payload, *, allow_manual=False,
                   allow_manual_without_evidence=False):
    """Validate a draft without correcting or discarding provider values."""
    normalized_lines = [_plain(line) for line in lines]
    normalized_candidates = [_plain(candidate) for candidate in candidates]
    lines_by_id = {line['line_id']: line for line in normalized_lines}
    candidates_by_id = {
        candidate['candidate_id']: candidate
        for candidate in normalized_candidates
    }
    if hasattr(provider_payload, 'model_dump'):
        payload = provider_payload.model_dump(mode='json')
    else:
        payload = copy.deepcopy(provider_payload)
    payload.pop('_system', None)
    policy = payload.get('policy') or {}
    if not isinstance(policy.get('insurance_type'), dict):
        policy['insurance_type'] = {
            'value': None,
            'evidence_line_ids': [],
        }
    rows = list(payload.get('coverage_rows') or [])
    issues = []
    row_codes = {}
    row_manual_fields = {}
    policy_codes = {}

    def add_issue(code, state, scope, *, row_id=None, field=None):
        issue = ValidationIssue(
            code=code, state=state, scope=scope,
            row_id=row_id, field=field)
        if issue not in issues:
            issues.append(issue)
        if scope == 'coverage':
            row_codes.setdefault(row_id, []).append(code)
        if scope == 'policy' and field is not None:
            policy_codes.setdefault(field, []).append(code)

    for field, evidence in policy.items():
        if not isinstance(evidence, dict):
            add_issue('EVIDENCE_LINE_NOT_FOUND', 'no_evidence', 'policy',
                      field=field)
            continue
        value = evidence.get('value')
        if value is None:
            continue
        if allow_manual and evidence.get('state') == 'manual':
            continue
        texts = _line_texts(evidence.get('evidence_line_ids'), lines_by_id)
        if texts is None:
            add_issue('EVIDENCE_LINE_NOT_FOUND', 'no_evidence', 'policy',
                      field=field)
        elif field in {'contract_date', 'expiry_date'}:
            if not _date_in_evidence(value, texts):
                add_issue('DATE_EVIDENCE_MISMATCH', 'no_evidence', 'policy',
                          field=field)
        elif field == 'monthly_premium':
            if not _money_in_evidence(value, texts, role='premium'):
                add_issue('PREMIUM_EVIDENCE_MISMATCH', 'no_evidence',
                          'policy', field=field)
        elif field in {'carrier_name', 'product_name'}:
            if not _text_in_evidence(value, texts):
                add_issue('TEXT_EVIDENCE_MISMATCH', 'no_evidence', 'policy',
                          field=field)

    contract = _date((policy.get('contract_date') or {}).get('value'))
    expiry = _date((policy.get('expiry_date') or {}).get('value'))
    if ((policy.get('contract_date') or {}).get('value') is not None
            and contract is None):
        add_issue('INVALID_DATE', 'invalid', 'policy', field='contract_date')
    if ((policy.get('expiry_date') or {}).get('value') is not None
            and expiry is None):
        add_issue('INVALID_DATE', 'invalid', 'policy', field='expiry_date')
    if contract is not None and expiry is not None and contract > expiry:
        add_issue('CONTRACT_AFTER_EXPIRY', 'invalid', 'policy',
                  field='contract_date')
    monthly_premium = (policy.get('monthly_premium') or {}).get('value')
    if type(monthly_premium) is int and monthly_premium < 0:
        add_issue('NEGATIVE_PREMIUM', 'invalid', 'policy',
                  field='monthly_premium')

    carrier_name = (policy.get('carrier_name') or {}).get('value')
    product_name = (policy.get('product_name') or {}).get('value')
    insurance_type = (policy.get('insurance_type') or {}).get('value')
    if insurance_type not in {'life', 'loss'}:
        add_issue('INSURANCE_TYPE_REQUIRED', 'invalid', 'policy',
                  field='insurance_type')
    carrier_kind = _carrier_kind(carrier_name)
    if carrier_kind and insurance_type and carrier_kind != insurance_type:
        add_issue('CARRIER_TYPE_CONTRADICTION', 'needs_review', 'policy',
                  field='insurance_type')
    product_kind = _product_kind(product_name)
    if product_kind and insurance_type and product_kind != insurance_type:
        add_issue('PRODUCT_TYPE_CONTRADICTION', 'needs_review', 'policy',
                  field='product_name')
    expected_company_code = CARRIER_CODE_BY_NAME.get(
        _compact_text(carrier_name))
    company_code = (policy.get('company_code') or {}).get('value')
    if (expected_company_code is not None
            and company_code is not None
            and expected_company_code != company_code):
        add_issue('CARRIER_CODE_CONTRADICTION', 'needs_review', 'policy',
                  field='company_code')

    candidate_rows = {}
    row_id_positions = {}
    duplicate_issue_positions = set()
    invalid_duplicate_source_ids = set()
    valid_duplicate_keepers = {}
    for index, row in enumerate(rows):
        row_id_positions.setdefault(row.get('row_id'), []).append(index)
        source_ids = row.get('source_candidate_ids') or []
        repeated = {
            candidate_id for candidate_id in source_ids
            if source_ids.count(candidate_id) > 1
            and candidate_id in candidates_by_id
        }
        if repeated:
            duplicate_issue_positions.add(index)
            invalid_duplicate_source_ids.update(repeated)
        for candidate_id in set(source_ids):
            if candidate_id in candidates_by_id:
                candidate_rows.setdefault(candidate_id, []).append(index)

    def source_id_set(row):
        return frozenset(row.get('source_candidate_ids') or [])

    def unique_row_position(row_id):
        positions = row_id_positions.get(row_id) or []
        return positions[0] if len(positions) == 1 else None

    for index, row in enumerate(rows):
        target_id = row.get('duplicate_of_row_id')
        if target_id is None:
            continue
        target_position = unique_row_position(target_id)
        target = (
            rows[target_position]
            if target_position is not None else None)
        valid_link = bool(
            row.get('disposition') == 'intentionally_excluded'
            and target is not None
            and target_position != index
            and target.get('disposition') != 'intentionally_excluded'
            and target.get('duplicate_of_row_id') is None
            and source_id_set(row)
            and source_id_set(row) == source_id_set(target)
        )
        if not valid_link:
            duplicate_issue_positions.add(index)
            invalid_duplicate_source_ids.update(
                candidate_id for candidate_id in source_id_set(row)
                if candidate_id in candidates_by_id)

    for candidate_id, positions in candidate_rows.items():
        if len(positions) <= 1:
            continue
        active_positions = [
            position for position in positions
            if rows[position].get('disposition') != 'intentionally_excluded'
        ]
        valid_group = len(active_positions) == 1
        keeper_position = active_positions[0] if valid_group else None
        if valid_group:
            keeper = rows[keeper_position]
            keeper_id = keeper.get('row_id')
            valid_group = bool(
                isinstance(keeper_id, str)
                and unique_row_position(keeper_id) == keeper_position
                and all(
                    position == keeper_position
                    or (
                        rows[position].get('disposition')
                        == 'intentionally_excluded'
                        and rows[position].get('duplicate_of_row_id')
                        == keeper_id
                        and source_id_set(rows[position])
                        == source_id_set(keeper)
                    )
                    for position in positions
                )
            )
        if valid_group:
            valid_duplicate_keepers[candidate_id] = keeper_position
            continue
        invalid_duplicate_source_ids.add(candidate_id)
        duplicate_issue_positions.update(positions)

    for position in sorted(duplicate_issue_positions):
        add_issue(
            'DUPLICATE_SOURCE_ROW', 'needs_review', 'coverage',
            row_id=rows[position].get('row_id'),
            field='source_candidate_ids')

    seen_row_ids = set()
    for row in rows:
        row_id = row.get('row_id')
        manual_fields = _trusted_row_review_metadata(
            row, allow_manual=allow_manual)
        row_manual_fields[row_id] = manual_fields
        row_codes.setdefault(row_id, [])
        if not isinstance(row_id, str) or not row_id.strip():
            add_issue('INVALID_ROW_ID', 'invalid', 'coverage',
                      row_id=row_id, field='row_id')
        if row_id in seen_row_ids:
            add_issue('DUPLICATE_ROW_ID', 'invalid', 'coverage',
                      row_id=row_id, field='row_id')
        seen_row_ids.add(row_id)
        raw_name = row.get('raw_name')
        if not isinstance(raw_name, str) or not raw_name.strip():
            add_issue('RAW_NAME_REQUIRED', 'invalid', 'coverage',
                      row_id=row_id, field='raw_name')
        mapping_manually_reviewed = bool(
            _STANDARD_MAPPING_FIELDS.intersection(manual_fields))
        if (row.get('disposition') == 'assigned'
                and not mapping_manually_reviewed
                and is_ambiguous_coverage_name(raw_name)):
            add_issue(
                'STANDARD_MAPPING_AMBIGUOUS', 'needs_review', 'coverage',
                row_id=row_id, field='standard_detail_name')
        elif (row.get('disposition') == 'assigned'
              and not mapping_manually_reviewed
              and _standard_mapping_contradicts_name(
                  raw_name, row.get('standard_detail_name'))):
            add_issue(
                'STANDARD_MAPPING_CONTRADICTION', 'needs_review', 'coverage',
                row_id=row_id, field='standard_detail_name')

        source_ids = row.get('source_candidate_ids') or []
        row_evidence_ids = set(row.get('evidence_line_ids') or [])
        for candidate_id in source_ids:
            if candidate_id not in candidates_by_id:
                add_issue('UNKNOWN_SOURCE_CANDIDATE', 'invalid', 'coverage',
                          row_id=row_id, field='source_candidate_ids')
                continue
            candidate_evidence_ids = set(
                candidates_by_id[candidate_id].get('evidence_line_ids') or [])
            if not row_evidence_ids.intersection(candidate_evidence_ids):
                add_issue(
                    'EVIDENCE_CANDIDATE_MISMATCH', 'no_evidence', 'coverage',
                    row_id=row_id, field='evidence_line_ids')

        texts = _line_texts(row.get('evidence_line_ids'), lines_by_id)
        manual_without_evidence = bool(
            allow_manual_without_evidence
            and _MANUAL_COVERAGE_FIELD_SET.issubset(manual_fields))
        if texts is None and not manual_without_evidence:
            add_issue('EVIDENCE_LINE_NOT_FOUND', 'no_evidence',
                      'coverage', row_id=row_id,
                      field='evidence_line_ids')
        elif texts is not None:
            if ('raw_name' not in manual_fields
                    and raw_name
                    and not _text_in_evidence(raw_name, texts)):
                add_issue('RAW_NAME_EVIDENCE_MISMATCH', 'no_evidence',
                          'coverage', row_id=row_id, field='raw_name')
            amount = row.get('assurance_amount')
            premium = row.get('premium')
            money_support, role_ambiguous = _row_money_evidence(
                amount, premium, texts)
            if ('assurance_amount' not in manual_fields
                    and amount is not None
                    and not money_support['assurance']):
                add_issue('AMOUNT_EVIDENCE_MISMATCH', 'no_evidence',
                          'coverage', row_id=row_id,
                          field='assurance_amount')
            if ('premium' not in manual_fields
                    and premium is not None
                    and not money_support['premium']):
                add_issue('PREMIUM_EVIDENCE_MISMATCH', 'no_evidence',
                          'coverage', row_id=row_id, field='premium')
            if (role_ambiguous
                    and 'assurance_amount' not in manual_fields):
                add_issue('AMOUNT_ROLE_AMBIGUOUS', 'no_evidence',
                          'coverage', row_id=row_id,
                          field='assurance_amount')

        if (row.get('disposition') == 'assigned'
                and row.get('assurance_amount') is None):
            add_issue('ASSURANCE_AMOUNT_REQUIRED', 'invalid', 'coverage',
                      row_id=row_id, field='assurance_amount')
        if (row.get('assurance_amount') is not None
                and row['assurance_amount'] < 0):
            add_issue('NEGATIVE_AMOUNT', 'invalid', 'coverage',
                      row_id=row_id, field='assurance_amount')
        if row.get('premium') is not None and row['premium'] < 0:
            add_issue('NEGATIVE_PREMIUM', 'invalid', 'coverage',
                      row_id=row_id, field='premium')
        for period_field in (
                'renewal_period', 'payment_period', 'warranty_period'):
            value = row.get(period_field)
            if value is not None and value <= 0:
                add_issue('INVALID_PERIOD', 'invalid', 'coverage',
                          row_id=row_id, field=period_field)
        for value_field, unit_field in (
                ('payment_period', 'payment_period_unit'),
                ('warranty_period', 'warranty_period_unit')):
            period_value = row.get(value_field)
            period_unit = row.get(unit_field)
            if period_value is not None and period_unit is None:
                add_issue('PERIOD_UNIT_REQUIRED', 'invalid', 'coverage',
                          row_id=row_id, field=unit_field)
            if (period_value is None
                    and period_unit is not None
                    and period_unit != 'lifetime'):
                add_issue('PERIOD_VALUE_REQUIRED', 'invalid', 'coverage',
                          row_id=row_id, field=value_field)
            if period_value is not None and period_unit == 'lifetime':
                add_issue(
                    'LIFETIME_PERIOD_HAS_VALUE', 'invalid', 'coverage',
                    row_id=row_id, field=value_field)
        if (row.get('is_renewal') is True
                and not row.get('renewal_period')):
            add_issue(
                'INVALID_RENEWAL_PAYMENT_COMBINATION', 'invalid', 'coverage',
                row_id=row_id, field='renewal_period')
        if (row.get('is_renewal') is True
                and row.get('payment_period_unit') == 'age'):
            add_issue(
                'INVALID_RENEWAL_PAYMENT_COMBINATION', 'invalid', 'coverage',
                row_id=row_id, field='payment_period_unit')
        if (row.get('is_renewal') is False
                and row.get('renewal_period') is not None):
            add_issue(
                'INVALID_RENEWAL_PAYMENT_COMBINATION', 'invalid', 'coverage',
                row_id=row_id, field='renewal_period')
        if row.get('is_renewal') is None:
            add_issue('RENEWAL_FLAG_REQUIRED', 'invalid', 'coverage',
                      row_id=row_id, field='is_renewal')
        if row.get('disposition') == 'assigned':
            payment_unit = row.get('payment_period_unit')
            warranty_unit = row.get('warranty_period_unit')
            if payment_unit not in {'years', 'age', 'lifetime'}:
                add_issue('PERIOD_UNIT_REQUIRED', 'invalid', 'coverage',
                          row_id=row_id, field='payment_period_unit')
            if warranty_unit not in {'years', 'age', 'lifetime'}:
                add_issue('PERIOD_UNIT_REQUIRED', 'invalid', 'coverage',
                          row_id=row_id, field='warranty_period_unit')
            if (row.get('premium') is not None
                    and row.get('is_renewal') is False
                    and payment_unit != 'lifetime'
                    and row.get('payment_period') is None):
                add_issue('PERIOD_VALUE_REQUIRED', 'invalid', 'coverage',
                          row_id=row_id, field='payment_period')
            if (row.get('premium') is not None
                    and row.get('is_renewal') is False
                    and payment_unit == 'age'
                    and contract is None):
                add_issue(
                    'CONTRACT_DATE_REQUIRED_FOR_AGE_PERIOD',
                    'invalid', 'coverage', row_id=row_id,
                    field='payment_period')
        payment_period = row.get('payment_period')
        warranty_period = row.get('warranty_period')
        payment_unit = row.get('payment_period_unit')
        warranty_unit = row.get('warranty_period_unit')
        if (type(payment_period) is int
                and type(warranty_period) is int
                and payment_unit == warranty_unit
                and payment_unit in {'years', 'age'}
                and payment_period > warranty_period):
            add_issue(
                'PAYMENT_PERIOD_EXCEEDS_WARRANTY', 'invalid', 'coverage',
                row_id=row_id, field='payment_period')
        if row.get('disposition') == 'assigned' and not all((
                row.get('standard_category'),
                row.get('standard_subcategory'),
                row.get('standard_detail_name'))):
            add_issue('STANDARD_MAPPING_REQUIRED', 'unmatched', 'coverage',
                      row_id=row_id, field='standard_detail_name')
        elif (row.get('disposition') == 'assigned'
              and (
                  row.get('standard_category'),
                  row.get('standard_subcategory'),
                  row.get('standard_detail_name'),
              ) not in STANDARD_COVERAGE_PATHS):
            add_issue('STANDARD_MAPPING_INVALID', 'unmatched', 'coverage',
                      row_id=row_id, field='standard_detail_name')
        if (row.get('disposition') == 'intentionally_excluded'
                and not row.get('exclusion_reason')):
            add_issue('EXCLUSION_REASON_REQUIRED', 'needs_review',
                      'coverage', row_id=row_id, field='exclusion_reason')

    next_row = len(rows) + 1
    for candidate in normalized_candidates:
        candidate_id = candidate['candidate_id']
        if candidate_id in candidate_rows:
            continue
        row_id = f'unmatched-{next_row:05d}'
        next_row += 1
        row = {
            'row_id': row_id,
            'raw_name': candidate['text_masked'],
            'assurance_amount': None,
            'premium': None,
            'is_renewal': None,
            'renewal_period': None,
            'payment_period': None,
            'payment_period_unit': None,
            'warranty_period': None,
            'warranty_period_unit': None,
            'disposition': 'unmatched',
            'standard_category': None,
            'standard_subcategory': None,
            'standard_detail_name': None,
            'exclusion_reason': None,
            'source_candidate_ids': [candidate_id],
            'evidence_line_ids': list(candidate['evidence_line_ids']),
        }
        rows.append(row)
        row_codes[row_id] = []
        add_issue('CLAUDE_OMITTED_CANDIDATE', 'unmatched', 'coverage',
                  row_id=row_id, field='source_candidate_ids')

    approved_excluded_row_ids = {
        row.get('row_id') for row in rows
        if _is_server_approved_exclusion(
            row, row_manual_fields.get(row.get('row_id'), ()))
    }
    if approved_excluded_row_ids:
        issues = [
            issue for issue in issues
            if (issue.scope != 'coverage'
                or issue.row_id not in approved_excluded_row_ids
                or issue.code in _EXCLUDED_ROW_INTEGRITY_CODES)
        ]
        for row_id in approved_excluded_row_ids:
            row_codes[row_id] = [
                code for code in row_codes.get(row_id, [])
                if code in _EXCLUDED_ROW_INTEGRITY_CODES
            ]

    comparable_rows = [
        row for row in rows if row.get('disposition') == 'assigned']
    comparable_premiums = [row.get('premium') for row in comparable_rows]
    has_known_premium = any(
        type(premium) is int for premium in comparable_premiums)
    has_unknown_premium = any(
        type(premium) is not int for premium in comparable_premiums)
    monthly_premium_manually_confirmed = bool(
        allow_manual
        and isinstance(policy.get('monthly_premium'), dict)
        and policy['monthly_premium'].get('state') == 'manual'
        and policy['monthly_premium'].get('planner_confirmed') is True
    )
    if not monthly_premium_manually_confirmed:
        if type(monthly_premium) is int and comparable_rows:
            if has_unknown_premium:
                add_issue(
                    'PREMIUM_SUM_INCOMPLETE', 'needs_review', 'policy',
                    field='monthly_premium')
            elif (sum(row['premium'] for row in comparable_rows)
                  != monthly_premium):
                add_issue(
                    'PREMIUM_SUM_MISMATCH', 'needs_review', 'policy',
                    field='monthly_premium')
        elif has_known_premium and has_unknown_premium:
            add_issue('PREMIUM_SUM_INCOMPLETE', 'needs_review', 'policy',
                      field='monthly_premium')

    for field, evidence in policy.items():
        if not isinstance(evidence, dict):
            continue
        codes = list(dict.fromkeys(policy_codes.get(field, [])))
        if any(code in _INVALID_CODES for code in codes):
            state = 'invalid'
        elif any(code in _NO_EVIDENCE_CODES for code in codes):
            state = 'no_evidence'
        elif codes:
            state = 'needs_review'
        elif allow_manual and evidence.get('state') == 'manual':
            state = 'manual'
        else:
            state = 'review_ready'
        evidence['state'] = state
        evidence['review_reason_codes'] = codes

    for row in rows:
        codes = list(dict.fromkeys(row_codes.get(row.get('row_id'), [])))
        row['state'] = _row_state(
            row, codes,
            manual_fields=row_manual_fields.get(row.get('row_id'), ()))
        row['review_reason_codes'] = codes

    candidate_bucket = {}
    rows_by_candidate = {}
    for row in rows:
        for candidate_id in row.get('source_candidate_ids') or []:
            if candidate_id in candidates_by_id:
                rows_by_candidate.setdefault(candidate_id, row)
    for candidate_id in candidates_by_id:
        if candidate_id in invalid_duplicate_source_ids:
            candidate_bucket[candidate_id] = 'unmatched'
            continue
        keeper_position = valid_duplicate_keepers.get(candidate_id)
        source_row = (
            rows[keeper_position]
            if keeper_position is not None
            else rows_by_candidate[candidate_id]
        )
        disposition = source_row.get('disposition')
        if disposition not in {
                'assigned', 'unmatched', 'intentionally_excluded'}:
            disposition = 'unmatched'
        candidate_bucket[candidate_id] = disposition

    counts = {
        disposition: sum(
            1 for value in candidate_bucket.values()
            if value == disposition)
        for disposition in (
            'assigned', 'unmatched', 'intentionally_excluded')
    }
    resolved_states = {'review_ready'}
    if allow_manual:
        resolved_states.add('manual')
    unresolved_count = sum(
        row['state'] not in resolved_states for row in rows)
    unresolved_count += sum(
        evidence.get('state') not in resolved_states
        for evidence in policy.values() if isinstance(evidence, dict))
    summary = {
        'detected_candidates': len(candidates_by_id),
        **counts,
        'unresolved_count': unresolved_count,
        'issue_count': len(issues),
    }
    payload['policy'] = policy
    payload['coverage_rows'] = rows
    payload['validation'] = {
        'unresolved_count': unresolved_count,
        'issues': [asdict(issue) for issue in issues],
    }
    return ValidationResult(
        draft=payload,
        issues=tuple(issues),
        summary=summary,
    )
