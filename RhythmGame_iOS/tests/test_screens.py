"""Headless smoke test: boot, walk every screen, simulate touches."""
import os
import sys
import traceback

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRC)

import pygame  # noqa: E402

failures = []


def tick(app, n=3):
    for _ in range(n):
        app.tick()


def tap(app, x, y):
    """Simulate a finger down+up at a point, one frame apart."""
    pygame.event.post(pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (int(x), int(y))}))
    app.tick()
    pygame.event.post(pygame.event.Event(
        pygame.MOUSEBUTTONUP, {"button": 1, "pos": (int(x), int(y))}))
    app.tick()


def check(name, fn):
    try:
        fn()
        print(f"  ok   {name}")
    except Exception as e:
        failures.append((name, traceback.format_exc()))
        print(f"  FAIL {name}: {type(e).__name__}: {e}")


def main():
    import paths
    print(f"data dir: {paths.DATA_DIR}")

    # A deliberately unreadable mp3, to prove the screens survive bad audio.
    os.makedirs(paths.RHYTHMS_DIR, exist_ok=True)
    bad = paths.song_mp3("smoketest")
    with open(bad, "wb") as f:
        f.write(b"not really an mp3")

    import chart_model
    notes = [chart_model.make_note(i * 0.4, i % 4, 0.2 if i % 5 == 0 else 0.0)
             for i in range(24)]
    chart_model.save_chart("smoketest", notes, 12.0)

    from app import App
    from screens.menu import MainMenu

    app = App()
    app.set_root(MainMenu(app))
    print(f"layout: {app.layout.width}x{app.layout.height} scale={app.layout.scale:.2f}")
    tick(app, 5)

    lay = app.layout
    cx = lay.width // 2

    def open_and_close(label, opener, extra=None):
        def run():
            opener()
            tick(app, 4)
            if extra:
                extra()
                tick(app, 4)
            app.pop_to_root()
            tick(app, 2)
        check(label, run)

    # -- each menu destination -------------------------------------------- #
    from screens.songs import SongSelectScreen, CreatorScreen
    from screens.charts import ChartsScreen
    from screens.settings_screen import SettingsScreen, ColorPickerScreen
    from screens.calibrate import CalibrationScreen
    from screens.editor import EditorScreen
    from screens.recorder import RecorderScreen
    from screens.play import PlayScreen
    from screens.results import ResultsScreen

    open_and_close("song select", lambda: app.push(SongSelectScreen(app)))
    open_and_close("creator", lambda: app.push(CreatorScreen(app)))
    open_and_close("charts", lambda: app.push(ChartsScreen(app)))
    open_and_close("settings", lambda: app.push(SettingsScreen(app)))
    open_and_close("colour picker",
                   lambda: app.push(ColorPickerScreen(app, "LEFT", "Left")))
    open_and_close("theme colour picker",
                   lambda: app.push(ColorPickerScreen(app, "THEME_ACCENT", "Accent")))
    open_and_close("calibration", lambda: app.push(CalibrationScreen(app)))

    # -- settings interaction --------------------------------------------- #
    def settings_scroll():
        app.push(SettingsScreen(app))
        tick(app, 3)
        scr = app.top
        # Drag to scroll, then release.
        pygame.event.post(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (cx, lay.height - 200)}))
        app.tick()
        for i in range(6):
            pygame.event.post(pygame.event.Event(
                pygame.MOUSEMOTION, {"pos": (cx, lay.height - 200 - i * 40),
                                     "rel": (0, -40), "buttons": (1, 0, 0)}))
            app.tick()
        pygame.event.post(pygame.event.Event(
            pygame.MOUSEBUTTONUP, {"button": 1, "pos": (cx, lay.height - 440)}))
        tick(app, 10)
        assert scr.scroll.offset > 0, "scroll did not move"
        app.pop_to_root()
    check("settings scroll", settings_scroll)

    # -- gameplay ---------------------------------------------------------- #
    def gameplay():
        app.push(PlayScreen(app, "smoketest"))
        tick(app, 6)
        scr = app.top
        # Tap each lane column.
        for lane in range(4):
            x = lay.width * (lane + 0.5) / 4
            tap(app, x, lay.height * 0.8)
        tick(app, 10)
        assert scr.road is not None
        app.pop_to_root()
    check("gameplay", gameplay)

    def gameplay_multitouch():
        app.push(PlayScreen(app, "smoketest"))
        tick(app, 6)
        scr = app.top
        # Four fingers down at once via raw finger events.
        for i in range(4):
            pygame.event.post(pygame.event.Event(
                pygame.FINGERDOWN,
                {"touch_id": 1, "finger_id": 100 + i,
                 "x": (i + 0.5) / 4, "y": 0.8, "dx": 0.0, "dy": 0.0,
                 "pressure": 1.0}))
        app.tick()
        assert len(scr.pid_lane) == 4, f"expected 4 fingers, got {len(scr.pid_lane)}"
        assert sorted(scr.pid_lane.values()) == [0, 1, 2, 3], scr.pid_lane
        for i in range(4):
            pygame.event.post(pygame.event.Event(
                pygame.FINGERUP,
                {"touch_id": 1, "finger_id": 100 + i,
                 "x": (i + 0.5) / 4, "y": 0.8, "dx": 0.0, "dy": 0.0,
                 "pressure": 1.0}))
        app.tick()
        assert not scr.pid_lane, "fingers not released"
        app.pop_to_root()
    check("gameplay multitouch", gameplay_multitouch)

    def pause_flow():
        app.push(PlayScreen(app, "smoketest"))
        tick(app, 4)
        scr = app.top
        pr = scr._pause_rect()
        tap(app, pr.centerx, pr.centery)
        tick(app, 2)
        assert scr.paused, "pause did not engage"
        tick(app, 3)
        app.pop_to_root()
    check("pause", pause_flow)

    # -- recorder ---------------------------------------------------------- #
    def recorder_chords():
        app.push(RecorderScreen(app, "smoketest"))
        tick(app, 4)
        scr = app.top
        # Rewind the clock anchor so the count-in has genuinely elapsed.
        scr._start_ticks -= 5000
        app.tick()
        assert scr.song_time > 0, f"still in count-in: {scr.song_time}"
        # Three fingers down together, then up together: one chord.
        for i in range(3):
            pygame.event.post(pygame.event.Event(
                pygame.FINGERDOWN,
                {"touch_id": 1, "finger_id": 200 + i,
                 "x": (i + 0.5) / 4, "y": 0.85, "dx": 0.0, "dy": 0.0,
                 "pressure": 1.0}))
        app.tick()
        assert len(scr.held) == 3, f"expected 3 held fingers, got {len(scr.held)}"
        for i in range(3):
            pygame.event.post(pygame.event.Event(
                pygame.FINGERUP,
                {"touch_id": 1, "finger_id": 200 + i,
                 "x": (i + 0.5) / 4, "y": 0.85, "dx": 0.0, "dy": 0.0,
                 "pressure": 1.0}))
        app.tick()
        lanes = sorted(n["lane"] for n in scr.notes)
        assert len(scr.notes) == 3, f"expected 3 notes, got {len(scr.notes)}"
        assert lanes == [0, 1, 2], lanes
        times = {round(n["timestamp"], 3) for n in scr.notes}
        assert len(times) == 1, f"chord notes not simultaneous: {times}"
        scr.finished = True          # don't let _finish save over the fixture
        app.pop_to_root()
    check("recorder chord capture", recorder_chords)

    # -- editor ------------------------------------------------------------ #
    def editor():
        app.push(EditorScreen(app, "smoketest"))
        tick(app, 4)
        scr = app.top
        before = len(scr.notes)
        # Tap empty lane space to add a note.
        lane_x = scr.lanes_rect.x + scr.lane_w * 2.5
        tap(app, lane_x, scr.canvas.y + scr.canvas.height * 0.7)
        tick(app, 2)
        assert len(scr.notes) == before + 1, "tap did not add a note"
        assert scr.selected is not None, "new note not selected"

        # Drag to scroll.
        start_view = scr.view_time
        pygame.event.post(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, {"button": 1,
                                     "pos": (int(lane_x), scr.canvas.bottom - 30)}))
        app.tick()
        for i in range(5):
            pygame.event.post(pygame.event.Event(
                pygame.MOUSEMOTION,
                {"pos": (int(lane_x), scr.canvas.bottom - 30 - i * 30),
                 "rel": (0, -30), "buttons": (1, 0, 0)}))
            app.tick()
        pygame.event.post(pygame.event.Event(
            pygame.MOUSEBUTTONUP, {"button": 1,
                                   "pos": (int(lane_x), scr.canvas.bottom - 180)}))
        app.tick()
        assert scr.view_time > start_view, "drag did not scroll the timeline"

        # Pinch zoom.
        start_pps = scr.pps
        for i, y in ((0, 0.4), (1, 0.6)):
            pygame.event.post(pygame.event.Event(
                pygame.FINGERDOWN,
                {"touch_id": 1, "finger_id": 300 + i, "x": 0.5, "y": y,
                 "dx": 0.0, "dy": 0.0, "pressure": 1.0}))
        app.tick()
        for i, y in ((0, 0.25), (1, 0.75)):
            pygame.event.post(pygame.event.Event(
                pygame.FINGERMOTION,
                {"touch_id": 1, "finger_id": 300 + i, "x": 0.5, "y": y,
                 "dx": 0.0, "dy": 0.1, "pressure": 1.0}))
        app.tick()
        assert scr.pps > start_pps, f"pinch did not zoom in ({start_pps} -> {scr.pps})"
        for i in range(2):
            pygame.event.post(pygame.event.Event(
                pygame.FINGERUP,
                {"touch_id": 1, "finger_id": 300 + i, "x": 0.5, "y": 0.5,
                 "dx": 0.0, "dy": 0.0, "pressure": 1.0}))
        app.tick()

        scr._dirty = False           # skip the discard prompt
        app.pop_to_root()
    check("editor add / scroll / pinch", editor)

    # -- scroll coordinate contract ---------------------------------------- #
    def scroll_coordinates():
        """
        Children of a ScrollView are laid out from x=0 in content space, but
        the view itself is inset by the safe area. Tapping a row's trailing
        button at its true *screen* position must reach that button - this is
        the regression guard for content/screen space getting mixed up.
        """
        from screens.songs import SongRow

        app.push(SongSelectScreen(app))
        tick(app, 3)
        scr = app.top
        rows = [w for w in scr.scroll.widgets if isinstance(w, SongRow)]
        assert rows, "no song rows built"
        row = rows[0]

        assert row.rect.x == 0, "rows should be laid out from content x=0"
        assert scr.scroll.rect.x > 0, "scroll view should be inset by the safe area"

        fired = []
        row.on_action = lambda: fired.append(True)
        row.on_primary = lambda: fired.append(False)

        # Convert the action button from content space to the screen.
        action = row._action_rect()
        sx = action.centerx + scr.scroll.rect.x
        sy = action.centery + scr.scroll.rect.y - int(scr.scroll.offset)
        tap(app, sx, sy)
        tick(app, 2)

        assert fired == [True], (
            f"tap at screen ({sx},{sy}) did not reach the row action: {fired}")
        app.pop_to_root()
    check("scroll coordinate contract", scroll_coordinates)

    # -- results ----------------------------------------------------------- #
    def results():
        app.push(ResultsScreen(app, "smoketest", {
            "score": 12345, "counts": {"PERFECT": 10, "GOOD": 3, "BAD": 1, "MISS": 2},
            "max_combo": 11, "accuracy": 82.5, "mistaps": 0, "ghost_tapping": True}))
        tick(app, 4)
        app.pop_to_root()
    check("results", results)

    # -- dialogs ----------------------------------------------------------- #
    def dialogs():
        from dialogs import ConfirmDialog, PromptDialog
        app.push(ConfirmDialog(app, "Title", "Message body", lambda: None))
        tick(app, 3)
        app.pop()
        app.push(PromptDialog(app, "Name", lambda v: None, initial="x"))
        tick(app, 3)
        app.pop()
        tick(app, 2)
    check("dialogs", dialogs)

    # -- degenerate display size ------------------------------------------- #
    def degenerate_layout():
        """
        On iOS, set_mode((0,0)) can hand back a 0x0 surface. A layout built
        from that puts every control off-screen and renders pure black with
        no exception — indistinguishable from a hang. Layout must refuse to
        be degenerate.
        """
        import platform_compat
        for w, h in ((0, 0), (0, 800), (300, 0), (-5, -5)):
            lay = platform_compat.Layout(w, h)
            assert lay.width >= 320 and lay.height >= 480, \
                f"Layout({w},{h}) -> {lay.width}x{lay.height}"
            assert lay.scale > 0, f"Layout({w},{h}) scale={lay.scale}"
            assert lay.content_width > 0, f"Layout({w},{h}) content_width={lay.content_width}"
            assert lay.content_height > 0, f"Layout({w},{h}) content_height={lay.content_height}"
        # A normal size must be passed through untouched.
        lay = platform_compat.Layout(430, 860)
        assert (lay.width, lay.height) == (430, 860), (lay.width, lay.height)
    check("degenerate display size", degenerate_layout)

    # -- entry point contract ---------------------------------------------- #
    def entry_point():
        """
        pygame-ios finds the frame callback by name at module scope. If it is
        renamed or nested the app builds fine and then shows a black screen,
        so guard the contract here.
        """
        import main as entry
        assert hasattr(entry, "_ios_tick"), "_ios_tick is missing"
        assert callable(entry._ios_tick), "_ios_tick is not callable"
        # Importing must not have started a blocking loop, and must not have
        # taken the desktop path on a device.
        assert entry._app is None, "importing main should not boot the app"
        assert hasattr(entry, "_draw_message"), "no on-device error reporting"
    check("entry point contract", entry_point)

    # -- toast ------------------------------------------------------------- #
    def toast():
        app.toast("Hello there")
        tick(app, 5)
        app.toast("Something failed", error=True)
        tick(app, 5)
    check("toast", toast)

    app.shutdown()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        for name, tb in failures:
            print(f"\n--- {name} ---\n{tb}")
        return 1
    print("all checks passed")
    return 0


def cleanup():
    """Remove the fixture so it doesn't show up as a real song in the app."""
    import paths
    for name in ("smoketest.mp3", "smoketest.json"):
        try:
            os.remove(os.path.join(paths.RHYTHMS_DIR, name))
        except OSError:
            pass


if __name__ == "__main__":
    try:
        code = main()
    finally:
        cleanup()
    sys.exit(code)
