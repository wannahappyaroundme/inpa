"""일일 배치 트리거 엔드포인트 — POST /api/v1/jobs/run-daily/ (spec 2026-07-04 §1).

호출자 = GitHub Actions cron(.github/workflows/daily-jobs.yml) 또는 수동 curl.
인증 = 헤더 X-JOB-TOKEN 을 env JOB_RUNNER_TOKEN 과 상수시간 비교(hmac.compare_digest).

★ fail-closed: env JOB_RUNNER_TOKEN 미설정 → 404 (엔드포인트 존재 자체 은폐).
   토큰 불일치/누락 → 403. 성공 → 200 + 생산자별 counts JSON.
★ ScopedRateThrottle('job_runner') — 토큰 무차별 대입/재실행 폭탄 방어
   (잡 자체는 KST 당일 멱등이라 재실행돼도 중복 알림 0).
"""
import hmac

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .jobs import run_daily_jobs


class RunDailyJobsView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # 토큰 헤더 전용 — 세션/DRF 토큰 인증 미사용
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'job_runner'

    def post(self, request):
        expected = getattr(settings, 'JOB_RUNNER_TOKEN', '') or ''
        if not expected:
            # env 미설정 = 기능 자체 없음(존재 은폐) — spec §1 fail-closed
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        provided = request.headers.get('X-JOB-TOKEN', '') or ''
        if not hmac.compare_digest(provided.encode(), expected.encode()):
            return Response({'detail': '토큰이 올바르지 않습니다.'},
                            status=status.HTTP_403_FORBIDDEN)
        result = run_daily_jobs()
        # 부분 실패 → 500 (GitHub Actions 가 재시도하도록; 멱등이라 재실행 안전)
        code = status.HTTP_200_OK if not result['errors'] else status.HTTP_500_INTERNAL_SERVER_ERROR
        return Response(result, status=code)
