import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, colorchooser
import os
import json
import shutil
import pygame
from game_engine import RhythmGame
from map_creator import MapCreator
from map_exporter import MapExporter
from sound import load_waveform
import chart_io
from settings import settings

LANE_NAMES = ["LEFT", "DOWN", "UP", "RIGHT"]

# A custom theme is written here and referenced by COLOR_THEME in settings.
CUSTOM_THEME_PATH = os.path.abspath("custom_theme.json")

# Typography (tuples so no Tk root is required to define them).
FONT_TITLE = ("Roboto", 30, "bold")
FONT_HEADING = ("Roboto", 18, "bold")
FONT_BODY = ("Roboto", 14)
FONT_BUTTON = ("Roboto", 15)
FONT_SMALL = ("Roboto", 12)

# A subtle divider color that works in both light and dark mode.
DIVIDER_COLOR = ("gray75", "gray28")


# ---------------------------------------------------------------------------- #
# Theming helpers
# ---------------------------------------------------------------------------- #
def _base_theme_path():
    """Path to a built-in customtkinter theme to use as a template."""
    return os.path.join(os.path.dirname(ctk.__file__),
                        "assets", "themes", "blue.json")


def apply_theme():
    """Apply the saved appearance mode and color theme. Call before building UI."""
    ctk.set_appearance_mode(settings.get("APPEARANCE_MODE", "Dark"))
    theme = settings.get("COLOR_THEME", "blue")
    try:
        ctk.set_default_color_theme(theme)
    except Exception:
        ctk.set_default_color_theme("blue")


def rgb_to_hex(rgb):
    r, g, b = (int(c) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def build_custom_theme(accent, hover, surface, background, text,
                       dest=CUSTOM_THEME_PATH):
    """
    Create a customtkinter theme file from chosen colors (hex strings):
      accent      - buttons, sliders, progress bars
      hover       - button hover highlight
      surface     - panels / frames
      background  - the whole app window background
      text        - label and control text
    """
    with open(_base_theme_path(), "r") as f:
        theme = json.load(f)

    def set_pair(widget, key, color):
        if widget in theme and key in theme[widget]:
            theme[widget][key] = [color, color]

    # App background.
    set_pair("CTk", "fg_color", background)
    set_pair("CTkToplevel", "fg_color", background)

    # Panels / frames.
    set_pair("CTkFrame", "fg_color", surface)
    set_pair("CTkFrame", "top_fg_color", surface)
    set_pair("CTkScrollableFrame", "label_fg_color", surface)

    # Accent-colored controls.
    set_pair("CTkButton", "fg_color", accent)
    set_pair("CTkButton", "hover_color", hover)
    set_pair("CTkOptionMenu", "fg_color", accent)
    set_pair("CTkOptionMenu", "hover_color", hover)
    set_pair("CTkOptionMenu", "button_color", hover)
    set_pair("CTkOptionMenu", "button_hover_color", accent)
    set_pair("CTkComboBox", "border_color", accent)
    set_pair("CTkComboBox", "button_color", accent)
    set_pair("CTkComboBox", "button_hover_color", hover)
    set_pair("CTkSlider", "button_color", accent)
    set_pair("CTkSlider", "button_hover_color", hover)
    set_pair("CTkSlider", "progress_color", accent)
    set_pair("CTkProgressBar", "progress_color", accent)
    set_pair("CTkCheckBox", "fg_color", accent)
    set_pair("CTkCheckBox", "hover_color", hover)
    set_pair("CTkSwitch", "progress_color", accent)

    # Text colors.
    for widget in ("CTkLabel", "CTkButton", "CTkEntry", "CTkOptionMenu",
                   "CTkComboBox", "CTkCheckBox", "CTkSwitch"):
        set_pair(widget, "text_color", text)
    set_pair("CTkScrollableFrame", "label_text_color", text)

    with open(dest, "w") as f:
        json.dump(theme, f, indent=2)
    return dest


# ---------------------------------------------------------------------------- #
# Small UI helpers
# ---------------------------------------------------------------------------- #
def primary_button(parent, text, command, **kwargs):
    return ctk.CTkButton(parent, text=text, command=command, height=46,
                         font=FONT_BUTTON, corner_radius=10, **kwargs)


# ---------------------------------------------------------------------------- #
# App shell
# ---------------------------------------------------------------------------- #
class AppUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Custom Rhythm Creator & Player")
        self.geometry("860x640")
        self.minsize(720, 560)

        # Transparent container so the themed window background shows through
        # (no more double-grey panel behind every screen).
        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True)

        self.current_screen = None

    def show_screen(self, screen_class, *args):
        if self.current_screen:
            self.current_screen.destroy()
        self.current_screen = screen_class(self.container, self, *args)
        self.current_screen.pack(fill="both", expand=True)


