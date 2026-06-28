"""직업 위험등급(JobRiskCode) 시드 — foliio 메리츠 직업표 707개 적재.

- 데이터: inpa/customers/data/job_risk_codes.json (foliio meritz_jobs.json 에서 검색·표시
  필요 필드만 추린 경량본). 전역 마스터(공유, owner 무관).
- 멱등: (sctg_cd, name) 기준 upsert → 매 배포 재실행해도 카운트 불변. Render startCommand
  의 seed_normalization 과 같은 위치에서 호출(아래 build/start 체인).
- 성능: 전체를 한 번에 읽어 bulk_create/bulk_update (배포당 쿼리 수 최소화).

사용법:
    python manage.py seed_jobs            # 멱등 upsert
    python manage.py seed_jobs --clear    # 전부 삭제 후 재적재
    python manage.py seed_jobs --dry-run  # DB 변경 없이 파싱 검증
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inpa.customers.models import JobRiskCode

DATA_PATH = Path(__file__).resolve().parents[2] / 'data' / 'job_risk_codes.json'

# bulk_update 대상 필드(고유키 sctg_cd·name 제외)
_UPDATE_FIELDS = [
    'risk_grade', 'mctg_cd', 'lctg_cd', 'alt_name',
    'description', 'synonym', 'kidi_cd', 'source',
]


class Command(BaseCommand):
    help = '직업 위험등급(JobRiskCode) 707개를 멱등 적재합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--file', '-f', default=str(DATA_PATH),
                            help=f'JSON 경로 (기본: {DATA_PATH})')
        parser.add_argument('--clear', action='store_true',
                            help='적재 전 기존 JobRiskCode 전부 삭제')
        parser.add_argument('--dry-run', action='store_true',
                            help='DB 변경 없이 파싱만 검증')

    def handle(self, *args, **options):
        path = Path(options['file'])
        if not path.exists():
            raise CommandError(f'데이터 파일이 없습니다: {path}')

        with path.open(encoding='utf-8') as f:
            rows = json.load(f)
        if not isinstance(rows, list):
            raise CommandError('JSON 최상위가 리스트가 아닙니다.')

        dry = options['dry_run']
        if dry:
            self.stdout.write(self.style.WARNING('🧪 dry-run (DB 변경 없음)'))

        with transaction.atomic():
            if options['clear'] and not dry:
                n = JobRiskCode.objects.count()
                JobRiskCode.objects.all().delete()
                self.stdout.write(self.style.WARNING(f'🗑  기존 {n}개 삭제'))

            existing = {(j.sctg_cd, j.name): j for j in JobRiskCode.objects.all()}
            to_create, to_update = [], []
            grade_stat = {1: 0, 2: 0, 3: 0, 9: 0}
            skipped = 0

            for row in rows:
                sctg = (row.get('sctg_cd') or '').strip()
                name = (row.get('name') or '').strip()
                if not sctg or not name:
                    skipped += 1
                    continue
                grade = int(row.get('risk_grade') or 9)
                if grade not in (1, 2, 3, 9):
                    grade = 9
                grade_stat[grade] += 1
                vals = dict(
                    risk_grade=grade,
                    mctg_cd=(row.get('mctg_cd') or '').strip(),
                    lctg_cd=(row.get('lctg_cd') or '').strip(),
                    alt_name=(row.get('alt_name') or '').strip(),
                    description=(row.get('description') or '').strip(),
                    synonym=(row.get('synonym') or '').strip(),
                    kidi_cd=(row.get('kidi_cd') or '').strip(),
                    source='meritz',
                )
                obj = existing.get((sctg, name))
                if obj is None:
                    to_create.append(JobRiskCode(sctg_cd=sctg, name=name, **vals))
                else:
                    changed = False
                    for k, v in vals.items():
                        if getattr(obj, k) != v:
                            setattr(obj, k, v)
                            changed = True
                    if changed:
                        to_update.append(obj)

            if dry:
                transaction.set_rollback(True)
            else:
                if to_create:
                    JobRiskCode.objects.bulk_create(to_create, batch_size=500)
                if to_update:
                    JobRiskCode.objects.bulk_update(to_update, _UPDATE_FIELDS, batch_size=500)

            # ── 동기화: 파일에 없는 (sctg_cd, name)은 삭제(파일이 정본 — 데이터 교체 시 옛 행 정리).
            #    Customer.job_code 는 SET_NULL 이라 직업 링크만 풀리고 고객은 보존된다. ──
            pruned = 0
            if not dry:
                file_keys = {((row.get('sctg_cd') or '').strip(), (row.get('name') or '').strip())
                             for row in rows}
                stale = [j.pk for (k, j) in existing.items() if k not in file_keys]
                if stale:
                    pruned = len(stale)
                    JobRiskCode.objects.filter(pk__in=stale).delete()

        self.stdout.write(self.style.SUCCESS('✅ 직업급수 시드 완료'))
        self.stdout.write(f'   - 신규: {len(to_create)} / 갱신: {len(to_update)} / 삭제(정리): {pruned} / 스킵: {skipped}')
        self.stdout.write(
            f'   - 등급: 1급 {grade_stat[1]} / 2급 {grade_stat[2]} / 3급 {grade_stat[3]} / 기타 {grade_stat[9]}'
        )
