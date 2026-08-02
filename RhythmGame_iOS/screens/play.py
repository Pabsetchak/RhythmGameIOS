"""
Gameplay: the piano-tiles road.

The judgment model is carried over intact from the desktop engine — same
timing windows, same audio-clock locking, same ghost-tap and chord-grace
rules — because that logic was already sound. What changed is everything
around it: the playfield is a receding road instead of four columns, input
is fingers instead of keys, and the whole thing runs as one frame-at-a-time
screen rather than a blocking loop.
"""

import pygame

import audio
import paths
from app import Screen
from chart_model import load_chart
from road import RoadGeometry
from settings_store import settings
from theme import (LANE_NAMES, NUM_LANES, draw_text, fill_rounded, fonts,
                   lerp, palette, shade)
from touch import DOWN, UP

# Timing window (seconds) within which a tap counts as hitting a note. Also
# the area of error: taps outside it score nothing, so spamming earns nothing.
HIT_WINDOW = 0.16
# A hold may be released this early and still count.
RELEASE_GRACE = 0.12

# Judgment thresholds, in seconds from the perfect moment.
PERFECT_WINDOW = 0.065
GOOD_WINDOW = 0.135

POPUP_LIFE = 0.7
POPUP_RISE = 80

# When ghost tapping is OFF, an empty-lane tap is forgiven if a real note was
# hit, or is about to be, within this window — so chords aren't punished.
CHORD_GRACE = 0.05

SCORE_PERFECT, SCORE_GOOD, SCORE_BAD = 300, 100, 50
COMBO_BONUS = 2

JUDGE_PERFECT = ("PERFECT", (90, 220, 255))
JUDGE_GOOD = ("GOOD", (120, 255, 140))
JUDGE_BAD = ("BAD", (255, 180, 90))
JUDGE_MISS = ("MISS", (255, 90, 90))

COUNT_IN_SECONDS = 3.0


class Note:
    __slots__ = ("lane", "time", "is_hold", "duration", "end", "state")

    def __init__(self, lane, time, is_hold, duration):
        self.lane = lane
        self.time = time
        self.is_hold = is_hold
        self.duration = duration
        self.end = time + duration
        self.state = "pending"      # -> active (hold held) -> hit / missed


