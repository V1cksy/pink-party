# Batch 3 validation: native Tailscale operations

Verified on 16 November 2026 on the ARM64 macOS 27.0.1 / 8 GiB host. Node 24.22.2, LiveKit 1.13.11 and the pinned project dependencies were retained. Native Tailscale 1.104.7 is installed, its system network extension is activated, and its signed-in untagged device is connected. The admin console showed the Free plan and one machine. No second physical device or friend login was available.

[Batch 1](validation.md) and [batch 2](validation-batch-2.md) remain historical records. New [local/synthetic counters and resource samples](validation-batch-3-resources.json) and [sanitised real Serve evidence](validation-batch-3-tailnet.json) are separate files. Real identities, addresses, certificates, policy backups and generated settings remain in ignored owner-only storage.

## Actual access configuration

The original Serve configuration was empty. The original policy was the initial unrestricted grant plus the default SSH policy definition. Its complete contents were inspected through the admin editor and preserved privately before changes. There were no other machines or Serve services to preserve.

The unrestricted network grant was replaced with one invited group, initially containing only the actual device owner, targeting only this Mac's Tailscale IPv4. The grant permits TCP 443 and UDP 7882. The default SSH policy definition was retained, but TCP 22 is not granted to this host. The policy editor accepted and saved four assertions: invited TCP/UDP acceptance, denial of the other application/control/media ports by protocol, and an uninvited synthetic source denied on 443 and 7882. These are control-plane policy tests; an uninvited physical peer has not been tested.

The first HTTPS consent page had optional Funnel checked by default. It was unchecked before the owner enabled HTTPS. Active Serve status confirmed no Funnel. Foreground Serve proxies HTTPS 443 to `http://127.0.0.1:3000`; it did not reset an existing handler. The original policy and before/active Serve snapshots are kept privately for rollback.

`setup:private` discovered the actual owner, DNS name and interface address. The generated allowlist contains only that owner. Setup, private startup, foreground Serve and diagnostics were exercised using the native app CLI. No invitation, router forwarding, VM, TURN or public hosting was added.

## HTTPS, identity and media evidence

Node verified the actual certificate chain and hostname without a custom CA or exception. The endpoint negotiated TLS 1.3 with a Let's Encrypt certificate valid from 16 November 2026 10:01:45 UTC to 14 February 2027 10:01:44 UTC. Chromium reported a secure context and rendered the private badge without a join-code field. The actual interface screenshot was inspected; the pink design remains unchanged.

The real Serve suite checked accepted owner identity, replacement of a forged denied-login header, foreign Origin rejection, HTTP Host rejection with correct TLS SNI, exact WSS CSP, missing admission Origin rejection and exclusion of LiveKit administration routes. Both current SDK signaling connections received HTTP 101. Both selected ICE pairs used UDP host candidates matching the configured Tailscale IPv4 on port 7882. Both clients received decoded audio samples with positive energy. The unmute check requires energy growth after the remote unmuted label and a fresh baseline. Leaving stopped capture tracks and removed audio elements.

A separate actual-Serve denial probe temporarily excluded the owner using a process-only synthetic allowlist. It returned 403 for pages, access/session/health APIs, admission and WSS, including a forged header naming that fixture's allowed login. All ten checks passed. The saved owner allowlist was unchanged and normal admission was restored. This demonstrates rejection and header replacement through Serve from the real authenticated Mac; it does not substitute for an uninvited or tagged peer.

Trusted-loopback probes against the actual private backend separately checked missing/denied identity, exact Host/Origin, CSP and blocked administration. Missing identity is also covered by offline injected-header tests. Real missing-identity/tagged-device behavior remains unperformed: no such peer was available. Programs on this Mac remain trusted and can forge loopback identity headers. Remote clients cannot directly reach the loopback backend.

Actual sockets were TCP `127.0.0.1:3000`, TCP `127.0.0.1:7880` and UDP `<configured Tailscale IPv4>:7882`. No application/control wildcard or LAN listener, TCP media listener, TURN or external STUN discovery was used. The selected private UDP path was exercised on this Mac. There were zero Tailscale peers, so direct versus DERP/peer-relay connectivity is not applicable to these observations. This does not prove the separate-home media route.

## Human listening and browser limits

The owner confirmed hearing their spoken phrase through Pink Party in two Chrome 157.0.8103.78 tabs on this Mac. They then confirmed speech after swapping tabs, mute silence, restored speech on unmute, and leave/rejoin with participant-count updates. The room was independently checked empty afterward. This is a same-Mac physical-microphone listening result, with two logical participants and one physical device. No recording was made.

The exact microphone/headset model and listening output selection were not confirmed. The macOS audio inventory immediately afterward listed a built-in mono 48 kHz microphone and built-in stereo 48 kHz speakers as defaults; that inventory does not prove which output the owner heard during the test. Browser network conditions were host-to-own-Serve HTTPS plus local access to the configured private UDP address. No remote-home network was involved.

