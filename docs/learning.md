# Contribution and learning record

The project owner selected the gaming hangout, required the pink design and voice chat, and agreed the local-first scope. Codex generated the application, LiveKit integration, local and private-access configuration, tests and documentation, then ran and debugged the automated checks. A separate Codex reviewer inspected the implementation. LiveKit and its SDKs provide the voice transport.

On 16 November 2026, the owner completed native Tailscale installation, sign-in, first-use onboarding and HTTPS consent, and confirmed hearing their speech through Pink Party in Chrome on one Mac. They also confirmed speech after swapping the muted tab, silence/restored speech with mute/unmute, and leave/rejoin with participant-count updates. Exact audio device selection was not confirmed. No second physical device was available.

Codex inspected and privately saved the existing policy, applied the scoped owner-only network grant, ran project setup and socket checks, and implemented the real Serve verification suite and Tailscale resource sampling. The owner has not confirmed independently running project scripts, reading the implementation or explaining its behaviour. See [current operational validation](validation-batch-3.md) for actual Tailscale evidence and the unresolved Safari/WebKit failure. The Linux deployment and Codex-run checks are recorded below. Owner-performed Linux administration, cloud deployment, incident response and backup recovery remain unconfirmed.

## Linux deployment and practical exercises

On 16 November 2026, the owner asked Codex to implement the Linux portfolio stage and perform the practical exercises. Codex installed Lima and an Ubuntu ARM64 VM, created the deployment scripts and restricted systemd service, and tested permissions, loopback sockets, backend-crash recovery, rejected configuration and journal diagnostics. The local browser/audio suite also passed inside the VM. See [Linux validation](validation-linux.md) and [repeatable operations](linux-deployment.md).

These results establish a working project artifact and recorded exercises performed with assistance. They do not record the owner operating Linux or demonstrating independent understanding. Any later owner practice should be added from the owner's actual observations.

## Scheduled monitoring and incident exercise

