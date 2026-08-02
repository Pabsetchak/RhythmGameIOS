"""
Audio: mixer setup, the synthesized hit-sound bank, music transport, and
waveform analysis for the editor.

Carried over from the desktop build with two changes: the sample bank is
written to the writable data directory rather than beside the source, and
the default mixer buffer is chosen per platform (iOS audio units dislike
very small buffers and answer them with dropouts rather than low latency).
"""

import array
import math
import os
import random
import struct
import wave

import pygame

import paths
import platform_compat

# Versioned so changing the synthesis regenerates the bank instead of
# reusing stale samples.
HITS_DIR = os.path.join(paths.ASSETS_DIR, "hits_v3")

# kind -> (body Hz, brightness, click, length, gain)
_KIND_PARAMS = {
    "perfect": (2100.0, 1.00, 0.90, 0.075, 1.00),   # bright, shimmery
    "good":    (1700.0, 0.55, 0.80, 0.065, 0.95),   # the standard tick
    "bad":     (1150.0, 0.20, 0.50, 0.060, 0.90),   # duller
    "ghost":   (1500.0, 0.30, 0.90, 0.030, 0.45),   # tiny neutral tick
    "miss":    (340.0,  0.00, 0.12, 0.090, 0.60),   # soft low thud
}
_VARIANTS = {"perfect": 3, "good": 3, "bad": 3, "ghost": 1, "miss": 1}
_PITCH_STEPS = [0.96, 1.0, 1.045]


def init_audio(buffer=None, frequency=44100):
    """
    (Re)initialize the mixer for low output latency. pygame only applies the
    buffer size on a fresh init, so any existing mixer is torn down first.
    Safe to call repeatedly.
    """
    if buffer is None:
        try:
            from settings_store import settings
            buffer = int(settings.get("AUDIO_BUFFER", 0))
        except Exception:
            buffer = 0
    if not buffer:
        buffer = platform_compat.audio_buffer_default()

    if pygame.mixer.get_init():
        pygame.mixer.quit()
    try:
        pygame.mixer.init(frequency=frequency, size=-16, channels=2,
                          buffer=buffer)
    except pygame.error:
        try:
            pygame.mixer.init()          # let SDL pick if the device is fussy
        except pygame.error as e:
            print(f"Audio unavailable: {e}")
            return
    try:
        # Plenty of channels so dense chords never cut each other off.
        pygame.mixer.set_num_channels(32)
    except pygame.error:
        pass


