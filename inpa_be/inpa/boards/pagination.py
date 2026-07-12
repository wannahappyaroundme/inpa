"""게시판 커서 기반 페이지네이션 (dev/17 §8.1).

피드 목록: 커서(base64 인코딩) 기반 무한스크롤.
최신순 정렬(-created_at), page_size 기본 20.

응답 구조:
  { "next_cursor": "base64string|null", "results": [...] }

내부 커서: base64(pk) — Post.id(BigAutoField) 기준 내림차순.
"""
import base64

from rest_framework.pagination import CursorPagination, PageNumberPagination
from rest_framework.response import Response


class BlogPostPagination(PageNumberPagination):
    """인파 노트 공개 목록 페이지네이션 — page_size 12.

    응답: {count, next, previous, results} (DRF PageNumberPagination 기본형).
    """
    page_size = 12
    page_size_query_param = 'page_size'
    max_page_size = 50


class PostCursorPagination(CursorPagination):
    """커서 기반 페이지네이션 — 피드 무한스크롤 (dev/17 §4.1).

    ordering은 최신순(-created_at) 기본. 인기순(like_count)은 추후 ordering 파라미터로.
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    ordering = '-created_at'
    cursor_query_param = 'cursor'

    def get_paginated_response(self, data):
        return Response({
            'next_cursor': self.get_next_link(),
            'previous_cursor': self.get_previous_link(),
            'results': data,
        })

    def get_paginated_response_schema(self, schema):
        return {
            'type': 'object',
            'properties': {
                'next_cursor': {'type': 'string', 'nullable': True},
                'previous_cursor': {'type': 'string', 'nullable': True},
                'results': schema,
            },
        }
