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
        # A degenerate size would put every control off-screen and render a
        # perfectly black display with no error to show for it. Refuse to
        # build a layout smaller than something usable.
        self.width = max(int(width), 320)
        self.height = max(int(height), 480)
        width, height = self.width, self.height
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


def native_size():
    """The device screen size, or None if it can't be determined."""
    try:
        sizes = pygame.display.get_desktop_sizes()
        if sizes and sizes[0][0] > 0 and sizes[0][1] > 0:
            return tuple(sizes[0])
    except Exception:
        pass
    try:
        info = pygame.display.Info()
        if info.current_w > 0 and info.current_h > 0:
            return (info.current_w, info.current_h)
    except Exception:
        pass
    return None


def _usable(surface):
    return (surface is not None
            and surface.get_width() >= 100 and surface.get_height() >= 100)


def init_display():
    """
    Open the window (or take over the device screen) and return
    (surface, Layout).

    On desktop, set_mode((0, 0)) means "use the desktop resolution". On iOS
    that is not dependable — SDL can return a 0x0 surface, which draws a
    perfectly black screen and raises nothing, so it looks identical to a
    hang. Ask for the real screen size first and only fall back to (0, 0),
    checking that whatever comes back is actually usable.
    """
    import diagnostics

    # Reuse a display that already exists. On iOS the window is created during
    # import (see main.py) and SDL_iPhoneSetAnimationCallback is bound to that
    # specific SDL_Window — calling set_mode again could replace it and orphan
    # the frame callback, which would stop the app dead.
    existing = pygame.display.get_surface()
    if existing is not None and _usable(existing):
        diagnostics.log(f"display: reusing existing surface {existing.get_size()}")
        return existing, Layout(*existing.get_size())

    if not IS_IOS:
        surface = pygame.display.set_mode(DEV_SIZE, pygame.RESIZABLE)
        pygame.display.set_caption("Rhythm Game")
        return surface, Layout(*surface.get_size())

    if not pygame.display.get_init():
        pygame.display.init()

    native = native_size()
    diagnostics.log(f"display: native_size() = {native}")

    attempts = []
    if native:
        attempts.append((native, pygame.FULLSCREEN))
        attempts.append((native, 0))
    attempts.append(((0, 0), pygame.FULLSCREEN))
    attempts.append(((0, 0), 0))

    surface = None
    for size, flags in attempts:
        try:
            candidate = pygame.display.set_mode(size, flags)
        except Exception as e:
            diagnostics.log(f"display: set_mode({size}, {flags}) raised {e!r}")
            continue
        got = candidate.get_size() if candidate else None
        diagnostics.log(f"display: set_mode({size}, {flags}) -> {got}")
        if _usable(candidate):
            surface = candidate
            break

    if surface is None:
        # Nothing produced a usable surface. Take the last one anyway so the
        # app can still run and report the problem rather than dying here.
        surface = pygame.display.get_surface()
        diagnostics.log(f"display: falling back to {surface and surface.get_size()}")

    w, h = surface.get_size() if surface else (0, 0)
    layout = Layout(w, h)
    diagnostics.log(f"display: surface {w}x{h}, layout "
                    f"{layout.width}x{layout.height} scale={layout.scale:.2f}")
    return surface, layout


def audio_buffer_default():
    """
    Mixer buffer size in samples.

    128 keeps hit sounds tight on desktop, but iOS audio units want a larger
    buffer — going too small there produces dropouts rather than lower
    latency, so start higher on device.
    """
    return 512 if IS_IOS else 128
