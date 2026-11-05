# Pink Party

A native macOS gaming hangout using vanilla TypeScript, Vite, Node.js 24 and native LiveKit. Keep the app small and use synthetic session data.

- Install with `npm ci`; generate ignored local credentials with `npm run setup`.
- Build with `npm run build`, start both services with `npm start`, stop with Ctrl+C.
- Run `npm run check`. Browser checks: install Chromium with `npx playwright install chromium`, start the app, close other room clients, then `npm run test:e2e`.
- Use `npm run format` before delivery. No separate linter is configured.
- Keep secrets in `.env` and generated `.local/`; never add them to bundles, logs, screenshots or Git.
- Keep local mode as the safe loopback default. Private mode requires the configured Tailscale IPv4, exact HTTPS origin and invited identity allowlist. Only LiveKit UDP 7882 binds to that private address; app/control listeners stay on loopback. No Funnel, public hosting or router forwarding.
- Follow docs/remote-access.md for private setup, policy review, foreground Serve and rollback. Keep real identities and generated configuration in ignored private files.
- Validate API input, bound network waits, and release tracks/audio on every exit path. The LiveKit cap is authoritative.
- Use readable functions and standard library helpers. Add dependencies only for a demonstrated need.
- Keep docs/validation.md factual. Separate synthetic media checks from human listening, and assisted implementation from the owner's confirmed work.
- Follow Conventional Commits and stage only task files. Preserve unrelated changes.
