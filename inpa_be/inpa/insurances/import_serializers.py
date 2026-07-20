from rest_framework import serializers

from .import_contract import (
    safe_confirmation_requirements,
    safe_import_target,
    safe_source_review,
)
from .import_pdf import MAX_FILE_BYTES
from .models import InsuranceExtractionJob
from .serializers import ManualCoverageWriteSerializer


_ALLOWED_PDF_CONTENT_TYPES = frozenset({
    '',
    'application/pdf',
    'application/octet-stream',
})


class InsuranceImportCreateSerializer(serializers.Serializer):
    file = serializers.FileField()
    intent = serializers.ChoiceField(
        choices=InsuranceExtractionJob.INTENT_CHOICES, default='add')
    portfolio_type = serializers.ChoiceField(choices=(1, 2), default=1)
    target_insurance_id = serializers.IntegerField(
        required=False, allow_null=True, min_value=1)
    duplicate_resolution_token = serializers.CharField(
        required=False, allow_blank=False, max_length=2048,
        trim_whitespace=False)

    def validate_file(self, uploaded_file):
        if uploaded_file.size > MAX_FILE_BYTES:
            raise serializers.ValidationError(
                '50MB 이하의 전자 PDF를 선택해 주세요.',
                code='FILE_TOO_LARGE')
        content_type = str(
            getattr(uploaded_file, 'content_type', '') or '').strip().lower()
        if content_type not in _ALLOWED_PDF_CONTENT_TYPES:
            raise serializers.ValidationError(
                '전자 PDF 파일을 선택해 주세요.',
                code='INVALID_PDF_MIME')
        try:
            uploaded_file.seek(0)
            magic = uploaded_file.read(5)
        except (AttributeError, OSError, ValueError, TypeError):
            magic = b''
        finally:
            try:
                uploaded_file.seek(0)
            except (AttributeError, OSError, ValueError, TypeError):
                pass
        if magic != b'%PDF-':
            raise serializers.ValidationError(
                '전자 PDF 파일을 선택해 주세요.',
                code='INVALID_PDF')
        return uploaded_file

    def validate(self, attrs):
        intent = attrs.get('intent', 'add')
        target_id = attrs.get('target_insurance_id')
        if intent == 'replace' and target_id is None:
            raise serializers.ValidationError({
                'target_insurance_id': '교체할 보험을 선택해 주세요.'})
        if intent == 'add' and target_id is not None:
            raise serializers.ValidationError({
                'target_insurance_id': '추가 등록에는 교체할 보험이 필요하지 않아요.'})
        return attrs


class InsuranceImportJobSerializer(serializers.ModelSerializer):
    job_id = serializers.UUIDField(source='id', read_only=True)
    customer_id = serializers.IntegerField(read_only=True)
    source_review = serializers.SerializerMethodField()
    target_insurance_id = serializers.SerializerMethodField()
    target_insurance_version = serializers.SerializerMethodField()
    confirmation_requirements = serializers.SerializerMethodField()

    def _source_review(self, obj):
        return safe_source_review(
            obj.validation_summary,
            expected_page_count=obj.page_count,
        )

    def get_source_review(self, obj):
        return self._source_review(obj)

    def get_target_insurance_id(self, obj):
        return safe_import_target(obj)['target_insurance_id']

    def get_target_insurance_version(self, obj):
        return safe_import_target(obj)['target_insurance_version']

    def get_confirmation_requirements(self, obj):
        return safe_confirmation_requirements(self._source_review(obj))

    class Meta:
        model = InsuranceExtractionJob
        fields = (
            'job_id', 'customer_id', 'status', 'intent', 'portfolio_type',
            'safe_display_name', 'page_count', 'draft_version', 'error_code',
            'target_insurance_id', 'target_insurance_version',
            'source_review', 'confirmation_requirements',
            'created_at', 'started_at', 'completed_at',
        )
        read_only_fields = fields


class InsuranceImportCreatedSerializer(serializers.ModelSerializer):
    job_id = serializers.UUIDField(source='id', read_only=True)

    class Meta:
        model = InsuranceExtractionJob
        fields = ('job_id', 'status')
        read_only_fields = fields


class _StrictFieldsSerializer(serializers.Serializer):
    """Reject client attempts to write server-owned draft fields."""

    def to_internal_value(self, data):
        if hasattr(data, 'keys'):
            unknown = set(data.keys()) - set(self.fields)
            if unknown:
                raise serializers.ValidationError({
                    field: '이 항목은 수정할 수 없어요.'
                    for field in sorted(unknown)
                })
        return super().to_internal_value(data)


