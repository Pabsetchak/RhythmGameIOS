"""
Chart editor, rebuilt for touch.

The desktop editor ran time left-to-right with lanes stacked as rows, which
is right for a wide window and wrong for a phone held upright — it would
leave four 40px rows in a tall empty screen. Here time runs top-to-bottom
and the lanes are four columns, so the editor uses the whole display and
matches the orientation of the road you actually play on.

Gestures, chosen so nothing needs a mode switch:

  drag on empty lane space   scroll through the song
  tap on empty lane space    add a note there
  drag a note                move it in time and between lanes
  drag a note's end handle   stretch it into a hold
  long press a note          delete it
  two-finger pinch           zoom the timeline
  drag the waveform gutter   scrub
"""

import pygame

import audio
import paths
import ui
from app import Screen
from chart_model import (HOLD_MIN, LANE_KEYS, NUM_LANES, load_chart,
                         resolve_holds, save_chart)
from dialogs import PromptDialog
from settings_store import settings
from theme import (draw_text, fill_rounded, fonts, lerp, palette, shade,
                   truncate)
from touch import DOWN, LONG, MOVE, UP

# Timeline zoom limits, in pixels per second of song.
MIN_PPS, MAX_PPS = 40.0, 420.0

# Grab tolerance for a hold's end handle, in design points. Generous,
# because a fingertip is roughly 8mm across and cannot aim at a 7px edge.
HANDLE_GRAB = 26

SNAP_OPTIONS = [("Off", 0.0), ("0.1", 0.1), ("0.05", 0.05)]


