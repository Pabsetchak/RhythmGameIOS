"""
Tap charter.

Play the song and tap along; every finger becomes a note. The desktop
version read the keyboard, where each key is its own independent switch, so
chords came for free. Reproducing that on a touchscreen is the whole job
here: each finger is tracked by its own SDL finger id, so four fingers
landing together produce four notes at the same timestamp in four different
lanes rather than one note or a smear.

A finger held down past HOLD_THRESHOLD becomes a hold note, exactly as a
held key did before.
"""

import pygame

import audio
import paths
import ui
from app import Screen
from chart_model import (HOLD_MIN, dedupe, make_note, resolve_holds,
                         save_chart)
from road import RoadGeometry
from settings_store import settings
from theme import (LANE_NAMES, NUM_LANES, draw_text, fill_rounded, fonts,
                   lerp, palette, shade, truncate)
from touch import DOWN, UP

# Held at least this long becomes a hold note rather than a tap.
HOLD_THRESHOLD = 0.15
COUNTDOWN_SECONDS = 3.0

# Recorded notes drift up the road for this long before fading out.
TRAIL_LIFE = 1.4


class RecorderScreen(Screen):
    def __init__(self, app, song_name):
        super().__init__(app)
        self.song_name = song_name

        self.notes = []
        # finger id -> (lane, press_time). One entry per finger, which is what
        # makes simultaneous taps land as separate notes.
        self.held = {}
        self.lane_flash = [0.0] * NUM_LANES

        self.song_time = -COUNTDOWN_SECONDS
        self.duration = 0.0
        self.music_started = False
        self.finished = False
        self._start_ticks = 0

        self.hit_sounds = None
        self.group = ui.Group()
        self.road = None

    # ------------------------------------------------------------------ #
    # Setup
    # ------------------------------------------------------------------ #
    def on_enter(self):
        try:
            self.hit_sounds = audio.HitSoundBank(
                float(settings.get("EDITOR_HIT_VOLUME", 0.5)))
        except Exception as e:
            print(f"Could not load hit sounds: {e}")

        self.duration = audio.sound_length(paths.song_audio(self.song_name))
        self._build()
        self._start_ticks = pygame.time.get_ticks()

    def on_resize(self):
        self._build()

    def _build(self):
        lay = self.layout
        self.hud_bottom = lay.content_top + self.s(58)
        self.road = RoadGeometry(lay, float(settings.get("PERSPECTIVE", 0.45)),
                                 self.hud_bottom)
        self.pps = float(settings.get("NOTE_SPEED", 620)) * lay.scale

        self.group.clear()
        btn_w = self.s(96)
        self.group.add(ui.Button(
            pygame.Rect(lay.content_right - btn_w, lay.content_top,
                        btn_w, self.s(38)),
            "Finish", self._finish, lay.scale, style=ui.Button.DANGER,
            font_size=14))
        self.group.add(ui.Button(
            pygame.Rect(lay.content_right - btn_w * 2 - self.s(8),
                        lay.content_top, btn_w, self.s(38)),
            "Undo", self._undo, lay.scale, style=ui.Button.GHOST,
            font_size=14))

    def on_exit(self):
        audio.stop_music()

    # ------------------------------------------------------------------ #
    # Clock
    # ------------------------------------------------------------------ #
    def _advance_clock(self):
        now = (pygame.time.get_ticks() - self._start_ticks) / 1000.0 - COUNTDOWN_SECONDS

        if not self.music_started and now >= 0:
            audio.play_music(paths.song_audio(self.song_name))
            self.music_started = True

        # Same audio-clock lock as gameplay. It matters more here: every note
        # written now is judged against that clock later, so drift between
        # recording and playback would bake a constant offset into the chart.
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
        if self.finished:
            return
        if self.group.handle_pointer(ev):
            return

        if ev.kind == DOWN:
            if ev.y < self.road.touch_top():
                return
            # Ignore taps during the count-in. Screening here rather than at
            # commit time means a finger that lands before zero is dropped
            # outright, instead of surfacing later as a phantom note at 0.0.
            if self.song_time < 0:
                return
            lane = self.road.lane_from_x(ev.x)
            # Each finger gets its own slot, keyed by SDL's finger id, so a
            # four-finger chord records as four independent presses.
            self.held[ev.pid] = (lane, max(0.0, self.song_time))
            self.lane_flash[lane] = 1.0
            if self.hit_sounds:
                self.hit_sounds.play("good")

        elif ev.kind == UP:
            entry = self.held.pop(ev.pid, None)
            if entry is not None:
                self._commit(entry[0], entry[1], max(0.0, self.song_time))

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._finish()

    def _commit(self, lane, press_t, release_t):
        """Turn a completed press into a tap or a hold."""
        if self.song_time < 0:
            return
        duration = max(0.0, release_t - press_t)
        if duration < HOLD_THRESHOLD:
            duration = 0.0
        elif duration < HOLD_MIN:
            duration = HOLD_MIN
        note = make_note(press_t, lane, duration)
        note["_recorded_at"] = press_t
        self.notes.append(note)

    def _undo(self):
        if self.notes:
            self.notes.pop()

    # ------------------------------------------------------------------ #
    # Frame
    # ------------------------------------------------------------------ #
    def update(self, dt, wall_now):
        for lane in range(NUM_LANES):
            if self.lane_flash[lane] > 0:
                self.lane_flash[lane] = max(0.0, self.lane_flash[lane] - dt * 3.5)

        if self.finished:
            return

        self._advance_clock()

        if self.duration and self.song_time >= self.duration:
            self._finish()

    def _finish(self):
        if self.finished:
            return
        self.finished = True

        # Commit anything still held when the song (or the user) stopped.
        end = max(0.0, self.song_time)
        for lane, press_t in self.held.values():
            self._commit(lane, press_t, end)
        self.held.clear()
        audio.stop_music()

        if not self.notes:
            self.app.toast("No notes recorded — chart not saved.", error=True)
            self.app.pop()
            return

        for n in self.notes:
            n.pop("_recorded_at", None)

        notes = dedupe(self.notes)
        resolve_holds(notes)
        duration = self.duration or (max(n["timestamp"] + n["duration"]
                                         for n in notes) + 2.0)
        ok, message = save_chart(self.song_name, notes, duration)
        self.app.toast(message, error=not ok)

        from screens.editor import EditorScreen
        self.app.replace(EditorScreen(self.app, self.song_name))

    # ------------------------------------------------------------------ #
    # Drawing
    # ------------------------------------------------------------------ #
    def draw(self, surface):
        surface.fill(palette.bg)
        self._draw_road(surface)
        self._draw_trail(surface)
        self._draw_pads(surface)
        self._draw_hud(surface)
        if self.song_time < 0:
            self._draw_countdown(surface)

    def _draw_road(self, surface):
        road = self.road
        for lane in range(NUM_LANES):
            pygame.draw.polygon(surface,
                                shade(palette.surface, -0.35 if lane % 2 else -0.25),
                                road.quad(lane, 0.0, 1.0))
        for lane in range(NUM_LANES + 1):
            idx = min(lane, NUM_LANES - 1)
            edge = 1 if lane == NUM_LANES else 0
            nx = road.lane_edges(idx, 0.0)[edge]
            fx = road.lane_edges(idx, 1.0)[edge]
            pygame.draw.line(surface, shade(palette.surface, 0.10),
                             (fx, road.y_at(1.0)), (nx, road.y_at(0.0)),
                             max(1, self.s(1)))

    def _draw_trail(self, surface):
        """
        Recorded notes drift up the road after you tap them, so the chart
        visibly accumulates behind you as you play.
        """
        road = self.road
        now = self.song_time
        for n in self.notes:
            age = now - n["timestamp"]
            if age < 0 or age > TRAIL_LIFE:
                continue
            near_flat = age * self.pps
            far_flat = near_flat + road.tile_h + n["duration"] * self.pps
            if near_flat > road.travel * 1.2:
                continue
            near_d = road.project(near_flat)
            far_d = road.project(min(far_flat, road.travel * 1.2))
            if far_d <= near_d:
                continue
            alpha = max(0.0, 1.0 - age / TRAIL_LIFE)
            color = lerp(palette.bg, palette.lane(n["lane"]), 0.25 + 0.75 * alpha)
            pygame.draw.polygon(surface, color, road.quad(n["lane"], near_d, far_d))

    def _draw_pads(self, surface):
        road = self.road
        held_lanes = {lane for lane, _ in self.held.values()}
        for lane in range(NUM_LANES):
            left, right = road.lane_edges(lane, 0.0)
            rect = pygame.Rect(int(left) + self.s(3), int(road.hit_y),
                               int(right - left) - self.s(6), road.pad_h)
            color = palette.lane(lane)
            active = lane in held_lanes
            flash = max(self.lane_flash[lane], 1.0 if active else 0.0)

            fill_rounded(surface, rect,
                         lerp(shade(palette.surface, -0.18), color,
                              0.16 + 0.6 * flash),
                         self.s(10))
            fill_rounded(surface, rect,
                         lerp(color, (255, 255, 255), flash * 0.7),
                         self.s(10), width=max(2, self.s(2)))
            draw_text(surface, LANE_NAMES[lane], fonts.get(11, bold=True),
                      lerp(palette.muted, palette.text, flash),
                      center=(rect.centerx, rect.centery))

    def _draw_hud(self, surface):
        lay = self.layout
        top = lay.content_top

        label = "● REC" if self.song_time >= 0 else "READY"
        color = palette.danger if self.song_time >= 0 else palette.muted
        draw_text(surface, label, fonts.get(16, bold=True), color,
                  midleft=(lay.content_left + self.s(4), top + self.s(13)))

        info_font = fonts.get(12)
        draw_text(surface, f"{len(self.notes)} notes", info_font, palette.muted,
                  midleft=(lay.content_left + self.s(4), top + self.s(34)))

        if self.duration:
            time_text = f"{self._fmt(max(0.0, self.song_time))} / {self._fmt(self.duration)}"
            draw_text(surface, time_text, info_font, palette.muted,
                      midleft=(lay.content_left + self.s(76), top + self.s(34)))

        bar = pygame.Rect(lay.content_left + self.s(4), top + self.s(48),
                          lay.content_width - self.s(8), self.s(3))
        fill_rounded(surface, bar, shade(palette.surface, 0.12), self.s(2))
        if self.duration > 0:
            f = max(0.0, min(1.0, self.song_time / self.duration))
            if f > 0:
                fill_rounded(surface, pygame.Rect(bar.x, bar.y,
                                                  int(bar.width * f), bar.height),
                             palette.danger, self.s(2))

        self.group.draw(surface)

    def _draw_countdown(self, surface):
        lay = self.layout
        remaining = -self.song_time
        count = max(1, min(int(COUNTDOWN_SECONDS), int(remaining) + 1))
        draw_text(surface, str(count), fonts.get(64, bold=True), palette.text,
                  center=(lay.width // 2, lay.height // 2 - self.s(40)))
        hint_font = fonts.get(14)
        draw_text(surface,
                  truncate("Tap the pads to the beat — use several fingers at once",
                           hint_font, lay.content_width),
                  hint_font, palette.muted,
                  center=(lay.width // 2, lay.height // 2 + self.s(16)))
        draw_text(surface, "Hold a pad to make a hold note", fonts.get(12),
                  palette.muted,
                  center=(lay.width // 2, lay.height // 2 + self.s(40)))

    @staticmethod
    def _fmt(seconds):
        seconds = max(0.0, seconds)
        return f"{int(seconds // 60)}:{seconds % 60:04.1f}"
