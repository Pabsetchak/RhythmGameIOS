"""
The .crchart bundle format: a zip holding a chart's JSON, its audio, and a
small manifest. The dedicated extension keeps it from being mistaken for a
plain .json or .mp3.

On iOS these land in the app's Documents directory, which the Files app can
browse when UIFileSharingEnabled and LSSupportsOpeningDocumentsInPlace are
set — that is how charts move on and off the device without a desktop.
"""

import json
import os
import zipfile

import paths

CHART_EXT = ".crchart"
MANIFEST_NAME = "chart.manifest"


def list_importable():
    """Any .crchart sitting in the data directory, ready to import."""
    try:
        return sorted(f for f in os.listdir(paths.DATA_DIR)
                      if f.lower().endswith(CHART_EXT))
    except OSError:
        return []


def export_chart(song_name, dest_path=None):
    """
    Bundle a chart and its audio into one .crchart file. With no destination
    it is written to the data directory, where the Files app can reach it.

    Returns (ok, message).
    """
    json_path = paths.song_json(song_name)
    audio_path = paths.song_audio(song_name)

    if not os.path.exists(json_path):
        return False, f"No chart data found for '{song_name}'."
    if not os.path.exists(audio_path):
        return False, f"No audio found for '{song_name}'."

    if dest_path is None:
        dest_path = os.path.join(paths.DATA_DIR, f"{song_name}{CHART_EXT}")
    elif not dest_path.lower().endswith(CHART_EXT):
        dest_path += CHART_EXT

    audio_ext = os.path.splitext(audio_path)[1].lower()
    manifest = {"format": "crchart", "version": 1, "song_name": song_name,
                "audio_ext": audio_ext}

    try:
        with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
            z.write(json_path, f"{song_name}.json")
            z.write(audio_path, f"{song_name}{audio_ext}")
    except (OSError, zipfile.BadZipFile) as e:
        return False, f"Export failed: {e}"

    return True, f"Exported {os.path.basename(dest_path)}"


def import_chart(src_path, overwrite=False):
    """
    Extract a .crchart into the rhythms folder.

    Returns (ok, song_name) on success or (False, message) on failure.
    """
    if not os.path.isabs(src_path):
        src_path = os.path.join(paths.DATA_DIR, src_path)

    if not zipfile.is_zipfile(src_path):
        return False, "That file is not a valid chart file."

    os.makedirs(paths.RHYTHMS_DIR, exist_ok=True)

    try:
        with zipfile.ZipFile(src_path, "r") as z:
            names = z.namelist()

            song_name = None
            if MANIFEST_NAME in names:
                try:
                    song_name = json.loads(z.read(MANIFEST_NAME)).get("song_name")
                except (json.JSONDecodeError, KeyError):
                    song_name = None

            json_member = next((n for n in names if n.lower().endswith(".json")), None)
            audio_member = next(
                (n for n in names
                 if os.path.splitext(n)[1].lower() in paths.AUDIO_EXTS), None)

            if not json_member or not audio_member:
                return False, "Chart file is missing its data or audio."

            if not song_name:
                song_name = os.path.splitext(os.path.basename(json_member))[0]

            audio_ext = os.path.splitext(audio_member)[1].lower()
            dest_json = paths.song_json(song_name)
            dest_audio = os.path.join(paths.RHYTHMS_DIR, f"{song_name}{audio_ext}")

            already_here = (os.path.exists(dest_json)
                            or song_name in paths.list_songs())
            if not overwrite and already_here:
                return False, f"A chart named '{song_name}' already exists."

            with z.open(json_member) as src, open(dest_json, "wb") as out:
                out.write(src.read())
            with z.open(audio_member) as src, open(dest_audio, "wb") as out:
                out.write(src.read())
    except (OSError, zipfile.BadZipFile) as e:
        return False, f"Import failed: {e}"

    return True, song_name


def list_importable_audio():
    """
    Loose audio files dropped into the data directory. On iOS this is how a
    song gets in: copy it into the app's folder with the Files app, then
    import it here.
    """
    try:
        return sorted(f for f in os.listdir(paths.DATA_DIR)
                      if os.path.splitext(f)[1].lower() in paths.AUDIO_EXTS)
    except OSError:
        return []


def import_audio(filename, song_name=None, overwrite=False):
    """Move a loose audio file from the data directory into rhythms/."""
    src = filename if os.path.isabs(filename) else os.path.join(paths.DATA_DIR, filename)
    if not os.path.exists(src):
        return False, "That file is no longer there."

    song_name = (song_name or os.path.splitext(os.path.basename(src))[0]).strip()
    if not song_name:
        return False, "Give the song a name."

    ext = os.path.splitext(src)[1].lower()
    if ext not in paths.AUDIO_EXTS:
        return False, f"{ext or 'That file'} is not a supported audio format."

    dest = os.path.join(paths.RHYTHMS_DIR, f"{song_name}{ext}")
    if os.path.abspath(src) == os.path.abspath(dest):
        return True, song_name
    if not overwrite and song_name in paths.list_songs():
        return False, f"A song named '{song_name}' already exists."

    try:
        os.makedirs(paths.RHYTHMS_DIR, exist_ok=True)
        with open(src, "rb") as fin, open(dest, "wb") as fout:
            fout.write(fin.read())
    except OSError as e:
        return False, f"Import failed: {e}"

    return True, song_name
