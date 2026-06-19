"""멀티테넌시 단일 강제점 — 소유자 전용 엔티티 공통.

dev/02 §0 가시성 매트릭스: '공유' 5개 군을 제외한 모든 것은 owner 스코프.
ViewSet에 이 믹스인을 붙이면 (1) 본인 데이터만 조회 (2) 생성 시 owner 자동 주입.
관리자(profile.is_admin)는 전체 조회 우회(운영 조회).
"""


class OwnedQuerySetMixin:
    owner_field = 'owner'

    def _is_admin(self):
        profile = getattr(self.request.user, 'profile', None)
        return bool(getattr(profile, 'is_admin', False))

    def get_queryset(self):
        qs = super().get_queryset()
        if self._is_admin():
            return qs
        return qs.filter(**{self.owner_field: self.request.user})

    def perform_create(self, serializer):
        serializer.save(**{self.owner_field: self.request.user})
