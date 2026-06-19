"""판촉물 Django Admin 등록."""
from django.contrib import admin

from .models import (
    PromotionOrder,
    PromotionOrderStatusLog,
    PromotionSample,
    PromotionSampleImage,
)


class PromotionSampleImageInline(admin.TabularInline):
    model = PromotionSampleImage
    extra = 1
    fields = ['image_url', 'is_primary', 'sort_order']


@admin.register(PromotionSample)
class PromotionSampleAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'is_available', 'sort_order', 'created_at']
    list_filter = ['category', 'is_available']
    search_fields = ['name']
    inlines = [PromotionSampleImageInline]
    ordering = ['sort_order', '-created_at']


class PromotionOrderStatusLogInline(admin.TabularInline):
    model = PromotionOrderStatusLog
    extra = 0
    readonly_fields = ['to_status', 'changed_by', 'changed_at', 'note']
    can_delete = False  # append-only


@admin.register(PromotionOrder)
class PromotionOrderAdmin(admin.ModelAdmin):
    list_display = ['pk', 'owner', 'sample', 'status', 'created_at', 'updated_at']
    list_filter = ['status']
    search_fields = ['owner__email', 'sample__name']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [PromotionOrderStatusLogInline]
    ordering = ['-created_at']

    fieldsets = [
        ('주문 기본', {'fields': ['owner', 'sample', 'form_response', 'status']}),
        ('관리자 처리', {'fields': ['admin_note', 'tracking_number', 'carrier']}),
        ('타임스탬프', {'fields': ['created_at', 'updated_at']}),
    ]
