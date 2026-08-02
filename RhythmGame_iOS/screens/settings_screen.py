"""Settings, plus the colour picker it pushes."""

import pygame

import ui
from screens.base import ScrollScreen
from settings_store import DEFAULTS, settings
from theme import (LANE_NAMES, draw_text, fill_rounded, fonts, hex_to_rgb,
                   palette, rgb_to_hex, shade)

FPS_OPTIONS = [30, 60, 120]
BUFFER_OPTIONS = [0, 128, 256, 512]
BUFFER_LABELS = ["Auto", "128", "256", "512"]

THEME_KEYS = [
    ("THEME_BG", "Background", "The window behind everything"),
    ("THEME_SURFACE", "Surface", "Cards, rows and panels"),
    ("THEME_ACCENT", "Accent", "Buttons, sliders, highlights"),
    ("THEME_TEXT", "Text", "Labels and headings"),
    ("THEME_MUTED", "Muted text", "Captions and hints"),
]


class SettingsScreen(ScrollScreen):
    title = "Settings"

    def build_body(self, scroll):
        lay = self.layout
        w = scroll.rect.width - self.s(8)
        y = 0

        # -- Gameplay --------------------------------------------------- #
        y = self.section_label(scroll, "GAMEPLAY", y)

        y = self._row(scroll, y, w, ui.Stepper(
            pygame.Rect(0, y, w, self.s(ui.ROW_H)),
            int(settings.get("NOTE_SPEED", 620)),
            lambda v: settings.set_and_save("NOTE_SPEED", int(v)),
            lay.scale, step=20, minimum=200, maximum=1400,
            label="Note speed", fmt=lambda v: f"{int(v)}"))

        y = self._row(scroll, y, w, ui.Segmented(
            pygame.Rect(0, y, w, self.s(ui.ROW_H)),
            [str(f) for f in FPS_OPTIONS],
            self._index_of(FPS_OPTIONS, int(settings.get("FPS", 60)), 1),
            lambda i, _l: settings.set_and_save("FPS", FPS_OPTIONS[i]),
            lay.scale, label="Frame rate"))

        y = self._slider_row(
            scroll, y, w, "Road perspective",
            float(settings.get("PERSPECTIVE", 0.45)),
            lambda v: self._save_live("PERSPECTIVE", round(v, 2)),
            fmt=lambda v: f"{int(v * 100)}%")

        y = self._row(scroll, y, w, ui.Switch(
            pygame.Rect(0, y, w, self.s(ui.ROW_H)),
            bool(settings.get("GHOST_TAPPING", True)),
            lambda v: settings.set_and_save("GHOST_TAPPING", v),
            lay.scale, label="Ghost tapping"))

        y = self._hint(scroll, y, w,
                       "Ghost tapping on: tapping an empty lane costs nothing. "
                       "Off: it breaks your combo.")

        y = self._row(scroll, y, w, ui.Switch(
            pygame.Rect(0, y, w, self.s(ui.ROW_H)),
            bool(settings.get("HIT_FLASH", True)),
            lambda v: settings.set_and_save("HIT_FLASH", v),
            lay.scale, label="Flash lanes on hit"))

        # -- Audio ------------------------------------------------------ #
        y = self.section_label(scroll, "AUDIO", y + self.s(10))

        y = self._slider_row(
            scroll, y, w, "Hit sound volume",
            float(settings.get("HIT_VOLUME", 0.5)),
            lambda v: self._save_live("HIT_VOLUME", round(v, 2)),
            fmt=lambda v: f"{int(v * 100)}%")

        y = self._slider_row(
            scroll, y, w, "Editor preview volume",
            float(settings.get("EDITOR_HIT_VOLUME", 0.5)),
            lambda v: self._save_live("EDITOR_HIT_VOLUME", round(v, 2)),
            fmt=lambda v: f"{int(v * 100)}%")

        y = self._row(scroll, y, w, ui.Segmented(
            pygame.Rect(0, y, w, self.s(ui.ROW_H)),
            BUFFER_LABELS,
            self._index_of(BUFFER_OPTIONS, int(settings.get("AUDIO_BUFFER", 0)), 0),
            self._on_buffer, lay.scale, label="Audio buffer"))

        y = self._hint(scroll, y, w,
                       "A smaller buffer tightens hit sounds but can crackle. "
                       "Auto picks a safe size for this device. Applies on the "
                       "next launch.")

        # -- Latency ---------------------------------------------------- #
        y = self.section_label(scroll, "LATENCY", y + self.s(10))

        scroll.add(ui.Button(pygame.Rect(0, y, w, self.s(ui.BUTTON_H)),
                             "Calibrate by tapping…", self._calibrate,
                             lay.scale))
        y += self.s(ui.BUTTON_H + 10)

        y = self._row(scroll, y, w, ui.Stepper(
            pygame.Rect(0, y, w, self.s(ui.ROW_H)),
            int(round(float(settings.get("AUDIO_OFFSET", 0.0)) * 1000)),
            lambda v: settings.set_and_save("AUDIO_OFFSET", round(v / 1000.0, 4)),
            lay.scale, step=5, minimum=-300, maximum=300,
            label="Audio offset", fmt=lambda v: f"{int(v)} ms"))

        y = self._row(scroll, y, w, ui.Stepper(
            pygame.Rect(0, y, w, self.s(ui.ROW_H)),
            int(round(float(settings.get("VISUAL_OFFSET", 0.0)) * 1000)),
            lambda v: settings.set_and_save("VISUAL_OFFSET", round(v / 1000.0, 4)),
            lay.scale, step=5, minimum=-300, maximum=300,
            label="Visual offset", fmt=lambda v: f"{int(v)} ms"))

        # -- Lane colours ----------------------------------------------- #
        y = self.section_label(scroll, "LANE COLOURS", y + self.s(10))
        for name in LANE_NAMES:
            y = self._color_row(scroll, y, w, name.title(), name)

        # -- Theme ------------------------------------------------------ #
        y = self.section_label(scroll, "THEME", y + self.s(10))
        for key, label, _desc in THEME_KEYS:
            y = self._color_row(scroll, y, w, label, key)

        scroll.add(ui.Button(pygame.Rect(0, y, w, self.s(ui.BUTTON_H)),
                             "Reset theme to default", self._reset_theme,
                             lay.scale, style=ui.Button.GHOST))
        y += self.s(ui.BUTTON_H + 20)

        scroll.set_content_height(y)

    # ------------------------------------------------------------------ #
    # Row builders
    # ------------------------------------------------------------------ #
    def _row(self, scroll, y, w, widget):
        scroll.add(ui.Card(pygame.Rect(0, y, w, self.s(ui.ROW_H)),
                           self.layout.scale))
        scroll.add(widget)
        return y + self.s(ui.ROW_H + 8)

    def _slider_row(self, scroll, y, w, label, value, on_change, fmt):
        h = self.s(74)
        scroll.add(ui.Card(pygame.Rect(0, y, w, h), self.layout.scale))
        scroll.add(ui.Label(pygame.Rect(self.s(16), y + self.s(6), w - self.s(90),
                                        self.s(24)),
                            label, self.layout.scale, size=15))
        value_label = ui.Label(
            pygame.Rect(w - self.s(76), y + self.s(6), self.s(60), self.s(24)),
            fmt(value), self.layout.scale, size=13, align="right",
            color=palette.accent)
        scroll.add(value_label)

        def changed(v):
            value_label.text = fmt(v)
            on_change(v)

        scroll.add(ui.Slider(
            pygame.Rect(self.s(4), y + self.s(32), w - self.s(8), self.s(38)),
            value, changed, self.layout.scale))
        return y + h + self.s(8)

    def _hint(self, scroll, y, w, text):
        note = ui.Wrapped(pygame.Rect(self.s(6), y, w - self.s(12), 0),
                          text, self.layout.scale, size=11)
        scroll.add(note)
        return y + note.measure() + self.s(12)

    def _color_row(self, scroll, y, w, label, key):
        h = self.s(ui.ROW_H)
        row = _ColorRow(pygame.Rect(0, y, w, h), label,
                        settings.get(key), self.layout.scale,
                        lambda: self._pick_color(key, label))
        scroll.add(row)
        return y + h + self.s(8)

    # ------------------------------------------------------------------ #
    # Handlers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _index_of(options, value, default):
        try:
            return options.index(value)
        except ValueError:
            return default

    def _save_live(self, key, value):
        """Persist on every change; these are cheap and users expect them
        to stick even if the app is killed from the switcher."""
        settings.set_and_save(key, value)

    def _on_buffer(self, index, _label):
        settings.set_and_save("AUDIO_BUFFER", BUFFER_OPTIONS[index])

    def _calibrate(self):
        from screens.calibrate import CalibrationScreen
        self.app.push(CalibrationScreen(self.app))

    def _pick_color(self, key, label):
        self.app.push(ColorPickerScreen(self.app, key, label))

    def _reset_theme(self):
        settings.reset_theme()
        palette.refresh()
        self.app.toast("Theme reset.")
        self.rebuild()


