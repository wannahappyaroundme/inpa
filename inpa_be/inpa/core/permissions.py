"""공통 권한 클래스 — dev/02 §0 가시성 매트릭스 강제."""
from rest_framework.permissions import BasePermission


def _is_admin(user):
    return bool(getattr(getattr(user, 'profile', None), 'is_admin', False))


class IsOwner(BasePermission):
    """객체 소유자 본인 또는 관리자만 접근."""

    def has_object_permission(self, request, view, obj):
        if _is_admin(request.user):
            return True
        owner_field = getattr(view, 'owner_field', 'owner')
        return getattr(obj, owner_field, None) == request.user


class IsAdmin(BasePermission):
    """관리자 콘솔 전용."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and _is_admin(request.user))


class IsEmailVerified(BasePermission):
    """이메일 인증(=User.is_active) 완료 사용자만. 미인증 시 403 EMAIL_NOT_VERIFIED."""
    message = 'EMAIL_NOT_VERIFIED'

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_active)
