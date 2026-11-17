# Project learning notes

Pink Party is Victoria Prado's personal gaming and operations portfolio project. The application integrates LiveKit voice transport with local/private access, a pink interface, Linux services, monitoring, recovery and hosted verification. LiveKit and its SDKs provide the voice transport.

On 16 November 2026, the owner completed native Tailscale installation, sign-in, first-use onboarding and HTTPS consent, and confirmed hearing their speech through Pink Party in Chrome on one Mac. They also confirmed speech after swapping the muted tab, silence/restored speech with mute/unmute, and leave/rejoin with participant-count updates. Exact audio device selection was not confirmed. No second physical device was available.

The private-access work included policy review and backup, a scoped owner-only network grant, socket checks, real Serve verification and separate Tailscale resource sampling. See [operational validation](validation-batch-3.md) for the recorded results and unresolved Safari/WebKit failure. The Linux and later operations exercises are recorded below.

## Linux deployment and practical exercises

The Linux stage on 16 November 2026 added Lima, an Ubuntu ARM64 VM, deployment scripts and a restricted systemd service. Automated exercises verified permissions, loopback sockets, backend-crash recovery, rejected configuration and journal diagnostics. The local browser/audio suite also passed inside the VM. See [Linux validation](validation-linux.md) and [repeatable operations](linux-deployment.md).

The validation reports retain the actual environment, commands, observations and limitations for each exercise.

## Scheduled monitoring and incident exercise