# ---------------------------------------------------------------------------- #
# Hit-sound bank
# ---------------------------------------------------------------------------- #
def _synth(path, freq, brightness, click, length, seed, attack=0.0):
    """
    One hit sample: a high-passed noise click over a short two/three-partial
    tonal body with a snappy exponential decay. Peak stays near 24000/32767
    so simultaneous hits sum without clipping.
    """
    framerate = 44100
    n = int(framerate * length)
    peak = 24000
    rng = random.Random(seed)
    decay = 5.5 / length

    frames = bytearray()
    prev_noise = 0.0
    for i in range(n):
        t = i / framerate
        env = math.exp(-t * decay)
        body = (0.62 * math.sin(2 * math.pi * freq * t)
                + 0.28 * math.sin(2 * math.pi * freq * 2.0 * t)
                + 0.18 * brightness * math.sin(2 * math.pi * freq * 3.2 * t))
        v = body * env
        if t < 0.003:
            noise = rng.uniform(-1.0, 1.0)
            v += click * (noise - prev_noise) * (1.0 - t / 0.003)
            prev_noise = noise
        if attack > 0 and t < attack:
            v *= t / attack
        value = max(-32767, min(32767, int(peak * v)))
        frames += struct.pack("<hh", value, value)

    with wave.open(path, "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(framerate)
        w.writeframes(bytes(frames))
    return path


def ensure_hitsound_bank(directory=HITS_DIR):
    """
    Make sure every sample exists on disk, synthesizing any that are missing.
    Pitch variants are pre-baked because pygame cannot repitch at play time.
    """
    os.makedirs(directory, exist_ok=True)
    bank = {}
    for kind, (freq, brightness, click, length, _gain) in _KIND_PARAMS.items():
        found = []
        count = _VARIANTS[kind]
        for i in range(count):
            pitch = _PITCH_STEPS[i] if count > 1 else 1.0
            path = os.path.join(directory, f"{kind}_{i}.wav")
            if not os.path.exists(path):
                try:
                    _synth(path, freq * pitch, brightness, click, length,
                           seed=(hash(kind) + i) & 0xFFFF,
                           attack=0.004 if kind == "miss" else 0.0)
                except OSError as e:
                    print(f"Could not write hit sound {path}: {e}")
                    continue
            found.append(path)
        bank[kind] = found
    return bank


class HitSoundBank:
    """
    Fire-and-forget playback with round-robin variant rotation (never the
    same variant twice running) and slight per-play volume jitter, so dense
    streams don't fatigue.
    """

    def __init__(self, volume=0.5):
        self.volume = float(volume)
        self._rng = random.Random()
        self._rr = {}
        self.sounds = {}
        for kind, files in ensure_hitsound_bank().items():
            loaded = []
            for p in files:
                try:
                    loaded.append(pygame.mixer.Sound(p))
                except pygame.error:
                    pass
            if loaded:
                self.sounds[kind] = loaded

    def set_volume(self, volume):
        self.volume = float(volume)

    def play(self, kind="good"):
        sounds = self.sounds.get(kind) or self.sounds.get("good")
        if not sounds:
            return
        if len(sounds) > 1:
            prev = self._rr.get(kind, -1)
            idx = (prev + self._rng.randint(1, len(sounds) - 1)) % len(sounds)
        else:
            idx = 0
        self._rr[kind] = idx
        snd = sounds[idx]
        gain = self.volume * _KIND_PARAMS.get(kind, _KIND_PARAMS["good"])[4]
        gain *= self._rng.uniform(0.88, 1.0)
        # Volume on the Sound (not the channel) so the attack transient is
        # already at level when it starts.
        snd.set_volume(max(0.0, min(1.0, gain)))
        snd.play()


# ---------------------------------------------------------------------------- #
# Music transport
# ---------------------------------------------------------------------------- #
def sound_length(path):
    """Duration of an audio file in seconds, or 0.0 if it can't be read."""
    try:
        return pygame.mixer.Sound(path).get_length()
    except (pygame.error, FileNotFoundError):
        return 0.0


def play_music(path, start=0.0):
    """
    Start a track, optionally from an offset. Returns the offset actually
    used — some SDL/MP3 builds reject a start position, in which case
    playback begins at zero and the caller needs to know.
    """
    try:
        pygame.mixer.music.load(path)
    except pygame.error as e:
        print(f"Could not load music: {e}")
        return None
    if start > 0:
        try:
            pygame.mixer.music.play(start=start)
            return start
        except pygame.error:
            pass
    try:
        pygame.mixer.music.play()
    except pygame.error as e:
        print(f"Could not play music: {e}")
        return None
    return 0.0


def stop_music():
    try:
        pygame.mixer.music.stop()
    except pygame.error:
        pass


def music_pos():
    """Seconds since playback started, or -1 if not playing."""
    try:
        ms = pygame.mixer.music.get_pos()
    except pygame.error:
        return -1.0
    return ms / 1000.0 if ms >= 0 else -1.0


# ---------------------------------------------------------------------------- #
# Waveform analysis
# ---------------------------------------------------------------------------- #
def load_waveform(path, buckets=1500):
    """
    Peak-amplitude envelope in 0..1, used to draw the editor's waveform.
    Decodes through the mixer with only the stdlib, so there is no numpy or
    pydub dependency to find an iOS wheel for.
    """
    try:
        if not pygame.mixer.get_init():
            init_audio()
        raw = pygame.mixer.Sound(path).get_raw()
    except (pygame.error, FileNotFoundError):
        return []

    samples = array.array("h")
    try:
        samples.frombytes(raw)
    except (ValueError, TypeError):
        return []

    n = len(samples)
    if n == 0 or buckets <= 0:
        return []

    peaks = [0.0] * buckets
    per = n / buckets
    for b in range(buckets):
        start = int(b * per)
        end = min(n, max(start + 1, int((b + 1) * per)))
        # Stride within the bucket so long songs stay fast to scan.
        step = max(1, (end - start) // 48)
        peak = 0
        for i in range(start, end, step):
            v = samples[i]
            if v < 0:
                v = -v
            if v > peak:
                peak = v
        peaks[b] = peak

    mx = max(peaks) or 1
    return [p / mx for p in peaks]
