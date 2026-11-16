# Pink Party

A gaming hangout using vanilla TypeScript, Vite, Node.js 24 and native LiveKit. macOS has local/private modes; the Ubuntu ARM64 VM is a separate local systemd lab. Keep the app small and use synthetic session data.

- Install with `npm ci`; generate ignored local credentials with `npm run setup`.
- Build with `npm run build`, start both services with `npm start`, stop with Ctrl+C.
- Run `npm run check`. Browser checks: install Chromium with `npx playwright install chromium`, start the app, close other room clients, then `npm run test:e2e`.
- Use `npm run format` before delivery. No separate linter is configured.
- Keep secrets in `.env` and generated `.local/`; never add them to bundles, logs, screenshots or Git.
- Keep local mode as the safe loopback default. Private mode requires the configured Tailscale IPv4, exact HTTPS origin and invited identity allowlist. Only LiveKit UDP 7882 binds to that private address; app/control listeners stay on loopback. No Funnel, public hosting or router forwarding.
- Follow docs/remote-access.md for private setup, policy review, foreground Serve and rollback. Keep real identities and generated configuration in ignored private files.
- Follow docs/linux-deployment.md for the Linux VM. Keep credentials separate, service files root-owned and app sockets on guest loopback. Use the public deployment manifest; do not copy host credentials or share host folders. Run Linux failure exercises and browser checks sequentially.
- Scheduled Linux monitoring uses an independent timer and root-only bounded history. Keep it running during application outages; web/control health never proves media reception. See docs/incident-linux-monitoring.md for the Codex-run batch-5 exercise. Preserve the separate Mac/Tailscale setup.
- Follow docs/linux-backups.md for scheduled snapshots and safe separate-directory restoration; docs/recovery-linux-backups.md records batch 6 and the latest final state. Keep archives, recovered credentials and raw reports private. Preserve working credentials and run service exercises sequentially. Backups share the guest disk and do not protect against its loss.
- Cloud remains later work. Independent owner practice is unconfirmed and is not a prerequisite for continuing implementation.
- Validate API input, bound network waits, and release tracks/audio on every exit path. The LiveKit cap is authoritative.
- Use readable functions and standard library helpers. Add dependencies only for a demonstrated need.
- Keep docs/validation.md factual. Separate synthetic media checks from human listening, and assisted implementation from the owner's confirmed work.
- Follow Conventional Commits and stage only task files. Preserve unrelated changes.
