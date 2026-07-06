# 26. DB 백업·복구 런북 (PM용, LB#4)

> 목적: Neon(운영 DB)의 모든 고객 데이터를 **대표님 자체 서버**에 매일 밤 암호화 보관하고, 사고 시 복구할 수 있게 한다. 감사 H-3(백업 부재) 해소. 스크립트는 `scripts/backup/`에 있음.

## A. 최초 설치 (서버에서 1회, 약 10분)

1. 도구 설치 (Ubuntu/Debian 기준):
   ```
   sudo apt-get update && sudo apt-get install -y postgresql-client gnupg
   ```
2. 저장소 스크립트 복사 (서버에 git이 있으면 clone, 없으면 `scripts/backup/` 3개 파일만 복사):
   ```
   mkdir -p ~/inpa-backup && cd ~/inpa-backup
   # neon_backup.sh, neon_restore.sh, backup.env.example 복사 후
   chmod +x neon_backup.sh neon_restore.sh
   ```
3. 암호문 파일 생성 (★ 잃어버리면 백업을 영영 못 엽니다. 비밀번호 관리자에 사본 보관):
   ```
   openssl rand -base64 32 > ~/.inpa-backup-pass && chmod 600 ~/.inpa-backup-pass
   ```
4. 설정 파일 작성:
   ```
   cp backup.env.example backup.env && chmod 600 backup.env
   ```
   `backup.env` 를 열어 `DATABASE_URL`(Neon 대시보드 > Connection Details 문자열), `BACKUP_DIR`, `GPG_PASSPHRASE_FILE` 채우기.
5. 수동 1회 실행으로 확인:
   ```
   ./neon_backup.sh
   ```
   성공 신호: `[OK] .../inpa-YYYYmmdd-HHMMSS.dump.gpg (크기)` 출력 + 해당 파일 생성.
6. 매일 새벽 3시 30분 자동 실행 등록:
   ```
   crontab -e
   ```
   맨 아래에 한 줄 추가:
   ```
   30 3 * * * /home/USER/inpa-backup/neon_backup.sh >> /home/USER/inpa-backup/backup.log 2>&1
   ```

## B. 매주 확인 (1분)

- `ls -lh $BACKUP_DIR | tail -3` 로 최근 파일 날짜·크기 확인. 크기가 갑자기 0에 가깝거나 날짜가 이틀 이상 벌어졌으면 `backup.log` 확인.
- `.last_success` 파일의 날짜가 어제 이후인지 확인.

## C. 복구 리허설 (분기 1회 필수 — "복원해 본 적 없는 백업은 소문일 뿐")

1. Neon 대시보드에서 **새 브랜치**(또는 로컬 postgres에 빈 DB) 생성 → 그 접속 문자열 복사.
2. 서버에서:
   ```
   TARGET_DATABASE_URL="<스크래치 DB URL>" ./neon_restore.sh <최근 백업파일.dump.gpg>
   ```
   확인 프롬프트에 `restore` 입력.
3. 점검: `psql "<스크래치 URL>" -c 'select count(*) from customers_customer;'` 가 실제 고객 수와 비슷하면 성공.
4. 스크래치 브랜치 삭제.

## D. 실제 사고 시 (운영 복구)

1. 침착하게: Neon 자체 PITR(짧은 기간)로 먼저 복구 가능한지 Neon 대시보드 > Restore 확인.
2. PITR로 안 되면: 위 C 절차로 **스크래치 브랜치에 먼저 복원**해 데이터 확인 → 정상이면 Render의 `DATABASE_URL` 환경변수를 그 브랜치로 교체(재배포) 또는 Neon에서 브랜치를 기본으로 승격.
3. 복구 후 Render Shell에서 `python manage.py check` + 서비스 화면 스모크 확인.

## E. 흔한 오류

| 증상 | 원인·해결 |
|---|---|
| `pg_dump 미설치` | A-1 다시 실행 |
| `invalid URI query parameter: "channel_binding"` 또는 `server version mismatch` | 서버의 PostgreSQL 클라이언트가 구버전(우분투 20.04 = 12). 아래 '구버전 우분투: 도커 우회' 적용 |
| `암호문 파일이 없거나 비어 있음` | A-3의 파일 경로가 backup.env 값과 같은지 확인 |
| `덤프 크기 …B < …B` | DATABASE_URL이 빈 DB/잘못된 브랜치를 보고 있을 가능성. Neon 접속 문자열 재확인 |
| cron이 안 돎 | `crontab -l`로 등록 확인, 경로가 절대경로인지 확인 |

## E-2. 구버전 우분투: 도커 우회 (2026-07-06 실적용)

우분투 20.04는 공식 PostgreSQL 저장소(PGDG) 지원이 끝나 최신 클라이언트를 설치할 수 없다.
서버에 도커가 있으면 스크립트가 도커 안의 최신 PostgreSQL을 쓰도록 한 번만 패치한다:

```
cd ~/inpa-backup
sed -i 's|^pg_dump --format=custom|docker run --rm -v "$BACKUP_DIR":"$BACKUP_DIR" postgres:18 pg_dump --format=custom|' neon_backup.sh
sed -i 's|^pg_restore --clean|docker run --rm -v /tmp:/tmp postgres:18 pg_restore --clean|' neon_restore.sh
```

- 이미지 버전(postgres:18)은 Neon 서버 버전 이상이어야 한다. 버전 불일치 오류 메시지에
  `server version: 18.x` 처럼 표시되니 그 숫자에 맞추면 된다.
- 첫 실행은 이미지 다운로드로 1~2분. `docker ps`가 권한 오류면
  `sudo usermod -aG docker <사용자>` 후 재접속.

## F. 개인정보 주의 (PIPA)

백업 파일에는 고객 개인정보가 들어 있습니다. 이 서버는 개인정보처리시스템입니다:
- 백업 폴더 접근 권한은 대표님 계정만(`chmod 700 $BACKUP_DIR`), 디스크 암호화 권장.
- 보존 30일 초과분은 스크립트가 자동 삭제(보존 기간을 늘리면 개인정보 보유 기간 고지와 어긋나지 않는지 확인).
- 서버 폐기·이전 시 백업 폴더를 안전 삭제(`shred`/디스크 초기화).
