import {
  ConnectionState,
  createLocalAudioTrack,
  Room,
  RoomEvent,
  Track,
  TrackEvent,
} from 'livekit-client';
import type { LocalAudioTrack, RemoteTrack } from 'livekit-client';

export type VoiceState =
  'disconnected' | 'connecting' | 'connected' | 'reconnecting' | 'error';
export interface Person {
  identity: string;
  name: string;
  local: boolean;
  muted: boolean;
  speaking: boolean;
}
export interface VoiceView {
  state: VoiceState;
  message: string;
  people: Person[];
  microphoneEnabled: boolean;
  playbackBlocked: boolean;
}
interface Attempt {
  room: Room;
  abort: AbortController;
  track?: LocalAudioTrack;
  audio: Map<RemoteTrack, HTMLMediaElement[]>;
  cancelled: boolean;
  toggling: boolean;
}

export function microphoneError(error: unknown): string {
  const name = error instanceof Error ? error.name : '';
  if (name === 'NotAllowedError' || name === 'PermissionDeniedError')
    return 'Microphone permission was denied. Allow the microphone in your browser’s site settings, then join again.';
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError')
    return 'No microphone found. Connect an audio input device, then join again.';
  if (name === 'NotReadableError' || name === 'TrackStartError')
    return 'Your microphone is unavailable. Close other apps using it, check your system input settings, then join again.';
  return 'Could not start the microphone. Check your browser permission and audio input device, then join again.';
}

export class VoiceController {
  private attempt?: Attempt;
  private view: VoiceView = {
    state: 'disconnected',
    message: 'Your seat is waiting. Join when you’re ready.',
    people: [],
    microphoneEnabled: false,
    playbackBlocked: false,
  };
  private onChange: (view: VoiceView) => void;
  private audioContainer: HTMLElement;

  constructor(
    audioContainer: HTMLElement,
    onChange: (view: VoiceView) => void,
  ) {
    this.audioContainer = audioContainer;
    this.onChange = onChange;
    this.emit();
  }

  private emit(patch: Partial<VoiceView> = {}) {
    this.view = { ...this.view, ...patch };
    const room = this.attempt?.room;
    if (
      room &&
      (room.state === ConnectionState.Connected ||
        room.state === ConnectionState.Reconnecting ||
        room.state === ConnectionState.SignalReconnecting)
    ) {
      this.view.people = [
        room.localParticipant,
        ...room.remoteParticipants.values(),
      ].map((person) => ({
        identity: person.identity,
        name: person.name || 'Guest',
        local: person === room.localParticipant,
        muted: !person.isMicrophoneEnabled,
        speaking: person.isSpeaking,
      }));
      this.view.microphoneEnabled = room.localParticipant.isMicrophoneEnabled;
    }
    this.onChange(this.view);
  }

  private async release(attempt: Attempt) {
    attempt.cancelled = true;
    attempt.abort.abort();
    attempt.track?.stop();
    attempt.room.removeAllListeners();
    for (const [track, elements] of attempt.audio) {
      track.detach();
      for (const element of elements) {
        element.pause();
        element.srcObject = null;
        element.remove();
      }
    }
    attempt.audio.clear();
    await attempt.room.disconnect(true);
  }

  private async finish(attempt: Attempt, state: VoiceState, message: string) {
    if (this.attempt !== attempt) return;
    this.attempt = undefined;
    this.emit({
      state,
      message,
      people: [],
      microphoneEnabled: false,
      playbackBlocked: false,
    });
    try {
      await this.release(attempt);
    } catch {
      this.emit({
        message: `${message} Refresh the page if your browser still shows microphone use.`,
      });
    }
  }

