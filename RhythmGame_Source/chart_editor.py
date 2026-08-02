import customtkinter as ctk
import tkinter as tk
import os
import json
import pygame

from settings import settings
from map_exporter import MapExporter
from sound import load_waveform, init_audio, HitSoundBank
from ui_manager import (BaseScreen, CreatorScreen, LANE_NAMES, rgb_to_hex,
                        FONT_BODY, FONT_HEADING, FONT_SMALL)

# Vertical layout of the editor canvas (pixels).
WAVE_TOP, WAVE_H = 10, 70
TL_TOP, TL_H = 84, 22
LANES_TOP, LANE_H, NUM_LANES = 112, 44, 4
CANVAS_H = LANES_TOP + LANE_H * NUM_LANES + 8
GUTTER_W = 66

TAP_W = 14          # drawn width of a tap note (pixels)
GRAB = 7            # px tolerance for grabbing a hold's end handle
HOLD_MIN = 0.06     # durations >= this become hold notes
LANE_KEYS = ["a", "s", "d", "f"]
REC_HOLD_THRESHOLD = 0.15   # held >= this while recording -> a hold note


def _parse_hex(c):
    if isinstance(c, str) and c.startswith("#") and len(c) == 7:
        try:
            return (int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16))
        except ValueError:
            return None
    return None


def _lerp_hex(a, b, f):
    """Blend two hex colors; returns hex, or `a` if either isn't parseable."""
    ca, cb = _parse_hex(a), _parse_hex(b)
    if not ca or not cb:
        return a
    return "#%02x%02x%02x" % tuple(int(ca[i] + (cb[i] - ca[i]) * f) for i in range(3))


