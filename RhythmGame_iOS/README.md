# Rhythm — iOS port

A touch-first rewrite of the desktop rhythm game, packaged as an unsigned
`.ipa` you can sideload onto your own device.

---

## Read this first: what is and isn't verified

Being straight about the state of this, because it affects how you should
approach the first build.

**Verified on Windows.** Every module compiles and both test suites pass.
`tests/test_screens.py` boots the app headless, walks all eleven screens, and
drives real multitouch, scroll, pinch and tap gestures through the actual
event pipeline. `tests/test_data.py` covers the chart format, audio-format
handling and lane rules.

**Verified about the build path**, by reading pygame-ios's source rather than
trusting its README: it stages your project with `shutil.copytree()`, so the
`screens/` package is copied recursively (a top-level-only copy would have
produced an app that built cleanly and then crashed on launch). It renames
the entry script to `__main__.py` and places everything under
`<template>/pygame-ios/app/pygame-ios`. The workflow asserts those files
arrived before it spends time on `xcodebuild`.

The workflow's YAML structure, all 11 of its shell blocks, and both embedded
Python snippets were checked locally — the shell with `bash -n`, the Python
by running it against real and malformed payloads.

**Not verified.** `xcodebuild` itself has never run, and the app has never
run on a device — there's no Mac here to try it on. Expect to iterate on the
first attempt.

**Known risks, in rough order of likelihood:**

1. **pygame-ios is young.** Its author states plainly that it is "not well
   tested" and "shouldn't be considered production ready." It is nonetheless
   the only current route to pygame-ce on iOS — Briefcase explicitly does not
   support pygame on mobile, so the `briefcase package iOS` route is a dead
   end regardless of signing.
2. **Only pygame-ce 2.5.5 and 2.5.6 have templates.** Confirmed by reading
   `patches/pygame-ce.json` in the templates repo. The workflow defaults to
   `2.5.6` and now *fails fast with a clear message* if you ask for anything
   else, rather than dying later on an obscure download error.
3. **MP3 decoding might be unavailable.** SDL2_mixer only decodes MP3 if it
   was compiled with a decoder. Encouragingly, pygame-ios's own example game
   ships and plays a `.mp3`, which is good evidence the template's build has
   one. The app accepts `.ogg`, `.wav`, `.m4a` and `.flac` as well, so
   **convert to OGG if you hit silence**.
4. **Touch timestamps are frame-quantised.** pygame doesn't expose SDL's
   per-event timestamps, so a tap is stamped at the frame it's read on — up to
   ~16ms at 60Hz. It's a near-constant bias, which is what the calibration
   screen exists to subtract. Run it once before you care about your scores.

---

## Building the IPA

### Via GitHub Actions (no Mac needed)

The repository is already initialised and committed on `main`, with a
`.gitignore` that keeps it at ~1 MB (the song audio, the PyInstaller output
and an unrelated 42 MB toolkit in this folder are all excluded). All that's
left is to publish it.

1. Create an empty repo on GitHub — **don't** let it add a README or
   `.gitignore`, or the first push will conflict.

2. Point this repo at it and push:

```bash
git remote add origin https://github.com/<you>/<repo>.git && git push -u origin main
```

3. Open **Actions → Build unsigned iOS IPA → Run workflow**. Optionally
   override the pygame-ce version (only `2.5.5` and `2.5.6` are accepted).

4. When it finishes, download the `*-unsigned.ipa` artifact from the run
   summary.

The workflow has two jobs. `test` runs on Linux: it compiles every module and
runs both suites headless. `build` runs on macOS and only starts if `test`
passed — macOS runners bill at **10× the Linux rate** against the free monthly
allowance (2,000 minutes on private repos, unlimited on public), so a broken
commit costs about a minute instead of fifteen. Budget roughly 100–150 billed
minutes per successful build on a private repo. The workflow runs only
manually or on a `v*` tag, never on every push.

Before spending macOS time, `build` also asserts that the staged bundle
actually contains `__main__.py` and the `screens/` package — without that
check, a staging failure would produce an app that builds cleanly and then
crashes on launch.

### On a Mac, if you have access to one

```bash
cd RhythmGame_iOS && pip install pygame-ios && pygame_ios . main.py 2.5.6
```

Then open the generated `.xcodeproj` and run it on a connected device. This
is the better path for debugging, because you get the Xcode console — and
since `main.py` prints any startup traceback, that console is where a crash
will explain itself.

---

## Installing it on your iPhone

The IPA is unsigned, which is exactly what sideloading tools expect: they
re-sign it with your own Apple ID before installing.

**Sideloadly** (Windows or macOS) — install it, plug in your iPhone, drag the
IPA in, enter your Apple ID, click Start.

**AltStore** — the same idea with automatic background refresh, which matters
because of the limits below.

With a **free** Apple ID: the app expires after **7 days** and must be
reinstalled or refreshed, and you can have at most **3** sideloaded apps at
once. A paid Developer account ($99/yr) raises that to a year.

Enable Developer Mode on the device the first time: **Settings → Privacy &
Security → Developer Mode**.

---

## Getting songs onto the device

The build sets `UIFileSharingEnabled`, so the app's folder is visible in the
**Files** app under **On My iPhone → Rhythm**.

1. Copy an audio file into that folder (AirDrop, iCloud Drive, or a cable).
2. In the app: **Create → Import an .mp3**, pick the file, name it.
3. Recording starts immediately — tap along.

Charts you export land in the same folder as `.crchart` bundles, which
contain the chart and its audio together. Drop someone else's `.crchart` in
there and it appears under **Charts → Available to import**.

---

