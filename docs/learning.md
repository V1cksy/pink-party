# Contribution and learning record

The project owner selected the gaming hangout, required the pink design and voice chat, and agreed the local-first scope. Codex generated the initial application, LiveKit integration, startup/configuration scripts, tests and documentation, then ran and debugged the automated checks. A separate Codex reviewer inspected the implementation. LiveKit and its SDKs provide the voice transport.

The owner has not yet confirmed personally running the setup, testing a physical microphone, reading the implementation or explaining its behaviour. Those steps remain pending. This project does not establish completed Linux administration, cloud deployment, remote access, incident response or backup recovery work.

## Follow a join request

1. `index.html` contains the page and labelled controls; `src/main.ts` connects them to the voice controller and renders session data and real participant state.
2. `src/voice.ts` posts the display name and code to `/api/voice-token`. It prevents a second active join attempt and allows cancellation.
3. `server/app.ts` checks the local request boundary and bounds request size, rate and concurrency. `server/admission.ts` validates the name/code, creates the room with a cap of four, checks occupancy and signs a 60-second token using server-only credentials.
4. The browser obtains a microphone track and connects directly to LiveKit using that token. It publishes microphone audio and attaches subscribed remote audio tracks to audio elements. Signaling uses WebSocket; audio uses encrypted WebRTC over loopback UDP.
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
