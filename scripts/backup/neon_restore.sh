#!/usr/bin/env bash
# 인파 DB 복구 — 암호화 백업(.dump.gpg)을 지정 DB로 복원한다.
# ★★★ 대상 DB(TARGET_DATABASE_URL)의 기존 데이터를 덮어쓴다. 운영 DB에 바로 쓰지 말고
#     반드시 빈 스크래치 DB(Neon 새 브랜치/로컬 postgres)에 먼저 복원해 점검할 것.
# 사용: TARGET_DATABASE_URL=postgres://... ./neon_restore.sh /path/inpa-YYYYmmdd-HHMMSS.dump.gpg
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$SCRIPT_DIR/backup.env}"
[ -f "$ENV_FILE" ] && . "$ENV_FILE"

FILE="${1:?사용법: TARGET_DATABASE_URL=... $0 <백업파일.dump.gpg>}"
: "${TARGET_DATABASE_URL:?복원 대상 TARGET_DATABASE_URL 이 필요합니다(운영 URL 금지, 스크래치 DB 사용)}"
: "${GPG_PASSPHRASE_FILE:?GPG_PASSPHRASE_FILE 이 필요합니다}"

command -v pg_restore >/dev/null || { echo "[ERR] pg_restore 미설치"; exit 1; }
[ -f "$FILE" ] || { echo "[ERR] 파일 없음: $FILE"; exit 1; }

echo "[확인] 복원 대상: ${TARGET_DATABASE_URL%%\?*}"
read -r -p "이 DB의 기존 데이터를 덮어씁니다. 계속하려면 'restore' 입력: " ANSWER
[ "$ANSWER" = "restore" ] || { echo "중단"; exit 1; }

TMP="$(mktemp /tmp/inpa-restore.XXXXXX.dump)"
trap 'rm -f "$TMP"' EXIT

echo "[1/2] 복호화"
gpg --batch --yes --decrypt --passphrase-file "$GPG_PASSPHRASE_FILE" --output "$TMP" "$FILE"

echo "[2/2] pg_restore (--clean --if-exists)"
pg_restore --clean --if-exists --no-owner --no-privileges \
           --dbname="$TARGET_DATABASE_URL" "$TMP"

echo "[OK] 복원 완료. 점검 예시: psql \"\$TARGET_DATABASE_URL\" -c 'select count(*) from customers_customer;'"