## What changed from the desktop version

### The playfield is a road

Four lanes recede toward a vanishing point, tiles narrow and slow as they
climb away from the hit line. The perspective strength is adjustable in
Settings (set it to 0 for flat columns).

The touch targets deliberately **don't** follow the perspective. The road is
full width at the hit line, so each lane's target is simply its quarter of
the screen — the entire column, top to bottom, the way Piano Tiles works.
Asking a fingertip to hit a shrinking trapezoid would be miserable.

### Charting is multitouch

Each finger is tracked by its own SDL finger id, so four fingers landing
together produce four notes at the same timestamp in four different lanes —
a real chord, not one note or a smear. Holding a pad past 150ms makes a hold
note, exactly as holding a key used to.

The recorder also stores the lane you actually tapped, which the old build
couldn't do.

### The editor runs vertically

Time flows top-to-bottom with the lanes as columns, because four 40px rows
in a tall portrait screen would have been unusable. Gestures:

| gesture | action |
|---|---|
| drag on empty lane space | scroll through the song |
| tap on empty lane space | add a note there |
| drag a note | move it in time and between lanes |
| drag a note's end cap | stretch it into a hold |
| long press a note | delete it |
| two-finger pinch | zoom the timeline |
| drag the waveform gutter | scrub |

### Charts now play the way they look

The desktop build assigned lanes **twice** — the editor laid them out
deterministically for readability, and then the game threw that away and
re-rolled them at random on every launch. A chart never played the way you
edited it, and never played the same way twice.

Lane assignment now happens once and is stored in the file. Charts saved by
the old build have no lane data, so they're laid out on load using the
editor's rules and then stay put.

### The UI is all pygame

customtkinter and tkinter are gone entirely — neither exists on iOS. Every
control was rebuilt with fingers in mind: nothing smaller than a 44pt target,
kinetic scrolling, and steppers instead of tiny numeric text fields.

One detail worth knowing: sliders decide by **direction**. Landing on a
slider and dragging up scrolls the list; only a sideways drag moves the knob.
Without that, a settings page full of sliders is impossible to scroll.

---

## Architecture

The single hard constraint is that **iOS owns the run loop**. pygame-ios
looks for a module-scope `_ios_tick` and drives it from
`SDL_iPhoneSetAnimationCallback`. A conventional `while True:
pygame.event.get()` loop never returns and the watchdog kills the app.

The desktop build had *three* such loops (game, recorder, calibration) plus
`tkinter.mainloop`. All of it is now one screen stack advanced one frame at a
time by `App.tick()`. "Start the game" is a push; "go back" is a pop.

```
main.py            _ios_tick entry point; desktop loop
app.py             screen stack, frame driver, toasts
paths.py           writable dirs (iOS sandbox vs desktop), audio formats
platform_compat.py display setup, scaling, safe-area insets
touch.py           multitouch -> pointer events, gestures
theme.py           palette, fonts, drawing helpers
ui.py              touch widget toolkit
dialogs.py         modal sheets
audio.py           mixer, synthesized hit sounds, transport, waveform
chart_model.py     chart load/save, lane layout
chart_io.py        .crchart bundles
road.py            perspective geometry
screens/           one file per screen
```

---

## Developing on a laptop

```bash
cd RhythmGame_iOS && python main.py
```

Opens a portrait window; the mouse stands in for a single finger and
`A`/`S`/`D`/`F` play the four lanes. Multitouch obviously can't be tested
this way — the test suite drives synthetic `FINGER*` events for that.

On desktop the app reads and writes `RhythmGame_iOS/rhythms/`, which is
**separate** from the original desktop game's `rhythms/` folder at the
project root. Copy songs across if you want the same library in both.

```bash
python tests/test_data.py      # chart format, audio formats, lane rules
python tests/test_screens.py   # boots every screen, drives real gestures
```

---

## If it fails

### "Failed to Sign …/libsurface.dylib.p/surface.c.o", or ldid asserts

```
ldid.cpp(869): _assert(): filetype == MH_EXECUTE || MH_DYLIB || MH_DYLINKER || MH_BUNDLE
```

**Fixed in the build — rebuild and use the new IPA.**

The template's pygame-ce build shipped meson's intermediate output inside the
bundle: directories named `*.dylib.p` / `*.a.p` full of `.c.o` object files,
plus `.a` static archives. Nothing loads them at runtime, but every signing
tool walks the bundle and signs each Mach-O file it finds. An object file is
`MH_OBJECT`, which is not one of the four types ldid accepts, so it asserts
and the install fails. The workflow now deletes them before packaging and
fails the build if any survive.

### Black screen on launch

Also addressed. Two causes were possible and both are handled:

- If iOS wasn't detected, `main.py` took the desktop path and entered a
  blocking loop, starving the run loop iOS owns. Detection now checks five
  independent signals, and the blocking loop only runs on an explicit
  desktop allowlist.
- A startup exception used to be printed to a console you can't see. It is
  now **drawn on the screen**, so you can read (or photograph) the traceback
  on the device.

If you now see a screen reading **"Starting…"** that never changes, the frame
callback isn't firing — that's a different problem from a crash, and the
splash exists to tell the two apart.

### Other

- **No `.xcodeproj` generated** — the pygame-ce version has no template. Only
  `2.5.5` and `2.5.6` exist; the workflow rejects anything else up front.
- **Silence but the game runs** — MP3 decoding is missing from this
  SDL2_mixer build. Convert to OGG; the app already accepts it.
- **Notes feel consistently early or late** — Settings → Calibrate. Use the
  headphones you actually play with; Bluetooth adds a great deal of latency.
