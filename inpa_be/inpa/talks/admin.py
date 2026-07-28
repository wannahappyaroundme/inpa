from django.contrib import admin

from .models import PersonalTalkTemplate, TalkTemplatePreference


@admin.register(PersonalTalkTemplate)
class PersonalTalkTemplateAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'owner',
        'title',
        'category',
        'channel',
        'sort_order',
        'is_active',
        'is_deleted',
        'updated_at',
    )
    list_filter = ('channel', 'is_active', 'is_deleted', 'category')
    search_fields = ('owner__email', 'title', 'source_key')
    raw_id_fields = ('owner',)


@admin.register(TalkTemplatePreference)
class TalkTemplatePreferenceAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'owner',
        'source_key',
        'is_hidden',
        'updated_at',
    )
    list_filter = ('is_hidden',)
    search_fields = ('owner__email', 'source_key')
    raw_id_fields = ('owner',)
