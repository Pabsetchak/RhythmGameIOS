"""
Modal sheets: confirmations and single-field prompts.

These are ordinary screens pushed onto the stack with `transparent = True`,
so the screen underneath keeps drawing and the sheet floats over it.
"""

import pygame

import ui
from app import Screen
from theme import draw_text, fill_rounded, fonts, palette
from touch import DOWN, UP


class _Sheet(Screen):
    transparent = True

    def __init__(self, app, title, message=None):
        super().__init__(app)
        self.title = title
        self.message = message
        self.group = ui.Group()
        self.panel = pygame.Rect(0, 0, 0, 0)
        self._dismiss_pid = None

    def _panel_rect(self, height):
        lay = self.layout
        width = min(lay.content_width, lay.s(340))
        rect = pygame.Rect(0, 0, width, height)
        rect.center = (lay.width // 2, lay.height // 2)
        return rect

    def handle_pointer(self, ev):
        if self.group.handle_pointer(ev):
            return
        # A tap on the dimmed backdrop dismisses the sheet.
        if ev.kind == DOWN and not self.panel.collidepoint(ev.x, ev.y):
            self._dismiss_pid = ev.pid
        elif ev.kind == UP and ev.pid == self._dismiss_pid:
            self._dismiss_pid = None
            if not self.panel.collidepoint(ev.x, ev.y) and ev.is_tap():
                self.dismiss()

    def dismiss(self):
        self.app.pop()

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.dismiss()

    def update(self, dt, now):
        self.group.update(dt)

    def _draw_backdrop(self, surface):
        veil = pygame.Surface((self.layout.width, self.layout.height),
                              pygame.SRCALPHA)
        veil.fill((0, 0, 0, 150))
        surface.blit(veil, (0, 0))

    def _draw_panel(self, surface):
        fill_rounded(surface, self.panel, palette.surface, self.s(18))

        y = self.panel.y + self.s(22)
        title_font = fonts.get(18, bold=True)
        draw_text(surface, self.title, title_font, palette.text,
                  center=(self.panel.centerx, y + title_font.get_height() // 2))
        y += title_font.get_height() + self.s(8)

        if self.message:
            body = ui.Wrapped(pygame.Rect(self.panel.x + self.s(20), y,
                                          self.panel.width - self.s(40), 0),
                              self.message, self.layout.scale, size=13,
                              align="center")
            body.draw(surface)


class ConfirmDialog(_Sheet):
    def __init__(self, app, title, message, on_confirm,
                 confirm_text="Confirm", danger=False):
        super().__init__(app, title, message)
        self.on_confirm = on_confirm
        self.confirm_text = confirm_text
        self.danger = danger

    def on_enter(self):
        lay = self.layout
        pad = self.s(20)
        body = ui.Wrapped(pygame.Rect(0, 0, min(lay.content_width, lay.s(340)) - pad * 2, 0),
                          self.message or "", lay.scale, size=13)
        text_h = body.measure() if self.message else 0
        height = self.s(96) + text_h + self.s(56) + self.s(20)
        self.panel = self._panel_rect(height)

        btn_y = self.panel.bottom - self.s(20) - self.s(ui.BUTTON_H)
        half = (self.panel.width - pad * 2 - self.s(10)) // 2

        self.group.clear()
        self.group.add(ui.Button(
            pygame.Rect(self.panel.x + pad, btn_y, half, self.s(ui.BUTTON_H)),
            "Cancel", self.dismiss, lay.scale, style=ui.Button.GHOST))
        self.group.add(ui.Button(
            pygame.Rect(self.panel.right - pad - half, btn_y, half, self.s(ui.BUTTON_H)),
            self.confirm_text, self._confirm, lay.scale,
            style=ui.Button.DANGER if self.danger else ui.Button.PRIMARY))

    def _confirm(self):
        self.app.pop()
        if self.on_confirm:
            self.on_confirm()

    def draw(self, surface):
        self._draw_backdrop(surface)
        self._draw_panel(surface)
        self.group.draw(surface)


class PromptDialog(_Sheet):
    """One text field plus confirm/cancel."""

    def __init__(self, app, title, on_submit, initial="", placeholder="",
                 message=None, confirm_text="Save"):
        super().__init__(app, title, message)
        self.on_submit = on_submit
        self.initial = initial
        self.placeholder = placeholder
        self.confirm_text = confirm_text
        self.field = None

    def on_enter(self):
        lay = self.layout
        pad = self.s(20)
        height = self.s(96) + self.s(52) + self.s(18) + self.s(ui.BUTTON_H) + self.s(20)
        if self.message:
            height += self.s(34)
        self.panel = self._panel_rect(height)

        field_y = self.panel.y + self.s(64) + (self.s(30) if self.message else 0)
        self.field = ui.TextField(
            pygame.Rect(self.panel.x + pad, field_y,
                        self.panel.width - pad * 2, self.s(52)),
            self.initial, lay.scale, placeholder=self.placeholder,
            on_submit=lambda _v: self._submit())

        btn_y = self.panel.bottom - self.s(20) - self.s(ui.BUTTON_H)
        half = (self.panel.width - pad * 2 - self.s(10)) // 2

        self.group.clear()
        self.group.add(self.field)
        self.group.add(ui.Button(
            pygame.Rect(self.panel.x + pad, btn_y, half, self.s(ui.BUTTON_H)),
            "Cancel", self.dismiss, lay.scale, style=ui.Button.GHOST))
        self.group.add(ui.Button(
            pygame.Rect(self.panel.right - pad - half, btn_y, half, self.s(ui.BUTTON_H)),
            self.confirm_text, self._submit, lay.scale))

        self.field.focus()

    def on_exit(self):
        if self.field:
            self.field.blur()

    def _submit(self):
        value = self.field.value.strip() if self.field else ""
        if not value:
            self.app.toast("Enter a name first.", error=True)
            return
        self.field.blur()
        self.app.pop()
        if self.on_submit:
            self.on_submit(value)

    def handle_event(self, event):
        if self.field and self.field.handle_event(event):
            return
        super().handle_event(event)

    def draw(self, surface):
        self._draw_backdrop(surface)
        self._draw_panel(surface)
        self.group.draw(surface)
