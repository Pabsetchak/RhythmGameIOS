"""Data-layer tests: audio format handling, chart round-trip, lane rules."""
import os
import shutil
import struct
import sys
import tempfile
import traceback
import wave

# Point the app's writable tree at a throwaway directory before importing it.
SANDBOX = tempfile.mkdtemp(prefix="rg_data_")
os.environ["HOME"] = SANDBOX

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRC)

import paths  # noqa: E402

# Redirect the module's directories at the sandbox.
paths.DATA_DIR = SANDBOX
paths.RHYTHMS_DIR = os.path.join(SANDBOX, "rhythms")
paths.ASSETS_DIR = os.path.join(SANDBOX, "assets")
paths.SETTINGS_PATH = os.path.join(paths.RHYTHMS_DIR, "SETTINGS.json")
paths.ensure_dirs()

import chart_io    # noqa: E402
import chart_model  # noqa: E402

results = []


def check(name, fn):
    try:
        fn()
        results.append((name, None))
        print(f"  ok   {name}")
    except Exception as e:
        results.append((name, traceback.format_exc()))
        print(f"  FAIL {name}: {type(e).__name__}: {e}")


def make_wav(path, seconds=2.0, rate=8000):
    """A real, decodable WAV so format handling is tested for real."""
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", 0) for _ in range(int(rate * seconds))))


# ---------------------------------------------------------------------------- #
def test_audio_formats():
    make_wav(os.path.join(paths.RHYTHMS_DIR, "wavsong.wav"))
    songs = paths.list_songs()
    assert "wavsong" in songs, f"wav not discovered: {songs}"
    found = paths.song_audio("wavsong")
    assert found.endswith(".wav"), found
    # A song with no audio at all still yields a usable conventional path.
    assert paths.song_audio("nothing").endswith(".mp3")


def test_preference_order():
    """.ogg wins over .mp3 when both are present."""
    make_wav(os.path.join(paths.RHYTHMS_DIR, "dual.mp3"))
    make_wav(os.path.join(paths.RHYTHMS_DIR, "dual.ogg"))
    assert paths.song_audio("dual").endswith(".ogg"), paths.song_audio("dual")
    assert paths.list_songs().count("dual") == 1, "duplicate song entry"


def test_lane_preservation():
    """
    The whole point of moving lane assignment into the file: a chart must
    play back in exactly the lanes it was saved with.
    """
    notes = [chart_model.make_note(i * 0.5, lane=(3 - i % 4)) for i in range(8)]
    original = [n["lane"] for n in notes]
    ok, msg = chart_model.save_chart("wavsong", notes, 10.0)
    assert ok, msg

    loaded, duration = chart_model.load_chart("wavsong")
    assert abs(duration - 10.0) < 1e-6, duration
    assert [n["lane"] for n in loaded] == original, \
        f"lanes changed on round-trip: {original} -> {[n['lane'] for n in loaded]}"


def test_legacy_chart_gets_lanes():
    """A chart with no lane field (old format) is laid out on load."""
    import json
    legacy = {
        "duration": 5.0,
        "note_events": [
            {"type": "quickPress", "key": "a", "timestamp": 0.1},
            {"type": "quickPress", "key": "a", "timestamp": 0.2},
            {"type": "quickPress", "key": "a", "timestamp": 0.3},
        ],
    }
    make_wav(os.path.join(paths.RHYTHMS_DIR, "legacy.wav"))
    with open(paths.song_json("legacy"), "w") as f:
        json.dump(legacy, f)

    loaded, _ = chart_model.load_chart("legacy")
    lanes = [n["lane"] for n in loaded]
    assert len(set(lanes)) > 1, f"close notes were not spread across lanes: {lanes}"


def test_dedupe():
    notes = [
        chart_model.make_note(1.000, lane=0),
        chart_model.make_note(1.005, lane=0),      # same lane, same instant
        chart_model.make_note(1.000, lane=1),      # a genuine chord partner
    ]
    out = chart_model.dedupe(notes)
    assert len(out) == 2, f"expected 2 notes after dedupe, got {len(out)}"
    assert sorted(n["lane"] for n in out) == [0, 1]


def test_dedupe_keeps_longer_hold():
    notes = [
        chart_model.make_note(2.0, lane=2, duration=0.0),
        chart_model.make_note(2.004, lane=2, duration=0.5),
    ]
    out = chart_model.dedupe(notes)
    assert len(out) == 1
    assert out[0]["duration"] == 0.5, out[0]


def test_resolve_holds():
    """A tap must not start inside a hold occupying the same lane."""
    notes = [
        chart_model.make_note(0.0, lane=0, duration=1.0),
        chart_model.make_note(0.5, lane=0),
    ]
    chart_model.resolve_holds(notes)
    assert notes[1]["lane"] != 0, "tap left buried inside the hold"


def test_crchart_roundtrip():
    make_wav(os.path.join(paths.RHYTHMS_DIR, "bundled.wav"))
    chart_model.save_chart("bundled", [chart_model.make_note(0.5, lane=2)], 4.0)

    ok, msg = chart_io.export_chart("bundled")
    assert ok, msg
    bundle = os.path.join(paths.DATA_DIR, "bundled.crchart")
    assert os.path.exists(bundle), "bundle not written"

    import zipfile
    with zipfile.ZipFile(bundle) as z:
        names = z.namelist()
    assert "bundled.wav" in names, f"audio extension not preserved: {names}"

    # Importing over an existing song is refused...
    ok, message = chart_io.import_chart("bundled.crchart")
    assert not ok and "already exists" in message, message
    # ...unless explicitly overwritten.
    ok, name = chart_io.import_chart("bundled.crchart", overwrite=True)
    assert ok, name
    assert name == "bundled", name

    # And the chart survives the trip with its lanes intact.
    loaded, _ = chart_model.load_chart("bundled")
    assert len(loaded) == 1 and loaded[0]["lane"] == 2, loaded


def test_import_rejects_unknown_format():
    junk = os.path.join(paths.DATA_DIR, "notes.txt")
    with open(junk, "w") as f:
        f.write("hello")
    ok, message = chart_io.import_audio("notes.txt")
    assert not ok and "supported" in message, message


def test_delete_removes_all_formats():
    make_wav(os.path.join(paths.RHYTHMS_DIR, "doomed.wav"))
    make_wav(os.path.join(paths.RHYTHMS_DIR, "doomed.ogg"))
    chart_model.save_chart("doomed", [chart_model.make_note(0.0)], 1.0)
    ok, message = chart_model.delete_song("doomed")
    assert ok, message
    assert "doomed" not in paths.list_songs(), "audio survived deletion"
    assert not os.path.exists(paths.song_json("doomed")), "chart survived deletion"


def main():
    print(f"sandbox: {SANDBOX}")
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            check(name[5:].replace("_", " "), fn)

    failures = [(n, tb) for n, tb in results if tb]
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        for n, tb in failures:
            print(f"\n--- {n} ---\n{tb}")
        return 1
    print(f"all {len(results)} checks passed")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(SANDBOX, ignore_errors=True)
    sys.exit(code)
