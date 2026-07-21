### 2026-07-16 Railway 배포 상태 반복 실패
Symptom: `master` 커밋마다 GitHub의 Railway 상태가 즉시 실패한다. PR #121 병합 커밋과 바로 이전 `master` 커밋에서 같은 증상이 반복됐지만, GitHub Actions와 Vercel 배포는 성공했고 운영 프론트 주소도 정상 응답했다.
Cause: 저장소 밖 Railway 프로젝트 연동이 여전히 이 저장소의 배포 상태를 보고하고 있다. Railway 설정과 실패 로그를 확인할 권한이 없어 세부 원인은 아직 확정하지 못했다.
Fix: 이번 프론트 랜딩은 기존 Vercel 배포 경로로 배포·검증했다. Railway 연동은 별도 인프라 작업으로 프로젝트 연결과 빌드 설정을 확인해 복구하거나, 사용하지 않는 연동이면 제거한다.
Prevention: 배포 전 GitHub 필수 상태 목록에서 실제 운영에 쓰는 GitHub Actions·Vercel과 보조 연동을 구분한다. 사용하지 않는 배포 연동은 상태 보고를 끄고, 사용 중이면 Railway 실패 로그와 담당 서비스를 운영 문서에 연결한다.

### 2026-07-16 Test throttle cache leaks across cases
Symptom: A full backend suite can return HTTP 429 in late insurance-import tests while the same tests pass with a fresh process/database.
Cause: Django rolls back database rows between `TestCase`s but does not reset cache state. When real DRF rates are active because of the test invocation/settings environment, repeated user PKs reuse `throttle_insurance_import_*` keys until the hourly limit is reached.
Fix: Use `CacheIsolatedTestRunner`; its result clears every configured cache immediately before each sequential test and rejects `--parallel` because Django worker results bypass the parent result mixin. Runtime throttle settings remain unchanged.
Prevention: Keep rate-boundary tests on their own cache and retain regressions proving sequential cases cannot share throttle history and parallel execution fails before cache work begins.

### 2026-07-17 npm lock regeneration omits optional transitive packages
Symptom: `npm install --package-lock-only` reported success after a merge, but `npm ci` repeatedly failed because `@emnapi/core` and `@emnapi/runtime` were missing from the lock file.
Cause: npm 11 regenerated the lock incrementally while a platform-specific `node_modules` tree existed, so dependencies of optional wasm bindings were referenced but their package records were omitted.
Fix: Generate `package-lock.json` from the final `package.json` in an empty directory with `--include=optional`, then prove it with `npm ci`.
Prevention: After dependency-conflict resolution, never trust `npm install --package-lock-only` alone. Regenerate from an empty tree and keep `npm ci` as the authoritative CI gate.

### 2026-07-21 Prunable Git worktree blocks private evaluation
Symptom: The private extraction evaluation command failed twice with `E_DATASET_PATH` before reading an otherwise valid dataset.
Cause: Git kept a `prunable` record for a deleted temporary worktree. Discovery resolved every listed path with `strict=True`, including the explicitly stale record, and therefore failed closed before validation.
Fix: Parse worktree porcelain records and skip only records Git marks `prunable`; missing non-prunable worktrees still fail closed.
Prevention: Regression tests cover the allowed prunable case, missing or malformed active records, and the command-level aggregate-output path.

### 2026-07-22 Render Free cold start exceeds health-check client timeout
Symptom: Production `/healthz/` succeeded in 0.29s, then one 60s request and three independent 20s requests connected but received no bytes. Render health logs stopped for about 14 minutes before recovering.
Cause: Render Events showed the web service had changed from Starter to Free on 2026-07-17. After roughly 15 minutes without external traffic, Gunicorn received SIGTERM. The wake path then ran migrations, cache setup, and five seed commands sequentially before starting Gunicorn, taking about 2m24s.
Fix: Waited for the new instance to finish booting and verified repeated internal health 200 responses plus an external 200 response in 0.51s. No billing or infrastructure tier was changed without PM approval.
Prevention: Restore an always-on Render plan before launch, or approve a deployment change that moves setup work out of the runtime start command. Keep the PM and agent docs aligned with the actual Render tier, and do not treat a 60s timeout during Free-tier wake as an application regression without checking Render events and boot logs.
