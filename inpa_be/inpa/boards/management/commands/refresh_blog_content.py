from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from inpa.boards.blog_release import (
    RELEASE_VERSION,
    ReleaseError,
    apply_release,
    load_release,
    restore_release,
    validate_release,
)


class Command(BaseCommand):
    help = '검증된 블로그 원고를 dry-run, 적용 또는 보호된 snapshot으로 복원합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--backup-out')
        parser.add_argument('--restore-from')
        parser.add_argument('--restore-from-marker', action='store_true')
        parser.add_argument('--confirm-version')
        parser.add_argument('--content-dir')
        parser.add_argument('--manifest-path')

    def handle(self, *args, **options):
        apply_requested = options['apply']
        restore_from = options['restore_from']
        restore_from_marker = options['restore_from_marker']
        if sum(bool(value) for value in (apply_requested, restore_from, restore_from_marker)) > 1:
            raise CommandError('--apply와 복원 옵션은 동시에 사용할 수 없습니다')
        if apply_requested and not options['backup_out']:
            raise CommandError('--apply에는 --backup-out이 필요합니다')
        if restore_from or restore_from_marker:
            if options['confirm_version'] != RELEASE_VERSION:
                raise CommandError(
                    f'--restore-from에는 --confirm-version {RELEASE_VERSION}이 필요합니다'
                )
            try:
                result = restore_release(
                    snapshot_path=Path(restore_from) if restore_from else None,
                    confirm_version=options['confirm_version'],
                )
            except ReleaseError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(
                f'restored={result["restored"]} unpublished={result["unpublished"]}'
            )
            self._write_slugs(result['restored_slugs'] + result['created_slugs'])
            return
        if options['confirm_version']:
            raise CommandError('--confirm-version은 --restore-from과 함께 사용해야 합니다')

        try:
            items, digest = load_release(
                options['content_dir'],
                options['manifest_path'],
            )
            errors = validate_release(items, manifest_path=options['manifest_path'])
        except ReleaseError as exc:
            raise CommandError(str(exc)) from exc
        if errors:
            raise CommandError('\n'.join(errors))

        published = sum(item.is_published for item in items)
        if not apply_requested:
            self.stdout.write(
                f'dry-run version={RELEASE_VERSION} items={len(items)} '
                f'published={published} drafts={len(items) - published} digest={digest}'
            )
            self._write_slugs([item.slug for item in items])
            return

        try:
            result = apply_release(
                items=items,
                digest=digest,
                backup_path=Path(options['backup_out']),
            )
        except ReleaseError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f'applied version={RELEASE_VERSION} created={result["created"]} '
            f'updated={result["updated"]}'
        )
        self._write_slugs([item.slug for item in items])

    def _write_slugs(self, slugs):
        for slug in sorted(slugs):
            self.stdout.write(f'slug={slug}')