class EditorScreen(Screen):
    def __init__(self, app, song_name):
        super().__init__(app)
        self.song_name = song_name

        self.notes = []
        self.duration = 0.0
        self.peaks = []
        self.hit_sounds = None

        self.pps = 130.0
        self.snap_index = 1
        self.view_time = 0.0        # song time at the top of the editor area
        self.position = 0.0         # playhead
        self.playing = False
        self._play_base = 0.0
        self._last_trigger = 0.0

        self.selected = None
        self._pid = None
        self._mode = None           # "scroll" | "move" | "resize" | "scrub"
        self._grab_dt = 0.0
        self._pinch_start = None
        self._dirty = False

        self.group = ui.Group()

    # ------------------------------------------------------------------ #
    # Setup
    # ------------------------------------------------------------------ #
    def on_enter(self):
        mp3 = paths.song_audio(self.song_name)
        self.duration = audio.sound_length(mp3)
        self.notes, self.duration = load_chart(self.song_name, self.duration)

        buckets = max(500, min(3000, int(self.duration * 40))) if self.duration else 1000
        self.peaks = audio.load_waveform(mp3, buckets)

        try:
            self.hit_sounds = audio.HitSoundBank(
                float(settings.get("EDITOR_HIT_VOLUME", 0.5)))
        except Exception as e:
            print(f"Editor: could not load hit sounds: {e}")

        self._build()

    def on_resize(self):
        self._build()

    def on_exit(self):
        audio.stop_music()

    def _build(self):
        lay = self.layout
        self.group.clear()

        top = lay.content_top
        nav_h = self.s(38)
        self.back_btn = self.group.add(ui.Button(
            ui.back_button_rect(lay), "Back", self._leave, lay.scale,
            style=ui.Button.GHOST, font_size=14))

        # Transport row.
        row_y = top + nav_h + self.s(8)
        row_h = self.s(44)
        x = lay.content_left

        self.play_btn = self.group.add(ui.Button(
            pygame.Rect(x, row_y, self.s(44), row_h), "▶", self._toggle_play,
            lay.scale, font_size=18))
        x += self.s(52)

        self._time_x = x
        x += self.s(70)

        snap_w = self.s(126)
        self.group.add(ui.Segmented(
            pygame.Rect(x, row_y, snap_w, row_h),
            [label for label, _ in SNAP_OPTIONS], self.snap_index,
            self._on_snap, lay.scale))
        x += snap_w + self.s(8)

        zoom_w = self.s(36)
        remaining = lay.content_right - x
        if remaining >= zoom_w * 2 + self.s(4):
            self.group.add(ui.Button(
                pygame.Rect(lay.content_right - zoom_w * 2 - self.s(4), row_y,
                            zoom_w, row_h),
                "−", lambda: self._zoom(1 / 1.35), lay.scale,
                style=ui.Button.PLAIN, font_size=18))
            self.group.add(ui.Button(
                pygame.Rect(lay.content_right - zoom_w, row_y, zoom_w, row_h),
                "+", lambda: self._zoom(1.35), lay.scale,
                style=ui.Button.PLAIN, font_size=18))

        # Bottom toolbar.
        bar_h = self.s(ui.BUTTON_H)
        bar_y = lay.content_bottom - bar_h
        gap = self.s(8)
        btn_w = (lay.content_width - gap * 3) // 4
        labels = [
            ("Rec", self._record, ui.Button.GHOST),
            ("Save as", self._save_as, ui.Button.GHOST),
            ("Delete", self._delete_selected, ui.Button.DANGER),
            ("Save", self._save, ui.Button.PRIMARY),
        ]
        self._delete_btn = None
        for i, (label, action, style) in enumerate(labels):
            btn = self.group.add(ui.Button(
                pygame.Rect(lay.content_left + i * (btn_w + gap), bar_y,
                            btn_w, bar_h),
                label, action, lay.scale, style=style, font_size=13))
            if label == "Delete":
                self._delete_btn = btn
                btn.enabled = self.selected is not None

        # Editor canvas.
        canvas_top = row_y + row_h + self.s(10)
        self.canvas = pygame.Rect(lay.content_left, canvas_top,
                                  lay.content_width,
                                  bar_y - self.s(10) - canvas_top)
        self.gutter_w = self.s(46)
        self.lanes_rect = pygame.Rect(self.canvas.x + self.gutter_w, self.canvas.y,
                                      self.canvas.width - self.gutter_w,
                                      self.canvas.height)
        self.lane_w = self.lanes_rect.width / NUM_LANES

    # ------------------------------------------------------------------ #
    # Coordinate mapping
    # ------------------------------------------------------------------ #
    def y_for(self, t):
        return self.canvas.y + (t - self.view_time) * self.pps

    def time_at(self, y):
        return self.view_time + (y - self.canvas.y) / self.pps

    def lane_at(self, x):
        lane = int((x - self.lanes_rect.x) / max(1.0, self.lane_w))
        return max(0, min(NUM_LANES - 1, lane))

    def lane_rect(self, lane):
        return pygame.Rect(int(self.lanes_rect.x + lane * self.lane_w),
                           self.lanes_rect.y, int(self.lane_w),
                           self.lanes_rect.height)

    def view_span(self):
        return self.canvas.height / self.pps

    def max_view_time(self):
        return max(0.0, self.duration - self.view_span() * 0.35)

    def _clamp_view(self):
        self.view_time = max(-0.25, min(self.max_view_time(), self.view_time))

    def snap(self, t):
        step = SNAP_OPTIONS[self.snap_index][1]
        if step > 0:
            t = round(t / step) * step
        return max(0.0, round(t, 4))

    # ------------------------------------------------------------------ #
    # Hit testing
    # ------------------------------------------------------------------ #
    def note_rect(self, n):
        lane = n["lane"]
        x = self.lanes_rect.x + lane * self.lane_w
        y0 = self.y_for(n["timestamp"])
        if n["type"] == "hold" and n["duration"] > 0:
            y1 = self.y_for(n["timestamp"] + n["duration"])
        else:
            y1 = y0 + self.s(16)
        return pygame.Rect(int(x) + self.s(3), int(y0),
                           int(self.lane_w) - self.s(6), max(self.s(10), int(y1 - y0)))

    def note_at(self, x, y):
        """Topmost note under the point, searched newest-first."""
        for n in reversed(self.notes):
            r = self.note_rect(n)
            if r.inflate(0, self.s(HANDLE_GRAB)).collidepoint(x, y):
                return n
        return None

    def on_handle(self, n, y):
        """True if y is within grabbing distance of the note's end."""
        r = self.note_rect(n)
        return abs(y - r.bottom) <= self.s(HANDLE_GRAB) * 0.5

    # ------------------------------------------------------------------ #
    # Input
    # ------------------------------------------------------------------ #
    def handle_pointer(self, ev):
        if self.group.handle_pointer(ev):
            return

        # A second finger anywhere on the canvas becomes a pinch-zoom and
        # cancels whatever single-finger gesture was in flight.
        if self.app.touch.active_count() >= 2:
            self._handle_pinch()
            return
        if self._pinch_start is not None and self.app.touch.active_count() < 2:
            self._pinch_start = None
            self._pid = None
            self._mode = None

        if ev.kind == DOWN:
            self._on_down(ev)
        elif ev.pid != self._pid:
            return
        elif ev.kind == MOVE:
            self._on_move(ev)
        elif ev.kind == LONG:
            self._on_long(ev)
        elif ev.kind == UP:
            self._on_up(ev)

    def _handle_pinch(self):
        dist = self.app.touch.pinch_distance()
        center = self.app.touch.pinch_center()
        if dist is None or dist < 1 or center is None:
            return
        if self._pinch_start is None:
            self._pinch_start = (dist, self.pps, self.time_at(center[1]))
            self._pid = None
            self._mode = None
            return
        start_dist, start_pps, anchor_t = self._pinch_start
        self.pps = max(MIN_PPS, min(MAX_PPS, start_pps * (dist / start_dist)))
        # Keep the song time under the pinch centre pinned in place.
        self.view_time = anchor_t - (center[1] - self.canvas.y) / self.pps
        self._clamp_view()

    def _on_down(self, ev):
        if self._pid is not None or not self.canvas.collidepoint(ev.x, ev.y):
            return
        self._pid = ev.pid

        if ev.x < self.lanes_rect.x:
            self._mode = "scrub"
            self._seek(self.time_at(ev.y))
            return

        note = self.note_at(ev.x, ev.y)
        if note is not None:
            self.selected = note
            self._sync_delete_button()
            if self.on_handle(note, ev.y):
                self._mode = "resize"
            else:
                self._mode = "move"
                self._grab_dt = self.time_at(ev.y) - note["timestamp"]
        else:
            # Might become a scroll; if the finger never moves it is an add.
            self._mode = "scroll"
            self._scroll_anchor = (ev.y, self.view_time)

    def _on_move(self, ev):
        if self._mode == "scroll":
            start_y, start_view = self._scroll_anchor
            self.view_time = start_view - (ev.y - start_y) / self.pps
            self._clamp_view()
        elif self._mode == "scrub":
            self._seek(self.time_at(ev.y))
        elif self._mode == "move" and self.selected is not None:
            n = self.selected
            n["timestamp"] = self.snap(self.time_at(ev.y) - self._grab_dt)
            lane = self.lane_at(ev.x)
            n["lane"] = lane
            n["key"] = LANE_KEYS[lane]
            self._dirty = True
        elif self._mode == "resize" and self.selected is not None:
            n = self.selected
            end = self.snap(self.time_at(ev.y))
            duration = max(0.0, end - n["timestamp"])
            n["duration"] = duration
            n["type"] = "hold" if duration >= HOLD_MIN else "quickPress"
            self._dirty = True

    def _on_long(self, ev):
        if self._mode in ("move", "resize") and self.selected is not None:
            pointer = ev.pointer
            if not pointer.moved:
                self.notes.remove(self.selected)
                self.selected = None
                self._sync_delete_button()
                self._dirty = True
                self._pid = None
                self._mode = None
                self.app.toast("Note deleted")

    def _on_up(self, ev):
        if self._mode == "scroll" and ev.is_tap():
            self._add_note(ev.x, ev.y)
        elif self._mode == "resize" and self.selected is not None:
            n = self.selected
            if n["duration"] < HOLD_MIN:
                n["duration"] = 0.0
                n["type"] = "quickPress"
            resolve_holds(self.notes)
        elif self._mode == "move":
            resolve_holds(self.notes)

        self._pid = None
        self._mode = None

    def _add_note(self, x, y):
        lane = self.lane_at(x)
        t = self.snap(self.time_at(y))
        note = {"type": "quickPress", "key": LANE_KEYS[lane],
                "timestamp": t, "duration": 0.0, "lane": lane}
        self.notes.append(note)
        self.selected = note
        self._sync_delete_button()
        self._dirty = True
        if self.hit_sounds:
            self.hit_sounds.play("ghost")

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._leave()
            elif event.key in (pygame.K_DELETE, pygame.K_BACKSPACE):
                self._delete_selected()
            elif event.key == pygame.K_SPACE:
                self._toggle_play()

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    def _sync_delete_button(self):
        if self._delete_btn is not None:
            self._delete_btn.enabled = self.selected is not None

    def _on_snap(self, index, _label):
        self.snap_index = index

    def _zoom(self, factor):
        anchor_t = self.time_at(self.canvas.centery)
        self.pps = max(MIN_PPS, min(MAX_PPS, self.pps * factor))
        self.view_time = anchor_t - (self.canvas.height * 0.5) / self.pps
        self._clamp_view()

    def _delete_selected(self):
        if self.selected in self.notes:
            self.notes.remove(self.selected)
            self.selected = None
            self._sync_delete_button()
            self._dirty = True

    def _seek(self, t):
        self.position = max(0.0, min(self.duration, t))
        self._last_trigger = self.position
        if self.playing:
            self._start_music()

    def _toggle_play(self):
        if self.playing:
            self._stop_music()
        else:
            self._start_music()

    def _start_music(self):
        used = audio.play_music(paths.song_audio(self.song_name), self.position)
        if used is None:
            self.app.toast("Could not play this track.", error=True)
            return
        # Some SDL builds refuse a start offset and begin from zero; follow
        # whatever actually happened rather than assuming.
        self._play_base = used
        if used != self.position:
            self.position = used
        self._last_trigger = self.position
        self.playing = True
        self.play_btn.text = "⏸"

    def _stop_music(self):
        audio.stop_music()
        self.playing = False
        self.play_btn.text = "▶"

    def _record(self):
        self._stop_music()
        from screens.recorder import RecorderScreen
        self.app.replace(RecorderScreen(self.app, self.song_name))

    def _save(self):
        ok, message = save_chart(self.song_name, self.notes, self.duration)
        if ok:
            self._dirty = False
        self.app.toast(message, error=not ok)

    def _save_as(self):
        self.app.push(PromptDialog(
            self.app, "Save a copy", self._do_save_as,
            initial=f"{self.song_name}_copy",
            message="The audio stays shared with the original.",
            confirm_text="Save"))

    def _do_save_as(self, name):
        import os
        import shutil
        src = paths.song_audio(self.song_name)
        dest = paths.song_audio(name)
        if os.path.exists(dest) and os.path.abspath(src) != os.path.abspath(dest):
            self.app.toast(f"'{name}' already exists.", error=True)
            return
        try:
            if os.path.abspath(src) != os.path.abspath(dest):
                shutil.copy2(src, dest)
        except OSError as e:
            self.app.toast(f"Could not copy audio: {e}", error=True)
            return
        ok, message = save_chart(name, self.notes, self.duration)
        if ok:
            self.song_name = name
            self._dirty = False
        self.app.toast(message, error=not ok)

    def _leave(self):
        self._stop_music()
        if self._dirty:
            from dialogs import ConfirmDialog
            self.app.push(ConfirmDialog(
                self.app, "Discard changes?",
                "This chart has unsaved edits.", self.app.pop,
                confirm_text="Discard", danger=True))
            return
        self.app.pop()

    # ------------------------------------------------------------------ #
    # Frame
    # ------------------------------------------------------------------ #
    def update(self, dt, now):
        self.group.update(dt)

        if not self.playing:
            return
        pos = audio.music_pos()
        if pos < 0:
            self._stop_music()
            return

        self.position = self._play_base + pos
        if self.position >= self.duration:
            self.position = self.duration
            self._stop_music()
            return

        self._fire_hits(self.position)
        self._follow_playhead()

    def _fire_hits(self, now):
        """One preview click per note the playhead just crossed."""
        prev = self._last_trigger
        if self.hit_sounds and now > prev:
            for n in self.notes:
                if prev < n["timestamp"] <= now:
                    self.hit_sounds.play()
                    break        # one cue per tick, so chords don't stack
        self._last_trigger = now

    def _follow_playhead(self):
        """Keep the playhead a third of the way down while playing."""
        target = self.position - self.view_span() * 0.33
        self.view_time += (target - self.view_time) * 0.25
        self._clamp_view()

    # ------------------------------------------------------------------ #
    # Drawing
    # ------------------------------------------------------------------ #
    def draw(self, surface):
        lay = self.layout
        surface.fill(palette.bg)

        ui.draw_nav_bar(surface, lay, truncate(self.song_name,
                                               fonts.get(24, bold=True),
                                               lay.content_width - lay.s(100)))

        draw_text(surface, self._fmt(self.position), fonts.get(13, bold=True),
                  palette.text,
                  midleft=(self._time_x, self.canvas.y - self.s(32)))

        self._draw_canvas(surface)
        self.group.draw(surface)

    def _draw_canvas(self, surface):
        prev_clip = surface.get_clip()
        surface.set_clip(self.canvas)

        fill_rounded(surface, self.canvas, shade(palette.surface, -0.30),
                     self.s(10))
        self._draw_lanes(surface)
        self._draw_grid(surface)
        self._draw_waveform(surface)
        self._draw_notes(surface)
        self._draw_playhead(surface)

        surface.set_clip(prev_clip)
        fill_rounded(surface, self.canvas, palette.divider, self.s(10),
                     width=max(1, self.s(1)))

    def _draw_lanes(self, surface):
        for lane in range(NUM_LANES):
            r = self.lane_rect(lane)
            pygame.draw.rect(surface,
                             shade(palette.surface, -0.22 if lane % 2 else -0.16),
                             r)
            # Lane colour chip at the very top so columns are identifiable.
            chip = pygame.Rect(r.x + self.s(4), self.canvas.y, r.width - self.s(8),
                               self.s(3))
            pygame.draw.rect(surface, palette.lane(lane), chip)

        pygame.draw.rect(surface, shade(palette.surface, -0.40),
                         pygame.Rect(self.canvas.x, self.canvas.y,
                                     self.gutter_w, self.canvas.height))

    def _draw_grid(self, surface):
        """Second gridlines with labels, plus subdivisions when zoomed in."""
        span = self.view_span()
        first = int(max(0.0, self.view_time))
        last = int(self.view_time + span) + 1

        show_tenths = self.pps * 0.1 >= 11
        faint = lerp(shade(palette.surface, -0.16), palette.text, 0.10)
        label_font = fonts.get(10)

        for sec in range(first, last + 1):
            y = self.y_for(sec)
            if y < self.canvas.y - 2 or y > self.canvas.bottom + 2:
                continue
            pygame.draw.line(surface, lerp(faint, palette.text, 0.18),
                             (self.lanes_rect.x, y), (self.lanes_rect.right, y))
            draw_text(surface, self._fmt(sec, short=True), label_font,
                      palette.muted,
                      midleft=(self.canvas.x + self.s(4), y + self.s(7)))

            if show_tenths:
                for k in range(1, 10):
                    ty = self.y_for(sec + k * 0.1)
                    if self.canvas.y <= ty <= self.canvas.bottom:
                        pygame.draw.line(surface, faint,
                                         (self.lanes_rect.x, ty),
                                         (self.lanes_rect.right, ty))

    def _draw_waveform(self, surface):
        if not self.peaks or self.duration <= 0:
            return
        nb = len(self.peaks)
        cx = self.canvas.x + self.gutter_w - self.s(11)
        half = self.s(9)
        step = max(1, int(self.s(2)))
        color = lerp(palette.accent, palette.bg, 0.35)

        y = self.canvas.y
        while y < self.canvas.bottom:
            t = self.time_at(y)
            if 0 <= t <= self.duration:
                b = min(nb - 1, int(t / self.duration * nb))
                amp = self.peaks[b] * half
                if amp >= 1:
                    pygame.draw.line(surface, color,
                                     (cx - amp, y), (cx + amp, y))
            y += step

    def _draw_notes(self, surface):
        for n in self.notes:
            r = self.note_rect(n)
            if r.bottom < self.canvas.y - 20 or r.top > self.canvas.bottom + 20:
                continue

            color = palette.lane(n["lane"])
            selected = n is self.selected

            if n["type"] == "hold" and n["duration"] > 0:
                fill_rounded(surface, r, lerp(color, palette.bg, 0.55), self.s(6))
                fill_rounded(surface, r, color, self.s(6), width=max(1, self.s(1)))
                # Solid head marks where the hold starts.
                head = pygame.Rect(r.x, r.y, r.width, self.s(8))
                fill_rounded(surface, head, color, self.s(4))
                # Light cap marks where it ends — and is the drag handle.
                cap = pygame.Rect(r.x, r.bottom - self.s(8), r.width, self.s(8))
                fill_rounded(surface, cap, palette.text, self.s(4))
            else:
                fill_rounded(surface, r, color, self.s(6))

            if selected:
                fill_rounded(surface, r.inflate(self.s(4), self.s(4)),
                             palette.text, self.s(8), width=max(2, self.s(2)))

    def _draw_playhead(self, surface):
        y = self.y_for(self.position)
        if self.canvas.y - 2 <= y <= self.canvas.bottom + 2:
            pygame.draw.line(surface, palette.danger,
                             (self.canvas.x, y), (self.canvas.right, y),
                             max(2, self.s(2)))

    @staticmethod
    def _fmt(seconds, short=False):
        seconds = max(0.0, seconds)
        if short:
            return f"{int(seconds // 60)}:{int(seconds % 60):02d}"
        return f"{int(seconds // 60)}:{seconds % 60:04.1f}"
