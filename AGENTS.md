# Pink Party

A local macOS gaming hangout using vanilla TypeScript, Vite, Node.js 24 and native LiveKit. Keep the app small and use synthetic session data.

- Install with `npm ci`; generate ignored local credentials with `npm run setup`.
- Build with `npm run build`, start both services with `npm start`, stop with Ctrl+C.
- Run `npm run check`. Browser checks: install Chromium with `npx playwright install chromium`, start the app, close other room clients, then `npm run test:e2e`.
- Use `npm run format` before delivery. No separate linter is configured.
- Keep secrets in `.env` and generated `.local/`; never add them to bundles, logs, screenshots or Git.
- Keep all listeners on loopback. Remote access and identity are later work.
- Validate API input, bound network waits, and release tracks/audio on every exit path. The LiveKit cap is authoritative.
- Use readable functions and standard library helpers. Add dependencies only for a demonstrated need.
- Keep docs/validation.md factual. Separate synthetic media checks from human listening, and assisted implementation from the owner's confirmed work.
- Follow Conventional Commits and stage only task files. Preserve unrelated changes.
