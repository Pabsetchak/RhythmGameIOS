"""Main menu."""

import pygame

import ui
from app import Screen
from theme import draw_text, fonts, palette


class MainMenu(Screen):
    def __init__(self, app):
        super().__init__(app)
        self.group = ui.Group()

    def on_enter(self):
        self._build()

    def on_resize(self):
        self._build()

    def _build(self):
        lay = self.layout
        self.group.clear()

        entries = [
            ("Play", "Pick a chart and tap along", self._play),
            ("Create", "Record or edit your own charts", self._create),
            ("Charts", "Import and export chart files", self._charts),
            ("Settings", "Speed, colours, latency, theme", self._settings),
        ]

        h = self.s(72)
        gap = self.s(12)
        total = len(entries) * h + (len(entries) - 1) * gap
        y = max(lay.content_top + self.s(150),
                lay.content_top + (lay.content_height - total) // 2)

        for label, subtitle, action in entries:
            self.group.add(ui.Button(
                pygame.Rect(lay.content_left, y, lay.content_width, h),
                label, action, lay.scale, align="left", font_size=18,
                subtitle=subtitle,
                style=ui.Button.PRIMARY if label == "Play" else ui.Button.PLAIN))
            y += h + gap

    def _play(self):
        from screens.songs import SongSelectScreen
        self.app.push(SongSelectScreen(self.app))

    def _create(self):
        from screens.songs import CreatorScreen
        self.app.push(CreatorScreen(self.app))

    def _charts(self):
        from screens.charts import ChartsScreen
        self.app.push(ChartsScreen(self.app))

    def _settings(self):
        from screens.settings_screen import SettingsScreen
        self.app.push(SettingsScreen(self.app))

    def handle_pointer(self, ev):
        self.group.handle_pointer(ev)

    def update(self, dt, now):
        self.group.update(dt)

    def draw(self, surface):
        lay = self.layout
        surface.fill(palette.bg)

        title_font = fonts.get(40, bold=True)
        y = lay.content_top + self.s(48)
        draw_text(surface, "Rhythm", title_font, palette.text,
                  center=(lay.width // 2, y))
        draw_text(surface, "Rhythm", title_font, palette.accent,
                  center=(lay.width // 2 - self.s(1), y - self.s(1)))
        draw_text(surface, "tap along, or build your own", fonts.get(14),
                  palette.muted,
                  center=(lay.width // 2, y + self.s(34)))

        self.group.draw(surface)