class PlayScreen(Screen):
    def __init__(self, app, song_name):
        super().__init__(app)
        self.song_name = song_name

        self.score = 0
        self.combo = 0
        self.max_combo = 0
        self.counts = {"PERFECT": 0, "GOOD": 0, "BAD": 0, "MISS": 0}
        self.mistaps = 0
        self.last_hit_time = -999.0

        self.ghost_tapping = bool(settings.get("GHOST_TAPPING", True))
        self.audio_offset = float(settings.get("AUDIO_OFFSET", 0.0))
        self.visual_offset = float(settings.get("VISUAL_OFFSET", 0.0))
        self.hit_flash = bool(settings.get("HIT_FLASH", True))

        self.popups = []
        self.lane_flash = [0.0] * NUM_LANES
        self.pid_lane = {}

        self.song_time = -COUNT_IN_SECONDS
        self.music_started = False
        self.paused = False
        self.finished = False
        self._start_ticks = 0
        self._pause_at = 0

        self.hit_sounds = None
        self.notes = []
        self.duration = 0.0
        self.road = None
        self._pause_group = None

    # ------------------------------------------------------------------ #
    # Setup
    # ------------------------------------------------------------------ #
    def on_enter(self):
        try:
            self.hit_sounds = audio.HitSoundBank(float(settings.get("HIT_VOLUME", 0.5)))
        except Exception as e:
            print(f"Could not load hit sounds: {e}")

        mp3 = paths.song_audio(self.song_name)
        self.duration = audio.sound_length(mp3)
        notes, duration = load_chart(self.song_name, self.duration)
        self.duration = duration or self.duration

        self.notes = [
            Note(int(n.get("lane", 0)) % NUM_LANES, n["timestamp"],
                 n["type"] == "hold" and n.get("duration", 0.0) > 0,
                 n.get("duration", 0.0))
            for n in notes
        ]
        self.notes.sort(key=lambda n: n.time)

        self._build_road()
        self._start_ticks = pygame.time.get_ticks()

    def on_resize(self):
        self._build_road()
        self._pause_group = None

    def _build_road(self):
        self.hud_bottom = self.layout.content_top + self.s(64)
        self.road = RoadGeometry(self.layout,
                                 float(settings.get("PERSPECTIVE", 0.45)),
                                 self.hud_bottom)
        # Note speed is authored in design points per second so notes travel
        # at the same apparent rate regardless of screen size.
        self.pps = float(settings.get("NOTE_SPEED", 620)) * self.layout.scale

    def on_exit(self):
        audio.stop_music()

    # ------------------------------------------------------------------ #
    # Clock
    # ------------------------------------------------------------------ #
    def _advance_clock(self):
        now = (pygame.time.get_ticks() - self._start_ticks) / 1000.0 - COUNT_IN_SECONDS

        if not self.music_started and now >= 0:
            audio.play_music(paths.song_audio(self.song_name))
            self.music_started = True

        # Lock the game clock to the audio clock. music.get_pos() is driven by
        # the audio callback, so nudging our wall-clock anchor toward it
        # absorbs start latency and drift — notes stay in sync with what you
        # actually hear rather than with the CPU.
        if self.music_started:
            mpos = audio.music_pos()
            if mpos >= 0:
                err = mpos - now
                if abs(err) > 0.002:
                    corr = max(-0.004, min(0.004, err * 0.15))
                    self._start_ticks -= corr * 1000.0
                    now += corr

        self.song_time = now

    # ------------------------------------------------------------------ #
    # Input
    # ------------------------------------------------------------------ #
    def handle_pointer(self, ev):
        if self.paused:
            if self._pause_group:
                self._pause_group.handle_pointer(ev)
            return

        if ev.kind == DOWN:
            if ev.y < self.road.touch_top():
                if self._pause_rect().collidepoint(ev.x, ev.y):
                    self._toggle_pause()
                return
            lane = self.road.lane_from_x(ev.x)
            self.pid_lane[ev.pid] = lane
            self.press_lane(lane, self.song_time)

        elif ev.kind == UP:
            lane = self.pid_lane.pop(ev.pid, None)
            if lane is None:
                return
            # Only end the hold once every finger on that lane has lifted.
            if lane not in self.pid_lane.values():
                self.release_lane(lane, self.song_time)

    def handle_event(self, event):
        if event.type != pygame.KEYDOWN:
            if event.type == pygame.KEYUP:
                lane = self._lane_for_key(event.key)
                if lane is not None:
                    self.release_lane(lane, self.song_time)
            return
        if event.key == pygame.K_ESCAPE:
            self._toggle_pause()
            return
        lane = self._lane_for_key(event.key)
        if lane is not None and not self.paused:
            self.press_lane(lane, self.song_time)

    def _lane_for_key(self, key):
        """Keyboard fallback, useful when developing on a desktop."""
        for lane, name in enumerate(LANE_NAMES):
            const = settings.get(f"{name}_BUTTON")
            if const and getattr(pygame, const, None) == key:
                return lane
        return None

    # ------------------------------------------------------------------ #
    # Judgment
    # ------------------------------------------------------------------ #
    def judge_and_score(self, diff):
        if diff <= PERFECT_WINDOW:
            return JUDGE_PERFECT, SCORE_PERFECT
        if diff <= GOOD_WINDOW:
            return JUDGE_GOOD, SCORE_GOOD
        return JUDGE_BAD, SCORE_BAD

    def add_popup(self, judge, lane, now):
        text, color = judge
        self.popups.append([text, color, lane, now])

    def play_hit_sound(self, kind="good"):
        if self.hit_sounds:
            self.hit_sounds.play(kind)

    def register_hit(self, judge, points, now, lane):
        self.add_popup(judge, lane, now)
        self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        self.score += points + self.combo * COMBO_BONUS
        self.counts[judge[0]] += 1
        self.last_hit_time = now
        if self.hit_flash:
            self.lane_flash[lane] = 1.0

    def register_miss(self, now, lane):
        self.play_hit_sound("miss")
        self.add_popup(JUDGE_MISS, lane, now)
        self.counts["MISS"] += 1
        self.combo = 0

    def near_real_hit(self, now):
        """A real note was just hit, or is about to be, in any lane."""
        if now - self.last_hit_time <= CHORD_GRACE:
            return True
        return any(n.state == "pending" and abs(n.time - now) <= CHORD_GRACE
                   for n in self.notes)

    def press_lane(self, lane, now):
        judge_now = now - self.audio_offset
        best = None
        best_diff = HIT_WINDOW
        for n in self.notes:
            if n.lane == lane and n.state == "pending":
                diff = abs(n.time - judge_now)
                if diff <= best_diff:
                    best_diff = diff
                    best = n

        if best is None:
            if self.hit_flash:
                self.lane_flash[lane] = 0.5
            if self.ghost_tapping or self.near_real_hit(now):
                self.play_hit_sound("ghost")
                return
            self.play_hit_sound("miss")
            self.add_popup(JUDGE_MISS, lane, now)
            self.combo = 0
            self.mistaps += 1
            return

        judge, points = self.judge_and_score(best_diff)
        # Sound first: its timbre encodes the judgment, and playing it before
        # the bookkeeping keeps it effectively instant with the tap.
        self.play_hit_sound(judge[0].lower())
        best.state = "active" if best.is_hold else "hit"
        self.register_hit(judge, points, now, lane)

    def release_lane(self, lane, now):
        judge_now = now - self.audio_offset
        for n in self.notes:
            if n.lane == lane and n.state == "active":
                if judge_now < n.end - RELEASE_GRACE:
                    n.state = "missed"
                    self.register_miss(now, lane)
                else:
                    n.state = "hit"
                    self.register_hit(JUDGE_PERFECT, SCORE_PERFECT, now, lane)
                break

    # ------------------------------------------------------------------ #
    # Frame
    # ------------------------------------------------------------------ #
    def update(self, dt, wall_now):
        for lane in range(NUM_LANES):
            if self.lane_flash[lane] > 0:
                self.lane_flash[lane] = max(0.0, self.lane_flash[lane] - dt * 4.0)

        if self.paused or self.finished:
            return

        self._advance_clock()
        now = self.song_time
        judge_now = now - self.audio_offset

        for n in self.notes:
            if n.state == "pending" and judge_now - n.time > HIT_WINDOW:
                n.state = "missed"
                self.register_miss(now, n.lane)
            elif n.state == "active" and judge_now >= n.end:
                # Held all the way through; releasing isn't required.
                n.state = "hit"
                self.register_hit(JUDGE_PERFECT, SCORE_PERFECT, now, n.lane)

        self.popups = [p for p in self.popups if now - p[3] < POPUP_LIFE]

        if self.music_started and self.duration and now >= self.duration + 1.0:
            if all(n.state in ("hit", "missed") for n in self.notes):
                self._finish()

    def _finish(self):
        if self.finished:
            return
        self.finished = True
        audio.stop_music()
        from screens.results import ResultsScreen
        self.app.replace(ResultsScreen(self.app, self.song_name, self._summary()))

    def _summary(self):
        c = self.counts
        total = sum(c.values())
        weighted = c["PERFECT"] * 1.0 + c["GOOD"] * 0.66 + c["BAD"] * 0.33
        return {
            "score": self.score,
            "counts": dict(c),
            "max_combo": self.max_combo,
            "accuracy": (weighted / total * 100.0) if total else 0.0,
            "mistaps": self.mistaps,
            "ghost_tapping": self.ghost_tapping,
        }

    # ------------------------------------------------------------------ #
    # Pause
    # ------------------------------------------------------------------ #
    def _pause_rect(self):
        size = self.s(40)
        return pygame.Rect(self.layout.content_right - size,
                           self.layout.content_top, size, size)

    def _toggle_pause(self):
        if self.finished:
            return
        self.paused = not self.paused
        if self.paused:
            self._pause_at = pygame.time.get_ticks()
            try:
                pygame.mixer.music.pause()
            except pygame.error:
                pass
            self._build_pause_ui()
        else:
            # Roll the clock anchor forward by however long we sat paused, so
            # the song time picks up exactly where it left off.
            self._start_ticks += pygame.time.get_ticks() - self._pause_at
            try:
                pygame.mixer.music.unpause()
            except pygame.error:
                pass
            self.pid_lane.clear()

    def _build_pause_ui(self):
        import ui
        lay = self.layout
        self._pause_group = ui.Group()
        w = min(lay.content_width, lay.s(280))
        x = (lay.width - w) // 2
        y = lay.height // 2 - lay.s(70)
        h = lay.s(ui.BUTTON_H)
        gap = lay.s(12)

        self._pause_group.add(ui.Button(pygame.Rect(x, y, w, h), "Resume",
                                        self._toggle_pause, lay.scale))
        self._pause_group.add(ui.Button(pygame.Rect(x, y + h + gap, w, h), "Restart",
                                        self._restart, lay.scale,
                                        style=ui.Button.GHOST))
        self._pause_group.add(ui.Button(pygame.Rect(x, y + (h + gap) * 2, w, h),
                                        "Quit to menu", self._quit, lay.scale,
                                        style=ui.Button.GHOST))

    def _restart(self):
        audio.stop_music()
        self.app.replace(PlayScreen(self.app, self.song_name))

    def _quit(self):
        audio.stop_music()
        self.app.pop()

    # ------------------------------------------------------------------ #
    # Drawing
    # ------------------------------------------------------------------ #
    def draw(self, surface):
        surface.fill(palette.bg)
        self._draw_road(surface)
        self._draw_notes(surface)
        self._draw_receptors(surface)
        self._draw_popups(surface)
        self._draw_hud(surface)
        if self.song_time < 0:
            self._draw_count_in(surface)
        if self.paused:
            self._draw_pause(surface)

    def _draw_road(self, surface):
        road = self.road
        # Sky above the horizon, fading into the road surface.
        sky = pygame.Rect(0, self.hud_bottom, self.layout.width,
                          road.horizon_y - self.hud_bottom + 1)
        if sky.height > 0:
            pygame.draw.rect(surface, shade(palette.bg, 0.04), sky)

        for lane in range(NUM_LANES):
            quad = road.quad(lane, 0.0, 1.0)
            base = shade(palette.surface, -0.35 if lane % 2 else -0.25)
            pygame.draw.polygon(surface, base, quad)

        # Lane dividers converging on the vanishing point.
        for lane in range(NUM_LANES + 1):
            if lane < NUM_LANES:
                nx = road.lane_edges(lane, 0.0)[0]
                fx = road.lane_edges(lane, 1.0)[0]
            else:
                nx = road.lane_edges(NUM_LANES - 1, 0.0)[1]
                fx = road.lane_edges(NUM_LANES - 1, 1.0)[1]
            pygame.draw.line(surface, shade(palette.surface, 0.10),
                             (fx, road.y_at(1.0)), (nx, road.y_at(0.0)),
                             max(1, self.s(1)))

        # Haze at the horizon so tiles fade in rather than pop.
        haze_h = self.s(46)
        haze = pygame.Surface((self.layout.width, haze_h), pygame.SRCALPHA)
        for i in range(haze_h):
            a = int(210 * (1.0 - i / haze_h))
            pygame.draw.line(haze, (*palette.bg, a), (0, i), (self.layout.width, i))
        surface.blit(haze, (0, road.horizon_y))

    def _draw_notes(self, surface):
        road = self.road
        vis_now = self.song_time - self.audio_offset + self.visual_offset
        tile_flat = road.tile_h

        # Far notes first so nearer ones overlap them correctly.
        for n in sorted(self.notes, key=lambda x: -x.time):
            if n.state in ("hit", "missed"):
                continue

            near_flat = (n.time - vis_now) * self.pps
            if n.is_hold:
                far_flat = (n.end - vis_now) * self.pps
                if n.state == "active":
                    near_flat = min(near_flat, 0.0)   # consumed down to the line
                far_flat = max(far_flat, near_flat + tile_flat * 0.35)
            else:
                far_flat = near_flat + tile_flat

            if near_flat > road.travel * 1.35 or far_flat < -road.tile_h:
                continue

            near_d = road.project(max(near_flat, -tile_flat))
            far_d = road.project(min(far_flat, road.travel * 1.35))
            if far_d <= near_d:
                continue

            color = palette.lane(n.lane)
            quad = road.quad(n.lane, near_d, far_d)
            inset = self._inset_quad(quad, self.s(3))

            if n.is_hold:
                body = lerp(color, palette.bg, 0.45)
                pygame.draw.polygon(surface, body, inset)
                pygame.draw.polygon(surface, color, inset, max(1, self.s(2)))
                # Bright cap on the head so the strike point is unmistakable.
                head_d = road.project(max(near_flat, 0.0))
                head_far = road.project(max(near_flat, 0.0) + tile_flat * 0.42)
                if n.state != "active":
                    pygame.draw.polygon(
                        surface, color,
                        self._inset_quad(road.quad(n.lane, head_d, head_far), self.s(3)))
            else:
                pygame.draw.polygon(surface, color, inset)
                # A lighter top edge gives the tile a little dimension.
                pygame.draw.polygon(surface, shade(color, 0.30), inset,
                                    max(1, self.s(2)))

    @staticmethod
    def _inset_quad(quad, amount):
        """Shrink a quad toward its centre so adjacent tiles don't touch."""
        cx = sum(p[0] for p in quad) / 4.0
        cy = sum(p[1] for p in quad) / 4.0
        out = []
        for x, y in quad:
            dx, dy = x - cx, y - cy
            dist = max(1e-3, (dx * dx + dy * dy) ** 0.5)
            f = max(0.0, 1.0 - amount / dist)
            out.append((cx + dx * f, cy + dy * f))
        return out

    def _draw_receptors(self, surface):
        road = self.road
        for lane in range(NUM_LANES):
            left, right = road.lane_edges(lane, 0.0)
            rect = pygame.Rect(int(left) + self.s(3), int(road.hit_y),
                               int(right - left) - self.s(6), road.pad_h)
            color = palette.lane(lane)
            flash = self.lane_flash[lane]

            fill = lerp(shade(palette.surface, -0.20), color, 0.18 + 0.55 * flash)
            fill_rounded(surface, rect, fill, self.s(10))
            fill_rounded(surface, rect, lerp(color, (255, 255, 255), flash * 0.6),
                         self.s(10), width=max(2, self.s(2)))

        # The hit line itself.
        y = int(road.hit_y)
        pygame.draw.line(surface, shade(palette.text, -0.25),
                         (0, y), (self.layout.width, y), max(2, self.s(2)))

    def _draw_popups(self, surface):
        road = self.road
        font = fonts.get(16, bold=True)
        for text, color, lane, start in self.popups:
            elapsed = self.song_time - start
            if elapsed < 0:
                continue
            x = road.lane_center(lane, 0.0)
            y = road.hit_y - self.s(18) - elapsed * POPUP_RISE * self.layout.scale
            alpha = int(255 * max(0.0, 1.0 - elapsed / POPUP_LIFE))
            draw_text(surface, text, font, color, center=(int(x), int(y)),
                      alpha=alpha)

    def _draw_hud(self, surface):
        lay = self.layout
        top = lay.content_top

        score_font = fonts.get(22, bold=True)
        draw_text(surface, f"{self.score:,}", score_font, palette.text,
                  midleft=(lay.content_left + self.s(4), top + self.s(14)))

        if self.combo > 1:
            combo_font = fonts.get(15, bold=True)
            draw_text(surface, f"{self.combo}x", combo_font, (255, 220, 120),
                      midleft=(lay.content_left + self.s(4), top + self.s(38)))

        # Progress through the song.
        bar = pygame.Rect(lay.content_left + self.s(4), top + self.s(52),
                          lay.content_width - self.s(56), self.s(4))
        fill_rounded(surface, bar, shade(palette.surface, 0.12), self.s(2))
        if self.duration > 0:
            f = max(0.0, min(1.0, self.song_time / self.duration))
            if f > 0:
                done = pygame.Rect(bar.x, bar.y, int(bar.width * f), bar.height)
                fill_rounded(surface, done, palette.accent, self.s(2))

        # Pause button.
        pr = self._pause_rect()
        fill_rounded(surface, pr, shade(palette.surface, 0.10), self.s(10))
        bar_w, bar_h = self.s(4), self.s(15)
        for i in (-1, 1):
            pygame.draw.rect(surface, palette.text,
                             (pr.centerx + i * self.s(4) - bar_w // 2,
                              pr.centery - bar_h // 2, bar_w, bar_h))

    def _draw_count_in(self, surface):
        lay = self.layout
        remaining = -self.song_time
        count = max(1, min(int(COUNT_IN_SECONDS), int(remaining) + 1))
        big = fonts.get(64, bold=True)
        draw_text(surface, str(count), big, palette.text,
                  center=(lay.width // 2, lay.height // 2 - self.s(30)))
        draw_text(surface, "Get ready…", fonts.get(16), palette.muted,
                  center=(lay.width // 2, lay.height // 2 + self.s(26)))

    def _draw_pause(self, surface):
        veil = pygame.Surface((self.layout.width, self.layout.height),
                              pygame.SRCALPHA)
        veil.fill((0, 0, 0, 170))
        surface.blit(veil, (0, 0))
        draw_text(surface, "Paused", fonts.get(28, bold=True), palette.text,
                  center=(self.layout.width // 2,
                          self.layout.height // 2 - self.s(120)))
        if self._pause_group is None:
            self._build_pause_ui()
        self._pause_group.draw(surface)
