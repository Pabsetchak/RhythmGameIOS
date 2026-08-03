"""
Filesystem layout.

On desktop the app can read and write next to its own source. On iOS it
cannot: the application bundle is mounted read-only, so anything the app
needs to modify (charts, settings, synthesized hit sounds) has to live in
the app's Documents directory instead.

Everything else in the codebase asks this module for a path rather than
building one from a relative string, so the same source runs unchanged on
both platforms.
"""

import os
import platform
import shutil
import sys


def _detect_ios():
    """
    Are we running on an iOS device?

    Getting this wrong is not cosmetic. If it returns False on device, main.py
    takes the desktop path and enters a blocking `while running:` loop, which
    starves the run loop iOS owns — the app shows a black screen and is then
    killed by the watchdog. So this checks several independent signals rather
    than trusting any single one.

    Python 3.13 reports sys.platform == "ios" (PEP 730), but the embedded
    interpreter in an app template is not guaranteed to be built that way.
    """
    if sys.platform == "ios":
        return True
    if getattr(sys, "_ios", False):
        return True
    try:
        if platform.system() in ("iOS", "iPadOS"):
            return True
    except Exception:
        pass
    try:
        machine = os.uname().machine
        if machine.startswith(("iPhone", "iPad", "iPod")):
            return True
    except Exception:
        pass
    # Both the normal install location and the live-container one put the
    # bundle under a /Containers/.../*.app path that cannot occur on macOS.
    here = os.path.abspath(__file__)
    if "/Containers/" in here and ".app/" in here:
        return True
    # UIKit sandboxes always have this; macOS never does.
    if os.path.isdir("/var/mobile/Containers") or os.path.isdir("/private/var/mobile"):
        return True
    return False


IS_IOS = _detect_ios()

# Where the source and any bundled starter content live. Read-only on iOS.
BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))


def _writable_base():
    """The directory the app is allowed to write into."""
    if IS_IOS:
        # ~/Documents inside the app's sandbox. Visible in the Files app when
        # UIFileSharingEnabled is set, so charts can be moved on and off the
        # device without a desktop.
        return os.path.expanduser("~/Documents")
    # On desktop, keep the original layout: everything sits beside the source.
    return BUNDLE_DIR


DATA_DIR = _writable_base()
RHYTHMS_DIR = os.path.join(DATA_DIR, "rhythms")
ASSETS_DIR = os.path.join(DATA_DIR, "assets")
SETTINGS_PATH = os.path.join(RHYTHMS_DIR, "SETTINGS.json")

# Starter content shipped inside the bundle, copied out on first launch.
_BUNDLED_RHYTHMS = os.path.join(BUNDLE_DIR, "rhythms")
_BUNDLED_ASSETS = os.path.join(BUNDLE_DIR, "assets")


# Audio formats accepted, in preference order.
#
# Not just .mp3: SDL2_mixer only decodes MP3 when it was compiled with a
# decoder, and whether the iOS template's build has one is not documented.
# OGG and WAV support are effectively always present, so accepting them
# gives a working fallback if MP3 turns out to be unavailable on device.
AUDIO_EXTS = (".ogg", ".mp3", ".wav", ".m4a", ".flac")


def song_audio(name):
    """Path to a song's audio, whichever supported format it is in."""
    for ext in AUDIO_EXTS:
        candidate = os.path.join(RHYTHMS_DIR, f"{name}{ext}")
        if os.path.exists(candidate):
            return candidate
    # Nothing on disk yet: hand back the conventional name so callers have
    # something to report or write to.
    return os.path.join(RHYTHMS_DIR, f"{name}.mp3")


def song_mp3(name):
    """Deprecated alias kept for call sites that only write."""
    return song_audio(name)


def song_json(name):
    return os.path.join(RHYTHMS_DIR, f"{name}.json")


def list_songs():
    """Names of every song that has audio available, in any accepted format."""
    try:
        names = set()
        for f in os.listdir(RHYTHMS_DIR):
            stem, ext = os.path.splitext(f)
            if ext.lower() in AUDIO_EXTS:
                names.add(stem)
        return sorted(names)
    except OSError:
        return []


def list_charts():
    """Names of every song that has a saved chart."""
    try:
        return sorted(f[:-5] for f in os.listdir(RHYTHMS_DIR)
                      if f.lower().endswith(".json") and f != "SETTINGS.json")
    except OSError:
        return []


def _seed_dir(src, dest):
    """Copy bundled files into the writable tree, never overwriting."""
    if not os.path.isdir(src) or os.path.abspath(src) == os.path.abspath(dest):
        return
    for entry in os.listdir(src):
        s = os.path.join(src, entry)
        d = os.path.join(dest, entry)
        if os.path.isdir(s):
            if not os.path.exists(d):
                try:
                    shutil.copytree(s, d)
                except OSError:
                    pass
        elif not os.path.exists(d):
            try:
                shutil.copy2(s, d)
            except OSError:
                pass


def ensure_dirs():
    """
    Create the writable tree and seed it from the bundle. Safe to call on
    every launch — existing user files are never replaced.
    """
    for d in (DATA_DIR, RHYTHMS_DIR, ASSETS_DIR):
        os.makedirs(d, exist_ok=True)
    if IS_IOS:
        _seed_dir(_BUNDLED_RHYTHMS, RHYTHMS_DIR)
        _seed_dir(_BUNDLED_ASSETS, ASSETS_DIR)