class InsurancePolicyChangeSerializer(_StrictFieldsSerializer):
    EDITABLE_FIELDS = (
        'carrier_name', 'company_code', 'insurance_type', 'product_name',
        'contract_date', 'expiry_date', 'monthly_premium',
    )

    field = serializers.ChoiceField(choices=EDITABLE_FIELDS)
    value = serializers.JSONField(allow_null=True)

    def validate(self, attrs):
        field = attrs['field']
        value = attrs['value']
        if value is None:
            return attrs
        if field in {'carrier_name', 'product_name'}:
            if not isinstance(value, str) or not value.strip():
                raise serializers.ValidationError({
                    'value': '확인한 내용을 입력해 주세요.'})
            attrs['value'] = value.strip()
            if len(attrs['value']) > 120:
                raise serializers.ValidationError({
                    'value': '120자 이하로 입력해 주세요.'})
        elif field == 'insurance_type':
            if value not in {'life', 'loss'}:
                raise serializers.ValidationError({
                    'value': '보험 종류를 다시 선택해 주세요.'})
        elif field in {'company_code', 'monthly_premium'}:
            if type(value) is not int or value < 0:
                raise serializers.ValidationError({
                    'value': '0 이상의 숫자를 입력해 주세요.'})
        elif field in {'contract_date', 'expiry_date'}:
            if (not isinstance(value, str)
                    or len(value) != 10
                    or value[4] != '-'
                    or value[7] != '-'):
                raise serializers.ValidationError({
                    'value': '날짜를 다시 선택해 주세요.'})
        return attrs


class InsuranceCoverageActionSerializer(_StrictFieldsSerializer):
    EDITABLE_FIELDS = (
        'raw_name', 'assurance_amount', 'premium', 'is_renewal',
        'renewal_period', 'payment_period', 'payment_period_unit',
        'warranty_period', 'warranty_period_unit',
    )
    ADD_FIELDS = (
        'raw_name', 'assurance_amount', 'premium', 'is_renewal',
        'renewal_period', 'payment_period', 'payment_period_unit',
        'warranty_period', 'warranty_period_unit', 'standard_category',
        'standard_subcategory', 'standard_detail_name',
    )
    ACTIONS = (
        'add', 'edit', 'assign', 'exclude', 'duplicate', 'undo_exclude',
        'confirm')
    PERIOD_UNITS = {'years', 'age', 'lifetime'}

    row_id = serializers.CharField(max_length=80, required=False)
    action = serializers.ChoiceField(choices=ACTIONS)
    raw_name = serializers.CharField(max_length=200, required=False)
    assurance_amount = serializers.IntegerField(
        min_value=0, allow_null=True, required=False)
    premium = serializers.IntegerField(
        min_value=0, allow_null=True, required=False)
    is_renewal = serializers.BooleanField(allow_null=True, required=False)
    renewal_period = serializers.IntegerField(
        min_value=1, allow_null=True, required=False)
    payment_period = serializers.IntegerField(
        min_value=1, allow_null=True, required=False)
    payment_period_unit = serializers.ChoiceField(
        choices=PERIOD_UNITS, allow_null=True, required=False)
    warranty_period = serializers.IntegerField(
        min_value=1, allow_null=True, required=False)
    warranty_period_unit = serializers.ChoiceField(
        choices=PERIOD_UNITS, allow_null=True, required=False)
    field = serializers.ChoiceField(
        choices=EDITABLE_FIELDS, required=False)
    value = serializers.JSONField(required=False, allow_null=True)
    standard_category = serializers.CharField(
        max_length=80, required=False)
    standard_subcategory = serializers.CharField(
        max_length=80, required=False)
    standard_detail_name = serializers.CharField(
        max_length=80, required=False)
    reason = serializers.CharField(
        max_length=300, required=False, trim_whitespace=True)
    target_row_id = serializers.CharField(max_length=80, required=False)

    def _validate_edit_value(self, field, value):
        if value is None:
            return
        if field == 'raw_name':
            if not isinstance(value, str) or not value.strip():
                raise serializers.ValidationError({
                    'value': '담보 이름을 입력해 주세요.'})
            if len(value.strip()) > 200:
                raise serializers.ValidationError({
                    'value': '200자 이하로 입력해 주세요.'})
            return
        if field in {'assurance_amount', 'premium'}:
            valid = type(value) is int and value >= 0
        elif field in {
                'renewal_period', 'payment_period', 'warranty_period'}:
            valid = type(value) is int and value > 0
        elif field == 'is_renewal':
            valid = type(value) is bool
        else:
            valid = value in self.PERIOD_UNITS
        if not valid:
            raise serializers.ValidationError({
                'value': '입력한 값을 다시 확인해 주세요.'})

    def validate(self, attrs):
        action = attrs['action']
        if action == 'add':
            if 'row_id' in attrs:
                raise serializers.ValidationError({
                    'row_id': '새 담보의 위치는 서버에서 정해요.'})
            unexpected = (
                set(attrs) - {'action'} - set(self.ADD_FIELDS))
            if unexpected:
                raise serializers.ValidationError(
                    '새 담보에 필요한 항목만 보내 주세요.')
            manual = ManualCoverageWriteSerializer(data={
                'data_version': 1,
                **{
                    field: attrs[field]
                    for field in self.ADD_FIELDS
                    if field in attrs
                },
            })
            manual.is_valid(raise_exception=True)
            validated = dict(manual.validated_data)
            validated.pop('data_version')
            return {'action': action, **validated}
        if 'row_id' not in attrs:
            raise serializers.ValidationError({
                'row_id': '수정할 담보를 다시 선택해 주세요.'})
        action_fields = {
            'edit': {'field', 'value'},
            'assign': {
                'standard_category', 'standard_subcategory',
                'standard_detail_name'},
            'exclude': {'reason'},
            'duplicate': {'reason', 'target_row_id'},
            'undo_exclude': set(),
            'confirm': set(),
        }
        supplied = set(attrs) - {'row_id', 'action'}
        required = action_fields[action]
        if supplied != required:
            raise serializers.ValidationError(
                '선택한 수정 방식에 필요한 항목만 보내 주세요.')
        if action == 'edit':
            self._validate_edit_value(attrs['field'], attrs['value'])
            if (attrs['field'] == 'raw_name'
                    and isinstance(attrs['value'], str)):
                attrs['value'] = attrs['value'].strip()
        if action in {'exclude', 'duplicate'} and not attrs['reason'].strip():
            raise serializers.ValidationError({
                'reason': '분석에서 제외하는 이유를 입력해 주세요.'})
        return attrs