The monitoring stage on 16 November 2026 added an independent systemd timer, service-cgroup ownership checks, bounded history and journal retention. A controlled service stop exercised status, socket and journal diagnosis, followed by service restoration and scheduled recovery. A separate failed-activation exercise verified that monitoring continued after rejected deployment and that normal service and credentials were restored. The [incident report](incident-linux-monitoring.md) records the timeline and limits; [operations](linux-deployment.md#scheduled-monitoring) provides repeatable commands.

The scheduled probe covers web/control readiness. Synthetic media reception is verified separately by the browser suite.

Questions for a later walkthrough:

- Why must the monitor remain independent of the application unit?
- How can a monitor execution succeed while the application is down, and how would you notice a failed monitor?
- Which timestamps measure service restoration and which measure scheduled recovery detection?
- What can an internal health probe miss, and what would an external watchdog or media test add?

## Scheduled backups and restoration

The backup stage on 16 November 2026 covered the startup-only synthetic session, private environment and generated LiveKit configuration. The systemd snapshot job uses locking, integrity checks, restrictive permissions and retention. The exercise observed a normal scheduled capture, compared a separate restore with the captured files, served changed synthetic data, removed the session file and verified startup failure, then restored the earlier session and verified the API response. Failed-backup and missing/corrupt-restore cases protected the deployment, credentials and previous archives. The [recovery report](recovery-linux-backups.md) gives observations; [operations](linux-backups.md) provides repeatable commands.

Same-disk snapshots cover file recovery and do not protect against VM/disk loss. The later [encrypted recovery stage](recovery-off-vm.md) adds storage outside the guest and a fresh Linux rebuild, with its own failure boundary.

Questions for a later walkthrough:

- Which files contain original data or credentials, and which are rebuilt or generated?
- Why does publishing a completed backup require more than successfully running tar?
- Why must restore reject archive paths and links even when a checksum matches?
- Why does a restored session require restart, while generated LiveKit YAML should be regenerated?
- Which observed time measures file restoration, and which includes application startup and API verification?
- What would an off-VM encrypted copy add, and what new access/key-management duties would it create?

## First cloud deployment and teardown

The AWS stage on 16 and 17 November 2026 used AWS Free, temporary CLI/cloud-node sign-in and an approved temporary network grant. Deployment helpers and Linux private-mode support provisioned an ARM64 Ubuntu host for service, backup, outage, reboot and cross-host synthetic-media checks. Cleanup restored configuration/policy and verified deletion of the instance, disk, address and network resources. The [cloud report](cloud-report.md) records scope, costs, timings and limits; [operations](cloud-deployment.md) provides repeatable commands.

Cloud backups remained on the host disk. Physical listening on the cloud path and separate-home human voice remain unverified. The later encrypted recovery stage is local and does not establish a cloud restore.

Questions for a later walkthrough:

- Why do credits on a Paid account differ from an active Free plan, and why does powering off a VM leave storage costs?
- Which checks establish trusted HTTPS, real remote identity, signaling, media reception and human listening?
- Why can the root monitor supply an identity header locally while a remote browser must use Serve?
- What did the separate-directory restore protect, and which losses would require independent backup storage?

## Encrypted off-VM recovery

The encrypted recovery stage on 17 November 2026 used age with a dedicated recovery identity retained separately from an off-VM Mac vault. The exercise exported a real scheduled synthetic capture, stopped the original guest and rebuilt a fresh Ubuntu ARM64 guest from public source and encrypted recovery material. Private comparisons verified exact files, loaded credentials and the served marker, alongside failure-boundary and service checks. The [recovery report](recovery-off-vm.md) records measured results and cleanup; [operations](encrypted-recovery.md) provides reproducible steps.

The vault and key share one physical Mac. Off-device protection and recovery after physical Mac loss remain untested.

Questions for a later walkthrough:

- Which loss can an off-VM vault on the same Mac survive, and which loss removes it too?
- Why does the source need a public recipient while recovery needs a separately retained identity?
- Why must successful age decryption precede archive parsing and file publication?
- What do authentication, SHA-256 consistency and provenance each establish?
- How do the recovered marker, process environment and decoded media distinguish restoration from a default install or HTTP-only check?

## Hosted continuous verification

The CI stage on 17 November 2026 added a GitHub Actions workflow for source and synthetic media checks on a standard public Ubuntu ARM64 runner. A successful hosted run was followed by an isolated deliberately failing test, confirming that later application/media work did not execute. The failure branch/worktree were removed. [The CI record](continuous-verification.md) links actual runs, permissions, cost boundary and limitations.

CI covers source checks, checksum-pinned dependencies, test failure propagation and ephemeral fixture handling. It does not deploy. The retained Linux VM and private recovery material were not used by the runner.

Questions for a later walkthrough:

- What does a green hosted run establish, and which operational claims need separate evidence?
- How do failed exit codes stop later work, and why test that on an isolated branch?
- Why use a pinned read-only checkout, disposable credentials and no private host files?
- What would change if the repository became private or the runner type changed?

## Follow a join request

1. `index.html` contains the page and labelled controls; `src/main.ts` connects them to the voice controller and renders session data and real participant state.
2. `src/voice.ts` posts the display name and code to `/api/voice-token`. It prevents a second active join attempt and allows cancellation.
3. `server/app.ts` and `server/access.ts` check the local or private request boundary and bound request size, rate and concurrency. `server/admission.ts` validates the name/code, creates the room with a cap of four, checks occupancy and signs a 60-second token using server-only credentials.
4. The browser obtains a microphone track and connects to LiveKit using that token; in private mode, signaling goes through the authenticated HTTPS proxy. It publishes microphone audio and attaches subscribed remote audio tracks to audio elements. Signaling uses WebSocket; audio uses encrypted WebRTC over loopback UDP locally, or the configured Tailscale IPv4 in private mode.
5. SDK events update the participant list, mute state and connection status. Leave, cancellation and failed joins stop tracks, remove audio elements and disconnect. Connection loss offers reconnection or a fresh join.

Start with `server/config.ts`, `server/admission.ts` and `src/voice.ts`. Then read `scripts/start.ts` to understand how the local services and generated configuration fit together. `tests/browser/media.spec.ts` shows how received bytes, decoded samples and audio energy establish synthetic media reception.

## Further lab exercises

Run setup and checks yourself; explain each service and port. Make a small change to the fictional session JSON, restart, and check the timezone. Repeat the listening check from a second physical device, then with an invited friend in another home. Record the changes, observations and diagnosis for each exercise.

## Interview questions

- Why does the browser need an application server to obtain a LiveKit token? Which secrets stay on the server?
- What happens if two people try to take the fourth seat at the same time? Why is an occupancy check alone insufficient?
- What does the token's 60-second expiry control, and why does a call keep working after that minute?
- How are the page, signaling and audio paths different? Why does a successful health endpoint not prove voice works?
- How do cancellation, microphone denial and leaving release resources? What could happen if a late capture result were ignored?
- What do the automated audio checks prove? What remains to test with physical devices and friends in separate homes?
- How do the source, service configuration and test reports explain the observed behaviour?

## Short physical-microphone check

1. Start the app, put on headphones, and open localhost:3000 in a regular and a private browser window. Join with two different display names, using the local code. Allow real microphone access.
2. Mute the private window. Speak into the microphone and listen for the voice arriving from the regular window through the private window's audio. Check that the remote mute label changes when toggled.
3. Swap which window is muted and repeat. Leave both rooms; the browser should release the microphone and both participant lists should empty.

Record your browser, input/output devices, whether speech was intelligible, and any errors. This is a listening check on one computer. Two people on separate devices and a call between separate homes remain later tests.

## Private-network practice

The setup and same-Mac listening checks above are recorded. The following walkthrough and peer-device exercises provide further ways to inspect the implementation; they are not prerequisites for continuing the project.

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
- Which boundaries remain unverified, and what evidence would establish them?

Add dated observations from completed exercises. Keep real login names, addresses and private device details outside the public repository.

## Scheduled encrypted recovery and freshness

I closed the gap between scheduled Linux snapshots and the manual off-VM export. A separate systemd service encrypts validated completed captures, while a Mac user agent collects only ciphertext and authenticates the archive before rolling retention. The original tested export and recovery identity stay outside automation.

The job records separate attempts, export success, authenticated collection and snapshot capture time. Revalidating an old copy does not make its data new. I used scheduled failures and recovery to check this distinction, including temporary key references, missing/stale captures and interrupted transfer. The [batch-10 report](scheduled-export-report.md) records the observations and [operations guide](scheduled-exports.md) explains the locking, spare publication slot and ambiguous post-publication failures.

The vault and identity still share the physical Mac. This stage protects access to guest recovery material; independent device/host-loss recovery needs separate custody.
