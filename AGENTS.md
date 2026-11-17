# Pink Party

A gaming hangout using vanilla TypeScript, Vite, Node.js 24 and native LiveKit. macOS has local/private modes; Ubuntu ARM64 runs the systemd lab locally and on a private cloud host. Keep the app small and use synthetic session data.

Victoria Prado owns the project. Use her voice for portfolio copy and omit unsolicited tool credits or contribution disclaimers. Describe implemented features and verified results directly; preserve software licence credits.

- Install with `npm ci`; generate ignored local credentials with `npm run setup`.
- Build with `npm run build`, start both services with `npm start`, stop with Ctrl+C.
- Run `npm run check`. Browser checks: install Chromium with `npx playwright install chromium`, start the app, close other room clients, then `npm run test:e2e`.
- Use `npm run format` before delivery. No separate linter is configured.
- Keep secrets in `.env` and generated `.local/`; never add them to bundles, logs, screenshots or Git.
- Keep local mode as the safe loopback default. Private mode requires the configured Tailscale IPv4, exact HTTPS origin and invited identity allowlist. Only LiveKit UDP 7882 binds to that private address; app/control listeners stay on loopback. No Funnel, unauthenticated public application services or router forwarding.
- Follow docs/remote-access.md for private setup, policy review, foreground Serve and rollback. Keep real identities and generated configuration in ignored private files.
- Follow docs/linux-deployment.md for the Linux VM. Keep credentials separate, service files root-owned and app sockets on guest loopback. Use the public deployment manifest; do not copy host credentials or share host folders. Run Linux failure exercises and browser checks sequentially.
- Scheduled Linux monitoring uses an independent timer and root-only bounded history. Keep it running during application outages; web/control health never proves media reception. See docs/incident-linux-monitoring.md for the batch-5 exercise. Preserve the separate Mac/Tailscale setup.
- Follow docs/linux-backups.md for scheduled snapshots and safe separate-directory restoration; docs/recovery-linux-backups.md records batch 6. Keep archives, recovered credentials and raw reports private. Preserve working credentials and run service exercises sequentially. Backups share the guest disk and do not protect against its loss.
- Follow docs/encrypted-recovery.md and docs/recovery-off-vm.md for age export and fresh local recovery. The source receives only a native public recipient; keep the recovery identity outside the VM/vault. Preserve the original VM and known-good material outside retention. Use the fresh-only local recovery installer, never normal setup over recovered credentials/session. The Mac vault and separate key directory share one physical host; no physical-host disaster recovery is established.
- Follow docs/cloud-deployment.md and docs/cloud-report.md for the AWS lab. Creation requires a live ACTIVE FREE plan with credit/expiry headroom; never upgrade or use Paid-plan credits as spending protection. Keep state, keys, identities, addresses and raw reports in ignored private files. Destroy the entire stack and verify actual disk/address/interface removal; shutdown alone is insufficient.
- Linux private configuration preserves separate host credentials and uses native tailscale0, a root-only monitor Host/login record and a separate foreground Serve unit. The monitor trusts local root and does not prove remote identity or media. Run disruptive checks sequentially and preserve the separate Mac settings/grants.
- Batch 7 deployed and removed a real AWS host, tested cross-host synthetic media, scheduled recovery, private backups and guest reboot. See docs/validation-cloud.json for exact scope. The local VM is stopped with its disk/stores retained. Batch 8 adds encrypted off-VM storage and fresh local recovery; off-device storage and separate-home human voice remain later work.
- Validate API input, bound network waits, and release tracks/audio on every exit path. The LiveKit cap is authoritative.
- Use readable functions and standard library helpers. Add dependencies only for a demonstrated need.
- Keep docs/validation.md factual. Separate automated synthetic media checks from human listening and preserve the recorded test boundaries.
- Follow Conventional Commits and stage only task files. Preserve unrelated changes.

- Follow docs/continuous-verification.md for hosted CI. scripts/ci-linux.sh is destructive only inside a fresh disposable Linux ARM64 Actions checkout; never run it over owner configuration. Keep the standard public-runner boundary, pinned checkout/read-only token, no secrets/artifact upload and loopback synthetic media. CI does not deploy.

- Follow docs/scheduled-exports.md for opt-in systemd encryption and user-scoped Mac collection. Keep the pinned vault/key outside rolling retention, decrypt only in separate private state, preserve captures/configuration before redeployment and never auto-start Lima. Inspect attempt/export/validation/capture times separately. Leave the Mac agent removed and optional export timer disabled after exercises; retain stores and use guarded shutdown.

- Follow docs/offsite-backups.md for the opt-in SFTP stage. Use a dedicated, quota-bounded, single-writer destination and independently available reader access and age identity. Keep custody separate from rolling storage. Batch 11 closed with local SFTP and launchd fixture evidence. See docs/offsite-backup-report.md for the verified scope and recovery boundary.
