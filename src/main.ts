import './style.css';
import { VoiceController } from './voice.ts';
import type { VoiceView } from './voice.ts';
import type { Session } from '../server/session.ts';

function element<T extends HTMLElement>(id: string): T {
  const value = document.getElementById(id);
  if (!value) throw new Error(`Missing interface element: ${id}`);
  return value as T;
}
const form = element<HTMLFormElement>('join-form');
const join = element<HTMLButtonElement>('join-button');
const mute = element<HTMLButtonElement>('mute-button');
const leave = element<HTMLButtonElement>('leave-button');
const playback = element<HTMLButtonElement>('playback-button');
const name = element<HTMLInputElement>('display-name');
const code = element<HTMLInputElement>('join-code');
let lastState = 'disconnected';
function render(view: VoiceView) {
  const inRoom = ['connected', 'reconnecting'].includes(view.state);
  const active = inRoom || view.state === 'connecting';
  const status = element('connection-state');
  status.textContent = view.state[0].toUpperCase() + view.state.slice(1);
  status.dataset.state = view.state;
  const message = element('room-message');
  if (message.textContent !== view.message) message.textContent = view.message;
  form.hidden = inRoom;
  name.disabled = active;
  code.disabled = active;
  join.disabled = active;
  join.textContent =
    view.state === 'connecting' ? 'Connecting…' : 'Join voice room';
  element('room-controls').hidden = !active;
  mute.hidden = !inRoom;
  mute.disabled = view.state !== 'connected';
  mute.textContent = view.microphoneEnabled
    ? 'Mute microphone'
    : 'Unmute microphone';
  mute.setAttribute('aria-pressed', String(!view.microphoneEnabled));
  leave.textContent =
    view.state === 'connecting' ? 'Cancel join' : 'Leave room';
  playback.hidden = !view.playbackBlocked;
  element('participant-count').textContent = `${view.people.length} / 4`;
  element('empty-room').hidden = view.people.length !== 0;
  const list = element('participants');
  list.replaceChildren(
    ...view.people.map((person) => {
      const li = document.createElement('li');
      li.dataset.identity = person.identity;
      li.dataset.speaking = String(person.speaking);
      const avatar = document.createElement('span');
      avatar.className = 'avatar';
      avatar.textContent = [...person.name][0]?.toUpperCase() || '?';
      avatar.setAttribute('aria-hidden', 'true');
      const label = document.createElement('span');
      label.className = 'person-name';
      label.textContent = `${person.name}${person.local ? ' (you)' : ''}`;
      const microphone = document.createElement('span');
      microphone.className = 'mic-state';
      microphone.textContent = person.muted
        ? 'Muted'
        : person.speaking
          ? 'Speaking'
          : 'Mic on';
      li.append(avatar, label, microphone);
      return li;
    }),
  );
  if (view.state !== lastState) {
    if (view.state === 'connected') {
      code.value = '';
      mute.focus();
    }
    if (
      active === false &&
      ['connected', 'connecting', 'reconnecting'].includes(lastState)
    )
      join.focus();
  }
  lastState = view.state;
}
const voice = new VoiceController(element('remote-audio'), render);
form.addEventListener('submit', (event) => {
  event.preventDefault();
  void voice.join(name.value, code.value);
});
mute.addEventListener('click', () => void voice.toggleMicrophone());
leave.addEventListener('click', () => void voice.leave());
playback.addEventListener('click', () => void voice.enablePlayback());
window.addEventListener('pagehide', () => void voice.leave());

async function loadSession() {
  try {
    const response = await fetch('/api/session', {
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error('Session unavailable');
    const session: Session = await response.json();
    element('session-game').textContent = session.game;
    element('session-title').textContent = session.title;
    element('session-description').textContent = session.description;
    element('session-tag').textContent = session.tag;
    const date = new Date(session.startsAt);
    element('session-time').textContent =
      `${new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: session.timeZone, timeZoneName: 'shortOffset' }).format(date)} · ${session.timeZone}`;
  } catch {
    element('session-game').textContent = 'Next session unavailable';
    element('session-error').hidden = false;
  }
}
void loadSession();
