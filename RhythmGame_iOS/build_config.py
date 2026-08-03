"""
Build target, decided when the app is packaged rather than guessed at runtime.

Detecting iOS at startup is a liability: if it guesses wrong on a device the
app takes the desktop path, enters a blocking loop, starves the run loop iOS
owns, and shows a black screen with nothing to explain it. The CI workflow
therefore overwrites TARGET with "ios" before it stages the app, so the
device build never runs the detection at all.

  "ios"      -> definitely a device build. No detection, no desktop path.
  "desktop"  -> definitely a laptop. Used by the test suites.
  None       -> fall back to sniffing the environment (paths._detect_ios).

The checked-in value is None so a plain `python main.py` still works and the
tests behave normally; only the packaged build has it forced.
"""

TARGET = None
