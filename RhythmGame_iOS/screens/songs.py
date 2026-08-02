"""Song lists: choosing something to play, and managing your own charts."""

import os

import pygame

import chart_io
import paths
import ui
from chart_model import delete_song
from dialogs import ConfirmDialog, PromptDialog
from screens.base import ScrollScreen
from theme import (draw_text, fill_rounded, fonts, palette, shade, truncate)


class SongRow(ui.Widget):
    """
    A song card: tapping the body runs the primary action, tapping the
    trailing button runs the secondary one, and a long press deletes.
    """

    def __init__(self, rect, name, subtitle, on_primary, scale=1.0,
                 action_label=None, on_action=None, on_long=None):
        super().__init__(rect, scale)
        self.name = name
        self.subtitle = subtitle
        self.on_primary = on_primary
        self.action_label = action_label
        self.on_action = on_action
        self.on_long = on_long
        self._action_pressed = False

    def _action_rect(self):
        if not self.action_label:
            return None
        w = self.s(72)
        return pygame.Rect(self.rect.right - w - self.s(10),
                           self.rect.centery - self.s(18), w, self.s(36))

    def on_press(self, x, y):
        self.pressed = True
        action = self._action_rect()
        self._action_pressed = bool(action and action.collidepoint(x, y))

    def on_release(self, x, y, tapped):
        self.pressed = False
        was_action = self._action_pressed
        self._action_pressed = False
        if not tapped:
            return
        if was_action and self.on_action:
            self.on_action()
        elif not was_action and self.on_primary:
            self.on_primary()

    def on_long_press(self, x, y):
        if self.on_long:
            self.on_long()
            return True
        return False

    def draw(self, surface, dx=0, dy=0):
        r = self.rect.move(dx, dy)
        bg = shade(palette.surface, 0.06 if self.pressed else 0.0)
        fill_rounded(surface, r, bg, self.s(ui.RADIUS))

        # _action_rect is in content space; move it alongside r so the text
        # width is measured against screen coordinates too.
        action = self._action_rect()
        arect = action.move(dx, dy) if action else None
        text_right = (arect.left if arect else r.right) - self.s(12)
        max_w = max(self.s(40), text_right - r.x - self.s(16))

        name_font = fonts.get(16, bold=True)
        if self.subtitle:
            draw_text(surface, truncate(self.name, name_font, max_w), name_font,
                      palette.text,
                      midleft=(r.x + self.s(16), r.centery - self.s(10)))
            sub_font = fonts.get(12)
            draw_text(surface, truncate(self.subtitle, sub_font, max_w), sub_font,
                      palette.muted,
                      midleft=(r.x + self.s(16), r.centery + self.s(11)))
        else:
            draw_text(surface, truncate(self.name, name_font, max_w), name_font,
                      palette.text, midleft=(r.x + self.s(16), r.centery))

        if arect:
            fill_rounded(surface, arect,
                         palette.accent if self._action_pressed
                         else shade(palette.surface, 0.16),
                         self.s(9))
            draw_text(surface, self.action_label, fonts.get(13, bold=True),
                      palette.text, center=arect.center)


def _chart_summary(song):
    """A short description of a song's chart state, for the row subtitle."""
    json_path = paths.song_json(song)
    if not os.path.exists(json_path):
        return "No chart yet — tap to record one"
    try:
        import json
        with open(json_path) as f:
            data = json.load(f)
        count = len(data.get("note_events", []))
        duration = float(data.get("duration", 0.0))
    except (OSError, ValueError, KeyError):
        return "Chart file unreadable"
    if duration > 0:
        return f"{count} notes · {int(duration // 60)}:{int(duration % 60):02d}"
    return f"{count} notes"


class SongSelectScreen(ScrollScreen):
    title = "Play"

    def build_body(self, scroll):
        songs = paths.list_songs()
        if not songs:
            self.empty_state(
                scroll,
                "No songs yet.\n\nAdd an .mp3 through Create, or import a "
                "chart file from the Charts screen.")
            return

        y = 0
        row_h = self.s(ui.ROW_H + 8)
        for song in songs:
            has_chart = os.path.exists(paths.song_json(song))
            scroll.add(SongRow(
                pygame.Rect(0, y, scroll.rect.width - self.s(8), row_h),
                song, _chart_summary(song),
                (lambda s=song: self._play(s)) if has_chart
                else (lambda s=song: self._record(s)),
                self.layout.scale,
                action_label="Play" if has_chart else "Record",
                on_action=(lambda s=song: self._play(s)) if has_chart
                else (lambda s=song: self._record(s))))
            y += row_h + self.s(8)
        scroll.set_content_height(y)

    def _play(self, song):
        from screens.play import PlayScreen
        self.app.push(PlayScreen(self.app, song))

    def _record(self, song):
        from screens.recorder import RecorderScreen
        self.app.push(RecorderScreen(self.app, song))