class BaseScreen(ctk.CTkFrame):
    """
    Common scaling layout: a full-width header (title + optional Back button),
    a divider, and a centered content column that grows with the window.
    Subclasses fill self.content.
    """

    def __init__(self, parent, app, title, back_to="MainMenu"):
        super().__init__(parent, fg_color="transparent")
        self.app = app

        # Centered content column (col 1) with flexible spacers either side.
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=12)
        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(2, weight=1)   # content row grows

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=3, sticky="ew",
                    padx=34, pady=(24, 6))
        ctk.CTkLabel(header, text=title, font=FONT_TITLE).pack(side="left")
        if back_to:
            target = MainMenu if back_to == "MainMenu" else back_to
            ctk.CTkButton(header, text="← Back", width=90, height=36,
                          font=FONT_BUTTON, corner_radius=10,
                          command=lambda: app.show_screen(target)).pack(side="right")

        ctk.CTkFrame(self, height=2, fg_color=DIVIDER_COLOR).grid(
            row=1, column=0, columnspan=3, sticky="ew", padx=34, pady=(0, 16))

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=2, column=1, sticky="nsew", pady=(0, 24))


# ---------------------------------------------------------------------------- #
# Main menu
# ---------------------------------------------------------------------------- #
class MainMenu(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        center = ctk.CTkFrame(self, fg_color="transparent")
        center.grid(row=0, column=0)

        ctk.CTkLabel(center, text="Rhythm Game",
                     font=("Roboto", 46, "bold")).pack(pady=(0, 6))
        ctk.CTkLabel(center, text="Create, import and play custom charts",
                     font=FONT_BODY, text_color=("gray40", "gray60")).pack(pady=(0, 28))

        buttons = [
            ("▶  Play Game", GameScreen),
            ("✚  Map Creator", CreatorScreen),
            ("⇅  Import / Export Charts", ChartsScreen),
            ("⚙  Settings", SettingsScreen),
        ]
        for text, screen in buttons:
            primary_button(center, text, command=lambda s=screen: app.show_screen(s),
                           width=300, anchor="w").pack(pady=7, fill="x")

        ctk.CTkButton(center, text="Exit", command=app.quit, width=300, height=40,
                      font=FONT_BUTTON, corner_radius=10,
                      fg_color="transparent", border_width=1).pack(pady=(18, 0), fill="x")


# ---------------------------------------------------------------------------- #
# Play
# ---------------------------------------------------------------------------- #
class GameScreen(BaseScreen):
    def __init__(self, parent, app):
        super().__init__(parent, app, "Select a Song")

        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        songs = [f[:-4] for f in os.listdir("rhythms") if f.endswith(".mp3")]

        if not songs:
            self._empty("No songs found in your rhythms folder yet.\n"
                        "Use the Map Creator to add one.")
            return

        scroll = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)
        for song in songs:
            primary_button(scroll, song,
                           command=lambda s=song: self.start_game(s),
                           anchor="w").pack(pady=5, fill="x")

    def _empty(self, msg):
        ctk.CTkLabel(self.content, text=msg, font=FONT_BODY,
                     justify="center", text_color=("gray40", "gray60")).grid(
            row=0, column=0)

    def start_game(self, song_name):
        RhythmGame(song_name).run()


