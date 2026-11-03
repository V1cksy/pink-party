# Batch 1 validation

Verified on 4 November 2026 (Europe/Madrid), on an ARM64 Mac running macOS 27.0.1 with 8 GiB RAM. Runtime: Node.js 24.22.2, npm 11.19.1, LiveKit Server 1.13.11. Browser automation: Playwright 1.64.1 with its Chromium 156 build. Versions of the SDKs and build tools are pinned in `package.json` and the lockfile.

## Commands and results

| Check                                                                                   | Actual outcome                                                                                                                      |
| --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `npm ci`                                                                                | Clean dependency installation succeeded; audit reported no vulnerabilities.                                                         |
| `npm run check`                                                                         | Passed strict TypeScript checks, 8 offline tests, production build and Prettier checks.                                             |
| `npm run test:e2e`                                                                      | All 13 browser tests passed against the running native LiveKit server; final run took 40.1 seconds.                                 |
| `npm audit --omit=dev`                                                                  | No known vulnerabilities reported by the registry at the time of the check.                                                         |
| `curl -fsS http://localhost:3000/api/health`                                            | Returned `{"status":"ok","voice":"ready"}`.                                                                                         |
| Vite with `npm run dev`; GET `http://127.0.0.1:5173/api/session` with its origin header | Returned the synthetic session successfully through the development proxy.                                                          |
| `lsof -nP -a -p <livekit-pid>,<app-pid> -i`                                             | The service processes had only TCP 127.0.0.1:3000, TCP 127.0.0.1:7880 and UDP 127.0.0.1:7882 sockets. No wildcard or LAN listeners. |
| Start a second `npm start`                                                              | Failed clearly with “Port 3000 is in use” and did not replace the running services.                                                 |
| Send SIGTERM to the startup supervisor                                                  | Both services stopped; the service ports were released.                                                                             |
| Send SIGTERM to LiveKit                                                                 | Supervisor detected its exit, stopped the application and exited with status 1. A subsequent `npm start` restored healthy services. |
| Run `npm run start:app` with LiveKit stopped                                            | Actual health response was 503 with `voice: unavailable`; a real browser join showed the voice-server recovery message.             |
| Scan built output against the three real `.env` values                                  | No real join code, API key or API secret found in `dist`. Generated files and secrets are ignored by Git.                           |

The build emits a size warning for the bundled LiveKit browser SDK: approximately 542 kB minified JavaScript, 141 kB gzip for the client bundle. The build succeeds. No download-speed or startup-performance claim is made. No separate linter is configured; TypeScript and Prettier are the required code checks.

## What the tests establish

Offline tests cover malformed input, unsafe/empty/oversized names, incorrect codes, invalid configuration, signed room-scoped token permissions and expiry, four-person admission rejection, voice-service errors, session validation, request host/origin/body boundaries, rate limiting and health responses.

The browser media test uses a generated 440 Hz WAV as fake microphone input. It connects real browser SDK clients to native LiveKit, publishes audio, subscribes and reads browser WebRTC inbound RTP statistics. Both clients received decoded audio with nonzero energy in the two-client check. At four clients, each received three audio streams with more than 1,000 bytes, more than 1,000 decoded samples and positive audio energy. Energy also increased after unmuting in the two-client check. [Raw media/resource results](validation-data.json) contain the observed counters.

The test also verifies actual mute labels, leave/rejoin participant updates, audio element removal, stopped capture tracks, and server-initiated disconnection. A fifth client holding an unexpired token issued before the room filled was rejected by LiveKit; another token request while full returned 409. A separately generated expired token was rejected by LiveKit.

Recovery checks cover permission denial, absent/busy devices, wrong admission code before capture, duplicate join requests, cancellation with a late capture, unreachable signaling, browser playback recovery, actual WebSocket interruption/reconnection, leave during delayed unmute, and device-ended recovery. The device/permission/autoplay failures are injected browser conditions; the SDK and media server are real. The WebSocket interruption preserves local media networking and does not represent an entire network outage.

Fresh-context code review identified a possible late SDK microphone restart after application cleanup. A test delays the real permission-query result by 500 ms and reacquisition by one second to exercise that ordering. Removing the inactive-attempt restart guard made the test fail with a live capture track after cleanup; restoring the guard passed. An immediate permission query did not reproduce the leak, so the delayed ordering is necessary to this regression check.

## Interface inspection

Actual Chromium screenshots were inspected at 1440 px desktop width and 390 px mobile width. The mobile test found no horizontal overflow. Labels, visible focus, a keyboard skip link, explicit mute text and connection states are implemented. This was a visual and keyboard check, not a formal accessibility audit or screen-reader test.

- [Desktop screenshot](interface.png)
- [Mobile screenshot](mobile.png)
- [Four local clients: one client's participant view](voice-room.png)

## Resource measurements

The media test calls `measureResources` from `scripts/measure.ts`. It samples each service process once per second for ten samples while the indicated synthetic clients publish and receive audio. Measurements were taken at approximately 00:15–00:16 CET; the raw file timestamps are UTC. All clients and services ran on this one Mac.

| Clients | Service     | Mean RSS (MiB) | Peak RSS (MiB) | Mean `ps` CPU (%) | Peak `ps` CPU (%) |
| ------- | ----------- | -------------: | -------------: | ----------------: | ----------------: |
| 2       | Application |          52.83 |          55.28 |              0.22 |               1.6 |
| 2       | LiveKit     |          79.54 |          81.81 |              4.28 |               4.9 |
| 4       | Application |          27.36 |          28.44 |              0.01 |               0.1 |
| 4       | LiveKit     |          80.95 |          87.30 |             10.46 |              13.6 |

RSS and the OS `ps` CPU estimate vary with process lifetime, garbage collection and other host activity. These short samples are not a scaling or endurance benchmark. They exclude all browser processes, the startup supervisor, npm, build tooling and other host applications. They therefore do not give the total memory cost of running four browsers on an 8 GiB Mac. Repeat with `npm run measure -- 10` under the conditions you want to inspect.

## Remaining checks

- A human listening test with a physical microphone and headphones is pending. Follow the [short manual check](learning.md#short-physical-microphone-check); synthetic counters do not establish audible speech quality.
- The two-to-four participant target has passed short synthetic tests on one Mac. Four humans, long gaming sessions, multiple physical devices and independent networks remain untested.
- Real browser/macOS permission-dialog behaviour, real device removal and browser autoplay policy differences need human checks. Failure messages and recovery paths passed injected tests.
- Safari, Firefox, mobile hardware and assistive technologies have not been tested.
- Friends joining from separate homes, private HTTPS/identity, Linux operation, monitoring, incident exercises, tested restoration and cloud deployment remain future batches.

The [contribution record](learning.md) distinguishes generated implementation and agent-run checks from the owner's pending hands-on work.
