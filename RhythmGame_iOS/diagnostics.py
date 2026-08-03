"""
Boot logging to a file.

A sideloaded build has no console, and if the screen stays black then
on-screen diagnostics can't help either. So the very first thing the app
does is write a log into its Documents directory, which you can read in the
Files app under "On My iPhone -> Rhythm -> boot_log.txt".

That gives a diagnostic ladder that pins down where things stopped:

  no file at all                 __main__.py never ran
  "import complete", no "tick 1" the frame callback is never called
  "tick 1" then a traceback      it crashed; the traceback says why
  "surface WxH" and frames       it is running and the problem is elsewhere

Nothing in here may raise. A diagnostic that breaks the app it is meant to
diagnose is worse than none.
"""

import os
import sys
import time
import traceback

LOG_NAME = "boot_log.txt"

_path = None
_start = time.time()
_frames = 0


def _candidates():
    """
    Places to try writing, most useful first.

    paths.DATA_DIR is the right answer on both platforms: on iOS it is the
    sandbox's ~/Documents, which is exactly what the Files app shows; on
    desktop it is the source folder, so a dev run doesn't drop a log into
    the user's real Documents.
    """
    out = []
    try:
        import paths
        out.append(os.path.join(paths.DATA_DIR, LOG_NAME))
    except Exception:
        pass
    try:
        out.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), LOG_NAME))
    except Exception:
        pass
    try:
        out.append(os.path.join(os.path.expanduser("~/Documents"), LOG_NAME))
    except Exception:
        pass
    try:
        import tempfile
        out.append(os.path.join(tempfile.gettempdir(), LOG_NAME))
    except Exception:
        pass
    return out


def _resolve():
    global _path
    if _path is not None:
        return _path
    for candidate in _candidates():
        try:
            os.makedirs(os.path.dirname(candidate), exist_ok=True)
            with open(candidate, "a"):
                pass
            _path = candidate
            return _path
        except Exception:
            continue
    _path = ""       # give up, but only try once
    return _path


def log(message):
    """Append one timestamped line. Never raises."""
    try:
        path = _resolve()
        if not path:
            return
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{time.time() - _start:7.3f}s] {message}\n")
    except Exception:
        pass


def exception(label):
    """Append a full traceback under a heading. Never raises."""
    try:
        log(f"!! {label}")
        path = _resolve()
        if not path:
            return
        with open(path, "a", encoding="utf-8") as f:
            f.write(traceback.format_exc())
            f.write("\n")
    except Exception:
        pass


def frame():
    """Record the first few frames, then fall silent."""
    global _frames
    _frames += 1
    if _frames <= 3:
        log(f"frame {_frames} drawn")
    elif _frames == 60:
        log("60 frames drawn - the app is running normally")


def begin(extra=None):
    """Truncate the log and write everything known about the environment."""
    global _path, _frames
    _path = None
    _frames = 0
    try:
        path = _resolve()
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write("Rhythm boot log\n")
                f.write(f"written {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 52 + "\n")
    except Exception:
        pass

    log(f"log file: {_path}")
    log(f"sys.platform   = {sys.platform!r}")
    log(f"sys.version    = {sys.version.split()[0]}")
    log(f"sys.executable = {sys.executable!r}")
    log(f"__file__       = {os.path.abspath(__file__)!r}")
    log(f"cwd            = {os.getcwd()!r}")
    try:
        import platform
        log(f"platform.system() = {platform.system()!r}")
    except Exception:
        log("platform.system() unavailable")
    try:
        u = os.uname()
        log(f"uname          = {u.sysname!r} {u.machine!r} {u.release!r}")
    except Exception:
        log("uname unavailable")
    log(f"HOME           = {os.environ.get('HOME')!r}")
    if extra:
        for key, value in extra.items():
            log(f"{key} = {value}")