class InsuranceImportDraftPatchSerializer(_StrictFieldsSerializer):
    draft_version = serializers.IntegerField(min_value=1)
    policy_changes = InsurancePolicyChangeSerializer(
        many=True, required=False, max_length=7)
    coverage_actions = InsuranceCoverageActionSerializer(
        many=True, required=False, max_length=2000)

    def validate(self, attrs):
        policy_changes = attrs.get('policy_changes') or []
        coverage_actions = attrs.get('coverage_actions') or []
        if not policy_changes and not coverage_actions:
            raise serializers.ValidationError(
                '수정할 항목을 선택해 주세요.')
        policy_fields = [item['field'] for item in policy_changes]
        if len(policy_fields) != len(set(policy_fields)):
            raise serializers.ValidationError({
                'policy_changes': '한 항목은 한 번씩 수정해 주세요.'})
        action_keys = [
            (item['row_id'], item['action'], item.get('field'))
            for item in coverage_actions
            if item['action'] != 'add'
        ]
        if len(action_keys) != len(set(action_keys)):
            raise serializers.ValidationError({
                'coverage_actions': '같은 담보 항목은 한 번씩 수정해 주세요.'})
        disposition_rows = [
            item['row_id'] for item in coverage_actions
            if item['action'] not in {'add', 'edit'}
        ]
        if len(disposition_rows) != len(set(disposition_rows)):
            raise serializers.ValidationError({
                'coverage_actions': '담보 위치나 제외 상태는 한 번씩 바꿔 주세요.'})
        return attrs


class InsuranceImportCancelSerializer(_StrictFieldsSerializer):
    pass


class InsuranceImportConfirmSerializer(_StrictFieldsSerializer):
    draft_version = serializers.IntegerField(min_value=1)
    target_insurance_version = serializers.IntegerField(
        min_value=1, required=False, allow_null=True)
    planner_confirmed_source_match = serializers.BooleanField()
    planner_confirmed_unread_pages = serializers.BooleanField(
        required=False, default=False)
