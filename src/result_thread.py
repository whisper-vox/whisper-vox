# Whisper Vox - voice dictation for Windows.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

import time
import threading
import traceback
import numpy as np
import sounddevice as sd
from collections import deque
from threading import Event

from transcription import transcribe, friendly_error
from config_manager import ConfigManager


# Names that are capture-capable but are NOT real microphones (loopback of
# speakers, mixers, generic mappers, line/SPDIF ports). A safety net on top of
# the WASAPI host-API filter below.
_NOT_A_MIC = (
    'output', 'speaker', 'loopback', 'stereo mix', 'what u hear', 'wave out',
    'spdif', 'sound mapper', 'primary sound capture', 'sum', 'line out',
)

# Cached recording target, so the hot path (activation key -> capture) never has
# to scan devices or reinit PortAudio. Primed at startup, refreshed in the
# BACKGROUND after each recording. _pa_lock serialises a PortAudio reinit against
# an open recording stream (Pa_Terminate would otherwise kill a live stream).
_pa_lock = threading.Lock()
_cached_device = None   # resolved PortAudio index, or None = system default
_cached_rate = None     # native sample rate; None until primed

# Continuous-mode energy VAD: normalized RMS (0..1) below this counts as silence.
_SILENCE_THRESHOLD = 0.02


def _pa_reinit():
    """Refresh PortAudio's device cache. It is captured once at import time, so a
    headset plugged in afterwards (and the new Windows default that comes with
    it) stays invisible until we tear PortAudio down and bring it back up."""
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass


def _preferred_hostapi():
    """Host API we enumerate/record through. WASAPI gives clean, full,
    de-duplicated names that match Windows Sound settings (MME truncates to 31
    chars; WDM-KS emits raw driver strings like '@System32\\drivers\\...').
    Fall back to MME if WASAPI is somehow unavailable."""
    apis = sd.query_hostapis()
    for i, h in enumerate(apis):
        if 'WASAPI' in h['name']:
            return i
    for i, h in enumerate(apis):
        if h['name'] == 'MME':
            return i
    return None


def list_input_devices(refresh=True):
    """Names of real microphones on the preferred host API (de-duplicated),
    for the Settings dropdown. Devices are referenced BY NAME, not by index:
    PortAudio indices shift on reinit/replug, names are stable."""
    if refresh:
        _pa_reinit()
    out, seen = [], set()
    ha = _preferred_hostapi()
    try:
        for d in sd.query_devices():
            if d.get('max_input_channels', 0) <= 0:
                continue
            if ha is not None and d['hostapi'] != ha:
                continue
            name = d['name']
            low = name.lower()
            if any(bad in low for bad in _NOT_A_MIC) or low in seen:
                continue
            seen.add(low)
            out.append(name)
    except Exception:
        pass
    return out


def _resolve_device(name):
    """Map a saved device NAME to a current PortAudio index on the preferred
    host API. Returns None (system default) when the name isn't found - e.g. the
    device was unplugged, or an old config still holds a numeric index."""
    if not name or not isinstance(name, str):
        return None
    ha = _preferred_hostapi()
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get('max_input_channels', 0) <= 0:
                continue
            if ha is not None and d['hostapi'] != ha:
                continue
            if d['name'] == name:
                return i
    except Exception:
        pass
    return None


def default_input_name(refresh=False):
    """Friendly name of the CURRENT default input device - i.e. what the
    "Default microphone" option actually records from right now. Read from the
    preferred (WASAPI) host API so the name is clean and updates when Windows
    switches the default after a headset is plugged in."""
    if refresh:
        _pa_reinit()
    try:
        ha = _preferred_hostapi()
        if ha is not None:
            di = sd.query_hostapis(ha)['default_input_device']
            if di is not None and di >= 0:
                return sd.query_devices(di)['name']
        return sd.query_devices(kind='input')['name']
    except Exception:
        return None


def _resolve_sample_rate(device):
    """Native default sample rate of the device (WASAPI rejects arbitrary rates
    like 16000; we record native and let Whisper resample server-side)."""
    try:
        info = sd.query_devices(kind='input') if device is None else sd.query_devices(device)
        sr = int(info['default_samplerate'])
        return sr if sr > 0 else 16000
    except Exception:
        return 16000


def refresh_device_cache(reinit=False):
    """Resolve the configured input device + its native rate and cache them, so
    the recording hot path opens the stream with ZERO device scanning. Called at
    startup, after a Settings rescan, and in the BACKGROUND after each recording
    (reinit=True) so the next activation already reflects the current default
    device. Serialised with an active recording via _pa_lock."""
    global _cached_device, _cached_rate
    with _pa_lock:
        if reinit:
            _pa_reinit()
        dev = _resolve_device(ConfigManager.get('sound_device'))
        _cached_device, _cached_rate = dev, _resolve_sample_rate(dev)