  async join(displayName: string, joinCode: string) {
    if (this.attempt) return;
    const attempt: Attempt = {
      room: new Room({ disconnectOnPageLeave: true }),
      abort: new AbortController(),
      audio: new Map(),
      cancelled: false,
      toggling: false,
    };
    this.attempt = attempt;
    this.emit({
      state: 'connecting',
      message: 'Checking your invitation…',
      people: [],
    });
    const current = () => this.attempt === attempt && !attempt.cancelled;
    const room = attempt.room;
    for (const event of [
      RoomEvent.ParticipantConnected,
      RoomEvent.ParticipantDisconnected,
      RoomEvent.TrackMuted,
      RoomEvent.TrackUnmuted,
      RoomEvent.LocalTrackPublished,
      RoomEvent.LocalTrackUnpublished,
      RoomEvent.ActiveSpeakersChanged,
    ]) {
      room.on(event, () => {
        if (current()) this.emit();
      });
    }
    room.on(RoomEvent.TrackSubscribed, (track) => {
      if (!current() || track.kind !== Track.Kind.Audio) return;
      const element = track.attach();
      element.dataset.participantAudio = 'true';
      this.audioContainer.append(element);
      attempt.audio.set(track, [element]);
      void element.play().catch(() => {
        if (current()) this.emit({ playbackBlocked: true });
      });
    });
    room.on(RoomEvent.TrackUnsubscribed, (track) => {
      for (const element of attempt.audio.get(track) ?? []) {
        element.pause();
        element.srcObject = null;
        element.remove();
      }
      track.detach();
      attempt.audio.delete(track);
    });
    room.on(RoomEvent.AudioPlaybackStatusChanged, () => {
      if (current()) this.emit({ playbackBlocked: !room.canPlaybackAudio });
    });
    room.on(RoomEvent.Reconnecting, () => {
      if (current())
        this.emit({
          state: 'reconnecting',
          message:
            'Connection lost. Trying to reconnect… You can leave and join again.',
        });
    });
    room.on(RoomEvent.SignalReconnecting, () => {
      if (current())
        this.emit({
          state: 'reconnecting',
          message:
            'Signaling interrupted. Trying to reconnect… You can leave and join again.',
        });
    });
    room.on(RoomEvent.Reconnected, () => {
      if (current())
        this.emit({
          state: 'connected',
          message: 'Back together. Your connection has recovered.',
        });
    });
    room.on(RoomEvent.Disconnected, () => {
      const failedJoin = this.view.state === 'connecting';
      void this.finish(
        attempt,
        failedJoin ? 'error' : 'disconnected',
        failedJoin
          ? 'Could not connect to voice. The room may be full or LiveKit may be unavailable. Check the services, then join again.'
          : 'Voice disconnected. Check the local services and join again.',
      );
    });
    room.on(RoomEvent.MediaDevicesError, (error) => {
      if (current()) this.emit({ message: microphoneError(error) });
    });
    let stage: 'admission' | 'microphone' | 'connection' = 'admission';
    try {
      const response = await fetch('/api/voice-token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ displayName, joinCode }),
        signal: AbortSignal.any([
          attempt.abort.signal,
          AbortSignal.timeout(8000),
        ]),
      });
      const data = await response.json();
      if (!response.ok)
        throw new Error(
          data.error || 'Could not check your invitation. Try again.',
        );
      if (!current()) return;
      stage = 'microphone';
      this.emit({ message: 'Allow your microphone to take your seat…' });
      const track = await createLocalAudioTrack({
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      });
      if (!current()) {
        track.stop();
        return;
      }
      attempt.track = track;
      // The SDK may reacquire a device after an ended event, even after leave.
      track.on(TrackEvent.Restarted, () => {
        if (!current()) track.stop();
      });
      track.on(TrackEvent.Ended, () => {
        if (current())
          void this.finish(
            attempt,
            'error',
            'Microphone disconnected. Reconnect your device, then join again.',
          );
      });
      stage = 'connection';
      this.emit({ message: 'Connecting to the voice room…' });
      await room.connect(data.url, data.token, {
        maxRetries: 1,
        peerConnectionTimeout: 10_000,
        websocketTimeout: 8000,
      });
      if (!current()) {
        await this.release(attempt);
        return;
      }
      await room.localParticipant.publishTrack(track, {
        source: Track.Source.Microphone,
        stopMicTrackOnMute: true,
      });
      if (!current()) {
        await this.release(attempt);
        return;
      }
      this.emit({ state: 'connected', message: 'You’re in. Say hello!' });
    } catch (error) {
      if (!current()) {
        await this.release(attempt);
        return;
      }
      const message =
        stage === 'microphone'
          ? microphoneError(error)
          : stage === 'admission' &&
              error instanceof Error &&
              error.name === 'Error'
            ? error.message
            : stage === 'admission'
              ? 'Invitation check failed. Check the application server, then join again.'
              : 'Could not connect to voice. The room may be full or LiveKit may be unavailable. Check the services, then join again.';
      await this.finish(attempt, 'error', message);
    }
  }

  async leave() {
    if (this.attempt)
      await this.finish(
        this.attempt,
        'disconnected',
        'You’ve left the room. See you next game!',
      );
  }

  async toggleMicrophone() {
    const attempt = this.attempt;
    if (!attempt || this.view.state !== 'connected' || attempt.toggling) return;
    attempt.toggling = true;
    try {
      await attempt.room.localParticipant.setMicrophoneEnabled(
        !attempt.room.localParticipant.isMicrophoneEnabled,
      );
      if (this.attempt === attempt)
        this.emit({
          message: attempt.room.localParticipant.isMicrophoneEnabled
            ? 'Microphone on. Your room can hear you.'
            : 'Microphone muted. You can still listen.',
        });
    } catch (error) {
      if (this.attempt === attempt)
        this.emit({ message: microphoneError(error) });
    } finally {
      attempt.toggling = false;
    }
  }

  async enablePlayback() {
    const attempt = this.attempt;
    if (!attempt) return;
    try {
      await attempt.room.startAudio();
      for (const elements of attempt.audio.values())
        for (const element of elements) await element.play();
      if (this.attempt === attempt)
        this.emit({ playbackBlocked: !attempt.room.canPlaybackAudio });
    } catch {
      if (this.attempt === attempt)
        this.emit({
          playbackBlocked: true,
          message:
            'Playback is still blocked. Allow sound for localhost in your browser, then click Enable sound.',
        });
    }
  }
}
