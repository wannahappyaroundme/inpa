from collections.abc import Mapping

from rest_framework import serializers

from .models import PersonalTalkTemplate, TalkTemplatePreference


class PersonalTalkTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PersonalTalkTemplate
        fields = (
            'id',
            'owner',
            'source_key',
            'title',
            'body',
            'category',
            'channel',
            'sort_order',
            'is_active',
            'is_deleted',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'owner',
            'is_deleted',
            'created_at',
            'updated_at',
        )
        extra_kwargs = {
            'body': {'trim_whitespace': False},
        }

    def validate_source_key(self, value):
        if value is None:
            return None
        return value.strip() or None

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('제목을 입력해 주세요.')
        return value

    def validate_body(self, value):
        if not value.strip():
            raise serializers.ValidationError('본문을 입력해 주세요.')
        return value

    def validate_category(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('분류를 입력해 주세요.')
        return value


class TalkTemplatePreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = TalkTemplatePreference
        fields = ('source_key', 'is_hidden')

    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            raise serializers.ValidationError(
                {'non_field_errors': ['JSON 객체를 보내 주세요.']}
            )
        if not isinstance(data.get('is_hidden'), bool):
            raise serializers.ValidationError(
                {'is_hidden': 'true 또는 false 값을 보내 주세요.'}
            )
        return super().to_internal_value(data)

    def validate_source_key(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('기본 화법 키를 입력해 주세요.')
        return value