# ---------------------------------------------------------------------------- #
# Map creator
# ---------------------------------------------------------------------------- #
class CreatorScreen(BaseScreen):
    def __init__(self, parent, app):
        super().__init__(parent, app, "Map Creator")

        self.content.grid_rowconfigure(2, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        primary_button(self.content, "Import Song File (.mp3)…",
                       command=self.import_song).grid(row=0, column=0,
                                                      sticky="ew", pady=(0, 14))

        ctk.CTkLabel(self.content,
                     text="Pick a song to edit its chart, or record a fresh one:",
                     font=FONT_BODY, anchor="w").grid(row=1, column=0,
                                                      sticky="ew", pady=(0, 6))

        self.songs_frame = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        self.songs_frame.grid(row=2, column=0, sticky="nsew")
        self.songs_frame.grid_columnconfigure(0, weight=1)
        self.refresh_songs()

    def refresh_songs(self):
        for w in self.songs_frame.winfo_children():
            w.destroy()
        songs = [f[:-4] for f in os.listdir("rhythms") if f.endswith(".mp3")]
        if not songs:
            ctk.CTkLabel(self.songs_frame, text="No songs yet — import one above.",
                         font=FONT_BODY, text_color=("gray40", "gray60")).pack(pady=10)
            return
        for song in songs:
            row = ctk.CTkFrame(self.songs_frame)
            row.pack(pady=4, fill="x")
            ctk.CTkLabel(row, text=song, font=FONT_BODY, anchor="w").pack(
                side="left", padx=14, pady=6, fill="x", expand=True)
            ctk.CTkButton(row, text="Record", width=90, height=34, corner_radius=8,
                          fg_color="transparent", border_width=1,
                          command=lambda s=song: self.record(s)).pack(
                side="right", padx=(4, 10), pady=6)
            ctk.CTkButton(row, text="Edit", width=90, height=34, corner_radius=8,
                          command=lambda s=song: self.open_editor(s)).pack(
                side="right", padx=4, pady=6)

    def import_song(self):
        file_path = filedialog.askopenfilename(filetypes=[("MP3 Files", "*.mp3")])
        if not file_path:
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Enter Song Name")
        dialog.geometry("360x180")
        dialog.attributes("-topmost", True)

        ctk.CTkLabel(dialog, text="Name for this song:",
                     font=FONT_HEADING).pack(pady=(20, 8))
        name_entry = ctk.CTkEntry(dialog, font=FONT_BODY, height=38)
        name_entry.insert(0, os.path.basename(file_path)[:-4])
        name_entry.pack(pady=6, padx=24, fill="x")

        def confirm():
            new_name = name_entry.get().strip()
            if new_name:
                shutil.copy(file_path, os.path.join("rhythms", f"{new_name}.mp3"))
                self.refresh_songs()
                dialog.destroy()
                self.record(new_name)

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=16, padx=24, fill="x")
        btn_frame.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(btn_frame, text="Record", command=confirm,
                      height=40, corner_radius=10).grid(row=0, column=0, padx=6, sticky="ew")
        ctk.CTkButton(btn_frame, text="Cancel", command=dialog.destroy,
                      height=40, corner_radius=10, fg_color="transparent",
                      border_width=1).grid(row=0, column=1, padx=6, sticky="ew")

    def record(self, song_name):
        """Capture a chart by playing along, then open it in the editor."""
        MapCreator(song_name).run()
        self.refresh_songs()
        self.open_editor(song_name)

    def open_editor(self, song_name):
        from chart_editor import ChartEditorScreen
        self.app.show_screen(ChartEditorScreen, song_name)


