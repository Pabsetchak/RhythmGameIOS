"""Post-song summary."""

import pygame

import ui
from app import Screen
from theme import draw_text, fill_rounded, fonts, palette, shade, truncate

ROWS = [
    ("PERFECT", (90, 220, 255)),
    ("GOOD", (120, 255, 140)),
    ("BAD", (255, 180, 90)),
    ("MISS", (255, 90, 90)),
]


def _grade(accuracy):
    for threshold, letter in ((95, "S"), (90, "A"), (80, "B"),
                              (70, "C"), (60, "D")):
        if accuracy >= threshold:
            return letter
    return "F"


class ResultsScreen(Screen):
    def __init__(self, app, song_name, summary):
        super().__init__(app)
        self.song_name = song_name
        self.summary = summary
        self.group = ui.Group()

    def on_enter(self):
        self._build()

    def on_resize(self):
        self._build()

    def _build(self):
        lay = self.layout
        self.group.clear()
        h = lay.s(ui.BUTTON_H)
        gap = lay.s(10)
        y = lay.content_bottom - h * 2 - gap
        self.group.add(ui.Button(
            pygame.Rect(lay.content_left, y, lay.content_width, h),
            "Play again", self._again, lay.scale))
        self.group.add(ui.Button(
            pygame.Rect(lay.content_left, y + h + gap, lay.content_width, h),
            "Back to songs", self.app.pop, lay.scale, style=ui.Button.GHOST))

    def _again(self):
        from screens.play import PlayScreen
        self.app.replace(PlayScreen(self.app, self.song_name))

    def handle_pointer(self, ev):
        self.group.handle_pointer(ev)

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.pop()

    def update(self, dt, now):
        self.group.update(dt)

    def draw(self, surface):
        lay = self.layout
        surface.fill(palette.bg)
        s = self.summary

        y = lay.content_top + self.s(8)
        title_font = fonts.get(15)
        draw_text(surface, truncate(self.song_name, title_font, lay.content_width),
                  title_font, palette.muted,
                  center=(lay.width // 2, y + title_font.get_height() // 2))
        y += title_font.get_height() + self.s(10)

        # Grade badge.
        accuracy = s.get("accuracy", 0.0)
        grade = _grade(accuracy)
        badge = self.s(96)
        rect = pygame.Rect(0, 0, badge, badge)
        rect.center = (lay.width // 2, y + badge // 2)
        fill_rounded(surface, rect, shade(palette.surface, 0.06), self.s(20))
        draw_text(surface, grade, fonts.get(52, bold=True), palette.accent,
                  center=rect.center)
        y = rect.bottom + self.s(14)

        draw_text(surface, f"{s.get('score', 0):,}", fonts.get(32, bold=True),
                  palette.text, center=(lay.width // 2, y + self.s(18)))
        y += self.s(44)
        draw_text(surface, f"{accuracy:0.1f}% accuracy", fonts.get(14),
                  palette.muted, center=(lay.width // 2, y))
        y += self.s(26)

        # Judgment breakdown.
        counts = s.get("counts", {})
        row_h = self.s(38)
        card = pygame.Rect(lay.content_left, y, lay.content_width,
                           row_h * len(ROWS) + self.s(16))
        fill_rounded(surface, card, palette.surface, self.s(14))
        ry = card.y + self.s(8)
        label_font = fonts.get(15, bold=True)
        for name, color in ROWS:
            draw_text(surface, name, label_font, color,
                      midleft=(card.x + self.s(16), ry + row_h // 2))
            draw_text(surface, str(counts.get(name, 0)), label_font, palette.text,
                      midright=(card.right - self.s(16), ry + row_h // 2))
            ry += row_h
        y = card.bottom + self.s(12)

        extras = [f"Max combo: {s.get('max_combo', 0)}"]
        if not s.get("ghost_tapping", True):
            extras.append(f"Mistaps: {s.get('mistaps', 0)}")
        small = fonts.get(13)
        for line in extras:
            draw_text(surface, line, small, palette.muted,
                      center=(lay.width // 2, y + small.get_height() // 2))
            y += small.get_height() + self.s(4)

        self.group.draw(surface)
