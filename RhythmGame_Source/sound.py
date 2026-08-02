import os
import math
import wave
import struct
import array
import random

ASSETS_DIR = "assets"
# Directory is versioned so updating the synthesis regenerates the assets
# instead of reusing old files.
HITS_DIR = os.path.join(ASSETS_DIR, "hits_v3")

# Mixer output buffer (samples). Smaller = lower latency, so hit sounds land
# closer to the key press. 128 @ 44.1 kHz ≈ 3 ms. Raise it (e.g. 256 or 512)
# if you hear crackling/popping.
AUDIO_BUFFER = 128

# ---------------------------------------------------------------------------- #
# Hit-sound bank
#
# Design follows standard rhythm-game feedback practice: each sound is a
# transient-forward percussive event — a sharp high-passed noise "click" layer
# (sub-5 ms attack) over a short tonal body — so it cuts through the music and
# reads as a discrete tick even in dense streams. Judgments get distinct
# timbres (accuracy information through the ears), and each judgment has
# round-robin pitch variants plus per-play volume jitter to avoid the fatigue
# of hearing one identical waveform on every note.
# ---------------------------------------------------------------------------- #

# kind -> synthesis parameters and relative gain.
_KIND_PARAMS = {
    #          body Hz  bright  click  length  gain
    "perfect": (2100.0,  1.00,  0.90,  0.075,  1.00),   # bright, shimmery
    "good":    (1700.0,  0.55,  0.80,  0.065,  0.95),   # the standard tick
    "bad":     (1150.0,  0.20,  0.50,  0.060,  0.90),   # duller
    "ghost":   (1500.0,  0.30,  0.90,  0.030,  0.45),   # tiny neutral tick
    "miss":    (340.0,   0.00,  0.12,  0.090,  0.60),   # soft low thud
}
_VARIANTS = {"perfect": 3, "good": 3, "bad": 3, "ghost": 1, "miss": 1}
_PITCH_STEPS = [0.96, 1.0, 1.045]      # round-robin detune per variant


def init_audio(buffer=None, frequency=44100):
    """
    (Re)initialize the mixer for low output latency so hit sounds line up with
    key presses. pygame only honours the buffer size on a fresh init, so this
    quits any existing mixer first. Safe to call repeatedly.

    The buffer size defaults to the user's AUDIO_BUFFER setting (smaller = less
    latency, but too small can crackle).
    """
    import pygame
    if buffer is None:
        try:
            from settings import settings
            buffer = int(settings.get("AUDIO_BUFFER", AUDIO_BUFFER))
        except Exception:
            buffer = AUDIO_BUFFER
    if pygame.mixer.get_init():
        pygame.mixer.quit()
    try:
        pygame.mixer.init(frequency=frequency, size=-16, channels=2, buffer=buffer)
    except Exception:
        pygame.mixer.init()   # fall back to defaults if the device is fussy
    # Plenty of channels so overlapping fire-and-forget hits never cut each
    # other off, even in dense chords/streams.
    try:
        pygame.mixer.set_num_channels(32)
    except Exception:
        pass


def _synth(path, freq, brightness, click, length, seed, attack=0.0):
    """
    Synthesize one hit sample: a high-passed noise click layered over a short
    two/three-partial tonal body with a snappy exponential decay.

    Peak is kept at ~24000/32767 so several simultaneous hits (chords) sum
    without clipping.
    """
    framerate = 44100
    n = int(framerate * length)
    peak = 24000
    rng = random.Random(seed)
    decay = 5.5 / length          # amplitude falls to ~e^-5.5 by the end

    frames = bytearray()
    prev_noise = 0.0
    for i in range(n):
        t = i / framerate
        env = math.exp(-t * decay)
        body = (0.62 * math.sin(2 * math.pi * freq * t)
                + 0.28 * math.sin(2 * math.pi * freq * 2.0 * t)
                + 0.18 * brightness * math.sin(2 * math.pi * freq * 3.2 * t))
        v = body * env
        # Click layer: first-difference of white noise tilts it toward high
        # frequencies (a crude high-pass), gated to the first 3 ms.
        if t < 0.003:
            noise = rng.uniform(-1.0, 1.0)
            v += click * (noise - prev_noise) * (1.0 - t / 0.003)
            prev_noise = noise
        # Optional attack ramp (used by the miss thud so it isn't harsh).
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
    Make sure the full hit-sound bank exists on disk, synthesizing any missing
    samples. Returns {kind: [paths...]}. Pitch variants are pre-baked because
    pygame can't repitch a Sound at play time.
    """
    os.makedirs(directory, exist_ok=True)
    bank = {}
    for kind, (freq, brightness, click, length, _gain) in _KIND_PARAMS.items():
        paths = []
        count = _VARIANTS[kind]
        for i in range(count):
            pitch = _PITCH_STEPS[i] if count > 1 else 1.0
            path = os.path.join(directory, f"{kind}_{i}.wav")
            if not os.path.exists(path):
                _synth(path, freq * pitch, brightness, click, length,
                       seed=(hash(kind) + i) & 0xFFFF,
                       attack=0.004 if kind == "miss" else 0.0)
            paths.append(path)
        bank[kind] = paths
    return bank


def ensure_hit_sound():
    """Backward-compatible alias: returns the path of the standard tick."""
    return ensure_hitsound_bank()["good"][1]


class HitSoundBank:
    """
    Loads the bank as pygame Sounds and plays them fire-and-forget with
    round-robin variant rotation (never the same variant twice in a row) and
    slight per-play volume jitter.
    """

    def __init__(self, volume=0.5):
        import pygame
        self.volume = float(volume)
        self._rng = random.Random()
        self._rr = {}
        self.sounds = {}
        for kind, paths in ensure_hitsound_bank().items():
            loaded = []
            for p in paths:
                try:
                    loaded.append(pygame.mixer.Sound(p))
                except Exception:
                    pass
            if loaded:
                self.sounds[kind] = loaded

    def set_volume(self, volume):
        self.volume = float(volume)

    def play(self, kind="good"):
        sounds = self.sounds.get(kind) or self.sounds.get("good")
        if not sounds:
            return
        # Round-robin that never repeats the same variant back-to-back.
        if len(sounds) > 1:
            prev = self._rr.get(kind, -1)
            idx = (prev + self._rng.randint(1, len(sounds) - 1)) % len(sounds)
        else:
            idx = 0
        self._rr[kind] = idx
        snd = sounds[idx]
        gain = self.volume * _KIND_PARAMS[kind][4] * self._rng.uniform(0.88, 1.0)
        # Set volume on the Sound before play() so the attack transient is
        # already at the right level (channel volume applies a chunk late).
        snd.set_volume(max(0.0, min(1.0, gain)))
        snd.play()


def load_waveform(path, buckets=1500):
    """
    Return a list of `buckets` peak-amplitude values in 0..1 describing the
    loudness envelope of an audio file. Used by the chart editor to draw a
    waveform. Falls back to an empty list if the audio can't be decoded.

    Decoding uses pygame's mixer (16-bit signed PCM) and only the stdlib, so
    there's no numpy/pydub dependency.
    """
    try:
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        raw = pygame.mixer.Sound(path).get_raw()
    except Exception:
        return []

    samples = array.array("h")
    try:
        samples.frombytes(raw)
    except Exception:
        return []

    n = len(samples)
    if n == 0 or buckets <= 0:
        return []

    peaks = [0.0] * buckets
    per = n / buckets
    for b in range(buckets):
        start = int(b * per)
        end = int((b + 1) * per)
        if end <= start:
            end = start + 1
        if end > n:
            end = n
        # Stride within the bucket so this stays fast for long songs.
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
