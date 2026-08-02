"""
Latency calibration, by tapping.

Two short tests, unchanged in method from the desktop version — only the
input moved from the space bar to the screen:

  audio   tap along with each beep; the median lateness becomes AUDIO_OFFSET
  visual  tap as each falling note meets the line; that becomes VISUAL_OFFSET

This matters more on a phone than it did on a desktop. Touch panels add
their own scan latency, Bluetooth headphones add a great deal more, and the
frame-quantised event timestamps described in touch.py add a little too.
All of it is constant enough to measure once and subtract thereafter.
"""

import math
from statistics import median

import pygame

import audio as audio_mod
import ui
from app import Screen
from settings_store import settings
from theme import draw_text, fill_rounded, fonts, lerp, palette, shade
from touch import DOWN

INTERVAL = 0.5          # seconds between beats (120 BPM)
WARMUP_BEATS = 4        # beats to settle in before anything is recorded
TAPS_WANTED = 16
MAX_BEATS = 40
TOLERANCE = 0.25        # taps further than this from a beat are noise
APPROACH = 1.0          # seconds a visual note takes to reach the line

INTRO, AUDIO, VISUAL, RESULTS = "intro", "audio", "visual", "results"


class CalibrationScreen(Screen):
    def __init__(self, app):
        super().__init__(app)
        self.phase = INTRO
        self.deltas = []
        self.results = {AUDIO: None, VISUAL: None}
        self.hit = None
        self.group = ui.Group()
        self._start = 0.0
        self._next_beat = 0
        self._flash = 0.0

    def on_enter(self):
        try:
            self.hit = audio_mod.HitSoundBank(0.8)
        except Exception as e:
            print(f"Calibration: no hit sounds: {e}")
        self._build()

    def on_resize(self):
        self._build()

    def _build(self):
        lay = self.layout
        self.group.clear()
        self.group.add(ui.Button(ui.back_button_rect(lay), "Back",
                                 self.app.pop, lay.scale,
                                 style=ui.Button.GHOST, font_size=14))

        h = self.s(ui.BUTTON_H)
        y = lay.content_bottom - h
        if self.phase == INTRO:
            self.group.add(ui.Button(
                pygame.Rect(lay.content_left, y, lay.content_width, h),
                "Start", self._begin_audio, lay.scale))
        elif self.phase == RESULTS:
            self.group.add(ui.Button(
                pygame.Rect(lay.content_left, y, lay.content_width, h),
                "Done", self.app.pop, lay.scale))

        # The tap target for the running tests: everything below the header.
        top = lay.content_top + self.s(120)
        self.tap_zone = pygame.Rect(lay.content_left, top, lay.content_width,
                                    lay.content_bottom - top - self.s(10))
        self.target_y = self.tap_zone.centery + self.s(30)

    # ------------------------------------------------------------------ #
    # Phases
    # ------------------------------------------------------------------ #
    def _begin(self, phase):
        self.phase = phase
        self.deltas = []
        self._start = pygame.time.get_ticks() / 1000.0
        self._next_beat = 0
        self._build()

    def _begin_audio(self):
        self._begin(AUDIO)

    def _elapsed(self):
        return pygame.time.get_ticks() / 1000.0 - self._start

    def _finish_phase(self):
        value = float(median(self.deltas)) if len(self.deltas) >= 5 else None
        self.results[self.phase] = value

        if self.phase == AUDIO:
            self._begin(VISUAL)
            return

        if self.results[AUDIO] is not None:
            settings.set("AUDIO_OFFSET", round(self.results[AUDIO], 4))
        if self.results[VISUAL] is not None:
            settings.set("VISUAL_OFFSET", round(self.results[VISUAL], 4))
        settings.save()
        self.phase = RESULTS
        self._build()

    # ------------------------------------------------------------------ #
    # Input
    # ------------------------------------------------------------------ #
    def handle_pointer(self, ev):
        if self.group.handle_pointer(ev):
            return
        if self.phase in (AUDIO, VISUAL) and ev.kind == DOWN:
            if self.tap_zone.collidepoint(ev.x, ev.y):
                self._tap()

    def handle_event(self, event):
        if event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_ESCAPE:
            self.app.pop()
        elif event.key == pygame.K_SPACE and self.phase in (AUDIO, VISUAL):
            self._tap()

    def _tap(self):
        t = self._elapsed()
        self._flash = 1.0
        nearest = round(t / INTERVAL) * INTERVAL
        d = t - nearest
        # Skip the warm-up beats, and ignore taps too far from any beat to be
        # a genuine attempt.
        if t > WARMUP_BEATS * INTERVAL and abs(d) <= TOLERANCE:
            self.deltas.append(d)

    # ------------------------------------------------------------------ #
    # Frame
    # ------------------------------------------------------------------ #
    def update(self, dt, now):
        self.group.update(dt)
        if self._flash > 0:
            self._flash = max(0.0, self._flash - dt * 4.0)

        if self.phase not in (AUDIO, VISUAL):
            return

        t = self._elapsed()
        while t >= self._next_beat * INTERVAL:
            if self.phase == AUDIO and self.hit:
                self.hit.play("perfect")
            self._next_beat += 1

        if (len(self.deltas) >= TAPS_WANTED
                or self._next_beat > MAX_BEATS + WARMUP_BEATS):
            self._finish_phase()

    # ------------------------------------------------------------------ #
    # Drawing
    # ------------------------------------------------------------------ #
    def draw(self, surface):
        surface.fill(palette.bg)
        if self.phase == INTRO:
            self._draw_intro(surface)
        elif self.phase == RESULTS:
            self._draw_results(surface)
        else:
            self._draw_test(surface)
        self.group.draw(surface)

    def _draw_intro(self, surface):
        lay = self.layout
        ui.draw_nav_bar(surface, lay, "Calibrate")
        body = ui.Wrapped(
            pygame.Rect(lay.content_left, lay.content_top + self.s(60),
                        lay.content_width, 0),
            "Two quick tests measure how late your taps land.\n\n"
            "1. Audio — tap along with each beep.\n"
            "2. Visual — tap as each note reaches the line.\n\n"
            "Keep a steady rhythm; the odd stray tap averages out. Wear the "
            "headphones you actually play with — Bluetooth adds a lot of "
            "latency, and this is what compensates for it.",
            lay.scale, size=14)
        body.draw(surface)

    def _draw_test(self, surface):
        lay = self.layout
        t = self._elapsed()

        title = "Audio test" if self.phase == AUDIO else "Visual test"
        ui.draw_nav_bar(surface, lay, title)

        hint = ("Tap anywhere with each beep" if self.phase == AUDIO
                else "Tap as the note reaches the line")
        draw_text(surface, hint, fonts.get(14), palette.muted,
                  center=(lay.width // 2, lay.content_top + self.s(56)))

        fill_rounded(surface, self.tap_zone,
                     lerp(shade(palette.surface, -0.25), palette.accent,
                          self._flash * 0.35),
                     self.s(16))

        # The hit line.
        pygame.draw.line(surface, palette.divider,
                         (self.tap_zone.x + self.s(20), self.target_y),
                         (self.tap_zone.right - self.s(20), self.target_y),
                         max(2, self.s(2)))

        if self.phase == VISUAL:
            speed = (self.target_y - self.tap_zone.y - self.s(20)) / APPROACH
            first = int(math.floor(t / INTERVAL))
            for k in range(0, 4):
                beat_t = (first + k) * INTERVAL
                dt = beat_t - t
                if -0.15 <= dt <= APPROACH:
                    y = self.target_y - dt * speed
                    rect = pygame.Rect(0, 0, self.s(90), self.s(26))
                    rect.center = (self.tap_zone.centerx, int(y))
                    fill_rounded(surface, rect, (120, 200, 255), self.s(7))
        else:
            # A pulse that peaks exactly on each beat.
            phase = (t % INTERVAL) / INTERVAL
            glow = max(0.0, 1.0 - phase * 4.0)
            radius = int(self.s(24) + glow * self.s(60))
            color = lerp(shade(palette.surface, 0.10), palette.accent, glow)
            pygame.draw.circle(surface, color,
                               (self.tap_zone.centerx, self.target_y), radius)

        progress = f"{len(self.deltas)} / {TAPS_WANTED} taps"
        if t <= WARMUP_BEATS * INTERVAL:
            progress = "Find the beat…"
        draw_text(surface, progress, fonts.get(15, bold=True), palette.text,
                  center=(lay.width // 2, self.tap_zone.bottom - self.s(28)))

    def _draw_results(self, surface):
        lay = self.layout
        ui.draw_nav_bar(surface, lay, "Calibrated")

        def fmt(v):
            return f"{v * 1000:+.0f} ms" if isinstance(v, float) else "not measured"

        y = lay.content_top + self.s(80)
        for label, key, color in (("Audio offset", AUDIO, (120, 200, 255)),
                                  ("Visual offset", VISUAL, (120, 255, 160))):
            card = pygame.Rect(lay.content_left, y, lay.content_width, self.s(64))
            fill_rounded(surface, card, palette.surface, self.s(14))
            draw_text(surface, label, fonts.get(14), palette.muted,
                      midleft=(card.x + self.s(16), card.centery))
            draw_text(surface, fmt(self.results[key]), fonts.get(18, bold=True),
                      color, midright=(card.right - self.s(16), card.centery))
            y += self.s(74)

        note = ui.Wrapped(
            pygame.Rect(lay.content_left, y + self.s(10), lay.content_width, 0),
            "Saved. A larger number means more latency is being compensated "
            "for. Run this again if you switch between speakers and "
            "headphones.", lay.scale, size=12)
        note.draw(surface)
