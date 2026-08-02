"""
Touch widget toolkit.

customtkinter cannot run on iOS, so every control the desktop build used is
rebuilt here in pygame with fingers rather than a mouse in mind:

  * nothing is smaller than a 44pt touch target
  * lists scroll with momentum and distinguish a scroll from a tap
  * a widget that wants drags (sliders) claims the gesture from the scroller
  * numbers are edited with steppers instead of tiny text fields

Coordinates: widgets store their rect in *content* space, which for a
ScrollView starts at (0, 0) in its top-left corner regardless of where that
view sits on screen. The container passes `dx`/`dy` when drawing (screen =
content + offset) and converts incoming pointer coordinates back the other
way, so a screen can lay its rows out from x=0 without knowing about safe
areas. A Group is unscrolled and its children are already in screen space,
so both offsets stay zero there.
"""

import pygame

import touch as touch_mod
from theme import (draw_text, fill_rounded, fonts, lerp, palette, shade,
                   truncate)

# Minimum comfortable touch target, in design points.
TOUCH_MIN = 44
ROW_H = 56
BUTTON_H = 52
RADIUS = 12


class Widget:
    """Base class. `scale` converts design points to device pixels."""

    wants_drag = False

    def __init__(self, rect, scale=1.0):
        self.rect = pygame.Rect(rect)
        self.scale = scale
        self.enabled = True
        self.pressed = False
        self.visible = True

    def s(self, value):
        return int(round(value * self.scale))

    def hit(self, x, y):
        return self.visible and self.enabled and self.rect.collidepoint(x, y)

    # Interaction hooks -------------------------------------------------- #
    def on_press(self, x, y):
        self.pressed = True

    def on_drag(self, x, y):
        pass

    def on_release(self, x, y, tapped):
        self.pressed = False

    def on_cancel(self):
        self.pressed = False

    def on_long_press(self, x, y):
        return False

    def update(self, dt):
        pass

    def draw(self, surface, dx=0, dy=0):
        pass


