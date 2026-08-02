"""
Colors, typography and small drawing helpers.

Fonts deserve a word: iOS has no fontconfig, so pygame.font.SysFont() cannot
resolve family names like "Arial" there. pygame ships freesansbold.ttf and
loads it for Font(None, size), which always works — that is the fallback.
If you drop regular.ttf / bold.ttf into assets/fonts/ they are used instead,
which is the easiest way to give the app real typography later.
"""

import os

import pygame

import paths
from settings_store import settings

_FONT_DIR = os.path.join(paths.ASSETS_DIR, "fonts")
_BUNDLED_FONT_DIR = os.path.join(paths.BUNDLE_DIR, "assets", "fonts")


# ---------------------------------------------------------------------------- #
# Color utilities
# ---------------------------------------------------------------------------- #
def hex_to_rgb(value, fallback=(255, 255, 255)):
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return tuple(int(c) for c in value[:3])
    if isinstance(value, str) and value.startswith("#") and len(value) == 7:
        try:
            return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))
        except ValueError:
            return fallback
    return fallback


def rgb_to_hex(rgb):
    r, g, b = (max(0, min(255, int(c))) for c in rgb[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


def lerp(a, b, f):
    """Blend two RGB colors; f=0 gives a, f=1 gives b."""
    f = max(0.0, min(1.0, f))
    return tuple(int(a[i] + (b[i] - a[i]) * f) for i in range(3))


def shade(color, f):
    """Darken (f<0) or lighten (f>0) a color by a fraction."""
    target = (255, 255, 255) if f > 0 else (0, 0, 0)
    return lerp(color, target, abs(f))


# ---------------------------------------------------------------------------- #
# Palette
# ---------------------------------------------------------------------------- #
LANE_NAMES = ["LEFT", "DOWN", "UP", "RIGHT"]
NUM_LANES = 4


class Palette:
    """Interface colors, re-read from settings whenever the theme changes."""

    def __init__(self):
        self.refresh()

    def refresh(self):
        self.bg = hex_to_rgb(settings.get("THEME_BG"), (11, 11, 20))
        self.surface = hex_to_rgb(settings.get("THEME_SURFACE"), (26, 26, 40))
        self.accent = hex_to_rgb(settings.get("THEME_ACCENT"), (74, 134, 255))
        self.text = hex_to_rgb(settings.get("THEME_TEXT"), (232, 232, 242))
        self.muted = hex_to_rgb(settings.get("THEME_MUTED"), (138, 138, 160))

        # Derived shades, so a theme only needs five colors to look coherent.
        self.surface_alt = shade(self.surface, 0.06)
        self.surface_deep = shade(self.surface, -0.35)
        self.accent_dim = lerp(self.accent, self.surface, 0.55)
        self.divider = lerp(self.surface, self.text, 0.18)
        self.danger = (224, 78, 76)
        self.success = (72, 199, 122)

        self.lanes = [hex_to_rgb(settings.get(name), (255, 255, 255))
                      for name in LANE_NAMES]

    def lane(self, index):
        return self.lanes[index % len(self.lanes)]


palette = Palette()


# ---------------------------------------------------------------------------- #
# Fonts
# ---------------------------------------------------------------------------- #
class FontBook:
    """Cached fonts, sized in design points and scaled to the device."""

    def __init__(self):
        self._cache = {}
        self._scale = 1.0
        self._regular = self._find("regular.ttf")
        self._bold = self._find("bold.ttf")

    @staticmethod
    def _find(name):
        for directory in (_FONT_DIR, _BUNDLED_FONT_DIR):
            candidate = os.path.join(directory, name)
            if os.path.exists(candidate):
                return candidate
        return None    # falls back to pygame's bundled freesansbold

    def set_scale(self, scale):
        if abs(scale - self._scale) > 1e-6:
            self._scale = scale
            self._cache.clear()

    def get(self, size, bold=False):
        key = (size, bold)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        px = max(8, int(round(size * self._scale)))
        path = self._bold if bold else self._regular
        try:
            font = pygame.font.Font(path, px)
        except Exception:
            font = pygame.font.Font(None, px)
        # Without a real regular weight, freesansbold is all we have — mark it
        # bold so callers that ask for bold still get a visible difference via
        # size rather than weight.
        self._cache[key] = font
        return font


fonts = FontBook()


# ---------------------------------------------------------------------------- #
# Drawing helpers
# ---------------------------------------------------------------------------- #
def draw_text(surface, text, font, color, center=None, topleft=None,
              midleft=None, midright=None, alpha=None):
    """Render a string and blit it by whichever anchor was supplied."""
    img = font.render(str(text), True, color)
    if alpha is not None and alpha < 255:
        img.set_alpha(int(alpha))
    if center is not None:
        rect = img.get_rect(center=center)
    elif midleft is not None:
        rect = img.get_rect(midleft=midleft)
    elif midright is not None:
        rect = img.get_rect(midright=midright)
    else:
        rect = img.get_rect(topleft=topleft or (0, 0))
    surface.blit(img, rect)
    return rect


def truncate(text, font, max_width, ellipsis="…"):
    """Shorten a string until it fits the given pixel width."""
    text = str(text)
    if font.size(text)[0] <= max_width:
        return text
    while text and font.size(text + ellipsis)[0] > max_width:
        text = text[:-1]
    return text + ellipsis


def fill_rounded(surface, rect, color, radius, width=0):
    pygame.draw.rect(surface, color, rect, width, border_radius=radius)


def vertical_gradient(surface, rect, top_color, bottom_color):
    """Cheap gradient: one horizontal line per row."""
    x, y, w, h = rect
    if h <= 0:
        return
    for i in range(h):
        f = i / max(1, h - 1)
        pygame.draw.line(surface, lerp(top_color, bottom_color, f),
                         (x, y + i), (x + w - 1, y + i))
