"""
Entry point.

iOS owns the run loop. pygame-ios looks for a module-scope `_ios_tick` and
wires it to SDL_iPhoneSetAnimationCallback, calling it once per display
refresh; a conventional `while True: pygame.event.get()` loop would never
return control and the watchdog would kill the app. So the loop lives here
only for desktop, and on device every frame arrives as a call to _ios_tick.

Keep the name and module-scope placement of _ios_tick as they are — the
template detects it by name.
"""

import sys
import traceback

import paths

_app = None
_failed = False


def _boot():
    """Create the app and show the main menu."""
    from app import App
    from screens.menu import MainMenu

    instance = App()
    instance.set_root(MainMenu(instance))
    return instance


def _ios_tick():
    """One frame. Called by the iOS run loop; must always return promptly."""
    global _app, _failed

    if _failed:
        return
    try:
        if _app is None:
            _app = _boot()
        _app.tick()
    except Exception:
        # A traceback on device is otherwise invisible. Print it (it reaches
        # the Xcode console) and stop ticking rather than raising every frame.
        _failed = True
        traceback.print_exc()


def _run_desktop():
    """Blocking loop, for developing on a laptop."""
    app = _boot()
    try:
        while app.running:
            app.tick()
    finally:
        app.shutdown()


paths.ensure_dirs()

if not paths.IS_IOS and __name__ == "__main__":
    try:
        _run_desktop()
    except KeyboardInterrupt:
        pass
    sys.exit(0)