# ---------------------------------------------------------------------------- #
# Button
# ---------------------------------------------------------------------------- #
class Button(Widget):
    PRIMARY, GHOST, DANGER, PLAIN = "primary", "ghost", "danger", "plain"

    def __init__(self, rect, text, on_tap, scale=1.0, style=PRIMARY,
                 font_size=16, align="center", subtitle=None):
        super().__init__(rect, scale)
        self.text = text
        self.subtitle = subtitle
        self.on_tap = on_tap
        self.style = style
        self.font_size = font_size
        self.align = align

    def on_release(self, x, y, tapped):
        self.pressed = False
        if tapped and self.enabled and self.on_tap:
            self.on_tap()

    def _colors(self):
        if self.style == self.PRIMARY:
            return palette.accent, palette.text, None
        if self.style == self.DANGER:
            return palette.danger, (255, 255, 255), None
        if self.style == self.GHOST:
            return None, palette.text, palette.divider
        return palette.surface, palette.text, None

    def draw(self, surface, dx=0, dy=0):
        if not self.visible:
            return
        r = self.rect.move(dx, dy)
        fill, text_color, border = self._colors()

        if not self.enabled:
            fill = palette.surface_alt if fill else None
            text_color = palette.muted

        if fill:
            if self.pressed:
                fill = shade(fill, -0.18)
            fill_rounded(surface, r, fill, self.s(RADIUS))
        elif self.pressed:
            fill_rounded(surface, r, palette.surface_alt, self.s(RADIUS))

        if border:
            fill_rounded(surface, r, border, self.s(RADIUS), width=max(1, self.s(1)))

        font = fonts.get(self.font_size, bold=True)
        pad = self.s(16)
        max_w = r.width - pad * 2
        label = truncate(self.text, font, max_w)

        if self.subtitle:
            sub_font = fonts.get(12)
            gap = self.s(2)
            total = font.get_height() + gap + sub_font.get_height()
            top = r.centery - total // 2
            if self.align == "left":
                draw_text(surface, label, font, text_color, topleft=(r.x + pad, top))
                draw_text(surface, truncate(self.subtitle, sub_font, max_w),
                          sub_font, palette.muted,
                          topleft=(r.x + pad, top + font.get_height() + gap))
            else:
                draw_text(surface, label, font, text_color,
                          center=(r.centerx, top + font.get_height() // 2))
                draw_text(surface, truncate(self.subtitle, sub_font, max_w),
                          sub_font, palette.muted,
                          center=(r.centerx, top + font.get_height() + gap
                                  + sub_font.get_height() // 2))
        elif self.align == "left":
            draw_text(surface, label, font, text_color, midleft=(r.x + pad, r.centery))
        else:
            draw_text(surface, label, font, text_color, center=r.center)


# ---------------------------------------------------------------------------- #
# Switch
# ---------------------------------------------------------------------------- #
class Switch(Widget):
    def __init__(self, rect, value, on_change, scale=1.0, label=""):
        super().__init__(rect, scale)
        self.value = bool(value)
        self.on_change = on_change
        self.label = label
        self._knob = 1.0 if self.value else 0.0

    def on_release(self, x, y, tapped):
        self.pressed = False
        if tapped and self.enabled:
            self.value = not self.value
            if self.on_change:
                self.on_change(self.value)

    def update(self, dt):
        target = 1.0 if self.value else 0.0
        # Ease toward the target so the knob slides rather than snaps.
        self._knob += (target - self._knob) * min(1.0, dt * 14.0)

    def draw(self, surface, dx=0, dy=0):
        if not self.visible:
            return
        r = self.rect.move(dx, dy)
        track_w, track_h = self.s(52), self.s(31)
        track = pygame.Rect(0, 0, track_w, track_h)
        track.midright = (r.right - self.s(4), r.centery)

        if self.label:
            font = fonts.get(15)
            draw_text(surface, truncate(self.label, font,
                                        track.left - r.left - self.s(20)),
                      font, palette.text, midleft=(r.x + self.s(14), r.centery))

        off_color = shade(palette.surface, 0.14)
        fill_rounded(surface, track, lerp(off_color, palette.success, self._knob),
                     track_h // 2)

        knob_r = track_h // 2 - self.s(3)
        cx = track.left + knob_r + self.s(3) + int((track_w - 2 * (knob_r + self.s(3))) * self._knob)
        pygame.draw.circle(surface, (255, 255, 255), (cx, track.centery), knob_r)


# ---------------------------------------------------------------------------- #
# Slider
# ---------------------------------------------------------------------------- #
class Slider(Widget):
    wants_drag = True

    def __init__(self, rect, value, on_change, scale=1.0,
                 minimum=0.0, maximum=1.0, live=True):
        super().__init__(rect, scale)
        self.minimum = minimum
        self.maximum = maximum
        self.value = max(minimum, min(maximum, value))
        self.on_change = on_change
        self.live = live      # fire while dragging, not only on release

    def _fraction(self):
        span = self.maximum - self.minimum
        return (self.value - self.minimum) / span if span else 0.0

    def _track(self, r):
        inset = self.s(18)
        return pygame.Rect(r.x + inset, r.centery - self.s(3),
                           max(1, r.width - inset * 2), self.s(6))

    def _set_from_x(self, x, r):
        track = self._track(r)
        f = (x - track.x) / max(1, track.width)
        f = max(0.0, min(1.0, f))
        new = self.minimum + f * (self.maximum - self.minimum)
        if new != self.value:
            self.value = new
            if self.live and self.on_change:
                self.on_change(self.value)

    def on_press(self, x, y):
        # Deliberately does not move the knob. Inside a scrolling list the
        # press may still turn out to be the start of a vertical scroll, and
        # jumping the value under a finger that was only passing through is
        # the single most irritating thing a mobile slider can do. The value
        # commits on a drag or on a tap-release instead.
        self.pressed = True

    def on_drag(self, x, y):
        self._set_from_x(x, self.rect)

    def on_release(self, x, y, tapped):
        self.pressed = False
        if tapped:
            self._set_from_x(x, self.rect)     # tap the track to jump
        if not self.live and self.on_change:
            self.on_change(self.value)

    def draw(self, surface, dx=0, dy=0):
        if not self.visible:
            return
        r = self.rect.move(dx, dy)
        track = self._track(r)
        fill_rounded(surface, track, shade(palette.surface, 0.16), track.height // 2)

        f = self._fraction()
        if f > 0:
            done = pygame.Rect(track.x, track.y, int(track.width * f), track.height)
            fill_rounded(surface, done, palette.accent, track.height // 2)

        knob_r = self.s(13 if self.pressed else 11)
        cx = track.x + int(track.width * f)
        pygame.draw.circle(surface, (255, 255, 255), (cx, track.centery), knob_r)


# ---------------------------------------------------------------------------- #
# Stepper — touch-friendly numeric entry
# ---------------------------------------------------------------------------- #
class Stepper(Widget):
    """
    A −/+ pair around a value. Far easier than a text field on a phone, and
    it cannot produce an invalid number.
    """

    # Held this long, the buttons start repeating.
    REPEAT_DELAY = 0.45
    REPEAT_RATE = 0.06

    def __init__(self, rect, value, on_change, scale=1.0, step=1,
                 minimum=None, maximum=None, fmt=str, label=""):
        super().__init__(rect, scale)
        self.value = value
        self.on_change = on_change
        self.step = step
        self.minimum = minimum
        self.maximum = maximum
        self.fmt = fmt
        self.label = label
        self._held = 0          # -1, 0 or +1
        self._held_for = 0.0
        self._next_repeat = 0.0

    def _btn_rects(self, r):
        w = self.s(TOUCH_MIN)
        minus = pygame.Rect(r.right - w * 2 - self.s(8), r.centery - w // 2, w, w)
        plus = pygame.Rect(r.right - w, r.centery - w // 2, w, w)
        return minus, plus

    def _apply(self, direction):
        new = self.value + self.step * direction
        if self.minimum is not None:
            new = max(self.minimum, new)
        if self.maximum is not None:
            new = min(self.maximum, new)
        new = round(new, 6)
        if new != self.value:
            self.value = new
            if self.on_change:
                self.on_change(self.value)

    def on_press(self, x, y):
        self.pressed = True
        minus, plus = self._btn_rects(self.rect)
        if minus.collidepoint(x, y):
            self._held = -1
        elif plus.collidepoint(x, y):
            self._held = 1
        else:
            self._held = 0
            return
        self._apply(self._held)
        self._held_for = 0.0
        self._next_repeat = self.REPEAT_DELAY

    def on_release(self, x, y, tapped):
        self.pressed = False
        self._held = 0

    def on_cancel(self):
        self.pressed = False
        self._held = 0

    def update(self, dt):
        if not self._held:
            return
        self._held_for += dt
        if self._held_for >= self._next_repeat:
            self._apply(self._held)
            self._next_repeat = self._held_for + self.REPEAT_RATE

    def draw(self, surface, dx=0, dy=0):
        if not self.visible:
            return
        r = self.rect.move(dx, dy)
        minus, plus = self._btn_rects(r)

        if self.label:
            font = fonts.get(15)
            draw_text(surface, truncate(self.label, font,
                                        minus.left - r.left - self.s(70)),
                      font, palette.text, midleft=(r.x + self.s(14), r.centery))

        value_font = fonts.get(15, bold=True)
        draw_text(surface, self.fmt(self.value), value_font, palette.accent,
                  midright=(minus.left - self.s(12), r.centery))

        for rect, glyph, active in ((minus, "−", self._held < 0),
                                    (plus, "+", self._held > 0)):
            bg = shade(palette.surface, 0.20 if active else 0.10)
            fill_rounded(surface, rect, bg, self.s(10))
            draw_text(surface, glyph, fonts.get(22, bold=True), palette.text,
                      center=rect.center)


# ---------------------------------------------------------------------------- #
# Segmented control
# ---------------------------------------------------------------------------- #
class Segmented(Widget):
    def __init__(self, rect, options, index, on_change, scale=1.0, label=""):
        super().__init__(rect, scale)
        self.options = list(options)
        self.index = max(0, min(len(self.options) - 1, index))
        self.on_change = on_change
        self.label = label

    def _seg_rects(self, r):
        band = self._band(r)
        n = max(1, len(self.options))
        w = band.width / n
        return [pygame.Rect(int(band.x + i * w), band.y,
                            int(w) + 1, band.height) for i in range(n)]

    def _band(self, r):
        if not self.label:
            return pygame.Rect(r.x + self.s(10), r.centery - self.s(17),
                               r.width - self.s(20), self.s(34))
        width = min(r.width * 0.58, self.s(200))
        return pygame.Rect(int(r.right - width - self.s(12)),
                           r.centery - self.s(17), int(width), self.s(34))

    def on_release(self, x, y, tapped):
        self.pressed = False
        if not tapped:
            return
        for i, seg in enumerate(self._seg_rects(self.rect)):
            if seg.collidepoint(x, y) and i != self.index:
                self.index = i
                if self.on_change:
                    self.on_change(i, self.options[i])
                return

    def draw(self, surface, dx=0, dy=0):
        if not self.visible:
            return
        r = self.rect.move(dx, dy)
        if self.label:
            font = fonts.get(15)
            band = self._band(r)
            draw_text(surface, truncate(self.label, font,
                                        band.left - r.left - self.s(22)),
                      font, palette.text, midleft=(r.x + self.s(14), r.centery))

        band = self._band(r)
        fill_rounded(surface, band, shade(palette.surface, 0.12), self.s(9))

        segs = self._seg_rects(r)
        if 0 <= self.index < len(segs):
            sel = segs[self.index].inflate(-self.s(4), -self.s(4))
            fill_rounded(surface, sel, palette.accent, self.s(7))

        font = fonts.get(13, bold=True)
        for i, seg in enumerate(segs):
            color = palette.text if i == self.index else palette.muted
            draw_text(surface, truncate(self.options[i], font, seg.width - self.s(6)),
                      font, color, center=seg.center)


# ---------------------------------------------------------------------------- #
# Text field
# ---------------------------------------------------------------------------- #
class TextField(Widget):
    """
    A single-line field. Focusing it starts SDL text input, which is what
    raises the on-screen keyboard on iOS; blurring stops it again so the
    keyboard doesn't linger over the rest of the UI.
    """

    def __init__(self, rect, value="", scale=1.0, placeholder="",
                 on_change=None, on_submit=None, max_len=48):
        super().__init__(rect, scale)
        self.value = str(value)
        self.placeholder = placeholder
        self.on_change = on_change
        self.on_submit = on_submit
        self.max_len = max_len
        self.focused = False
        self._caret_t = 0.0

    def focus(self):
        if self.focused:
            return
        self.focused = True
        self._caret_t = 0.0
        try:
            pygame.key.set_text_input_rect(self.rect)
            pygame.key.start_text_input()
        except Exception:
            pass

    def blur(self):
        if not self.focused:
            return
        self.focused = False
        try:
            pygame.key.stop_text_input()
        except Exception:
            pass

    def on_release(self, x, y, tapped):
        self.pressed = False
        if tapped:
            self.focus()

    def handle_event(self, event):
        """Feed raw pygame events here while focused."""
        if not self.focused:
            return False
        if event.type == pygame.TEXTINPUT:
            if len(self.value) + len(event.text) <= self.max_len:
                self.value += event.text
                if self.on_change:
                    self.on_change(self.value)
            return True
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                self.value = self.value[:-1]
                if self.on_change:
                    self.on_change(self.value)
                return True
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.blur()
                if self.on_submit:
                    self.on_submit(self.value)
                return True
            if event.key == pygame.K_ESCAPE:
                self.blur()
                return True
        return False

    def update(self, dt):
        self._caret_t += dt

    def draw(self, surface, dx=0, dy=0):
        if not self.visible:
            return
        r = self.rect.move(dx, dy)
        fill_rounded(surface, r, shade(palette.surface, 0.10), self.s(RADIUS))
        if self.focused:
            fill_rounded(surface, r, palette.accent, self.s(RADIUS),
                         width=max(2, self.s(2)))

        font = fonts.get(16)
        pad = self.s(14)
        shown = self.value or self.placeholder
        color = palette.text if self.value else palette.muted
        # Keep the tail visible while typing rather than the head.
        text = shown
        while text and font.size(text)[0] > r.width - pad * 2:
            text = text[1:]
        rect = draw_text(surface, text, font, color, midleft=(r.x + pad, r.centery))

        if self.focused and (self._caret_t % 1.0) < 0.5:
            cx = rect.right + self.s(2) if self.value else r.x + pad
            pygame.draw.line(surface, palette.accent,
                             (cx, r.centery - font.get_height() // 2),
                             (cx, r.centery + font.get_height() // 2),
                             max(1, self.s(2)))


# ---------------------------------------------------------------------------- #
# Row — a labelled surface panel other widgets sit on
# ---------------------------------------------------------------------------- #
class Card(Widget):
    """Non-interactive background panel, drawn behind a group of widgets."""

    def __init__(self, rect, scale=1.0, color=None):
        super().__init__(rect, scale)
        self.color = color

    def hit(self, x, y):
        return False

    def draw(self, surface, dx=0, dy=0):
        if not self.visible:
            return
        fill_rounded(surface, self.rect.move(dx, dy),
                     self.color or palette.surface, self.s(RADIUS))


class Label(Widget):
    def __init__(self, rect, text, scale=1.0, size=14, color=None,
                 align="left", bold=False):
        super().__init__(rect, scale)
        self.text = text
        self.size = size
        self.color = color
        self.align = align
        self.bold = bold

    def hit(self, x, y):
        return False

    def draw(self, surface, dx=0, dy=0):
        if not self.visible:
            return
        r = self.rect.move(dx, dy)
        font = fonts.get(self.size, bold=self.bold)
        color = self.color or palette.text
        text = truncate(self.text, font, r.width)
        if self.align == "center":
            draw_text(surface, text, font, color, center=r.center)
        elif self.align == "right":
            draw_text(surface, text, font, color, midright=(r.right, r.centery))
        else:
            draw_text(surface, text, font, color, midleft=(r.x, r.centery))


class Wrapped(Widget):
    """Multi-line paragraph, wrapped to the widget width."""

    def __init__(self, rect, text, scale=1.0, size=13, color=None, align="left"):
        super().__init__(rect, scale)
        self.text = text
        self.size = size
        self.color = color
        self.align = align

    def hit(self, x, y):
        return False

    def lines(self):
        font = fonts.get(self.size)
        out = []
        for para in str(self.text).split("\n"):
            words = para.split(" ")
            current = ""
            for word in words:
                trial = f"{current} {word}".strip()
                if current and font.size(trial)[0] > self.rect.width:
                    out.append(current)
                    current = word
                else:
                    current = trial
            out.append(current)
        return out

    def measure(self):
        font = fonts.get(self.size)
        return len(self.lines()) * (font.get_height() + self.s(3))

    def draw(self, surface, dx=0, dy=0):
        if not self.visible:
            return
        font = fonts.get(self.size)
        color = self.color or palette.muted
        r = self.rect.move(dx, dy)
        y = r.y
        step = font.get_height() + self.s(3)
        for line in self.lines():
            if self.align == "center":
                draw_text(surface, line, font, color,
                          center=(r.centerx, y + font.get_height() // 2))
            else:
                draw_text(surface, line, font, color, topleft=(r.x, y))
            y += step


# ---------------------------------------------------------------------------- #
# Scrolling container
# ---------------------------------------------------------------------------- #
class ScrollView:
    """
    A clipped, momentum-scrolling column of widgets.

    Gesture arbitration, which decides by *direction* rather than by which
    widget happened to be underneath. A press is held provisionally; once
    the finger has moved past the slop threshold:

      mostly horizontal, over a widget that wants drags -> the widget claims it
      otherwise                                          -> it becomes a scroll

    Releasing without ever passing the threshold delivers a tap. This is what
    lets a settings page full of sliders still scroll normally: landing on a
    slider and dragging up scrolls the list, and only a sideways drag moves
    the knob.
    """

    FRICTION = 3.2          # velocity decay per second
    RUBBER = 0.45           # resistance factor past the ends

    def __init__(self, rect, scale=1.0):
        self.rect = pygame.Rect(rect)
        self.scale = scale
        self.widgets = []
        self.offset = 0.0
        self.velocity = 0.0
        self.content_height = 0
        self._pid = None
        self._claim = None          # widget that has won the gesture
        self._provisional = None    # pressed, but the gesture is undecided
        self._drag_candidate = None # provisional widget that accepts drags
        self._start_offset = 0.0
        self._start_x = 0.0
        self._start_y = 0.0
        self._decided = False
        self._scrolling = False
        self._samples = []

    def s(self, value):
        return int(round(value * self.scale))

    # Content ---------------------------------------------------------- #
    def clear(self):
        self.widgets = []
        self.content_height = 0

    def add(self, widget):
        self.widgets.append(widget)
        self.content_height = max(self.content_height, widget.rect.bottom)
        return widget

    def set_content_height(self, height):
        self.content_height = height

    def max_offset(self):
        return max(0.0, self.content_height - self.rect.height + self.s(16))

    # Input ------------------------------------------------------------ #
    def _to_content(self, x, y):
        """Screen coordinates -> the content space children are laid out in."""
        return x - self.rect.x, y + self.offset - self.rect.y

    def _widget_at(self, cx, cy):
        for w in reversed(self.widgets):
            if w.hit(cx, cy):
                return w
        return None

    def handle_pointer(self, ev):
        if ev.kind == touch_mod.DOWN:
            if not self.rect.collidepoint(ev.x, ev.y) or self._pid is not None:
                return False
            self._pid = ev.pid
            self._start_offset = self.offset
            self._start_x = ev.x
            self._start_y = ev.y
            self._decided = False
            self._scrolling = False
            self.velocity = 0.0
            self._samples = [(ev.time, ev.y)]

            cx, cy = self._to_content(ev.x, ev.y)
            w = self._widget_at(cx, cy)
            if w is not None:
                self._provisional = w
                self._drag_candidate = w if w.wants_drag else None
                w.on_press(cx, cy)
            return True

        if ev.pid != self._pid:
            return False

        if ev.kind == touch_mod.MOVE:
            self._samples.append((ev.time, ev.y))
            if len(self._samples) > 6:
                self._samples.pop(0)
            cx, cy = self._to_content(ev.x, ev.y)

            if self._claim is not None:
                self._claim.on_drag(cx, cy)
                return True

            dx = ev.x - self._start_x
            dy = ev.y - self._start_y
            if not self._decided:
                if max(abs(dx), abs(dy)) <= self.s(touch_mod.TAP_SLOP):
                    return True
                self._decided = True
                if self._drag_candidate is not None and abs(dx) > abs(dy):
                    # A sideways drag on a slider: hand it the gesture.
                    self._claim = self._drag_candidate
                    self._provisional = None
                    self._claim.on_drag(cx, cy)
                    return True
                self._scrolling = True
                if self._provisional is not None:
                    self._provisional.on_cancel()
                    self._provisional = None

            if self._scrolling:
                self._set_offset(self._start_offset - dy, rubber=True)
            return True

        if ev.kind == touch_mod.LONG:
            if self._provisional is not None and not self._scrolling:
                cx, cy = self._to_content(ev.x, ev.y)
                if self._provisional.on_long_press(cx, cy):
                    self._provisional.on_cancel()
                    self._provisional = None
            return True

        if ev.kind == touch_mod.UP:
            cx, cy = self._to_content(ev.x, ev.y)
            if self._claim is not None:
                self._claim.on_release(cx, cy, False)
            elif self._provisional is not None:
                self._provisional.on_release(cx, cy, not self._scrolling and ev.is_tap())
            if self._scrolling:
                self.velocity = self._fling_velocity(ev.time)
            self._pid = None
            self._claim = None
            self._provisional = None
            self._drag_candidate = None
            self._decided = False
            self._scrolling = False
            return True

        return False

    def _fling_velocity(self, now):
        """Pixels per second from the last few move samples."""
        if len(self._samples) < 2:
            return 0.0
        t0, y0 = self._samples[0]
        t1, y1 = self._samples[-1]
        dt = t1 - t0
        if dt <= 1e-4 or (now - t1) > 0.09:
            return 0.0     # finger paused before lifting: no fling
        return -(y1 - y0) / dt

    def _set_offset(self, value, rubber=False):
        lo, hi = 0.0, self.max_offset()
        if rubber:
            if value < lo:
                value = lo + (value - lo) * self.RUBBER
            elif value > hi:
                value = hi + (value - hi) * self.RUBBER
        else:
            value = max(lo, min(hi, value))
        self.offset = value

    def scroll_to(self, y):
        self._set_offset(y)

    # Frame ------------------------------------------------------------ #
    def update(self, dt):
        for w in self.widgets:
            w.update(dt)

        if self._pid is None:
            if abs(self.velocity) > 1.0:
                self.offset += self.velocity * dt
                self.velocity *= max(0.0, 1.0 - self.FRICTION * dt)
            else:
                self.velocity = 0.0

            # Spring back if a fling overshot the ends.
            lo, hi = 0.0, self.max_offset()
            if self.offset < lo:
                self.offset += (lo - self.offset) * min(1.0, dt * 12.0)
                self.velocity = 0.0
                if abs(self.offset - lo) < 0.5:
                    self.offset = lo
            elif self.offset > hi:
                self.offset += (hi - self.offset) * min(1.0, dt * 12.0)
                self.velocity = 0.0
                if abs(self.offset - hi) < 0.5:
                    self.offset = hi

    def draw(self, surface):
        prev_clip = surface.get_clip()
        surface.set_clip(self.rect)
        dx = self.rect.x
        dy = self.rect.y - int(self.offset)
        for w in self.widgets:
            # Skip anything scrolled well outside the viewport.
            if w.rect.bottom + dy < self.rect.top - 40:
                continue
            if w.rect.top + dy > self.rect.bottom + 40:
                continue
            w.draw(surface, dx, dy)
        surface.set_clip(prev_clip)
        self._draw_scrollbar(surface)

    def _draw_scrollbar(self, surface):
        span = self.max_offset()
        if span <= 0:
            return
        track_h = self.rect.height
        thumb_h = max(self.s(30),
                      int(track_h * self.rect.height / max(1, self.content_height)))
        f = max(0.0, min(1.0, self.offset / span))
        y = self.rect.y + int((track_h - thumb_h) * f)
        bar = pygame.Rect(self.rect.right - self.s(5), y, self.s(3), thumb_h)
        fill_rounded(surface, bar, palette.divider, self.s(2))


# ---------------------------------------------------------------------------- #
# Simple non-scrolling widget group
# ---------------------------------------------------------------------------- #
class Group:
    """A fixed set of widgets with the same press/tap arbitration."""

    def __init__(self):
        self.widgets = []
        self._pid = None
        self._claim = None

    def clear(self):
        self.widgets = []

    def add(self, widget):
        self.widgets.append(widget)
        return widget

    def handle_pointer(self, ev):
        if ev.kind == touch_mod.DOWN:
            if self._pid is not None:
                return False
            for w in reversed(self.widgets):
                if w.hit(ev.x, ev.y):
                    self._pid = ev.pid
                    self._claim = w
                    w.on_press(ev.x, ev.y)
                    return True
            return False

        if ev.pid != self._pid or self._claim is None:
            return False

        if ev.kind == touch_mod.MOVE:
            if self._claim.wants_drag:
                self._claim.on_drag(ev.x, ev.y)
            return True
        if ev.kind == touch_mod.LONG:
            self._claim.on_long_press(ev.x, ev.y)
            return True
        if ev.kind == touch_mod.UP:
            self._claim.on_release(ev.x, ev.y, ev.is_tap())
            self._pid = None
            self._claim = None
            return True
        return False

    def update(self, dt):
        for w in self.widgets:
            w.update(dt)

    def draw(self, surface):
        for w in self.widgets:
            w.draw(surface)


# ---------------------------------------------------------------------------- #
# Chrome
# ---------------------------------------------------------------------------- #
def draw_nav_bar(surface, layout, title, subtitle=None):
    """Title block at the top of a screen. Returns its bottom y."""
    top = layout.content_top
    font = fonts.get(24, bold=True)
    x = layout.content_left + layout.s(6)
    draw_text(surface, truncate(title, font, layout.content_width - layout.s(110)),
              font, palette.text, topleft=(x, top))
    y = top + font.get_height()
    if subtitle:
        sub_font = fonts.get(12)
        draw_text(surface, truncate(subtitle, sub_font, layout.content_width - layout.s(110)),
                  sub_font, palette.muted, topleft=(x, y + layout.s(2)))
        y += sub_font.get_height() + layout.s(2)
    return y + layout.s(10)


def back_button_rect(layout):
    """Top-right, where a thumb can reach it one-handed."""
    w, h = layout.s(78), layout.s(38)
    return pygame.Rect(layout.content_right - w, layout.content_top, w, h)
