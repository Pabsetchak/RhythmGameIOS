"""
Display setup and screen geometry.

The game is designed in "points" against a 390pt-wide reference (an iPhone
14/15 class screen) and scaled to whatever it actually runs on, so a single
layout works from an SE up to an iPad and in a desktop window while you're
developing.
"""

import pygame

from paths import IS_IOS

# The layout reference. Sizes throughout the UI are expressed against this
# width and multiplied by Layout.scale at draw time.
REF_WIDTH = 390.0

# Scale is clamped so an iPad doesn't render comically oversized controls.
MIN_SCALE, MAX_SCALE = 0.85, 1.65

# Desktop development window, portrait so it matches phone proportions.
DEV_SIZE = (430, 860)


class Layout:
    """Screen geometry plus the safe-area insets to keep UI clear of."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.scale = max(MIN_SCALE, min(MAX_SCALE, width / REF_WIDTH))

        # SDL doesn't surface UIKit's safe-area insets, so infer them. A tall
        # aspect ratio means a notch or Dynamic Island at the top and a home
        # indicator at the bottom; the classic 16:9 devices have neither.
        tall = IS_IOS and (height / max(width, 1)) > 1.9
        self.safe_top = int(50 * self.scale) if tall else int(18 * self.scale)
        self.safe_bottom = int(30 * self.scale) if tall else int(10 * self.scale)
        self.safe_left = int(8 * self.scale)
        self.safe_right = int(8 * self.scale)

    def s(self, value):
        """Scale a design-point value to device pixels."""
        return int(round(value * self.scale))

    @property
    def content_top(self):
        return self.safe_top

    @property
    def content_bottom(self):
        return self.height - self.safe_bottom

    @property
    def content_height(self):
        return self.content_bottom - self.content_top

    @property
    def content_left(self):
        return self.safe_left

    @property
    def content_right(self):
        return self.width - self.safe_right

    @property
    def content_width(self):
        return self.content_right - self.content_left


def init_display():
    """
    Open the window (or take over the device screen) and return
    (surface, Layout).
    """
    if IS_IOS:
        # (0, 0) asks SDL for the full native resolution.
        surface = pygame.display.set_mode((0, 0))
    else:
        surface = pygame.display.set_mode(DEV_SIZE, pygame.RESIZABLE)
        pygame.display.set_caption("Rhythm Game")

    w, h = surface.get_size()
    return surface, Layout(w, h)


def audio_buffer_default():
    """
    Mixer buffer size in samples.

    128 keeps hit sounds tight on desktop, but iOS audio units want a larger
    buffer — going too small there produces dropouts rather than lower
    latency, so start higher on device.
    """
    return 512 if IS_IOS else 128
