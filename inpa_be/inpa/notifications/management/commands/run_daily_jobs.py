"""일일 리마인더 알림 생성 커맨드 — 수동/Render Shell 용 (spec 2026-07-04 §1).

HTTP 트리거(POST /api/v1/jobs/run-daily/)와 동일한 notifications/jobs.py::run_daily_jobs
를 호출한다. KST 당일 멱등이라 같은 날 여러 번 실행해도 중복 알림이 생기지 않는다.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from inpa.notifications.jobs import run_daily_jobs


class Command(BaseCommand):
    help = '일일 리마인더 알림 생성 (생일/만기/상담/할일/미열람 공유) — KST 당일 멱등'

    def handle(self, *args, **options):
        result = run_daily_jobs()
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        if result['errors']:
            raise CommandError(f"일부 생산자 실패: {', '.join(result['errors'])}")
        self.stdout.write(self.style.SUCCESS(
            f"완료: {result['date']} 신규 알림 {result['total_created']}건"))