Safari 27.0.1 loaded the private page but its native microphone attempt stalled or failed. A separate Playwright WebKit 27.2 diagnostic reproduced `could not establish pc connection` after real authenticated WSS 101. ICE was checking with requests sent and no response in the captured sample; its emitted local candidate was a LAN candidate and the server advertised the configured private IPv4. The root cause remains unresolved. A WebKit WSS-only probe succeeded with the original CSP, so no CSP weakening or network-binding change was made. Chromium synthetic media and the owner's Chrome listening check passed. Safari voice support is not claimed.

## Checks and resource measurements

The unchanged baseline passed `npm run check`: 14 offline tests, TypeScript, build and formatting. Initial local browser and synthetic TLS/identity runs passed in 51.1 and 29.1 seconds respectively. Final checks:

| Command                        | Result                                                                                                           |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| `npm run check`                | 14 offline tests, TypeScript, production build and Prettier passed.                                              |
| `npm run test:e2e`             | 13 local-mode cases passed in 41.3 seconds.                                                                      |
| `npm run test:private`         | Two synthetic TLS/identity proxy cases passed in 16.8 seconds.                                                   |
| `npm run test:tailnet`         | One real Serve case passed in 14.5 seconds, using two synthetic microphones on one Mac.                          |
| `npm run diagnose:private`     | Actual device match, trusted HTTPS, owner identity, application health and authenticated LiveKit control passed. |
| `npm run measure:private -- 2` | CLI smoke check sampled app, LiveKit, Tailscale app, network extension and Serve CLI separately.                 |

The existing bundled-client size warning remains. Browser failure, delayed capture, cancellation and SDK restart cleanup regressions still pass. Fresh-context review corrected the new unmute assertion to compare against a fresh post-unmute energy baseline; final review found no remaining code defects. A stale evidence label was corrected to describe checks outside the synthetic suite's scope.

`npm run test:tailnet` is a new opt-in check against running real Serve and an empty private room. It uses normal certificate trust, two synthetic microphones on one Mac and actual WebSocket/ICE/media evidence. It never starts a proxy or supplies a trusted test identity. Its raw private results and screenshots stay ignored. `npm run measure:private -- 10` lists the application, LiveKit and native Tailscale components separately. Follow the [repeatable operations](remote-access.md#repeat-the-real-serve-check).

The new sampler initially failed to find the extension because macOS truncates a `ps` command field when another column follows it. Keeping that field last, then reading arguments only for matching Tailscale processes, fixed discovery. Each same-named process is reported separately. The two-second CLI smoke check and the ten-second real Serve sample exercised discovery on this host. RSS and `ps` CPU are process estimates; browsers, startup supervisors, npm/build tools and unrelated host processes are excluded. No performance improvement or total host cost is claimed.

Ten samples, one second apart, with real Serve and two synthetic Chromium clients on this Mac:

| Process                     | Mean / peak RSS MiB | Mean / peak `ps` CPU % |
| --------------------------- | ------------------- | ---------------------- |
| Application                 | 53.06 / 74.11       | 0.16 / 0.80            |
| LiveKit                     | 74.62 / 77.33       | 4.26 / 5.70            |
| Tailscale app               | 15.72 / 16.19       | 0.13 / 1.20            |
| Tailscale network extension | 26.97 / 33.25       | 2.45 / 2.70            |
| Foreground Serve CLI        | 11.57 / 11.84       | 0.02 / 0.20            |

These are same-host synthetic-call measurements, not remote-call overhead. The earlier zero-client private-backend sample and final local/proxy samples are retained separately in the raw data. Human listening was brief and was not resource-profiled.

## Shutdown and retained settings

Stopping foreground Serve restored the original empty Serve configuration; the HTTPS endpoint stopped responding. The scoped policy, HTTPS consent, owner allowlist and installed Tailscale client remain. Tailscale stays connected. Stopping this app does not disconnect the tailnet or revert access for unrelated services.

Private mode was stopped and local mode restarted successfully for the final browser checks. The final local shutdown released app TCP 3000, control TCP 7880 and media UDP 7882. No Pink Party backend, test proxy or Serve process is left running. Start local mode with `npm start`, or private mode with `npm run start:private` and `npm run serve:private` in separate terminals; stop each terminal with Ctrl+C. The [operations guide](remote-access.md) covers policy review, rollback and adding actual invited logins.

## Remaining peer-device test

Use the [exact manual call test](remote-access.md#exact-manual-call-test-still-needed) when a second physical device and an invited friend's exact Tailscale login are available. Align the real application allowlist and network group, validate the policy again, and have the owner perform the normal invitation/share process. This work sent no messages or invitations.

From separate homes, verify the certificate and WSS, actual selected UDP candidates and increasing decoded audio counters, and intelligible speech in both directions. Record device/browser versions, audio devices, network types, participant count and direct/relayed Tailscale status privately. Check mute/unmute, participant updates, leave/rejoin and a client network interruption/recovery. Test an uninvited/tagged peer and attempted allowed-login spoofing; only a real peer can establish those network boundaries.

Linux deployment, monitoring/incident exercises, tested backup restoration and cloud remain later batches. [Learning notes](learning.md) credit the owner's confirmed actions, assisted implementation and LiveKit's transport separately.
