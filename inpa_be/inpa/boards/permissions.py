"""게시판 도메인 권한 클래스 (dev/17 §9).

IsAuthorOrAdmin  — Post/Comment 수정·삭제 (작성자 또는 관리자)
IsAdminOnly      — Notice/Faq 쓰기, InquiryReply 작성 (관리자 전용)

core/permissions.py의 IsAdmin과 목적은 같으나 게시판 도메인 명확성을 위해 분리.
core.permissions._is_admin 헬퍼 재사용.
"""
from rest_framework.permissions import BasePermission, SAFE_METHODS

from inpa.core.permissions import _is_admin


class IsAuthorOrAdmin(BasePermission):
    """공유 테이블(Post/Comment) 수정·삭제 권한.

    SAFE_METHODS(GET/HEAD/OPTIONS): 인증된 설계사 전원 허용 (has_permission 레벨).
    unsafe(POST/PATCH/DELETE): 객체 단위 — 작성자(obj.author) 또는 관리자.

    주의: is_hidden=True 글은 get_object 레벨에서 관리자만 노출.
    """
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return obj.author == request.user or _is_admin(request.user)


class IsAdminOnly(BasePermission):
    """Notice·Faq 쓰기 / Report 처리 / InquiryReply 작성·수정 — 관리자 전용."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and _is_admin(request.user)
        )