# ---------------------------------------------------------------------------- #
# Charts (import / export)
# ---------------------------------------------------------------------------- #
class ChartsScreen(BaseScreen):
    def __init__(self, parent, app):
        super().__init__(parent, app, "Import / Export Charts")

        self.content.grid_rowconfigure(3, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        primary_button(self.content, "Import Chart (*.crchart)…",
                       command=self.import_chart).grid(row=0, column=0,
                                                       sticky="ew", pady=(0, 14))

        ctk.CTkLabel(self.content, text="Export a chart from your collection:",
                     font=FONT_BODY, anchor="w").grid(row=1, column=0,
                                                      sticky="ew", pady=(0, 6))

        self.songs_frame = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        self.songs_frame.grid(row=3, column=0, sticky="nsew")
        self.songs_frame.grid_columnconfigure(0, weight=1)

        self.status = ctk.CTkLabel(self.content, text="", font=FONT_BODY)
        self.status.grid(row=4, column=0, sticky="ew", pady=(10, 0))

        self.refresh_songs()

    def refresh_songs(self):
        for w in self.songs_frame.winfo_children():
            w.destroy()
        songs = [f[:-5] for f in os.listdir("rhythms")
                 if f.endswith(".json") and f != "SETTINGS.json"]
        if not songs:
            ctk.CTkLabel(self.songs_frame, text="No charts to export yet.",
                         font=FONT_BODY, text_color=("gray40", "gray60")).pack(pady=10)
            return
        for song in songs:
            row = ctk.CTkFrame(self.songs_frame)
            row.pack(pady=4, fill="x")
            ctk.CTkLabel(row, text=song, font=FONT_BODY, anchor="w").pack(
                side="left", padx=14, pady=6, fill="x", expand=True)
            ctk.CTkButton(row, text="Export", width=100, height=34, corner_radius=8,
                          command=lambda s=song: self.export_chart(s)).pack(
                side="right", padx=10, pady=6)

    def export_chart(self, song_name):
        dest = filedialog.asksaveasfilename(
            defaultextension=chart_io.CHART_EXT,
            initialfile=f"{song_name}{chart_io.CHART_EXT}",
            filetypes=[("Rhythm Chart", f"*{chart_io.CHART_EXT}")])
        if not dest:
            return
        ok, msg = chart_io.export_chart(song_name, dest)
        self._set_status(msg, ok)

    def import_chart(self):
        src = filedialog.askopenfilename(
            filetypes=[("Rhythm Chart", f"*{chart_io.CHART_EXT}")])
        if not src:
            return
        ok, result = chart_io.import_chart(src, overwrite=False)
        if ok:
            self.refresh_songs()
            self._set_status(f"Imported '{result}'.", True)
        elif "already exists" in result:
            self._confirm_overwrite(src)
        else:
            self._set_status(result, False)

    def _confirm_overwrite(self, src):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Overwrite?")
        dialog.geometry("360x170")
        dialog.attributes("-topmost", True)
        ctk.CTkLabel(dialog, text="A chart with this name already exists.\nOverwrite it?",
                     font=FONT_BODY, justify="center").pack(pady=(22, 10), padx=14)

        def do_overwrite():
            ok, result = chart_io.import_chart(src, overwrite=True)
            dialog.destroy()
            if ok:
                self.refresh_songs()
                self._set_status(f"Imported '{result}' (overwritten).", True)
            else:
                self._set_status(result, False)

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=12, padx=24, fill="x")
        btn_frame.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(btn_frame, text="Overwrite", command=do_overwrite,
                      height=40, corner_radius=10).grid(row=0, column=0, padx=6, sticky="ew")
        ctk.CTkButton(btn_frame, text="Cancel", command=dialog.destroy,
                      height=40, corner_radius=10, fg_color="transparent",
                      border_width=1).grid(row=0, column=1, padx=6, sticky="ew")

    def _set_status(self, text, ok):
        self.status.configure(text=text, text_color=("#1a7f37" if ok else "#c0392b"))


