"""
Entry point.

iOS owns the run loop. pygame-ios looks for a module-scope `_ios_tick` and
wires it to SDL_iPhoneSetAnimationCallback, calling it once per display
refresh; a conventional `while True: pygame.event.get()` loop would never
return control and the watchdog would kill the app. So the loop lives here
only for desktop, and on device every frame arrives as a call to _ios_tick.

Keep the name and module-scope placement of _ios_tick as they are — the
template detects it by name.

Anything that goes wrong is drawn on the screen rather than only printed.
On a sideloaded build there is no console to read, and a bare exception is
indistinguishable from a hang: both are a black screen.
"""

import sys
import traceback

import paths

# Platforms where a blocking loop is the correct thing to do. Anything not on
# this list gets the callback-driven path, so a failure to recognise iOS can
# never result in the run loop being starved.
_DESKTOP_PLATFORMS = ("win32", "linux", "linux2", "darwin", "cygwin")

_app = None
_error_text = None


# ---------------------------------------------------------------------------- #
# On-device diagnostics
# ---------------------------------------------------------------------------- #
def _screen():
    """A surface to draw on, creating one if the app never got that far."""
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
        # Diagnostics must never become the failure.
        pass


def _draw_splash():
    """
    Shown at import, replaced by the first real frame.

    If this stays on screen it means _ios_tick is never being called, which
    is a very different problem from the app crashing — worth being able to
    tell apart without a debugger.
    """
    _draw_message(
        "Starting…",
        f"platform: {sys.platform}\n"
        f"detected iOS: {paths.IS_IOS}\n"
        f"data dir: {paths.DATA_DIR}\n\n"
        "If this screen stays up, the frame callback is not firing.",
        background=(10, 10, 20), color=(150, 150, 180))


# ---------------------------------------------------------------------------- #
# Boot
# ---------------------------------------------------------------------------- #
def _boot():
    from app import App
    from screens.menu import MainMenu

    instance = App()
    instance.set_root(MainMenu(instance))
    return instance


def _ios_tick():
    """One frame. Called by the iOS run loop; must always return promptly."""
    global _app, _error_text

    if _error_text is not None:
        # Keep the failure on screen instead of reverting to black.
        _draw_message("Crashed on startup", _error_text)
        return

    try:
        if _app is None:
            _app = _boot()
        _app.tick()
    except Exception:
        _error_text = traceback.format_exc()
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


paths.ensure_dirs()

if paths.IS_IOS:
    _draw_splash()
elif __name__ == "__main__" and sys.platform in _DESKTOP_PLATFORMS:
    try:
        _run_desktop()
    except KeyboardInterrupt:
        pass
    sys.exit(0)
