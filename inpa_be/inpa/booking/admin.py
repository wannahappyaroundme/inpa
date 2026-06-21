from django.contrib import admin

from .models import Meeting, MeetingSlot


@admin.register(MeetingSlot)
class MeetingSlotAdmin(admin.ModelAdmin):
    list_display = ('id', 'owner', 'start_at', 'duration_min', 'status')
    list_filter = ('status',)
    raw_id_fields = ('owner',)


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ('id', 'owner', 'customer', 'start_at', 'method', 'status')
    list_filter = ('status', 'method')
    raw_id_fields = ('owner', 'customer', 'slot')
