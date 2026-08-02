import json
import os

RHYTHMS_DIR = "rhythms"
SETTINGS_PATH = os.path.join(RHYTHMS_DIR, "SETTINGS.json")

# All known settings live here. New keys added in updates are merged into an
# existing SETTINGS.json on load, so older config files pick up new defaults
# without losing the user's saved values.
DEFAULTS = {
    # Note colors (RGB) for the four lanes.
    "LEFT": [255, 80, 80],
    "DOWN": [100, 150, 255],
    "UP": [100, 255, 100],
    "RIGHT": [200, 100, 255],

    # Gameplay.
    "NOTE_SPEED": 700,
    "FPS": 120,
    "HIT_VOLUME": 0.5,         # gameplay hit-sound volume, 0.0 - 1.0
    "EDITOR_HIT_VOLUME": 0.5,  # chart-editor preview hit-sound volume, 0.0 - 1.0
    "GHOST_TAPPING": True,     # allow penalty-free taps on empty lanes

    # Latency / calibration.
    "AUDIO_OFFSET": 0.0,       # seconds; + means your taps land late (judgment comp)
    "VISUAL_OFFSET": 0.0,      # seconds; shifts note graphics vs the music
    "AUDIO_BUFFER": 128,       # mixer buffer (samples); lower = less latency

    # Keybindings (pygame key constant names).
    "LEFT_BUTTON": "K_a",
    "DOWN_BUTTON": "K_s",
    "UP_BUTTON": "K_UP",
    "RIGHT_BUTTON": "K_RIGHT",

    # UI theming (customtkinter).
    "APPEARANCE_MODE": "Dark",     # "Light" | "Dark" | "System"
    "COLOR_THEME": "blue",         # built-in name or path to a custom theme json
}


class Settings:
    def __init__(self):
        self.ensure_rhythms_dir()
        self.data = self.load_settings()

    def ensure_rhythms_dir(self):
        if not os.path.exists(RHYTHMS_DIR):
            os.makedirs(RHYTHMS_DIR)

    def load_settings(self):
        try:
            with open(SETTINGS_PATH, "r") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}

        # Merge in any defaults the saved file is missing.
        changed = False
        for key, value in DEFAULTS.items():
            if key not in data:
                data[key] = value
                changed = True

        if changed:
            self.data = data
            self.save_settings()

        return data

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save_settings(self, data=None):
        if data is not None:
            self.data = data
        with open(SETTINGS_PATH, "w") as f:
            json.dump(self.data, f, indent=4)


# Singleton instance
settings = Settings()
