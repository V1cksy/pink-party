# Continuous verification

[Verify](https://github.com/V1cksy/pink-party/actions/workflows/verify.yml) checks pushes and pull requests targeting `main`, with a manual dispatch option. It runs the source checks and synthetic browser/media suite on a fresh Ubuntu 24.04 ARM64 GitHub-hosted runner. [The workflow](../.github/workflows/verify.yml) and [CI script](../scripts/ci-linux.sh) are the executable configuration.

## What runs

The script downloads Node.js and LiveKit using the shared [checksum pins](../deploy/linux/runtimes.sh), installs age through Ubuntu packages, and uses `npm ci` with the committed lockfile. It runs `npm run check`: TypeScript, offline TypeScript/Python tests, build and formatting. A failed check stops the job before the application/browser stage.

After installing Chromium, it generates new runner-only credentials, masks their values in Actions diagnostics and starts Node/LiveKit on loopback in a dedicated process group. A bounded web/control readiness check precedes the browser suite. The media case separately verifies received bytes, decoded samples and audio energy, along with capacity and microphone cleanup. Readiness alone does not prove media reception.

The script preserves its failing exit status, stops its application process group on exit/interruption and removes generated environment, media files, screenshots, raw service output and test-result files. It refuses an existing `.env`/`.local`, and only accepts the Linux ARM64 Actions environment. It is intended for a fresh disposable checkout, not a local deployment or the owner's Mac.

No repository secrets, owner environment, recovery key, AWS access or Tailscale state are supplied. Only ordinary test output is published. Raw application logs, screenshots and browser artifacts are not uploaded. Credentials and ephemeral identities generated inside tests are synthetic fixtures, not the owner's configuration.

## Execution and permissions

The action is pinned to a full commit SHA, with credential persistence disabled. The token has `contents: read`; other workflow permissions are absent. Pull requests use `pull_request`, without a privileged `pull_request_target` job or untrusted text interpolated into shell code. Runs on the same Git ref cancel older work. Each job has a 20-minute bound and browser installation a separate ten-minute bound.

The repository was verified public with Actions enabled before this stage. GitHub documents [standard runners as free for public repositories](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#standard-github-hosted-runners-for-public-repositories); the job skips if repository visibility becomes private. No larger runner, artifact upload/storage, paid feature or AWS resource is configured. Recheck current pricing and visibility before changing that boundary. [GitHub's secure-use reference](https://docs.github.com/en/actions/reference/security/secure-use) explains commit pinning, minimal permissions and masking.

This workflow verifies code; it does not deploy, publish a release, edit branch protection or restart any retained VM. A green result does not establish private-network access, physical listening, systemd/VM recovery or an independent owner skill. Those have separate [Linux](validation-linux.md), [cloud](cloud-report.md) and [recovery](recovery-off-vm.md) records. Branch protection was not configured, so a failed run is visible evidence rather than a guarantee that Git rejects a direct push.

## Inspect or repeat

```sh
gh run list --workflow verify.yml --limit 5
gh workflow run verify.yml --ref main
gh run view RUN_ID
```

Choose the exact run and commit before reading its result. Review individual step conclusions and cancelled/skipped states; a skipped job has not passed its checks. Keep downloaded raw logs private. To reproduce source checks locally, run `npm run check`; for browser checks follow [local development](local-development.md). Do not fake the hosted-runner environment in a personal checkout.

For a controlled failure exercise, create a task-specific temporary branch from reviewed `main`, add a clearly labelled deliberately failing test, push that branch and manually dispatch the workflow against it. Confirm failure reaches Actions and later media steps do not execute. Retain the run URL and inspected result, then delete only that task-created branch/worktree. Do not merge the deliberate failure or change the owner's working configuration.

This stage is Codex-run assisted project work. Actual hosted runs and their limits will be recorded after execution; configuration alone is not a completed CI result.
