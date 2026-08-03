"""
Entry point.

iOS owns the run loop. pygame-ios looks for a module-scope `_ios_tick` and
wires it to SDL_iPhoneSetAnimationCallback, calling it once per display
refresh; a conventional `while True: pygame.event.get()` loop would never
return control and the watchdog would kill the app. So the loop lives here
only for desktop, and on device every frame arrives as a call to _ios_tick.

Keep the name and module-scope placement of _ios_tick as they are — the
template detects it by name.

Two rules this module follows, both learned the hard way:

  * Import does no graphics. Touching pygame.display before the template's
    own SDL setup has finished can leave the screen black permanently. Every
    display call happens inside a tick.
  * Import does write a log file. If the screen is black there is no console
    and no on-screen message to read, so diagnostics.py records progress to
    Documents/boot_log.txt, readable in the Files app.
"""

import os
import sys
import traceback

import diagnostics
import paths

# Platforms where a blocking loop is the correct thing to do. Anything not on
# this list gets the callback-driven path, so failing to recognise iOS can
# never result in the run loop being starved.
_DESKTOP_PLATFORMS = ("win32", "linux", "linux2", "cygwin", "darwin")

_app = None
_error_text = None
_splash_shown = False


def _is_real_desktop():
    """
    A blocking loop is only safe somewhere it cannot starve a UI run loop.

    "darwin" is ambiguous — it covers both macOS and, on some builds, iOS —
    so for darwin we additionally require something only macOS has.
    """
    if paths.IS_IOS:
        return False
    if sys.platform not in _DESKTOP_PLATFORMS:
        return False
    if sys.platform == "darwin":
        for macos_only in ("/System/Library/CoreServices/Finder.app",
                           "/Applications/Utilities"):
            if os.path.isdir(macos_only):
                return True
        return False
    return True


# ---------------------------------------------------------------------------- #
# On-screen diagnostics (only ever called from inside a tick)
# ---------------------------------------------------------------------------- #
def _screen():
    import pygame
    if not pygame.display.get_init():
        pygame.display.init()
    surface = pygame.display.get_surface()
    if surface is None:
        surface = pygame.display.set_mode((0, 0) if paths.IS_IOS else (430, 860))
    return surface


def _draw_message(title, body, background=(18, 6, 6), color=(255, 205, 205)):
    """Wrap `body` to the screen width and show it. Never raises."""
    try:
        import pygame
        surface = _screen()
        if not pygame.font.get_init():
            pygame.font.init()

        width = surface.get_width()
        head = pygame.font.Font(None, max(22, width // 18))
        mono = pygame.font.Font(None, max(16, width // 30))
        per_line = max(24, int(width / max(1, mono.size("x")[0])) - 2)

        surface.fill(background)
        y = 60
        surface.blit(head.render(title, True, (255, 255, 255)), (12, y))
        y += head.get_height() + 12

        for raw in body.splitlines():
            if not raw.strip():
                y += mono.get_height() // 2
                continue
            line = raw.rstrip()
            while line:
                surface.blit(mono.render(line[:per_line], True, color), (12, y))
                line = line[per_line:]
                y += mono.get_height() + 2
                if y > surface.get_height() - 20:
                    break
            if y > surface.get_height() - 20:
                break

        pygame.display.flip()
    except Exception:
        diagnostics.exception("failed to draw on-screen message")


# ---------------------------------------------------------------------------- #
# Boot
# ---------------------------------------------------------------------------- #
def _boot():
    diagnostics.log("boot: importing App")
    from app import App
    diagnostics.log("boot: importing MainMenu")
    from screens.menu import MainMenu

    diagnostics.log("boot: constructing App")
    instance = App()
    diagnostics.log(f"boot: display surface = {instance.surface.get_size()}")
    diagnostics.log("boot: setting root screen")
    instance.set_root(MainMenu(instance))
    diagnostics.log("boot: ready")
    return instance


def _ios_tick():
    """One frame. Called by the iOS run loop; must always return promptly."""
    global _app, _error_text, _splash_shown

    if _error_text is not None:
        _draw_message("Crashed on startup", _error_text)
        return

    try:
        if not _splash_shown:
            # First contact with the display, now that the template's own
            # setup has certainly finished.
            _splash_shown = True
            diagnostics.log("tick 1 reached - the frame callback IS firing")
            _draw_message(
                "Starting…",
                f"platform: {sys.platform}\n"
                f"iOS detected: {paths.IS_IOS}\n"
                f"reason: {paths.IOS_REASON}\n\n"
                "Loading…",
                background=(10, 10, 20), color=(150, 150, 180))
            return          # let this frame present before the heavy work

        if _app is None:
            _app = _boot()

        _app.tick()
        diagnostics.frame()
    except Exception:
        _error_text = traceback.format_exc()
        diagnostics.exception("exception in _ios_tick")
        traceback.print_exc()
        _draw_message("Crashed on startup", _error_text)


def _run_desktop():
    """Blocking loop, for developing on a laptop."""
    app = _boot()
    try:
        while app.running:
            app.tick()
    finally:
        app.shutdown()


# ---------------------------------------------------------------------------- #
# Module-level startup — no graphics here, only logging
# ---------------------------------------------------------------------------- #
diagnostics.begin({
    "build_config.TARGET": repr(paths.BUILD_TARGET),
    "paths.IS_IOS": paths.IS_IOS,
    "how decided": paths.IOS_REASON,
    "__name__": __name__,
    "_is_real_desktop()": _is_real_desktop(),
})

try:
    paths.ensure_dirs()
    diagnostics.log(f"data dir ready: {paths.DATA_DIR}")
except Exception:
    diagnostics.exception("ensure_dirs failed")

if _is_real_desktop() and __name__ == "__main__":
    diagnostics.log("taking the DESKTOP path (blocking loop)")
    try:
        _run_desktop()
    except KeyboardInterrupt:
        pass
    sys.exit(0)
else:
    diagnostics.log("taking the CALLBACK path - waiting for _ios_tick")
    diagnostics.log(f"_ios_tick defined at module scope: {'_ios_tick' in globals()}")
