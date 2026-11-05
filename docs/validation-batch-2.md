# Batch 2 validation: private-access implementation

Verified by Codex on 4 and 5 November 2026, on the same ARM64 macOS 27.0.1 / 8 GiB host as batch 1. Node 24.22.2, LiveKit 1.13.11, pinned SDKs and Playwright Chromium 156 were used. [Batch 1 results](validation.md) and its raw measurements are retained unchanged.

## Implemented and exercised

Private mode has an exact Tailscale HTTPS origin and user allowlist, separate from local development-code admission. Pages, API calls and signaling require an invited identity supplied through the trusted loopback proxy. Remote URL responses use WSS at the configured host. The LiveKit generator restricts private media to the configured Tailscale IPv4 /32, with loopback-only HTTP/control, UDP 7882, no external STUN, TCP media or TURN. Native startup verifies the configured Tailscale device and interface before launch.

The first `npm run check` established the unchanged baseline: all eight offline tests, TypeScript, build and formatting passed. After implementation:

| Check                                               | Observed result                                                                                                                             |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `npm run check`                                     | 14 offline tests passed, strict TypeScript, production build and Prettier passed.                                                           |
| `npm run test:e2e`                                  | All 13 existing browser tests passed in 41.8 seconds against real native LiveKit and the local app.                                         |
| `npm run test:private`                              | Two additional browser tests passed in 17.0 seconds against the synthetic TLS/identity proxy and real native LiveKit.                       |
| `npm audit --omit=dev`                              | No known vulnerabilities reported at the time of the check.                                                                                 |
| `npm run diagnose`                                  | Local app health and authenticated LiveKit API passed.                                                                                      |
| `npm run setup:private` without Tailscale installed | Failed with an installation/sign-in diagnostic; no private settings or identities were invented.                                            |
| `lsof -nP -iTCP:3000 -iTCP:7880 -iUDP:7882`         | Local listeners were TCP 127.0.0.1:3000, TCP 127.0.0.1:7880 and UDP 127.0.0.1:7882. No wildcard/LAN socket was observed for these services. |

Fresh startup became healthy; a second startup rejected the occupied app port without replacing it. SIGTERM to the supervisor returned exit 0 and released all three sockets. Stopping LiveKit caused supervisor exit 1 and stopped the app; the sockets were released. Services were left stopped.

The existing build size warning persists: the bundled LiveKit client makes the main minified JavaScript chunk larger than 500 kB. No performance improvement is claimed.

Offline tests cover exact allowed/denied/missing identity, forged identity on local-mode and non-loopback boundaries, exact host/origin, no private fallback to a development code, private configuration validation, room-scoped microphone-only 60-second token grants, cap rejection, protected HTTP/WebSocket entry points and refusal to overwrite conflicting Serve/Funnel configuration. Existing input, rate, health and local admission tests remain.

The local browser suite again received real synthetic audio in both directions at two clients, and three streams per client at four clients. LiveKit rejected a fifth client with an unexpired token and an already expired token. Mute, leave/rejoin, participant updates, signaling interruption/reconnect and capture cleanup passed. Permission/device/autoplay and delayed device recovery cases are injected conditions. [This batch's local raw counters and resource samples](validation-batch-2-local.json) are separate from the historical data.

The private browser harness starts a synthetic HTTPS proxy on loopback 3443 and an ephemeral loopback application listener. It injects allowlisted or denied test identities and replaces a browser's forged identity header. A fixture certificate was verified using its explicit CA with Node HTTPS; Chromium's certificate exception is confined to this test configuration. Browsers reported a secure context, hid the local code input, opened the current SDK's `/livekit/rtc/v1` WSS route, and received decoded audio with positive energy through actual LiveKit loopback media. Mute labels, signaling reconnect, leave and audio/capture cleanup passed. [Synthetic proxy evidence](validation-batch-2-proxy.json) labels these conditions explicitly. This does **not** test Tailscale identity verification or a Tailscale certificate.

The first proxy run exposed that the SDK initially uses `/rtc/v1` before falling back to legacy `/rtc`. The proxy was corrected to allow both exact SDK routes and their validation routes. The corrected run used v1 directly and reconnected over it.

A fresh-context Codex review found a cancellation race during asynchronous startup. A launch guard now prevents either service from starting after shutdown is requested. The regression test delays a fake Tailscale lookup beyond the four-second cleanup timer and injects an interface and port probes; no real Tailscale identity or network interface is used. It failed with “A service launched after shutdown” when the guard was removed and passed after restoration.

The generated private-mode desktop screenshot was inspected: the pink layout and voice controls were preserved, with the private badge and no development-code field. This was the synthetic proxy interface, not the real Tailscale endpoint.

## Resource samples

Ten samples, one second apart, during synthetic calls on this Mac. RSS and `ps` CPU are process samples, not total host costs or an endurance benchmark.

| Condition                        | Process                                         | Mean / peak RSS MiB | Mean / peak `ps` CPU % |
| -------------------------------- | ----------------------------------------------- | ------------------- | ---------------------- |
| Local, 2 clients                 | Application                                     | 26.00 / 28.59       | 0.06 / 0.30            |
| Local, 2 clients                 | LiveKit                                         | 71.56 / 78.50       | 3.65 / 4.60            |
| Local, 4 clients                 | Application                                     | 24.45 / 32.30       | 0.47 / 4.40            |
| Local, 4 clients                 | LiveKit                                         | 72.21 / 83.30       | 8.23 / 12.80           |
| Synthetic HTTPS proxy, 2 clients | Fixture proxy + application in one Node process | 77.69 / 87.80       | 0.19 / 0.70            |
| Synthetic HTTPS proxy, 2 clients | LiveKit                                         | 68.29 / 80.20       | 3.23 / 3.60            |

Excluded: all browsers, supervisors, npm/build tools, other host applications and Tailscale (not running). The synthetic proxy sample also excludes the separate idle local application process. These conditions differ from a deployed private call; they do not establish Tailscale overhead or an improvement over batch 1.

## External setup and remaining evidence

The authorised Homebrew installation of `tailscale-app` 1.104.5 downloaded the native package but stopped because the installer requires an administrator password. No password was requested through chat and no OS permission was bypassed. Tailscale was not installed, connected or signed in by this work. No existing tailnet/Serve configuration or account policy could be inspected, so none was changed. The scripts will inspect Serve before a future change; the policy example still needs review against the actual tailnet.

Remaining checks are explicit dependencies:

- Owner completes native installation, macOS approval and Tailscale sign-in. Private setup then discovers the real owner login and address; friends' exact identities remain unknown.
- Review real tailnet policy, HTTPS certificate consent and absence of conflicting Serve/Funnel services. Validate policy in Tailscale's editor; the synthetic example has not been submitted to that service.
- Inspect the actual private HTTPS page/certificate, secure context and authenticated WSS upgrade from a second physical Tailscale device. Verify real missing/denied identity and attempted header spoofing through Serve.
- Inspect actual private sockets and selected ICE candidates/counters on Tailscale. Configuration generation and local media tests alone do not establish those results.
- Complete intelligible human two-way audio from separate homes, mute/unmute, participant updates, leave/rejoin and a client network interruption/recovery. No physical microphone/headphone check or remote device/browser/network has been confirmed.
- Sample real private-call resource use, including the Tailscale process separately.

Use the [exact manual test](remote-access.md#exact-manual-call-test-still-needed). The owner has not confirmed personally running setup, reading code, understanding the access design or hearing audio. [Learning exercises and attribution](learning.md) keep assisted implementation separate from personal evidence. Linux deployment, monitoring/incident exercises, tested backup recovery and cloud deployment remain later batches.
