"""
Multitouch input.

SDL reports touches as FINGERDOWN / FINGERMOTION / FINGERUP with normalized
coordinates and a per-finger id, and mice as MOUSEBUTTON* / MOUSEMOTION with
pixel coordinates. This module folds both into one stream of pointer events
so screens never branch on platform, and tracks each pointer's history so
gestures (tap, long press, drag, pinch) can be recognised on top.

Timing note: pygame does not expose SDL's per-event timestamps, so every
event drained in a frame is stamped with that frame's poll time. At 60 Hz
that is up to ~16 ms of quantisation on a tap. It is a constant-ish bias
rather than random jitter, which is exactly what the calibration screen's
AUDIO_OFFSET is there to absorb.
"""

import math
import time

import pygame

# A pointer may wander this many points and still count as a tap rather than
# a drag. Fingers are far less precise than a mouse, so this is generous.
TAP_SLOP = 14.0
# Held longer than this without moving = a long press.
LONG_PRESS = 0.45
# Released within this long = a tap (guards against a slow press-and-hold).
TAP_MAX_TIME = 0.6

DOWN = "down"
MOVE = "move"
UP = "up"
LONG = "long"

# Sentinel pointer id used for the desktop mouse, kept distinct from any
# integer finger id SDL might hand out.
MOUSE_PID = "mouse"


class Pointer:
    """One finger (or the mouse) currently touching the screen."""

    __slots__ = ("pid", "x", "y", "start_x", "start_y", "start_time",
                 "prev_x", "prev_y", "moved", "long_fired")

    def __init__(self, pid, x, y, now):
        self.pid = pid
        self.x = self.start_x = self.prev_x = x
        self.y = self.start_y = self.prev_y = y
        self.start_time = now
        self.moved = False
        self.long_fired = False

    @property
    def pos(self):
        return (self.x, self.y)

    @property
    def start_pos(self):
        return (self.start_x, self.start_y)

    @property
    def delta(self):
        """Movement since the previous frame."""
        return (self.x - self.prev_x, self.y - self.prev_y)

    @property
    def total_delta(self):
        """Movement since the finger went down."""
        return (self.x - self.start_x, self.y - self.start_y)

    def travel(self):
        dx, dy = self.total_delta
        return math.hypot(dx, dy)


class PointerEvent:
    """A single pointer transition, in device pixels."""

    __slots__ = ("kind", "pid", "x", "y", "time", "pointer")

    def __init__(self, kind, pointer, now):
        self.kind = kind
        self.pid = pointer.pid
        self.x = pointer.x
        self.y = pointer.y
        self.time = now
        self.pointer = pointer

    @property
    def pos(self):
        return (self.x, self.y)

    def is_tap(self):
        """True if this UP ends a short, stationary press."""
        return (self.kind == UP
                and not self.pointer.moved
                and not self.pointer.long_fired
                and (self.time - self.pointer.start_time) <= TAP_MAX_TIME)


class TouchInput:
    """
    Translates raw pygame events into pointer events and keeps the set of
    live pointers. Feed it every event, then read `events` for the frame.
    """

    def __init__(self, layout):
        self.layout = layout
        self.pointers = {}
        self.events = []
        self.now = time.perf_counter()
        # Slop scales with the display so it stays a constant physical size.
        self._slop = TAP_SLOP * layout.scale

    def set_layout(self, layout):
        self.layout = layout
        self._slop = TAP_SLOP * layout.scale

    # ------------------------------------------------------------------ #
    # Frame lifecycle
    # ------------------------------------------------------------------ #
    def begin_frame(self):
        self.events = []
        self.now = time.perf_counter()
        for p in self.pointers.values():
            p.prev_x, p.prev_y = p.x, p.y

    def end_frame(self):
        """Emit long-press events for anything held still long enough."""
        for p in self.pointers.values():
            if (not p.long_fired and not p.moved
                    and (self.now - p.start_time) >= LONG_PRESS):
                p.long_fired = True
                self.events.append(PointerEvent(LONG, p, self.now))

    # ------------------------------------------------------------------ #
    # Event intake
    # ------------------------------------------------------------------ #
    def handle(self, event):
        t = event.type
        if t == pygame.FINGERDOWN:
            self._down(event.finger_id,
                       event.x * self.layout.width,
                       event.y * self.layout.height)
        elif t == pygame.FINGERMOTION:
            self._move(event.finger_id,
                       event.x * self.layout.width,
                       event.y * self.layout.height)
        elif t == pygame.FINGERUP:
            self._up(event.finger_id,
                     event.x * self.layout.width,
                     event.y * self.layout.height)
        elif t == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._down(MOUSE_PID, event.pos[0], event.pos[1])
        elif t == pygame.MOUSEMOTION and self.pointers.get(MOUSE_PID):
            self._move(MOUSE_PID, event.pos[0], event.pos[1])
        elif t == pygame.MOUSEBUTTONUP and event.button == 1:
            self._up(MOUSE_PID, event.pos[0], event.pos[1])

    def _down(self, pid, x, y):
        # A duplicate DOWN for a live pointer would strand the old one; treat
        # it as the start of a fresh press.
        if pid in self.pointers:
            self._up(pid, x, y)
        p = Pointer(pid, x, y, self.now)
        self.pointers[pid] = p
        self.events.append(PointerEvent(DOWN, p, self.now))

    def _move(self, pid, x, y):
        p = self.pointers.get(pid)
        if p is None:
            return
        p.x, p.y = x, y
        if not p.moved and p.travel() > self._slop:
            p.moved = True
        self.events.append(PointerEvent(MOVE, p, self.now))

    def _up(self, pid, x, y):
        p = self.pointers.pop(pid, None)
        if p is None:
            return
        p.x, p.y = x, y
        self.events.append(PointerEvent(UP, p, self.now))

    # ------------------------------------------------------------------ #
    # Gesture helpers
    # ------------------------------------------------------------------ #
    def active_count(self):
        return len(self.pointers)

    def two_finger_pair(self):
        """The two longest-lived pointers, oldest first, or None."""
        if len(self.pointers) < 2:
            return None
        ordered = sorted(self.pointers.values(), key=lambda p: p.start_time)
        return ordered[0], ordered[1]

    def pinch_distance(self):
        """Current spread between the two primary pointers, or None."""
        pair = self.two_finger_pair()
        if pair is None:
            return None
        a, b = pair
        return math.hypot(a.x - b.x, a.y - b.y)

    def pinch_center(self):
        pair = self.two_finger_pair()
        if pair is None:
            return None
        a, b = pair
        return ((a.x + b.x) * 0.5, (a.y + b.y) * 0.5)

    def cancel_all(self):
        """Drop every live pointer, e.g. when a screen is torn down."""
        self.pointers.clear()
        self.events = []
