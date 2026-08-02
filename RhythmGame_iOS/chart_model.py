"""
Chart data: loading, saving, and lane layout.

The desktop build assigned lanes in two unrelated places — the game picked
them at random on every launch, while the editor laid them out
deterministically — so a chart never played the way it looked in the editor.
Lane assignment now lives here and the lane is stored in the file, which
means what you edit is what you play.

Charts written by the old build have no "lane" field. Those are laid out on
load using the editor's readability rules, so they open and play correctly.
"""

import json
import os
from datetime import datetime

import paths

NUM_LANES = 4
LANE_KEYS = ["a", "s", "d", "f"]

# Durations at or above this are holds rather than taps.
HOLD_MIN = 0.06

# Notes closer together than this are "close" and get spread across lanes.
SPREAD_WINDOW = 0.35


def make_note(timestamp, lane=0, duration=0.0):
    is_hold = duration >= HOLD_MIN
    return {
        "type": "hold" if is_hold else "quickPress",
        "key": LANE_KEYS[lane % NUM_LANES],
        "timestamp": round(max(0.0, timestamp), 4),
        "duration": round(duration, 4) if is_hold else 0.0,
        "lane": lane % NUM_LANES,
    }


# ---------------------------------------------------------------------------- #
# Lane layout
# ---------------------------------------------------------------------------- #
def assign_lanes(notes):
    """
    Lay notes out for readability: notes close together in time are spread
    across the lanes (least-recently-used first), a lane busy with a hold is
    never reused, and well-separated notes fall back to the leftmost free
    lane so sparse sections stay tidy.
    """
    last_used = [-1e9] * NUM_LANES
    hold_until = [0.0] * NUM_LANES
    prev_t = None

    for n in sorted(notes, key=lambda x: x["timestamp"]):
        t = n["timestamp"]
        free = [l for l in range(NUM_LANES) if hold_until[l] <= t + 1e-6]
        cands = free if free else list(range(NUM_LANES))

        if prev_t is None or (t - prev_t) > SPREAD_WINDOW:
            lane = min(cands)
        else:
            lane = max(cands, key=lambda l: t - last_used[l])

        n["lane"] = lane
        n["key"] = LANE_KEYS[lane]
        end = t + max(n.get("duration", 0.0), 0.0)
        last_used[lane] = end
        if n["type"] == "hold" and n.get("duration", 0.0) > 0:
            hold_until[lane] = end
        prev_t = t
    return notes


def hold_covering(notes, lane, t, exclude=None):
    """A hold in `lane` whose span covers time `t`, or None."""
    for m in notes:
        if m is exclude or m["type"] != "hold" or m.get("duration", 0.0) <= 0:
            continue
        if m["lane"] == lane and m["timestamp"] - 1e-6 <= t < m["timestamp"] + m["duration"]:
            return m
    return None


def resolve_holds(notes):
    """
    Ensure no note starts inside another note's hold in the same lane. Holds
    are processed earliest-first so they act as anchors and only the later,
    conflicting notes move.
    """
    for n in sorted(notes, key=lambda x: x["timestamp"]):
        if hold_covering(notes, n["lane"], n["timestamp"], exclude=n):
            free = [l for l in range(NUM_LANES)
                    if not hold_covering(notes, l, n["timestamp"], exclude=n)]
            if free:
                n["lane"] = min(free, key=lambda l: abs(l - n["lane"]))
                n["key"] = LANE_KEYS[n["lane"]]
    return notes


def dedupe(notes, eps=0.012):
    """
    Drop notes that land on the same lane at effectively the same moment.
    Tapping with several fingers occasionally double-registers a lane, and a
    stacked pair is unhittable.
    """
    out = []
    for n in sorted(notes, key=lambda x: x["timestamp"]):
        clash = next((m for m in out
                      if m["lane"] == n["lane"]
                      and abs(m["timestamp"] - n["timestamp"]) < eps), None)
        if clash is None:
            out.append(n)
        elif n.get("duration", 0.0) > clash.get("duration", 0.0):
            # Keep whichever is the longer hold.
            out[out.index(clash)] = n
    return out


# ---------------------------------------------------------------------------- #
# Load / save
# ---------------------------------------------------------------------------- #
def load_chart(song_name, fallback_duration=0.0):
    """
    Read a chart. Returns (notes, duration). Missing or corrupt files yield
    an empty chart rather than raising, so the editor can still open a song
    that has audio but no chart yet.
    """
    path = paths.song_json(song_name)
    notes = []
    duration = fallback_duration
    needs_layout = False

    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Could not load chart '{song_name}': {e}")
            data = {}

        if data.get("duration"):
            try:
                duration = float(data["duration"]) or duration
            except (TypeError, ValueError):
                pass

        for e in data.get("note_events", []):
            try:
                t = float(e.get("timestamp", 0.0))
            except (TypeError, ValueError):
                continue
            is_hold = e.get("type") == "hold"
            try:
                dur = float(e.get("duration", 0.0)) if is_hold else 0.0
            except (TypeError, ValueError):
                dur = 0.0
            lane = e.get("lane")
            if lane is None:
                needs_layout = True
                lane = 0
            notes.append({
                "type": "hold" if is_hold and dur > 0 else "quickPress",
                "key": e.get("key", "a"),
                "timestamp": t,
                "duration": dur,
                "lane": int(lane) % NUM_LANES,
            })

    if not duration:
        end = max((n["timestamp"] + n["duration"] for n in notes), default=30.0)
        duration = end + 5.0

    # Only re-lay-out charts from the old format; a chart that already
    # carries lanes is left exactly as its author arranged it.
    if needs_layout:
        assign_lanes(notes)
    resolve_holds(notes)
    return notes, duration


def export_events(notes):
    """Notes in save order, trimmed to the on-disk shape."""
    out = []
    for n in sorted(notes, key=lambda x: x["timestamp"]):
        base = {
            "type": n["type"],
            "key": n.get("key", "a"),
            "lane": int(n.get("lane", 0)) % NUM_LANES,
            "timestamp": round(n["timestamp"], 4),
        }
        if n["type"] == "hold" and n.get("duration", 0.0) > 0:
            base["duration"] = round(n["duration"], 4)
        out.append(base)
    return out


def save_chart(song_name, notes, duration):
    """
    Write a chart beside its audio. Returns (ok, message).
    """
    os.makedirs(paths.RHYTHMS_DIR, exist_ok=True)
    audio_name = os.path.basename(paths.song_audio(song_name))
    data = {
        "recorded_at": datetime.now().isoformat(),
        "audio_file": f"rhythms/{audio_name}",
        "duration": round(float(duration), 4),
        "note_events": export_events(notes),
    }
    try:
        with open(paths.song_json(song_name), "w") as f:
            json.dump(data, f, indent=4)
    except OSError as e:
        return False, f"Save failed: {e}"
    return True, f"Saved {len(notes)} notes to {song_name}."


def delete_song(song_name):
    """Remove a song's chart and its audio in whatever format. (ok, message)."""
    targets = [paths.song_json(song_name)]
    targets += [os.path.join(paths.RHYTHMS_DIR, f"{song_name}{ext}")
                for ext in paths.AUDIO_EXTS]

    removed = False
    for path in targets:
        if os.path.exists(path):
            try:
                os.remove(path)
                removed = True
            except OSError as e:
                return False, f"Could not delete: {e}"
    if not removed:
        return False, "Nothing to delete."
    return True, f"Deleted '{song_name}'."