On 16 November 2026, the owner authorised Codex to implement scheduled Linux monitoring and perform a documented incident exercise. Codex added an independent systemd timer, reused service-cgroup ownership checks, bounded the history and journal, and ran a controlled service stop. Codex inspected status, sockets and journal evidence, restored the service and verified scheduled recovery. A separate failed-activation exercise checked that monitoring continued after a rejected deployment and that normal service and credentials were restored. The [incident report](incident-linux-monitoring.md) records the actual timeline and limits; [operations](linux-deployment.md#scheduled-monitoring) provides repeatable commands.

This adds assisted project evidence for systemd timers, health monitoring, log retention, incident diagnosis and recovery. The probe covers web/control readiness; synthetic media reception is verified separately. The owner has not confirmed independent monitoring or incident practice, and that practice is not required before further implementation.

Questions for a later walkthrough:

- Why must the monitor remain independent of the application unit?
- How can a monitor execution succeed while the application is down, and how would you notice a failed monitor?
- Which timestamps measure service restoration and which measure scheduled recovery detection?
- What can an internal health probe miss, and what would an external watchdog or media test add?

## Scheduled backups and restoration

On 16 November 2026, the owner authorised Codex to implement and exercise Linux backups. Codex inspected the startup-only synthetic session, private environment and generated LiveKit configuration, then implemented a small systemd snapshot job with locking, integrity checks, restrictive permissions and retention. Codex observed a normal scheduled capture, compared a separate restore with the captured files, served changed synthetic data, removed the file and verified startup failure, then restored the earlier session and verified it through the application's API. Failed-backup and missing/corrupt-restore exercises checked that the deployment, credentials and previous archives were protected. The [recovery report](recovery-linux-backups.md) gives actual observations; [operations](linux-backups.md) provides repeatable commands.

This is assisted portfolio evidence for backup scoping, systemd scheduling, integrity validation and file recovery. It is not independent owner practice or professional backup administration. Same-disk snapshots do not protect against VM/disk loss. Cloud and independent backup storage remain later work; owner practice is not a prerequisite for further implementation.

Questions for a later walkthrough:

- Which files contain original data or credentials, and which are rebuilt or generated?
- Why does publishing a completed backup require more than successfully running tar?
- Why must restore reject archive paths and links even when a checksum matches?
- Why does a restored session require restart, while generated LiveKit YAML should be regenerated?
- Which observed time measures file restoration, and which includes application startup and API verification?
- What would an off-VM encrypted copy add, and what new access/key-management duties would it create?

## Follow a join request

1. `index.html` contains the page and labelled controls; `src/main.ts` connects them to the voice controller and renders session data and real participant state.
2. `src/voice.ts` posts the display name and code to `/api/voice-token`. It prevents a second active join attempt and allows cancellation.
3. `server/app.ts` and `server/access.ts` check the local or private request boundary and bounds request size, rate and concurrency. `server/admission.ts` validates the name/code, creates the room with a cap of four, checks occupancy and signs a 60-second token using server-only credentials.
4. The browser obtains a microphone track and connects to LiveKit using that token; in private mode, signaling goes through the authenticated HTTPS proxy. It publishes microphone audio and attaches subscribed remote audio tracks to audio elements. Signaling uses WebSocket; audio uses encrypted WebRTC over loopback UDP locally, or the configured Tailscale IPv4 in private mode.
5. SDK events update the participant list, mute state and connection status. Leave, cancellation and failed joins stop tracks, remove audio elements and disconnect. Connection loss offers reconnection or a fresh join.

Start with `server/config.ts`, `server/admission.ts` and `src/voice.ts`. Then read `scripts/start.ts` to understand how the local services and generated configuration fit together. `tests/browser/media.spec.ts` shows how received bytes, decoded samples and audio energy establish synthetic media reception.

## Owner practice to record next

Run setup and checks yourself; explain each service and port. Make a small change to the fictional session JSON, restart, and check the timezone. Repeat the listening check from a second physical device, then with an invited friend in another home. Record what you changed, observed and understood here, without treating generated code as independently written work.

## Interview questions

- Why does the browser need an application server to obtain a LiveKit token? Which secrets stay on the server?
- What happens if two people try to take the fourth seat at the same time? Why is an occupancy check alone insufficient?
- What does the token's 60-second expiry control, and why does a call keep working after that minute?
- How are the page, signaling and audio paths different? Why does a successful health endpoint not prove voice works?
- How do cancellation, microphone denial and leaving release resources? What could happen if a late capture result were ignored?
- What do the automated audio checks prove? What remains to test with physical devices and friends in separate homes?
- Which code was generated with assistance, and which parts have you personally changed, tested and learned to explain?

## Short physical-microphone check

1. Start the app, put on headphones, and open localhost:3000 in a regular and a private browser window. Join with two different display names, using the local code. Allow real microphone access.
2. Mute the private window. Speak into the microphone and listen for the voice arriving from the regular window through the private window's audio. Check that the remote mute label changes when toggled.
3. Swap which window is muted and repeat. Leave both rooms; the browser should release the microphone and both participant lists should empty.

Record your browser, input/output devices, whether speech was intelligible, and any errors. This is a listening check on one computer. Two people on separate devices and a call between separate homes remain later tests.

## Private-network practice

The owner has completed the setup and same-Mac listening steps above. The code walkthrough, independent diagnostics and peer-device exercises below still need owner observations.

1. Read the [network diagram and operations guide](remote-access.md). Trace a page request, an allowlist rejection, a token request and the separate signaling/media paths. Find the matching checks in `server/access.ts`, `server/admission.ts` and `server/signaling.ts`.
2. Run local mode, inspect the three sockets with `lsof`, and stop it. After Tailscale setup, repeat in private mode. Explain why the application still listens on loopback while UDP 7882 changes address.
3. With a second device, test an invited and an uninvited login. Compare the app allowlist with the tailnet policy. Explain what happens if the policy still contains an allow-all rule, and why a browser-supplied identity header must be replaced by Serve.
4. Complete the guide's short real-microphone/headphone check and separate-home call. Check the certificate, WSS upgrade and received audio separately. Record what each person actually heard, then test mute, leave and reconnect.
5. Stop Serve while a test client is connected. Observe which layer fails, restore it and try recovery. Then stop the backend and restore it. Record the result and whether a fresh join was required. These are proposed exercises, not a completed incident-response record.

Additional interview questions:

- What does TLS protect, and why can the page load while voice still fails?
- Who verifies a Tailscale identity? At which local boundary does the app trust it, and what can a program already running on the host forge?
- Why do network rules and the application allowlist both exist? Why are additive grants easy to misconfigure?
- What does an ICE selected candidate pair establish? Which counters and listening checks would you use to distinguish media delivery from microphone or playback failure?
- How would you remove an invited user during a call? Why are token expiry and immediate revocation different?
- What remains unverified in this project, and which implementation/operation steps have you personally performed?

Append dated owner observations only after the owner confirms them. Keep real login names, addresses and private device details outside the public repository.
