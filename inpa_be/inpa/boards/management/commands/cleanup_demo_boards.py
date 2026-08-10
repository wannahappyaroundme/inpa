"""공지와 FAQ에 남은 [DEMO] 행만 좁게 정리한다."""

from django.core.management.base import BaseCommand
from django.db import transaction

from inpa.boards.models import Faq, Notice


class Command(BaseCommand):
    help = '제목이 [DEMO]로 시작하는 공지와 FAQ만 정리합니다(기본 dry-run).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='확인된 [DEMO] 공지와 FAQ를 실제로 삭제합니다.',
        )

    def handle(self, *args, **options):
        notice_rows = Notice.objects.filter(title__startswith='[DEMO]')
        faq_rows = Faq.objects.filter(question__startswith='[DEMO]')
        notice_count = notice_rows.count()
        faq_count = faq_rows.count()

        if not options['apply']:
            self.stdout.write(
                f'[dry-run] 정리 대상: 공지 {notice_count}건, FAQ {faq_count}건. '
                '--apply를 붙이면 이 두 종류만 삭제합니다.'
            )
            return

        with transaction.atomic():
            notice_rows.select_for_update().delete()
            faq_rows.select_for_update().delete()

        self.stdout.write(self.style.SUCCESS(
            f'[완료] [DEMO] 공지 {notice_count}건, FAQ {faq_count}건을 정리했습니다.'
        ))
