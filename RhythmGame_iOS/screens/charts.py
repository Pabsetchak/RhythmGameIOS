"""
Importing and exporting .crchart bundles.

On iOS everything moves through the app's Documents folder: exports are
written there and imports are read from there. With UIFileSharingEnabled set
(the build does set it) that folder appears in the Files app under "On My
iPhone → Rhythm", so charts can be shared over AirDrop, Messages, iCloud
Drive or a cable without the app needing a file picker of its own.
"""

import pygame

import chart_io
import paths
import ui
from dialogs import ConfirmDialog
from screens.base import ScrollScreen
from screens.songs import SongRow
from theme import palette


class ChartsScreen(ScrollScreen):
    title = "Charts"
    subtitle = "Share charts as .crchart files"

    def build_body(self, scroll):
        lay = self.layout
        y = 0

        note = ui.Wrapped(
            pygame.Rect(self.s(4), y, scroll.rect.width - self.s(12), 0),
            "Exported charts land in this app's folder. Open the Files app, "
            "go to On My iPhone → Rhythm, and share them from there. Chart "
            "files copied into that folder show up below.",
            lay.scale, size=12)
        scroll.add(note)
        y += note.measure() + self.s(16)

        # -- Import ----------------------------------------------------- #
        pending = chart_io.list_importable()
        y = self.section_label(scroll, "AVAILABLE TO IMPORT", y)
        if not pending:
            scroll.add(ui.Label(
                pygame.Rect(self.s(4), y, scroll.rect.width, self.s(30)),
                "Nothing waiting.", lay.scale, size=13, color=palette.muted))
            y += self.s(36)
        else:
            row_h = self.s(ui.ROW_H)
            for filename in pending:
                scroll.add(SongRow(
                    pygame.Rect(0, y, scroll.rect.width - self.s(8), row_h),
                    filename, None,
                    lambda f=filename: self._import(f), lay.scale,
                    action_label="Import",
                    on_action=lambda f=filename: self._import(f)))
                y += row_h + self.s(8)

        # -- Export ----------------------------------------------------- #
        y = self.section_label(scroll, "EXPORT A CHART", y + self.s(10))
        charts = paths.list_charts()
        if not charts:
            scroll.add(ui.Label(
                pygame.Rect(self.s(4), y, scroll.rect.width, self.s(30)),
                "No charts to export yet.", lay.scale, size=13,
                color=palette.muted))
            y += self.s(36)
        else:
            row_h = self.s(ui.ROW_H)
            for song in charts:
                scroll.add(SongRow(
                    pygame.Rect(0, y, scroll.rect.width - self.s(8), row_h),
                    song, None, lambda s=song: self._export(s), lay.scale,
                    action_label="Export",
                    on_action=lambda s=song: self._export(s)))
                y += row_h + self.s(8)

        scroll.set_content_height(y)

    # ------------------------------------------------------------------ #
    def _export(self, song):
        ok, message = chart_io.export_chart(song)
        self.app.toast(message, error=not ok)
        self.rebuild()

    def _import(self, filename):
        ok, result = chart_io.import_chart(filename)
        if ok:
            self.app.toast(f"Imported '{result}'.")
            self.rebuild()
            return
        if "already exists" in result:
            self.app.push(ConfirmDialog(
                self.app, "Overwrite?",
                f"{result} Replace the existing copy?",
                lambda: self._import_over(filename),
                confirm_text="Overwrite", danger=True))
        else:
            self.app.toast(result, error=True)

    def _import_over(self, filename):
        ok, result = chart_io.import_chart(filename, overwrite=True)
        if ok:
            self.app.toast(f"Imported '{result}' (replaced).")
            self.rebuild()
        else:
            self.app.toast(result, error=True)