class ChartEditorScreen(BaseScreen):
    def __init__(self, parent, app, song_name):
        super().__init__(parent, app, song_name, back_to=CreatorScreen)
        self.song_name = song_name
        self.mp3 = os.path.join("rhythms", f"{song_name}.mp3")
        self.json_path = os.path.join("rhythms", f"{song_name}.json")

        self.pps = 130.0
        self.snap_step = 0.1        # seconds; 0 = off
        self.position = 0.0
        self._playing = False
        self._play_base = 0.0
        self._after_id = None
        self._last_trigger_pos = 0.0    # for firing hit sounds during preview
        self.hit_sound = None
        self._recording = False
        self.rec_held = {}              # keysym -> press time while recording

        self.notes = []
        self.active = None      # note being dragged
        self.selected = None
        self.mode = None        # "move" | "resize"
        self.drag_dx = 0.0
        self.playhead = None

        self._resolve_theme_colors()
        self.lane_colors = [rgb_to_hex(settings.get(LANE_NAMES[i], [255, 255, 255]))
                            for i in range(NUM_LANES)]

        self._load_audio()
        self._load_chart()
        self._build_ui()

        # Press Escape anywhere in the editor to go back. Bound at the root so
        # it works regardless of which widget has focus; removed on destroy.
        self.app.bind("<Escape>", self._on_escape)

        self.after(50, self._first_draw)

    def _on_escape(self, event=None):
        # While recording, Escape is the stop keybind; otherwise it leaves.
        if self._recording:
            self._stop_recording()
        else:
            self.app.show_screen(CreatorScreen)

    # -- theming -- #
    def _resolve_theme_colors(self):
        def tc(widget, key, fallback):
            try:
                v = ctk.ThemeManager.theme[widget][key]
                if isinstance(v, (list, tuple)):
                    return v[0 if ctk.get_appearance_mode() == "Light" else 1]
                return v
            except Exception:
                return fallback
        light = ctk.get_appearance_mode() == "Light"
        self.c_bg = tc("CTkFrame", "fg_color", "#2b2b2b")
        self.c_text = tc("CTkLabel", "text_color", "#202020" if light else "#dcdcdc")
        self.c_accent = tc("CTkButton", "fg_color", "#3a7ebf")
        self.c_grid = "#c8c8c8" if light else "#3c3c3c"
        self.c_play = "#ff5252"

    def _to_hex(self, c):
        """Resolve any Tk color name (e.g. 'gray17') to a #rrggbb hex string."""
        if _parse_hex(c):
            return c
        try:
            r, g, b = self.main.winfo_rgb(c)
            return "#%02x%02x%02x" % (r // 256, g // 256, b // 256)
        except Exception:
            return c

    def _normalize_colors(self):
        """Convert resolved colors to hex and derive band/lane shades.
        Must run after the canvas exists (uses winfo_rgb)."""
        self.c_bg = self._to_hex(self.c_bg)
        self.c_text = self._to_hex(self.c_text)
        self.c_accent = self._to_hex(self.c_accent)
        self.c_grid = self._to_hex(self.c_grid)
        self.c_wave = _lerp_hex(self.c_accent, self.c_bg, 0.4)
        self.c_waveband = _lerp_hex(self.c_bg, self.c_text, 0.05)
        self.c_timeband = _lerp_hex(self.c_bg, self.c_text, 0.11)
        self.c_lane_a = self.c_bg
        self.c_lane_b = _lerp_hex(self.c_bg, self.c_text, 0.06)

    # -- data -- #
    def _load_audio(self):
        self.duration = 0.0
        self.peaks = []
        try:
            init_audio()      # low-latency mixer so preview hits stay tight
            self.duration = pygame.mixer.Sound(self.mp3).get_length()
        except Exception as e:
            print(f"Editor: could not load audio: {e}")
        buckets = max(500, min(3000, int(self.duration * 40))) if self.duration else 1000
        self.peaks = load_waveform(self.mp3, buckets)

        # Note-hit sounds for previewing (same bank as the game, but with its
        # own volume so the editor preview is independent of gameplay).
        try:
            self.hit_sound = HitSoundBank(float(settings.get("EDITOR_HIT_VOLUME", 0.5)))
        except Exception as e:
            print(f"Editor: could not load hit sounds: {e}")

    def _load_chart(self):
        if os.path.exists(self.json_path):
            try:
                with open(self.json_path) as f:
                    data = json.load(f)
                if data.get("duration"):
                    self.duration = self.duration or float(data["duration"])
                for e in data.get("note_events", []):
                    is_hold = e.get("type") == "hold"
                    self.notes.append({
                        "type": "hold" if is_hold else "quickPress",
                        "key": e.get("key", "a"),
                        "timestamp": float(e.get("timestamp", 0.0)),
                        "duration": float(e.get("duration", 0.0)) if is_hold else 0.0,
                        "lane": 0,
                    })
            except Exception as e:
                print(f"Editor: could not load chart: {e}")
        if not self.duration:
            end = max((n["timestamp"] + n["duration"] for n in self.notes), default=30.0)
            self.duration = end + 5.0
        self._assign_lanes()
        self._resolve_holds()

    # Notes within this gap (seconds) count as "close" and get spread out.
    SPREAD_WINDOW = 0.35

    def _assign_lanes(self):
        """
        Lay notes out for readability: notes close together in time are spread
        across the four lanes (least-recently-used first), while a lane busy
        with a hold is never reused. Notes that are well separated fall back to
        the leftmost free lane, so sparse sections stay tidy.
        """
        last_used = [-1e9] * NUM_LANES   # when each lane last held a note
        hold_until = [0.0] * NUM_LANES   # lane blocked by a hold until this time
        prev_t = None

        for n in sorted(self.notes, key=lambda x: x["timestamp"]):
            t = n["timestamp"]
            free = [l for l in range(NUM_LANES) if hold_until[l] <= t + 1e-6]
            cands = free if free else list(range(NUM_LANES))

            if prev_t is None or (t - prev_t) > self.SPREAD_WINDOW:
                lane = min(cands)                       # sparse: keep it tidy
            else:
                # Close to the previous note: pick the lane idle the longest.
                lane = max(cands, key=lambda l: t - last_used[l])

            n["lane"] = lane
            n["key"] = LANE_KEYS[lane]
            end = t + max(n["duration"], 0.0)
            last_used[lane] = end
            if n["type"] == "hold" and n["duration"] > 0:
                hold_until[lane] = end
            prev_t = t

    def _hold_covering(self, lane, t, exclude=None):
        """Return a hold note in `lane` whose span covers time `t` (or None)."""
        for m in self.notes:
            if m is exclude or m["type"] != "hold" or m["duration"] <= 0:
                continue
            if m["lane"] == lane and m["timestamp"] - 1e-6 <= t < m["timestamp"] + m["duration"]:
                return m
        return None

    def _resolve_holds(self):
        """
        Make sure no note starts inside another lane's hold: if a beat would
        sit inside a hold, move it to a lane that has no hold there. Holds are
        processed earliest-first so they act as anchors; only later, conflicting
        notes are relocated. Lanes are display-only, so this just keeps the
        layout readable (and mirrors how the game avoids spawning on holds).
        """
        for n in sorted(self.notes, key=lambda x: x["timestamp"]):
            if self._hold_covering(n["lane"], n["timestamp"], exclude=n):
                free = [l for l in range(NUM_LANES)
                        if not self._hold_covering(l, n["timestamp"], exclude=n)]
                if free:
                    n["lane"] = min(free, key=lambda l: abs(l - n["lane"]))
                    n["key"] = LANE_KEYS[n["lane"]]

    # -- UI -- #
    def _build_ui(self):
        self.content.grid_rowconfigure(1, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        # Toolbar (two rows so nothing gets cramped on narrow windows).
        bar = ctk.CTkFrame(self.content)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        row1 = ctk.CTkFrame(bar, fg_color="transparent")
        row1.pack(fill="x")
        row2 = ctk.CTkFrame(bar, fg_color="transparent")
        row2.pack(fill="x")

        # Row 1: transport, snap, zoom, save.
        self.play_btn = ctk.CTkButton(row1, text="▶ Play", width=90, height=34,
                                      corner_radius=8, command=self._toggle_play)
        self.play_btn.pack(side="left", padx=(10, 6), pady=6)

        self.time_label = ctk.CTkLabel(row1, text="", font=FONT_BODY, width=120)
        self.time_label.pack(side="left", padx=6)

        ctk.CTkLabel(row1, text="Snap", font=FONT_BODY).pack(side="left", padx=(12, 2))
        self.snap_menu = ctk.CTkOptionMenu(
            row1, width=92, values=["Off", "0.1 s", "0.01 s"], command=self._on_snap)
        self.snap_menu.set("0.1 s")
        self.snap_menu.pack(side="left", padx=(2, 8), pady=6)

        ctk.CTkButton(row1, text="−", width=38, height=34, corner_radius=8,
                      command=lambda: self._zoom(1 / 1.3)).pack(side="left", padx=(12, 2), pady=6)
        ctk.CTkButton(row1, text="+", width=38, height=34, corner_radius=8,
                      command=lambda: self._zoom(1.3)).pack(side="left", padx=2, pady=6)
        ctk.CTkLabel(row1, text="Zoom", font=FONT_SMALL).pack(side="left", padx=(2, 6))

        ctk.CTkButton(row1, text="Save As / Export…", width=150, height=34,
                      corner_radius=8, fg_color="transparent", border_width=1,
                      command=self._save_as).pack(side="right", padx=(6, 10), pady=6)
        ctk.CTkButton(row1, text="Save", width=90, height=34, corner_radius=8,
                      command=self._save).pack(side="right", padx=6, pady=6)

        # Row 2: editor preview hit-sound volume (independent of gameplay).
        ctk.CTkLabel(row2, text="Preview hit volume", font=FONT_BODY).pack(
            side="left", padx=(10, 6), pady=(0, 8))
        self.vol_value = ctk.CTkLabel(row2, text="", font=FONT_SMALL, width=42)
        self.vol_value.pack(side="left", padx=(0, 6), pady=(0, 8))
        self.vol_slider = ctk.CTkSlider(row2, from_=0, to=100, width=180,
                                        command=self._on_editor_volume)
        saved_vol = float(settings.get("EDITOR_HIT_VOLUME", 0.5)) * 100
        self.vol_slider.set(saved_vol)
        self.vol_slider.pack(side="left", padx=4, pady=(0, 8))
        # Show the saved value directly — don't route through the handler at
        # build time, so construction never re-saves (or corrupts) the setting.
        self.vol_value.configure(text=f"{int(saved_vol)}%")

        # Section recorder: play along from the playhead to lay down notes.
        self.rec_btn = ctk.CTkButton(row2, text="● Record", width=130, height=34,
                                     corner_radius=8, command=self._toggle_record)
        self.rec_btn.pack(side="right", padx=(6, 10), pady=(0, 8))
        self._rec_default_fg = self.rec_btn.cget("fg_color")
        self._rec_default_hover = self.rec_btn.cget("hover_color")

        # Editor canvases.
        edit = ctk.CTkFrame(self.content, fg_color="transparent")
        edit.grid(row=1, column=0, sticky="nsew")
        edit.grid_columnconfigure(1, weight=1)
        edit.grid_rowconfigure(0, weight=1)

        self.gutter = tk.Canvas(edit, width=GUTTER_W, height=CANVAS_H,
                                bg=self.c_bg, highlightthickness=0, bd=0)
        self.gutter.grid(row=0, column=0, sticky="ns")

        self.main = tk.Canvas(edit, height=CANVAS_H, bg=self.c_bg,
                              highlightthickness=0, bd=0)
        self.main.grid(row=0, column=1, sticky="nsew")

        hbar = ctk.CTkScrollbar(edit, orientation="horizontal", command=self.main.xview)
        hbar.grid(row=1, column=1, sticky="ew", pady=(4, 0))
        self.main.configure(xscrollcommand=hbar.set)

        self.main.bind("<ButtonPress-1>", self._on_press)
        self.main.bind("<B1-Motion>", self._on_motion)
        self.main.bind("<ButtonRelease-1>", self._on_release)
        self.main.bind("<Button-3>", self._on_right)
        self.main.bind("<Delete>", lambda e: self._delete_selected())
        self.main.bind("<BackSpace>", lambda e: self._delete_selected())

        self.status = ctk.CTkLabel(
            self.content, font=FONT_SMALL, text_color=("gray40", "gray60"),
            text="Click a lane to add a note  •  drag to move  •  drag the right "
                 "edge to make a hold  •  right-click to delete    │    "
                 "bright tick = note start, light cap = hold end")
        self.status.grid(row=2, column=0, sticky="ew", pady=(8, 0))

    def _first_draw(self):
        self._normalize_colors()
        self._redraw_static()
        self._draw_gutter()
        self.playhead = self.main.create_line(0, 0, 0, CANVAS_H,
                                              fill=self.c_play, width=2, tags="playhead")
        self._draw_notes()
        self._update_playhead()
        self._update_time_label()

    # -- drawing -- #
    def total_width(self):
        return self.duration * self.pps + 60

    # y-boundaries of each editor region.
    BAND_WAVE_BOTTOM = 82
    BAND_TIME_BOTTOM = LANES_TOP          # = 112

    def _redraw_static(self):
        self.main.delete("static")
        w = self.total_width()
        self.main.configure(scrollregion=(0, 0, w, CANVAS_H))
        lanes_bottom = LANES_TOP + NUM_LANES * LANE_H

        # Region background bands so each section reads as its own area.
        self.main.create_rectangle(0, 0, w, self.BAND_WAVE_BOTTOM,
                                   fill=self.c_waveband, outline="", tags="static")
        self.main.create_rectangle(0, self.BAND_WAVE_BOTTOM, w, self.BAND_TIME_BOTTOM,
                                   fill=self.c_timeband, outline="", tags="static")
        for l in range(NUM_LANES):
            y0 = LANES_TOP + l * LANE_H
            self.main.create_rectangle(0, y0, w, y0 + LANE_H, outline="",
                                       fill=self.c_lane_b if l % 2 else self.c_lane_a,
                                       tags="static")

        # Waveform (filled polygon), kept inside the top band.
        mid = WAVE_TOP + WAVE_H / 2
        half = WAVE_H / 2 - 2
        if self.peaks and self.duration > 0:
            nb = len(self.peaks)
            step = max(2, int(self.pps * 0.012))
            top, bot = [], []
            x = 0
            while x <= w:
                b = min(nb - 1, int(x / self.pps / self.duration * nb))
                amp = self.peaks[b] * half
                top += [x, mid - amp]
                bot += [x, mid + amp]
                x += step
            self.main.create_polygon(*(top + bot[::-1]), fill=self.c_wave,
                                     outline="", tags="static")
        else:
            self.main.create_line(0, mid, w, mid, fill=self.c_grid, tags="static")

        # Timeline ticks + labels + second gridlines through the lanes.
        show_tenths = self.pps * 0.1 >= 9
        faint = _lerp_hex(self.c_grid, self.c_bg, 0.5)
        sec = 0.0
        while sec <= self.duration + 1:
            x = sec * self.pps
            self.main.create_line(x, self.BAND_WAVE_BOTTOM, x, self.BAND_TIME_BOTTOM,
                                  fill=self.c_text, tags="static")
            self.main.create_text(x + 3, self.BAND_WAVE_BOTTOM + 2, anchor="nw",
                                  text=self._fmt(sec), fill=self.c_text,
                                  font=("Roboto", 9), tags="static")
            self.main.create_line(x, LANES_TOP, x, lanes_bottom, fill=self.c_grid,
                                  tags="static")
            if show_tenths:
                for k in range(1, 10):
                    xt = (sec + k * 0.1) * self.pps
                    self.main.create_line(xt, LANES_TOP, xt, lanes_bottom,
                                          fill=faint, tags="static")
            else:
                xh = (sec + 0.5) * self.pps
                self.main.create_line(xh, self.BAND_TIME_BOTTOM - 7, xh,
                                      self.BAND_TIME_BOTTOM, fill=self.c_text,
                                      tags="static")
            sec += 1.0

        # Bold separators between regions + lane separators.
        for y in (self.BAND_WAVE_BOTTOM, self.BAND_TIME_BOTTOM, lanes_bottom):
            self.main.create_line(0, y, w, y, fill=self.c_grid, width=2, tags="static")
        for l in range(1, NUM_LANES):
            y = LANES_TOP + l * LANE_H
            self.main.create_line(0, y, w, y, fill=faint, tags="static")

    def _draw_gutter(self):
        g = self.gutter
        g.delete("all")
        g.configure(bg=self.c_bg)
        lanes_bottom = LANES_TOP + NUM_LANES * LANE_H

        # Mirror the region bands so labels sit on matching backgrounds.
        g.create_rectangle(0, 0, GUTTER_W, self.BAND_WAVE_BOTTOM,
                           fill=self.c_waveband, outline="")
        g.create_rectangle(0, self.BAND_WAVE_BOTTOM, GUTTER_W, self.BAND_TIME_BOTTOM,
                           fill=self.c_timeband, outline="")
        for l in range(NUM_LANES):
            y0 = LANES_TOP + l * LANE_H
            g.create_rectangle(0, y0, GUTTER_W, y0 + LANE_H, outline="",
                               fill=self.c_lane_b if l % 2 else self.c_lane_a)

        g.create_text(GUTTER_W / 2, WAVE_TOP + WAVE_H / 2, text="WAVE",
                      fill=self.c_text, font=("Roboto", 10, "bold"))
        g.create_text(GUTTER_W / 2, (self.BAND_WAVE_BOTTOM + self.BAND_TIME_BOTTOM) / 2,
                      text="TIME", fill=self.c_text, font=("Roboto", 10, "bold"))
        for l in range(NUM_LANES):
            y = LANES_TOP + l * LANE_H + LANE_H / 2
            g.create_rectangle(8, y - 8, 22, y + 8, outline="", fill=self.lane_colors[l])
            g.create_text(GUTTER_W - 8, y, anchor="e", text=str(l + 1),
                          fill=self.c_text, font=("Roboto", 11, "bold"))

        for y in (self.BAND_WAVE_BOTTOM, self.BAND_TIME_BOTTOM, lanes_bottom):
            g.create_line(0, y, GUTTER_W, y, fill=self.c_grid, width=2)
        g.create_line(GUTTER_W - 1, 0, GUTTER_W - 1, CANVAS_H, fill=self.c_grid, width=2)

    def _draw_notes(self):
        self.main.delete("note")
        cap = 8
        for n in self.notes:
            lane = n["lane"]
            x0 = n["timestamp"] * self.pps
            y0 = LANES_TOP + lane * LANE_H + 6
            y1 = LANES_TOP + (lane + 1) * LANE_H - 6
            color = self.lane_colors[lane]
            sel = n is self.selected

            if n["type"] == "hold" and n["duration"] > 0:
                x1 = (n["timestamp"] + n["duration"]) * self.pps
                body = _lerp_hex(color, self.c_bg, 0.5)
                # Dimmed body with a colored border.
                self.main.create_rectangle(x0, y0, x1, y1, fill=body, outline=color,
                                           width=1, tags="note")
                # Solid bright head = where the hold STARTS.
                self.main.create_rectangle(x0, y0, x0 + cap, y1, fill=color,
                                           outline="", tags="note")
                # Light end cap = where the hold ENDS.
                self.main.create_rectangle(x1 - cap, y0, x1, y1, fill=self.c_text,
                                           outline="", tags="note")
                self.main.create_line(x1, y0 - 3, x1, y1 + 3, fill=self.c_text,
                                      width=2, tags="note")
                if sel:
                    self.main.create_rectangle(x0, y0, x1, y1, outline=self.c_play,
                                               width=2, tags="note")
            else:
                x1 = x0 + TAP_W
                self.main.create_rectangle(x0, y0, x1, y1, fill=color,
                                           outline=self.c_play if sel else "",
                                           width=2 if sel else 0, tags="note")

            # Bright start tick marks where every note begins.
            self.main.create_line(x0, y0 - 3, x0, y1 + 3, fill=self.c_text,
                                  width=2, tags="note")

        if self.playhead is not None:
            self.main.tag_raise("playhead")

    def _update_playhead(self):
        if self.playhead is None:
            return
        x = self.position * self.pps
        self.main.coords(self.playhead, x, 0, x, CANVAS_H)
        self.main.tag_raise("playhead")

    def _update_time_label(self):
        self.time_label.configure(
            text=f"{self._fmt(self.position)} / {self._fmt(self.duration)}")

    def _fmt(self, s):
        s = max(0.0, s)
        return f"{int(s // 60)}:{s % 60:04.1f}"

    # -- interaction -- #
    def _lane_from_y(self, y):
        if LANES_TOP <= y < LANES_TOP + NUM_LANES * LANE_H:
            return int((y - LANES_TOP) // LANE_H)
        return None

    def _note_at(self, x, lane):
        hit = None
        for n in self.notes:
            if n["lane"] != lane:
                continue
            x0 = n["timestamp"] * self.pps
            if n["type"] == "hold" and n["duration"] > 0:
                x1 = (n["timestamp"] + n["duration"]) * self.pps
            else:
                x1 = x0 + TAP_W
            if x0 - 3 <= x <= x1 + GRAB:
                hit = n
        return hit

    def _snap(self, t):
        if self.snap_step > 0:
            t = round(t / self.snap_step) * self.snap_step
        return max(0.0, round(t, 4))

    def _on_press(self, event):
        self.main.focus_set()
        x = self.main.canvasx(event.x)
        y = event.y
        lane = self._lane_from_y(y)
        if lane is None:
            if y < LANES_TOP:           # waveform / timeline -> seek
                self._seek(x / self.pps)
            self.active = None
            return

        note = self._note_at(x, lane)
        if note:
            self.selected = note
            self.active = note
            if note["type"] == "hold" and note["duration"] > 0:
                x1 = (note["timestamp"] + note["duration"]) * self.pps
            else:
                x1 = note["timestamp"] * self.pps + TAP_W
            if abs(x - x1) <= GRAB:
                self.mode = "resize"
            else:
                self.mode = "move"
                self.drag_dx = x - note["timestamp"] * self.pps
        else:
            # Create a new note and start stretching it (drag right -> hold).
            note = {"type": "quickPress", "key": LANE_KEYS[lane],
                    "timestamp": self._snap(x / self.pps), "duration": 0.0, "lane": lane}
            self.notes.append(note)
            self.selected = note
            self.active = note
            self.mode = "resize"
        self._draw_notes()

    def _on_motion(self, event):
        if not self.active:
            return
        x = self.main.canvasx(event.x)
        if self.mode == "move":
            self.active["timestamp"] = self._snap((x - self.drag_dx) / self.pps)
            lane = self._lane_from_y(event.y)
            if lane is not None:
                self.active["lane"] = lane
                self.active["key"] = LANE_KEYS[lane]
        elif self.mode == "resize":
            dur = max(0.0, self._snap(x / self.pps) - self.active["timestamp"])
            self.active["duration"] = dur
            self.active["type"] = "hold" if dur >= HOLD_MIN else "quickPress"
        self._draw_notes()

    def _on_release(self, event):
        if self.active and self.active["duration"] < HOLD_MIN:
            self.active["duration"] = 0.0
            self.active["type"] = "quickPress"
        self.active = None
        self.mode = None
        self._resolve_holds()
        self._draw_notes()

    def _on_right(self, event):
        x = self.main.canvasx(event.x)
        lane = self._lane_from_y(event.y)
        if lane is None:
            return
        note = self._note_at(x, lane)
        if note:
            self.notes.remove(note)
            if self.selected is note:
                self.selected = None
            self._draw_notes()

    def _delete_selected(self):
        if self._recording:
            return
        if self.selected in self.notes:
            self.notes.remove(self.selected)
            self.selected = None
            self._draw_notes()

    # -- transport -- #
    def _on_snap(self, value):
        self.snap_step = {"Off": 0.0, "0.1 s": 0.1, "0.01 s": 0.01}.get(value, 0.1)

    def _on_editor_volume(self, value):
        vol = round(value / 100.0, 2)
        settings.set("EDITOR_HIT_VOLUME", vol)
        settings.save_settings()
        if self.hit_sound:
            self.hit_sound.set_volume(vol)
        self.vol_value.configure(text=f"{int(value)}%")

    # -- section recording -- #
    def _current_pos(self):
        """Live song position (accurate to the audio clock while playing)."""
        if self._playing and pygame.mixer.get_init():
            p = pygame.mixer.music.get_pos()
            if p >= 0:
                return self._play_base + p / 1000.0
        return self.position

    def _toggle_record(self):
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        """Play from the playhead and capture any key as notes until stopped."""
        self._recording = True
        self.rec_held = {}
        self.rec_btn.configure(text="■ Stop (Esc)", fg_color="#c0392b",
                               hover_color="#a93226")
        self.play_btn.configure(state="disabled")
        self.status.configure(
            text="● Recording — play along on any keys; press Esc (or Stop) to finish.")
        # Capture every key while recording (Escape is handled as the stop key).
        self.app.bind("<KeyPress>", self._rec_keydown)
        self.app.bind("<KeyRelease>", self._rec_keyup)
        if not self._playing:
            self._start_music()

    def _stop_recording(self):
        if not self._recording:
            return
        self._recording = False
        # Commit any keys still held down at the moment we stop.
        now = self._current_pos()
        for press_t in list(self.rec_held.values()):
            self._commit_recorded(press_t, now)
        self.rec_held = {}

        try:
            self.app.unbind("<KeyPress>")
            self.app.unbind("<KeyRelease>")
        except Exception:
            pass
        self._stop_music()
        self.play_btn.configure(state="normal")
        self.rec_btn.configure(text="● Record", fg_color=self._rec_default_fg,
                               hover_color=self._rec_default_hover)

        # Lay out the merged set and redraw.
        self._assign_lanes()
        self._resolve_holds()
        self._draw_notes()
        self.status.configure(text=f"Recording added. Total notes: {len(self.notes)}")

    def _rec_keydown(self, event):
        if not self._recording:
            return
        ks = event.keysym
        if ks == "Escape" or ks in self.rec_held:   # stop key / auto-repeat
            return
        self.rec_held[ks] = self._current_pos()
        if self.hit_sound:
            self.hit_sound.play()                    # audible feedback

    def _rec_keyup(self, event):
        if not self._recording:
            return
        ks = event.keysym
        if ks in self.rec_held:
            self._commit_recorded(self.rec_held.pop(ks), self._current_pos())

    def _commit_recorded(self, press_t, release_t):
        press_t = max(0.0, min(self.duration, press_t))
        dur = max(0.0, release_t - press_t)
        is_hold = dur >= REC_HOLD_THRESHOLD
        self.notes.append({
            "type": "hold" if is_hold else "quickPress",
            "key": "a",                              # lane/key set by _assign_lanes
            "timestamp": round(press_t, 4),
            "duration": round(dur, 4) if is_hold else 0.0,
            "lane": 0,
        })

    def _zoom(self, factor):
        self.pps = max(40.0, min(400.0, self.pps * factor))
        self._redraw_static()
        self._draw_notes()
        self._update_playhead()

    def _seek(self, t):
        self.position = max(0.0, min(self.duration, t))
        self._last_trigger_pos = self.position   # don't replay earlier hits
        self._update_playhead()
        self._update_time_label()
        if self._playing:
            self._start_music()

    def _toggle_play(self):
        if self._playing:
            self._stop_music()
        else:
            self._start_music()

    def _start_music(self):
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(self.mp3)
            try:
                # Start at the current position if the backend supports it...
                pygame.mixer.music.play(start=self.position)
                self._play_base = self.position
            except Exception:
                # ...otherwise fall back to playing from the top so the music
                # still plays (some SDL/MP3 builds reject a start offset).
                pygame.mixer.music.play()
                self._play_base = 0.0
                self.position = 0.0
                self._update_playhead()
                self._update_time_label()
        except Exception as e:
            self.status.configure(text=f"Playback error: {e}")
            return
        self._last_trigger_pos = self.position
        self._playing = True
        self.play_btn.configure(text="⏸ Pause")
        self._poll()

    def _stop_music(self):
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
        self._playing = False
        if self.play_btn.winfo_exists():
            self.play_btn.configure(text="▶ Play")

    def _poll(self):
        if not self._playing:
            return
        pos = pygame.mixer.music.get_pos()
        if pos < 0:
            self._stop_music()
            return
        self.position = self._play_base + pos / 1000.0
        if self.position >= self.duration:
            self._fire_hits(self.duration)
            self.position = self.duration
            self._update_playhead()
            self._update_time_label()
            if self._recording:
                self._stop_recording()
            else:
                self._stop_music()
            return
        self._fire_hits(self.position)
        self._update_playhead()
        self._update_time_label()
        self._autoscroll()
        self._after_id = self.after(30, self._poll)

    def _fire_hits(self, now):
        """Play the hit sound once for each note the playhead has just passed."""
        prev = self._last_trigger_pos
        if self.hit_sound and now > prev:
            for n in self.notes:
                if prev < n["timestamp"] <= now:
                    self.hit_sound.play()
                    break       # one cue per tick avoids stacking on chords
        self._last_trigger_pos = now

    def _autoscroll(self):
        view_w = self.main.winfo_width()
        total = self.total_width()
        if total <= 0 or view_w <= 1:
            return
        x = self.position * self.pps
        left = x - view_w * 0.3
        self.main.xview_moveto(max(0.0, min(1.0, left / total)))

    # -- saving -- #
    def _export_notes(self):
        out = []
        for n in sorted(self.notes, key=lambda x: x["timestamp"]):
            if n["type"] == "hold" and n["duration"] > 0:
                out.append({"type": "hold", "key": n["key"],
                            "timestamp": round(n["timestamp"], 4),
                            "duration": round(n["duration"], 4)})
            else:
                out.append({"type": "quickPress", "key": n["key"],
                            "timestamp": round(n["timestamp"], 4)})
        return out

    def _save(self):
        ok = MapExporter("rhythms").export(self.song_name, self.mp3,
                                           self._export_notes(), self.duration)
        self.status.configure(
            text=f"Saved {len(self.notes)} notes to {self.song_name}.json"
            if ok else "Save failed.")

    def _save_as(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Save As")
        dialog.geometry("360x180")
        dialog.attributes("-topmost", True)
        ctk.CTkLabel(dialog, text="New chart name:", font=FONT_HEADING).pack(pady=(20, 8))
        entry = ctk.CTkEntry(dialog, font=FONT_BODY, height=38)
        entry.insert(0, f"{self.song_name}_copy")
        entry.pack(pady=6, padx=24, fill="x")

        def confirm():
            name = entry.get().strip()
            if not name:
                return
            ok = MapExporter("rhythms").export(name, self.mp3,
                                               self._export_notes(), self.duration)
            dialog.destroy()
            if ok:
                self.song_name = name
                self.mp3 = os.path.join("rhythms", f"{name}.mp3")
                self.json_path = os.path.join("rhythms", f"{name}.json")
                self.status.configure(text=f"Exported as '{name}'.")
            else:
                self.status.configure(text="Export failed.")

        bf = ctk.CTkFrame(dialog, fg_color="transparent")
        bf.pack(pady=16, padx=24, fill="x")
        bf.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(bf, text="Export", command=confirm, height=40,
                      corner_radius=10).grid(row=0, column=0, padx=6, sticky="ew")
        ctk.CTkButton(bf, text="Cancel", command=dialog.destroy, height=40,
                      corner_radius=10, fg_color="transparent",
                      border_width=1).grid(row=0, column=1, padx=6, sticky="ew")

    def destroy(self):
        # Stop playback, cancel the poll loop, and drop key bindings when
        # leaving the editor.
        self._recording = False
        try:
            self.app.unbind("<Escape>")
            self.app.unbind("<KeyPress>")
            self.app.unbind("<KeyRelease>")
        except Exception:
            pass
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
        self._stop_music()
        super().destroy()
