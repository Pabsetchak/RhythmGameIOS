import pygame
import math
from statistics import median

from settings import settings
from sound import init_audio, HitSoundBank

SCREEN_W, SCREEN_H = 800, 600
TARGET_Y = 430
INTERVAL = 0.5          # seconds between beats (120 BPM)
WARMUP_BEATS = 4        # beats before we start recording
TAPS_WANTED = 16        # taps to collect per test
MAX_BEATS = 40          # safety cap
TOLERANCE = 0.25        # ignore taps further than this from a beat
APPROACH = 1.0          # seconds a visual note takes to fall to the line


class CalibrationGame:
    """
    Two short tap-tests that measure the player's latency:

      * Audio  — tap SPACE to each beep; the median lateness is the audio
                 offset (output + input latency the judgment should compensate).
      * Visual — tap SPACE as each falling note hits the line (no sound); the
                 median lateness is the visual offset (display latency).

    Results are saved to AUDIO_OFFSET / VISUAL_OFFSET in settings.
    """

    def __init__(self):
        init_audio()
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("Latency Calibration")
        self.clock = pygame.time.Clock()
        self.font_big = pygame.font.SysFont("Arial", 44, bold=True)
        self.font = pygame.font.SysFont("Arial", 26)
        self.font_small = pygame.font.SysFont("Arial", 20)

        self.hit = None
        try:
            self.hit = HitSoundBank(0.8)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def run(self):
        if not self._intro():
            pygame.quit()
            return
        audio = self._test("audio")
        if audio == "quit":
            pygame.quit()
            return
        visual = self._test("visual")
        if visual == "quit":
            pygame.quit()
            return

        if isinstance(audio, float):
            settings.set("AUDIO_OFFSET", round(audio, 4))
        if isinstance(visual, float):
            settings.set("VISUAL_OFFSET", round(visual, 4))
        settings.save_settings()

        self._results(audio, visual)
        pygame.quit()

    # ------------------------------------------------------------------ #
    def _intro(self):
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return False
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return False
                    return True
            self.screen.fill((12, 12, 20))
            self._center(self.font_big, "Latency Calibration", 140, (255, 255, 255))
            lines = [
                "Two quick tests will measure your timing offset.",
                "",
                "1) AUDIO: tap SPACE in time with each beep.",
                "2) VISUAL: tap SPACE as each note hits the line.",
                "",
                "Just keep a steady rhythm — accuracy averages out.",
                "",
                "Press any key to begin   •   Esc to cancel",
            ]
            y = 230
            for ln in lines:
                self._center(self.font_small, ln, y, (200, 200, 215))
                y += 32
            pygame.display.flip()
            self.clock.tick(60)

    def _test(self, mode):
        deltas = []
        start = pygame.time.get_ticks() / 1000.0
        next_beat = 0
        speed = (TARGET_Y - 40) / APPROACH

        while True:
            t = pygame.time.get_ticks() / 1000.0 - start

            # Trigger beats as time passes (beep on the audio test). Use the
            # bright "perfect" sound as a steady reference tone.
            while t >= next_beat * INTERVAL:
                if mode == "audio" and self.hit and next_beat >= 0:
                    self.hit.play("perfect")
                next_beat += 1

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return "quit"
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return "quit"
                    if event.key == pygame.K_SPACE:
                        nearest = round(t / INTERVAL) * INTERVAL
                        d = t - nearest
                        if t > WARMUP_BEATS * INTERVAL and abs(d) <= TOLERANCE:
                            deltas.append(d)

            if len(deltas) >= TAPS_WANTED or next_beat > MAX_BEATS + WARMUP_BEATS:
                break

            self._draw_test(mode, t, speed, len(deltas))
            self.clock.tick(120)

        return float(median(deltas)) if len(deltas) >= 5 else None

    # ------------------------------------------------------------------ #
    def _draw_test(self, mode, t, speed, count):
        self.screen.fill((12, 12, 20))
        title = "Audio Calibration" if mode == "audio" else "Visual Calibration"
        self._center(self.font_big, title, 70, (255, 255, 255))

        instr = ("Tap SPACE to each beep" if mode == "audio"
                 else "Tap SPACE when a note reaches the line")
        self._center(self.font, instr, 130, (200, 200, 215))

        # Hit line.
        pygame.draw.line(self.screen, (90, 90, 120), (250, TARGET_Y),
                         (550, TARGET_Y), 3)
        pygame.draw.rect(self.screen, (70, 70, 100),
                         (360, TARGET_Y - 14, 80, 28), 2, border_radius=6)

        if mode == "visual":
            # Falling notes for the next few beats.
            first = int(math.floor(t / INTERVAL))
            for k in range(0, 4):
                bt = (first + k) * INTERVAL
                dt = bt - t
                if -0.15 <= dt <= APPROACH:
                    y = TARGET_Y - dt * speed
                    pygame.draw.rect(self.screen, (120, 200, 255),
                                     (360, y - 14, 80, 28), border_radius=6)
        else:
            # Subtle pulse that flashes right on each beat.
            phase = (t % INTERVAL) / INTERVAL
            glow = max(0, 1.0 - phase * 4)
            r = int(20 + glow * 90)
            col = (int(120 + glow * 135), int(120 + glow * 80), 140)
            pygame.draw.circle(self.screen, col, (SCREEN_W // 2, TARGET_Y), r)

        self._center(self.font, f"Taps: {count} / {TAPS_WANTED}", 520, (180, 230, 180))
        self._center(self.font_small, "Esc to cancel", 565, (120, 120, 140))
        pygame.display.flip()

    def _results(self, audio, visual):
        def fmt(v):
            return f"{v * 1000:+.0f} ms" if isinstance(v, float) else "not measured"

        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return
                if event.type == pygame.KEYDOWN:
                    return
            self.screen.fill((12, 12, 20))
            self._center(self.font_big, "Calibration Saved", 150, (255, 255, 255))
            self._center(self.font, f"Audio offset:  {fmt(audio)}", 270, (120, 200, 255))
            self._center(self.font, f"Visual offset: {fmt(visual)}", 320, (120, 255, 160))
            self._center(self.font_small,
                         "Higher = more latency compensated for.", 380, (180, 180, 195))
            self._center(self.font_small, "Press any key to return.", 520, (140, 140, 160))
            pygame.display.flip()
            self.clock.tick(60)

    def _center(self, font, text, y, color):
        surf = font.render(text, True, color)
        self.screen.blit(surf, surf.get_rect(center=(SCREEN_W // 2, y)))