class CreatorScreen(ScrollScreen):
    title = "Create"
    subtitle = "Long-press a song to delete it"

    def build_body(self, scroll):
        lay = self.layout
        y = 0

        scroll.add(ui.Button(
            pygame.Rect(0, y, scroll.rect.width - self.s(8), self.s(ui.BUTTON_H)),
            "Import an .mp3", self._import_audio, lay.scale))
        y += self.s(ui.BUTTON_H + 10)

        loose = chart_io.list_importable_audio()
        if loose:
            scroll.add(ui.Label(
                pygame.Rect(self.s(4), y, scroll.rect.width, self.s(20)),
                f"{len(loose)} file(s) waiting in your app folder",
                lay.scale, size=11, color=palette.accent))
            y += self.s(26)

        songs = paths.list_songs()
        if not songs:
            self.empty_state(
                scroll,
                "No songs yet.\n\nCopy an .mp3 into the Rhythm folder with the "
                "Files app, then tap Import above.", y)
            return

        y = self.section_label(scroll, "YOUR SONGS", y + self.s(4))

        row_h = self.s(ui.ROW_H + 8)
        for song in songs:
            scroll.add(SongRow(
                pygame.Rect(0, y, scroll.rect.width - self.s(8), row_h),
                song, _chart_summary(song),
                lambda s=song: self._edit(s), lay.scale,
                action_label="Record", on_action=lambda s=song: self._record(s),
                on_long=lambda s=song: self._confirm_delete(s)))
            y += row_h + self.s(8)
        scroll.set_content_height(y)

    # ------------------------------------------------------------------ #
    def _edit(self, song):
        from screens.editor import EditorScreen
        self.app.push(EditorScreen(self.app, song))

    def _record(self, song):
        from screens.recorder import RecorderScreen
        self.app.push(RecorderScreen(self.app, song))

    def _confirm_delete(self, song):
        self.app.push(ConfirmDialog(
            self.app, f"Delete '{song}'?",
            "The audio and its chart will both be removed.",
            lambda: self._delete(song), confirm_text="Delete", danger=True))

    def _delete(self, song):
        ok, message = delete_song(song)
        self.app.toast(message, error=not ok)
        self.rebuild()

    # ------------------------------------------------------------------ #
    def _import_audio(self):
        """
        iOS has no file picker available to pygame, so the flow is: put the
        .mp3 in the app's folder with the Files app, then pick it from this
        list. On desktop the same list shows whatever sits beside the app.
        """
        files = chart_io.list_importable_audio()
        if not files:
            self.app.toast("No .mp3 files found in your app folder.", error=True)
            return
        self.app.push(_PickFileScreen(
            self.app, "Import audio", files, self._name_and_import,
            "Copy .mp3 files into the app's folder using the Files app, "
            "then pick one here."))

    def _name_and_import(self, filename):
        default = os.path.splitext(os.path.basename(filename))[0]
        self.app.push(PromptDialog(
            self.app, "Name this song",
            lambda name: self._do_import(filename, name),
            initial=default, confirm_text="Import"))

    def _do_import(self, filename, name):
        ok, result = chart_io.import_audio(filename, name)
        if not ok:
            self.app.toast(result, error=True)
            return
        self.app.toast(f"Imported '{result}'.")
        self.rebuild()
        self._record(result)


class _PickFileScreen(ScrollScreen):
    """A plain list of filenames to choose from."""

    def __init__(self, app, title, files, on_pick, hint=None):
        super().__init__(app)
        self.title = title
        self.subtitle = None
        self.files = files
        self.on_pick = on_pick
        self.hint = hint

    def build_body(self, scroll):
        y = 0
        if self.hint:
            note = ui.Wrapped(pygame.Rect(self.s(4), y, scroll.rect.width - self.s(12), 0),
                              self.hint, self.layout.scale, size=12)
            scroll.add(note)
            y += note.measure() + self.s(14)

        row_h = self.s(ui.ROW_H)
        for name in self.files:
            scroll.add(SongRow(
                pygame.Rect(0, y, scroll.rect.width - self.s(8), row_h),
                name, None, lambda n=name: self._pick(n), self.layout.scale))
            y += row_h + self.s(8)
        scroll.set_content_height(y)

    def _pick(self, name):
        self.app.pop()
        self.on_pick(name)
