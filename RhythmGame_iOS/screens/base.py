"""
Shared scaffolding for the list-style screens: a title, a Back button, and a
scrolling body. Subclasses implement `build_body` and populate self.scroll.
"""

import pygame

import ui
from app import Screen
from theme import fonts, palette


class ScrollScreen(Screen):
    title = ""
    subtitle = None

    def __init__(self, app):
        super().__init__(app)
        self.chrome = ui.Group()
        self.scroll = None

    # ------------------------------------------------------------------ #
    def on_enter(self):
        self.rebuild()

    def on_resize(self):
        self.rebuild()

    def rebuild(self):
        lay = self.layout
        offset = self.scroll.offset if self.scroll else 0.0

        self.chrome.clear()
        self.chrome.add(ui.Button(ui.back_button_rect(lay), "Back",
                                  self.on_back, lay.scale,
                                  style=ui.Button.GHOST, font_size=14))

        # Measure the header the same way draw() will lay it out.
        header_h = fonts.get(24, bold=True).get_height() + self.s(10)
        if self.subtitle:
            header_h += fonts.get(12).get_height() + self.s(2)

        body_top = lay.content_top + header_h
        self.scroll = ui.ScrollView(
            pygame.Rect(lay.content_left, body_top, lay.content_width,
                        lay.content_bottom - body_top), lay.scale)
        self.build_body(self.scroll)
        self.scroll.scroll_to(offset)

    def build_body(self, scroll):
        raise NotImplementedError

    def on_back(self):
        self.app.pop()

    # ------------------------------------------------------------------ #
    def handle_pointer(self, ev):
        if self.chrome.handle_pointer(ev):
            return
        if self.scroll:
            self.scroll.handle_pointer(ev)

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.on_back()

    def update(self, dt, now):
        self.chrome.update(dt)
        if self.scroll:
            self.scroll.update(dt)

    def draw(self, surface):
        surface.fill(palette.bg)
        ui.draw_nav_bar(surface, self.layout, self.title, self.subtitle)
        if self.scroll:
            self.scroll.draw(surface)
        self.chrome.draw(surface)

    # ------------------------------------------------------------------ #
    # Helpers for building bodies
    # ------------------------------------------------------------------ #
    def empty_state(self, scroll, message, y=0):
        note = ui.Wrapped(pygame.Rect(0, y + self.s(30),
                                      scroll.rect.width, 0),
                          message, self.layout.scale, size=14, align="center")
        scroll.add(note)
        scroll.set_content_height(y + self.s(30) + note.measure())

    def section_label(self, scroll, text, y):
        scroll.add(ui.Label(pygame.Rect(self.s(4), y, scroll.rect.width, self.s(26)),
                            text, self.layout.scale, size=12,
                            color=palette.muted))
        return y + self.s(30)
