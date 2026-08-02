"""
Application shell.

The desktop build ran a blocking `while running:` loop per activity — the
game had one, the recorder had one, and tkinter had its own mainloop on top.
None of that works on iOS: the OS owns the run loop, and a Python loop that
never returns starves it, so the app is killed for being unresponsive.

Everything here is therefore driven by App.tick(), which advances exactly one
frame and returns. Activities become Screens on a stack instead of nested
loops, so "start the game" is a push and "go back" is a pop.
"""

import time

import pygame

import paths
import platform_compat
from theme import fonts, palette
from touch import TouchInput


class Screen:
    """
    One view. Subclasses override the hooks they care about.

    Set `transparent = True` to have the screen below drawn first, which is
    how modal sheets and confirmation dialogs are built.
    """

    transparent = False

    def __init__(self, app):
        self.app = app

    @property
    def layout(self):
        return self.app.layout

    def s(self, value):
        return self.app.layout.s(value)

    # Lifecycle -------------------------------------------------------- #
    def on_enter(self):
        pass

    def on_exit(self):
        pass

    def on_resize(self):
        pass

    # Input ------------------------------------------------------------ #
    def handle_pointer(self, ev):
        pass

    def handle_event(self, event):
        """Raw pygame events — keyboard, mostly useful on desktop."""
        pass

    # Frame ------------------------------------------------------------ #
    def update(self, dt, now):
        pass

    def draw(self, surface):
        pass


class App:
    def __init__(self):
        paths.ensure_dirs()

        # Mixer before display: pygame only honours the buffer size on a
        # fresh init, and the audio device must be up before any Sound loads.
        import audio
        audio.init_audio()

        pygame.init()
        self.surface, self.layout = platform_compat.init_display()
        fonts.set_scale(self.layout.scale)
        palette.refresh()

        self.touch = TouchInput(self.layout)
        self.clock = pygame.time.Clock()
        self.running = True
        self.stack = []
        self._last_time = time.perf_counter()
        self._toast = None          # (message, expiry, is_error)

        # Text input is only wanted while a field is focused; leaving it on
        # keeps the iOS keyboard hovering over everything.
        pygame.key.set_text_input_rect(pygame.Rect(0, 0, 1, 1))
        try:
            pygame.key.stop_text_input()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Screen stack
    # ------------------------------------------------------------------ #
    @property
    def top(self):
        return self.stack[-1] if self.stack else None

    def set_root(self, screen):
        while self.stack:
            self.stack.pop().on_exit()
        self.push(screen)

    def push(self, screen):
        self.touch.cancel_all()
        self.stack.append(screen)
        screen.on_enter()

    def pop(self):
        if len(self.stack) <= 1:
            return
        self.touch.cancel_all()
        self.stack.pop().on_exit()

    def replace(self, screen):
        if self.stack:
            self.touch.cancel_all()
            self.stack.pop().on_exit()
        self.push(screen)

    def pop_to_root(self):
        while len(self.stack) > 1:
            self.touch.cancel_all()
            self.stack.pop().on_exit()

    # ------------------------------------------------------------------ #
    # Toast
    # ------------------------------------------------------------------ #
    def toast(self, message, error=False, seconds=2.4):
        self._toast = (str(message), time.perf_counter() + seconds, error)

    # ------------------------------------------------------------------ #
    # Frame
    # ------------------------------------------------------------------ #
    def tick(self):
        """Advance one frame. Never blocks."""
        self.touch.begin_frame()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                return
            if event.type == pygame.VIDEORESIZE:
                self._resize(event.size)
                continue
            self.touch.handle(event)
            if self.top:
                self.top.handle_event(event)

        self.touch.end_frame()

        top = self.top
        if top:
            for pev in self.touch.events:
                top.handle_pointer(pev)

        now = time.perf_counter()
        dt = min(0.1, now - self._last_time)     # clamp after a stall
        self._last_time = now

        if top:
            top.update(dt, now)

        self._draw(now)

        # Cap the frame rate. On iOS this also yields to the OS run loop.
        self.clock.tick(int(self.app_fps()))

    def app_fps(self):
        from settings_store import settings
        try:
            return max(30, min(120, int(settings.get("FPS", 60))))
        except (TypeError, ValueError):
            return 60

    def _draw(self, now):
        # A transparent screen needs whatever is beneath it drawn first.
        start = len(self.stack) - 1
        while start > 0 and self.stack[start].transparent:
            start -= 1
        for screen in self.stack[start:]:
            screen.draw(self.surface)

        self._draw_toast(now)
        pygame.display.flip()

    def _draw_toast(self, now):
        if not self._toast:
            return
        message, expiry, error = self._toast
        if now >= expiry:
            self._toast = None
            return

        lay = self.layout
        font = fonts.get(14)
        pad = lay.s(14)
        text_w = min(font.size(message)[0], lay.content_width - pad * 2)
        w = text_w + pad * 2
        h = lay.s(42)
        x = (lay.width - w) // 2
        y = lay.content_bottom - h - lay.s(16)

        # Fade out over the last third of a second.
        alpha = 255 if expiry - now > 0.33 else int(255 * (expiry - now) / 0.33)
        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        color = palette.danger if error else palette.surface_alt
        pygame.draw.rect(panel, (*color, min(240, alpha)),
                         pygame.Rect(0, 0, w, h), border_radius=lay.s(12))
        panel.set_alpha(alpha)
        self.surface.blit(panel, (x, y))

        from theme import draw_text, truncate
        draw_text(self.surface, truncate(message, font, text_w), font,
                  palette.text, center=(lay.width // 2, y + h // 2), alpha=alpha)

    def _resize(self, size):
        self.surface = pygame.display.set_mode(size, pygame.RESIZABLE)
        self.layout = platform_compat.Layout(*size)
        fonts.set_scale(self.layout.scale)
        self.touch.set_layout(self.layout)
        for screen in self.stack:
            screen.on_resize()

    def shutdown(self):
        import audio
        audio.stop_music()
        while self.stack:
            self.stack.pop().on_exit()
        pygame.quit()