class ResultThread(threading.Thread):
    """One recording -> transcription cycle, on its own thread.

    Qt-free: where the PyQt5 version emitted statusSignal/resultSignal/levelSignal,
    this calls plain callbacks passed in by the orchestrator. Callbacks fire on
    THIS worker thread, so the caller is responsible for any marshalling it needs
    (e.g. pushing into the WebView from a worker thread). Created fresh per
    activation (threading.Thread is one-shot — start() exactly once).

        on_status(state: str)   'preparing' | 'recording' | 'transcribing' | 'idle'
        on_result(text: str)    final transcription ('' on error/empty)
        on_level(level: float)  normalized 0..1 audio level for the meter
        on_error(reason: str)   recording produced no text — short, user-facing reason
    """

    def __init__(self, on_status=None, on_result=None, on_level=None, on_error=None):
        super().__init__(daemon=True)
        self.is_recording = False
        self.is_running = True
        self._lock = threading.Lock()
        self._on_status = on_status or (lambda s: None)
        self._on_result = on_result or (lambda t: None)
        self._on_level = on_level or (lambda v: None)
        self._on_error = on_error or (lambda r: None)

    def stop_recording(self):
        with self._lock:
            self.is_recording = False

    def stop(self):
        with self._lock:
            self.is_running = False
        self._on_status('idle')
        # join() only from another thread and only once started.
        if self.is_alive() and threading.current_thread() is not self:
            self.join()

    def run(self):
        try:
            if not self.is_running:
                return

            with self._lock:
                self.is_recording = True

            # Show "Preparing..." up front. _record_audio() flips the status to
            # "Recording" itself, the moment the FIRST real audio frame arrives -
            # i.e. when the OS/hardware audio path is actually delivering sound,
            # which is the honest "we're listening now" signal (it also covers the
            # cold-start warm-up: stream.start() returning does NOT mean samples
            # are flowing yet).
            self._on_status('preparing')
            ConfigManager.console_print('Preparing to record...')
            audio_data, sample_rate = self._record_audio()
            # No background reinit here: we don't subscribe to Windows device-
            # change events, so an auto-reinit didn't actually switch to a newly
            # plugged default anyway. Device rescan happens only at startup and
            # via the ↻ button. (On-failure recovery inside _record_audio still
            # reinits when a pinned device won't start - e.g. Bluetooth.)

            if not self.is_running or audio_data is None:
                self._on_status('idle')
                return

            self._on_status('transcribing')
            ConfigManager.console_print('Transcribing...')

            start = time.time()
            result = transcribe(audio_data, sample_rate)
            elapsed = time.time() - start
            # Log timing as a system event, but NEVER the transcribed text.
            ConfigManager.console_print(f'Transcription completed in {elapsed:.2f}s ({len(result)} chars).')
            ConfigManager.console_print(f'Result: {result}', to_file=False)  # stdout only, never logged

            if not self.is_running:
                return

            self._on_status('idle')
            self._on_result(result)

        except Exception as e:
            ConfigManager.console_print(f'ERROR: {type(e).__name__}: {e}')
            ConfigManager.console_print(traceback.format_exc())  # full traceback to stdout + log
            self._on_error(friendly_error(e))   # drives the red overlay cue
            self._on_result('')
        finally:
            self.stop_recording()

    def _record_audio(self):
        # HOT PATH - intentionally minimal: NO PortAudio reinit / device scan
        # here, so capture starts the instant the activation key is pressed (the
        # first words stop getting clipped). Device + native rate come from the
        # cache - primed at startup, refreshed in the background after each
        # recording. _pa_lock stops a background reinit from tearing down this
        # stream mid-recording.
        global _cached_device, _cached_rate
        frame_ms = 30
        recording = []
        with _pa_lock:
            if _cached_rate is None:   # very first use - resolve once (no reinit)
                dev = _resolve_device(ConfigManager.get('sound_device'))
                _cached_device, _cached_rate = dev, _resolve_sample_rate(dev)
            device, sample_rate = _cached_device, _cached_rate

            audio_buffer = deque(maxlen=int(sample_rate * frame_ms / 1000))
            data_ready = Event()

            def callback(indata, frames, time_info, status):
                if status:
                    ConfigManager.console_print(f'Audio status: {status}')
                audio_buffer.extend(indata[:, 0])
                data_ready.set()

            def _open_start(dev, sr):
                # Open AND start - Bluetooth / WDM-KS devices often OPEN fine but
                # fail on start(). Try low latency first (faster), then the
                # device's default. Returns a started stream, or None on failure.
                for lat in ('low', None):
                    s = None
                    try:
                        s = sd.InputStream(samplerate=sr, channels=1, dtype='int16',
                                           blocksize=int(sr * frame_ms / 1000),
                                           latency=lat, callback=callback, device=dev)
                        s.start()
                        try:
                            _nm = sd.query_devices(dev)['name'] if dev is not None else 'system default'
                        except Exception:
                            _nm = '?'
                        ConfigManager.console_print(
                            f'[mic] RECORDING FROM: "{_nm}" (device={dev}, rate={sr}, latency={lat})')
                        return s
                    except Exception as e:
                        ConfigManager.console_print(
                            f'[mic] device={dev} latency={lat} failed: {type(e).__name__}: {e}')
                        if s is not None:
                            try:
                                s.close()
                            except Exception:
                                pass
                return None

            try:
                _dn = sd.query_devices(device)['name'] if device is not None else 'system default'
            except Exception:
                _dn = '?'
            ConfigManager.console_print(f'[mic] opening device={device} ({_dn}) rate={sample_rate}')

            stream = _open_start(device, sample_rate)
            if stream is None:
                # The cached index can go stale (Bluetooth endpoints shift, and
                # the open can succeed yet start() fail with a WDM-KS error). A
                # fresh reinit + re-resolve gives a valid CURRENT index - this is
                # what the old per-recording reinit did, now only on failure so it
                # doesn't slow the common path.
                ConfigManager.console_print('[mic] reinitialising PortAudio and re-resolving...')
                _pa_reinit()
                dev = _resolve_device(ConfigManager.get('sound_device'))
                _cached_device, _cached_rate = dev, _resolve_sample_rate(dev)
                device, sample_rate = _cached_device, _cached_rate
                audio_buffer = deque(maxlen=int(sample_rate * frame_ms / 1000))
                stream = _open_start(device, sample_rate)
            if stream is None and device is not None:
                # Last resort: fall back to the system default so recording still
                # works even if the pinned device refuses to start.
                ConfigManager.console_print('[mic] falling back to the system default device')
                device, sample_rate = None, _resolve_sample_rate(None)
                audio_buffer = deque(maxlen=int(sample_rate * frame_ms / 1000))
                stream = _open_start(device, sample_rate)
            if stream is None:
                raise RuntimeError('Could not open any microphone')

            frame_size = int(sample_rate * frame_ms / 1000)
            # Continuous mode: energy-VAD auto-stop. RMS is already computed for
            # the meter, so this costs nothing extra. The silence timer only
            # starts AFTER speech is first heard, so the quiet moment before you
            # start talking never stops the recording.
            mode = ConfigManager.get('recording_mode', 'hold_to_record')
            silence_ms = ConfigManager.get('silence_duration', 2000)
            speech_started = False
            silence_accum_ms = 0.0
            announced_recording = False
            try:
                while self.is_running and self.is_recording:
                    data_ready.wait(timeout=0.1)
                    data_ready.clear()
                    if len(audio_buffer) < frame_size:
                        continue
                    frame = np.array(list(audio_buffer), dtype=np.int16)
                    audio_buffer.clear()
                    if not announced_recording:
                        # First real audio frame -> the mic is truly live now.
                        # Flip the status window from "Preparing..." to "Recording".
                        self._on_status('recording')
                        announced_recording = True
                    recording.extend(frame)
                    # Feed the status-window level meter. sqrt() is perceptual -
                    # it lifts quiet speech so the meter reacts to soft voices.
                    rms = float(np.sqrt(np.mean((frame.astype(np.float32) / 32768.0) ** 2)))
                    self._on_level(min(1.0, (rms ** 0.5) * 2.6))

                    if mode == 'continuous':
                        if rms >= _SILENCE_THRESHOLD:
                            speech_started = True
                            silence_accum_ms = 0.0
                        elif speech_started:
                            silence_accum_ms += 1000.0 * len(frame) / sample_rate
                            if silence_accum_ms >= silence_ms:
                                ConfigManager.console_print(
                                    'Continuous: silence reached, auto-stopping.')
                                break
            finally:
                try:
                    stream.stop()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass

        audio_data = np.array(recording, dtype=np.int16)
        duration = len(audio_data) / sample_rate
        ConfigManager.console_print(
            f'Recording finished. {audio_data.size} samples, {duration:.2f}s'
        )

        min_ms = ConfigManager.get('min_duration', 100)
        if duration * 1000 < min_ms:
            ConfigManager.console_print('Discarded: too short.')
            return None, sample_rate

        return audio_data, sample_rate
