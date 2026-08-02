"""
Persistent settings.

Same merge-on-load behaviour as the desktop build — new keys added in an
update appear in an existing SETTINGS.json without discarding saved values —
but the file now lives in the writable data directory rather than beside the
source, so it works inside an iOS sandbox.
"""

import json
import os

import paths

DEFAULTS = {
    # Note colors (RGB) for the four lanes.
    "LEFT": [255, 80, 80],
    "DOWN": [100, 150, 255],
    "UP": [100, 255, 100],
    "RIGHT": [200, 100, 255],

    # Gameplay. NOTE_SPEED is in design points per second and is scaled to
    # the device, so notes travel at the same apparent speed on every screen.
    "NOTE_SPEED": 620,
    "FPS": 60,
    "HIT_VOLUME": 0.5,
    "EDITOR_HIT_VOLUME": 0.5,
    "GHOST_TAPPING": True,

    # How strongly the road narrows toward the horizon. 0 = flat columns,
    # 1 = strong vanishing-point perspective.
    "PERSPECTIVE": 0.45,
    # Haptic-style screen flash on hit, for feedback without a controller.
    "HIT_FLASH": True,

    # Latency / calibration.
    "AUDIO_OFFSET": 0.0,
    "VISUAL_OFFSET": 0.0,
    "AUDIO_BUFFER": 0,          # 0 = pick a sensible default for the platform

    # Desktop-only keyboard fallback, handy while developing on a laptop.
    "LEFT_BUTTON": "K_a",
    "DOWN_BUTTON": "K_s",
    "UP_BUTTON": "K_d",
    "RIGHT_BUTTON": "K_f",

    # Interface theme (hex strings).
    "THEME_BG": "#0b0b14",
    "THEME_SURFACE": "#1a1a28",
    "THEME_ACCENT": "#4a86ff",
    "THEME_TEXT": "#e8e8f2",
    "THEME_MUTED": "#8a8aa0",
}


class Settings:
    def __init__(self):
        paths.ensure_dirs()
        self.data = self._load()

    def _load(self):
        try:
            with open(paths.SETTINGS_PATH, "r") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            data = {}

        changed = False
        for key, value in DEFAULTS.items():
            if key not in data:
                data[key] = value
                changed = True

        self.data = data
        if changed:
            self.save()
        return data

    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value):
        self.data[key] = value

    def set_and_save(self, key, value):
        self.data[key] = value
        self.save()

    def save(self, data=None):
        if data is not None:
            self.data = data
        try:
            os.makedirs(os.path.dirname(paths.SETTINGS_PATH), exist_ok=True)
            with open(paths.SETTINGS_PATH, "w") as f:
                json.dump(self.data, f, indent=4)
        except OSError as e:
            print(f"Could not save settings: {e}")

    def reset_theme(self):
        for key in ("THEME_BG", "THEME_SURFACE", "THEME_ACCENT",
                    "THEME_TEXT", "THEME_MUTED"):
            self.data[key] = DEFAULTS[key]
        self.save()


settings = Settings()