# ---------------------------------------------------------------------------- #
# Settings
# ---------------------------------------------------------------------------- #
class SettingsScreen(BaseScreen):
    def __init__(self, parent, app):
        super().__init__(parent, app, "Settings")

        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        scroll = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        # --- Gameplay ---------------------------------------------------- #
        self._heading(scroll, "Gameplay")
        for key in ["NOTE_SPEED", "FPS"]:
            self._numeric_row(scroll, key)

        ghost = self._card(scroll)
        self.ghost_switch = ctk.CTkSwitch(
            ghost, text="Ghost tapping (no penalty for tapping empty lanes)",
            font=FONT_BODY, command=self._on_ghost)
        (self.ghost_switch.select if settings.get("GHOST_TAPPING", True)
         else self.ghost_switch.deselect)()
        self.ghost_switch.pack(side="left", padx=14, pady=10)

        # --- Audio ------------------------------------------------------- #
        self._heading(scroll, "Audio")
        vol = self._card(scroll)
        ctk.CTkLabel(vol, text="Gameplay Hit Volume", font=FONT_BODY).pack(
            side="left", padx=14)
        self.vol_label = ctk.CTkLabel(vol, text="", font=FONT_BODY, width=46)
        self.vol_label.pack(side="right", padx=14)
        slider = ctk.CTkSlider(vol, from_=0, to=100, command=self._on_volume)
        slider.set(float(settings.get("HIT_VOLUME", 0.5)) * 100)
        slider.pack(side="left", padx=14, pady=12, expand=True, fill="x")
        self._update_vol_label(settings.get("HIT_VOLUME", 0.5) * 100)
        ctk.CTkLabel(scroll, text="The chart editor's preview volume is set "
                     "separately, in the editor toolbar.",
                     font=FONT_SMALL, text_color=("gray40", "gray60")).pack(
            anchor="w", pady=(0, 4))

        # --- Latency / calibration --------------------------------------- #
        self._heading(scroll, "Latency")

        primary_button(scroll, "Calibrate Latency  (tap-test)…",
                       command=self._run_calibration).pack(pady=(2, 6), fill="x")

        self.audio_off_label = self._offset_row(scroll, "Audio offset (ms)", "AUDIO_OFFSET")
        self.visual_off_label = self._offset_row(scroll, "Visual offset (ms)", "VISUAL_OFFSET")

        buf = self._card(scroll)
        ctk.CTkLabel(buf, text="Audio buffer", font=FONT_BODY, width=130,
                     anchor="w").pack(side="left", padx=14)
        buf_menu = ctk.CTkOptionMenu(buf, values=["64", "128", "256", "512"],
                                     command=self._on_buffer)
        buf_menu.set(str(settings.get("AUDIO_BUFFER", 128)))
        buf_menu.pack(side="right", padx=14, pady=10)
        ctk.CTkLabel(scroll, text="Lower buffer = less hit-sound delay, but may "
                     "crackle. Applies next time you play.",
                     font=FONT_SMALL, text_color=("gray40", "gray60")).pack(
            anchor="w", pady=(0, 4))

        # --- Note colors ------------------------------------------------- #
        self._heading(scroll, "Note Colors")
        self.color_buttons = {}
        for name in LANE_NAMES:
            row = self._card(scroll)
            ctk.CTkLabel(row, text=name, font=FONT_BODY, width=80, anchor="w").pack(
                side="left", padx=14)
            current = settings.get(name, [255, 255, 255])
            btn = ctk.CTkButton(row, text="", width=70, height=30, corner_radius=8,
                                fg_color=rgb_to_hex(current),
                                hover=False,
                                command=lambda n=name: self._pick_note_color(n))
            btn.pack(side="right", padx=14, pady=8)
            self.color_buttons[name] = btn

        # --- Theme ------------------------------------------------------- #
        self._heading(scroll, "Theme")
        mode = self._card(scroll)
        ctk.CTkLabel(mode, text="Appearance", font=FONT_BODY, width=110,
                     anchor="w").pack(side="left", padx=14)
        mode_menu = ctk.CTkOptionMenu(mode, values=["Light", "Dark", "System"],
                                      command=self._on_appearance)
        mode_menu.set(settings.get("APPEARANCE_MODE", "Dark"))
        mode_menu.pack(side="right", padx=14, pady=10)

        theme_card = self._card(scroll)
        ctk.CTkLabel(theme_card, text="Color Theme", font=FONT_BODY, width=110,
                     anchor="w").pack(side="left", padx=14)
        current_theme = settings.get("COLOR_THEME", "blue")
        if current_theme not in ("blue", "dark-blue", "green"):
            current_theme = "custom"
        theme_menu = ctk.CTkOptionMenu(theme_card,
                                       values=["blue", "dark-blue", "green", "custom"],
                                       command=self._on_color_theme)
        theme_menu.set(current_theme)
        theme_menu.pack(side="right", padx=14, pady=10)

        primary_button(scroll, "Create Custom Theme…",
                       command=lambda: app.show_screen(ThemeCreatorScreen)).pack(
            pady=(8, 4), fill="x")
        self.theme_note = ctk.CTkLabel(
            scroll, text="Color theme changes apply after restarting the app.",
            font=FONT_SMALL, text_color=("gray40", "gray60"))
        self.theme_note.pack(pady=(0, 6))

        # --- Keybindings ------------------------------------------------- #
        self._heading(scroll, "Keybindings")
        ctk.CTkLabel(scroll, text="Use Pygame key constants (e.g. K_a, K_UP).",
                     font=FONT_SMALL, text_color=("gray40", "gray60")).pack(
            anchor="w", pady=(0, 6))
        for key in ["LEFT_BUTTON", "DOWN_BUTTON", "UP_BUTTON", "RIGHT_BUTTON"]:
            self._key_row(scroll, key)

    # -- builders -- #
    def _heading(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=FONT_HEADING, anchor="w").pack(
            anchor="w", pady=(18, 6), fill="x")

    def _card(self, parent):
        card = ctk.CTkFrame(parent, corner_radius=10)
        card.pack(pady=5, fill="x")
        return card

    def _numeric_row(self, parent, key):
        card = self._card(parent)
        ctk.CTkLabel(card, text=key, font=FONT_BODY, width=110, anchor="w").pack(
            side="left", padx=14)
        entry = ctk.CTkEntry(card, font=FONT_BODY, height=34)
        entry.insert(0, str(settings.get(key)))
        entry.pack(side="left", padx=14, pady=10, expand=True, fill="x")

        def save_val():
            try:
                settings.set(key, int(entry.get()))
                settings.save_settings()
            except ValueError:
                pass
        ctk.CTkButton(card, text="Save", width=72, height=34, corner_radius=8,
                      command=save_val).pack(side="left", padx=14)

    def _key_row(self, parent, key):
        card = self._card(parent)
        ctk.CTkLabel(card, text=key.replace("_BUTTON", ""), font=FONT_BODY,
                     width=110, anchor="w").pack(side="left", padx=14)
        entry = ctk.CTkEntry(card, font=FONT_BODY, height=34)
        entry.insert(0, str(settings.get(key)))
        entry.pack(side="left", padx=14, pady=10, expand=True, fill="x")

        def save_key():
            val = entry.get().strip()
            if val and not val.startswith("K_"):
                val = "K_" + val
            settings.set(key, val)
            settings.save_settings()
        ctk.CTkButton(card, text="Save", width=72, height=34, corner_radius=8,
                      command=save_key).pack(side="left", padx=14)

    def _offset_row(self, parent, label, key):
        """A row to view/edit a latency offset in milliseconds. Returns the entry."""
        card = self._card(parent)
        ctk.CTkLabel(card, text=label, font=FONT_BODY, width=130,
                     anchor="w").pack(side="left", padx=14)
        entry = ctk.CTkEntry(card, font=FONT_BODY, height=34)
        entry.insert(0, f"{settings.get(key, 0.0) * 1000:.0f}")
        entry.pack(side="left", padx=14, pady=10, expand=True, fill="x")

        def save_off():
            try:
                settings.set(key, round(float(entry.get()) / 1000.0, 4))
                settings.save_settings()
            except ValueError:
                pass
        ctk.CTkButton(card, text="Save", width=72, height=34, corner_radius=8,
                      command=save_off).pack(side="left", padx=14)
        return entry

    def _run_calibration(self):
        from calibration import CalibrationGame
        CalibrationGame().run()
        # Refresh the displayed values with whatever calibration saved.
        for entry, key in ((self.audio_off_label, "AUDIO_OFFSET"),
                           (self.visual_off_label, "VISUAL_OFFSET")):
            entry.delete(0, "end")
            entry.insert(0, f"{settings.get(key, 0.0) * 1000:.0f}")

    def _on_buffer(self, value):
        try:
            settings.set("AUDIO_BUFFER", int(value))
            settings.save_settings()
        except ValueError:
            pass

    # -- handlers -- #
    def _update_vol_label(self, pct):
        self.vol_label.configure(text=f"{int(pct)}%")

    def _on_volume(self, value):
        settings.set("HIT_VOLUME", round(value / 100.0, 2))
        settings.save_settings()
        self._update_vol_label(value)

    def _on_ghost(self):
        settings.set("GHOST_TAPPING", bool(self.ghost_switch.get()))
        settings.save_settings()

    def _pick_note_color(self, name):
        current = settings.get(name, [255, 255, 255])
        rgb, hex_str = colorchooser.askcolor(color=rgb_to_hex(current),
                                             title=f"{name} note color")
        if rgb:
            settings.set(name, [int(c) for c in rgb])
            settings.save_settings()
            self.color_buttons[name].configure(fg_color=hex_str)

    def _on_appearance(self, value):
        settings.set("APPEARANCE_MODE", value)
        settings.save_settings()
        ctk.set_appearance_mode(value)   # applies live

    def _on_color_theme(self, value):
        if value == "custom":
            if os.path.exists(CUSTOM_THEME_PATH):
                settings.set("COLOR_THEME", CUSTOM_THEME_PATH)
            else:
                self.theme_note.configure(
                    text="No custom theme yet — use 'Create Custom Theme…' first.")
                return
        else:
            settings.set("COLOR_THEME", value)
        settings.save_settings()
        self.theme_note.configure(text="Color theme saved. Restart the app to apply.")


