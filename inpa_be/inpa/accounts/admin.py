from django.contrib import admin

from .models import Profile, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('id', 'email', 'is_active', 'is_staff', 'date_joined')
    search_fields = ('email',)
    ordering = ('-date_joined',)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'agent_type', 'affiliation', 'is_admin', 'is_dormant',
                    'onboarding_completed_at', 'ref_code')
    search_fields = ('user__email', 'ref_code', 'affiliation')
    list_filter = ('agent_type', 'is_admin', 'is_dormant')
