### 2026-07-16 Railway 배포 상태 반복 실패
Symptom: `master` 커밋마다 GitHub의 Railway 상태가 즉시 실패한다. PR #121 병합 커밋과 바로 이전 `master` 커밋에서 같은 증상이 반복됐지만, GitHub Actions와 Vercel 배포는 성공했고 운영 프론트 주소도 정상 응답했다.
Cause: 저장소 밖 Railway 프로젝트 연동이 여전히 이 저장소의 배포 상태를 보고하고 있다. Railway 설정과 실패 로그를 확인할 권한이 없어 세부 원인은 아직 확정하지 못했다.
Fix: 이번 프론트 랜딩은 기존 Vercel 배포 경로로 배포·검증했다. Railway 연동은 별도 인프라 작업으로 프로젝트 연결과 빌드 설정을 확인해 복구하거나, 사용하지 않는 연동이면 제거한다.
Prevention: 배포 전 GitHub 필수 상태 목록에서 실제 운영에 쓰는 GitHub Actions·Vercel과 보조 연동을 구분한다. 사용하지 않는 배포 연동은 상태 보고를 끄고, 사용 중이면 Railway 실패 로그와 담당 서비스를 운영 문서에 연결한다.