class ThemeCreatorScreen(BaseScreen):
    def __init__(self, parent, app):
        super().__init__(parent, app, "Custom Theme Creator", back_to=SettingsScreen)

        self.content.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.content,
                     text="Pick the colors used across the interface, then save.",
                     font=FONT_BODY, anchor="w").grid(row=0, column=0,
                                                      sticky="ew", pady=(0, 12))

        # label -> (default color, description)
        self.specs = [
            ("Background", "#242424", "The whole app window background"),
            ("Surface", "#2b2b2b", "Panels and cards"),
            ("Accent", "#3a7ebf", "Buttons, sliders, progress bars"),
            ("Hover", "#2c5f91", "Button hover highlight"),
            ("Text", "#dce4ee", "Label and control text"),
        ]
        self.colors = {label: default for label, default, _ in self.specs}
        self.buttons = {}

        body = ctk.CTkFrame(self.content, fg_color="transparent")
        body.grid(row=1, column=0, sticky="ew")
        body.grid_columnconfigure(0, weight=1)

        for label, default, desc in self.specs:
            card = ctk.CTkFrame(body, corner_radius=10)
            card.pack(pady=5, fill="x")
            text_col = ctk.CTkFrame(card, fg_color="transparent")
            text_col.pack(side="left", padx=14, pady=10, fill="x", expand=True)
            ctk.CTkLabel(text_col, text=label, font=FONT_BODY, anchor="w").pack(anchor="w")
            ctk.CTkLabel(text_col, text=desc, font=FONT_SMALL, anchor="w",
                         text_color=("gray40", "gray60")).pack(anchor="w")
            btn = ctk.CTkButton(card, text="", width=80, height=34, corner_radius=8,
                                fg_color=default, hover=False,
                                command=lambda l=label: self._pick(l))
            btn.pack(side="right", padx=14)
            self.buttons[label] = btn

        self.status = ctk.CTkLabel(self.content, text="", font=FONT_BODY)
        self.status.grid(row=2, column=0, sticky="ew", pady=(12, 6))

        primary_button(self.content, "Save & Use This Theme",
                       command=self._save).grid(row=3, column=0, sticky="ew")

    def _pick(self, label):
        rgb, hex_str = colorchooser.askcolor(color=self.colors[label],
                                             title=f"{label} color")
        if hex_str:
            self.colors[label] = hex_str
            self.buttons[label].configure(fg_color=hex_str)

    def _save(self):
        try:
            build_custom_theme(self.colors["Accent"], self.colors["Hover"],
                               self.colors["Surface"], self.colors["Background"],
                               self.colors["Text"])
            settings.set("COLOR_THEME", CUSTOM_THEME_PATH)
            settings.save_settings()
            self.status.configure(
                text="Custom theme saved! Restart the app to see it.",
                text_color="#1a7f37")
        except Exception as e:
            self.status.configure(text=f"Could not save theme: {e}",
                                  text_color="#c0392b")


