#!/usr/bin/env bash
# 인파 DB 야간 백업 — PM 자체 서버에서 cron 으로 실행 (LB#4, audit H-3).
# Neon Postgres 를 pg_dump(custom format)로 받아 GPG 대칭 암호화해 보관하고,
# 보존 기간이 지난 파일은 삭제한다. 성공 시 heartbeat 파일 갱신.
#
# 필요 도구: postgresql-client(pg_dump), gnupg(gpg)
# 환경 파일: 같은 디렉터리의 backup.env (chmod 600) — 예시는 backup.env.example
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$SCRIPT_DIR/backup.env}"
[ -f "$ENV_FILE" ] && . "$ENV_FILE"

: "${DATABASE_URL:?backup.env 에 DATABASE_URL(Neon 접속 문자열)이 필요합니다}"
: "${BACKUP_DIR:?backup.env 에 BACKUP_DIR(백업 저장 경로)가 필요합니다}"
: "${GPG_PASSPHRASE_FILE:?backup.env 에 GPG_PASSPHRASE_FILE(암호문 파일 경로, chmod 600)가 필요합니다}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
MIN_BYTES="${MIN_BYTES:-102400}"   # 산출물 최소 크기(기본 100KB) — 빈 덤프 오탐지

command -v pg_dump >/dev/null || { echo "[ERR] pg_dump 미설치 (postgresql-client)"; exit 1; }
command -v gpg >/dev/null || { echo "[ERR] gpg 미설치 (gnupg)"; exit 1; }
[ -s "$GPG_PASSPHRASE_FILE" ] || { echo "[ERR] 암호문 파일이 없거나 비어 있음: $GPG_PASSPHRASE_FILE"; exit 1; }

mkdir -p "$BACKUP_DIR"

# 중복 실행 방지 락
LOCK="$BACKUP_DIR/.backup.lock"
exec 9>"$LOCK"
flock -n 9 || { echo "[SKIP] 이미 실행 중"; exit 0; }

STAMP="$(date +%Y%m%d-%H%M%S)"
TMP="$BACKUP_DIR/inpa-$STAMP.dump.tmp"
OUT="$BACKUP_DIR/inpa-$STAMP.dump.gpg"

echo "[1/3] pg_dump 시작 ($STAMP)"
pg_dump --format=custom --no-owner --no-privileges --dbname="$DATABASE_URL" --file="$TMP"

SIZE=$(stat -c%s "$TMP" 2>/dev/null || stat -f%z "$TMP")
if [ "$SIZE" -lt "$MIN_BYTES" ]; then
  rm -f "$TMP"
  echo "[ERR] 덤프 크기 ${SIZE}B < ${MIN_BYTES}B — 비정상으로 판단, 중단"; exit 1
fi

echo "[2/3] GPG 암호화 (${SIZE}B)"
gpg --batch --yes --symmetric --cipher-algo AES256 \
    --passphrase-file "$GPG_PASSPHRASE_FILE" \
    --output "$OUT" "$TMP"
rm -f "$TMP"

echo "[3/3] 보존 정리 (${RETENTION_DAYS}일 초과 삭제)"
find "$BACKUP_DIR" -name 'inpa-*.dump.gpg' -mtime +"$RETENTION_DAYS" -print -delete

date +%FT%T > "$BACKUP_DIR/.last_success"
echo "[OK] $OUT ($(du -h "$OUT" | cut -f1))"
