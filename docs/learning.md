# Contribution and learning record

The project owner selected the gaming hangout, required the pink design and voice chat, and agreed the local-first scope. Codex generated the application, LiveKit integration, local and private-access configuration, tests and documentation, then ran and debugged the automated checks. A separate Codex reviewer inspected the implementation. LiveKit and its SDKs provide the voice transport.

The owner has not yet confirmed personally running the setup, testing a physical microphone, reading the implementation or explaining its behaviour. Those steps remain pending. The private-access implementation has agent-run tests with a synthetic identity/TLS proxy and real loopback media. Actual Tailscale access and a separate-home human call remain pending. This project does not establish completed Linux administration, cloud deployment, incident response or backup recovery work.

## Follow a join request

1. `index.html` contains the page and labelled controls; `src/main.ts` connects them to the voice controller and renders session data and real participant state.
2. `src/voice.ts` posts the display name and code to `/api/voice-token`. It prevents a second active join attempt and allows cancellation.
3. `server/app.ts` and `server/access.ts` check the local or private request boundary and bounds request size, rate and concurrency. `server/admission.ts` validates the name/code, creates the room with a cap of four, checks occupancy and signs a 60-second token using server-only credentials.
4. The browser obtains a microphone track and connects to LiveKit using that token; in private mode, signaling goes through the authenticated HTTPS proxy. It publishes microphone audio and attaches subscribed remote audio tracks to audio elements. Signaling uses WebSocket; audio uses encrypted WebRTC over loopback UDP locally, or the configured Tailscale IPv4 in private mode.
5. SDK events update the participant list, mute state and connection status. Leave, cancellation and failed joins stop tracks, remove audio elements and disconnect. Connection loss offers reconnection or a fresh join.

Start with `server/config.ts`, `server/admission.ts` and `src/voice.ts`. Then read `scripts/start.ts` to understand how the local services and generated configuration fit together. `tests/browser/media.spec.ts` shows how received bytes, decoded samples and audio energy establish synthetic media reception.

## Owner practice to record next

Run setup and checks yourself; explain each service and port. Make a small change to the fictional session JSON, restart, and check the timezone. Use a physical microphone and headphones for a short human listening test. Record what you changed, observed and understood here, without treating generated code as independently written work.

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

These are exercises to perform and explain; none has been confirmed as completed by the owner.

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