class _ColorRow(ui.Widget):
    """A label with a colour swatch that opens the picker."""

    def __init__(self, rect, label, value, scale, on_tap):
        super().__init__(rect, scale)
        self.label = label
        self.value = value
        self.on_tap = on_tap

    def on_release(self, x, y, tapped):
        self.pressed = False
        if tapped and self.on_tap:
            self.on_tap()

    def draw(self, surface, dx=0, dy=0):
        r = self.rect.move(dx, dy)
        fill_rounded(surface, r,
                     shade(palette.surface, 0.06 if self.pressed else 0.0),
                     self.s(ui.RADIUS))
        draw_text(surface, self.label, fonts.get(15), palette.text,
                  midleft=(r.x + self.s(16), r.centery))
        swatch = pygame.Rect(0, 0, self.s(52), self.s(30))
        swatch.midright = (r.right - self.s(16), r.centery)
        fill_rounded(surface, swatch, hex_to_rgb(self.value), self.s(8))
        fill_rounded(surface, swatch, palette.divider, self.s(8),
                     width=max(1, self.s(1)))


class ColorPickerScreen(ScrollScreen):
    """
    Three channel sliders and a live preview. A hue wheel would look nicer,
    but sliders are far easier to land precisely with a fingertip and they
    make the exact value visible, which matters when matching a theme.
    """

    def __init__(self, app, key, label):
        super().__init__(app)
        self.key = key
        self.title = label
        self.is_lane = key in LANE_NAMES
        self.rgb = list(hex_to_rgb(settings.get(key), (255, 255, 255)))

    def build_body(self, scroll):
        lay = self.layout
        w = scroll.rect.width - self.s(8)
        y = 0

        self._preview = _Preview(pygame.Rect(0, y, w, self.s(110)),
                                 self.rgb, lay.scale)
        scroll.add(self._preview)
        y += self.s(122)

        for i, (name, tint) in enumerate((("Red", (255, 90, 90)),
                                          ("Green", (110, 220, 120)),
                                          ("Blue", (110, 150, 255)))):
            y = self._channel(scroll, y, w, i, name, tint)

        scroll.add(ui.Button(pygame.Rect(0, y, w, self.s(ui.BUTTON_H)),
                             "Reset to default", self._reset, lay.scale,
                             style=ui.Button.GHOST))
        y += self.s(ui.BUTTON_H + 20)
        scroll.set_content_height(y)

    def _channel(self, scroll, y, w, index, name, tint):
        h = self.s(74)
        scroll.add(ui.Card(pygame.Rect(0, y, w, h), self.layout.scale))
        scroll.add(ui.Label(pygame.Rect(self.s(16), y + self.s(6),
                                        w - self.s(90), self.s(24)),
                            name, self.layout.scale, size=15))
        value_label = ui.Label(
            pygame.Rect(w - self.s(76), y + self.s(6), self.s(60), self.s(24)),
            str(self.rgb[index]), self.layout.scale, size=13, align="right",
            color=tint)
        scroll.add(value_label)

        def changed(v):
            self.rgb[index] = int(v)
            value_label.text = str(int(v))
            self._preview.rgb = self.rgb
            self._apply()

        scroll.add(ui.Slider(
            pygame.Rect(self.s(4), y + self.s(32), w - self.s(8), self.s(38)),
            self.rgb[index], changed, self.layout.scale,
            minimum=0, maximum=255))
        return y + h + self.s(8)

    def _apply(self):
        # Lane colours are stored as RGB lists, theme colours as hex strings.
        value = [int(c) for c in self.rgb] if self.is_lane else rgb_to_hex(self.rgb)
        settings.set_and_save(self.key, value)
        palette.refresh()

    def _reset(self):
        default = DEFAULTS.get(self.key)
        if default is None:
            return
        self.rgb = list(hex_to_rgb(default, (255, 255, 255)))
        self._apply()
        self.rebuild()


class _Preview(ui.Widget):
    def __init__(self, rect, rgb, scale):
        super().__init__(rect, scale)
        self.rgb = rgb

    def hit(self, x, y):
        return False

    def draw(self, surface, dx=0, dy=0):
        r = self.rect.move(dx, dy)
        fill_rounded(surface, r, tuple(int(c) for c in self.rgb), self.s(14))
        fill_rounded(surface, r, palette.divider, self.s(14),
                     width=max(1, self.s(1)))
        label = rgb_to_hex(self.rgb).upper()
        # Pick readable text for whatever colour is behind it.
        luma = 0.299 * self.rgb[0] + 0.587 * self.rgb[1] + 0.114 * self.rgb[2]
        color = (20, 20, 20) if luma > 150 else (245, 245, 245)
        draw_text(surface, label, fonts.get(16, bold=True), color, center=r.center)
