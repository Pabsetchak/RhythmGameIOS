import os
import json
import zipfile

# Custom rhythm-chart file type. It's a zip archive under the hood, holding the
# chart JSON, its audio, and a small manifest — but the dedicated extension
# keeps it from being confused with a plain .json or .mp3.
CHART_EXT = ".crchart"
MANIFEST_NAME = "chart.manifest"


def export_chart(song_name, dest_path, rhythms_dir="rhythms"):
    """
    Bundle a chart (JSON + MP3) into a single .crchart file.

    Returns (True, message) on success or (False, message) on failure.
    """
    json_path = os.path.join(rhythms_dir, f"{song_name}.json")
    audio_path = os.path.join(rhythms_dir, f"{song_name}.mp3")

    if not os.path.exists(json_path):
        return False, f"No chart data found for '{song_name}'."
    if not os.path.exists(audio_path):
        return False, f"No audio found for '{song_name}'."

    if not dest_path.lower().endswith(CHART_EXT):
        dest_path += CHART_EXT

    manifest = {
        "format": "crchart",
        "version": 1,
        "song_name": song_name,
    }

    try:
        with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
            z.write(json_path, f"{song_name}.json")
            z.write(audio_path, f"{song_name}.mp3")
    except Exception as e:
        return False, f"Export failed: {e}"

    return True, f"Exported to {dest_path}"


def import_chart(src_path, rhythms_dir="rhythms", overwrite=False):
    """
    Extract a .crchart file into the rhythms folder.

    Returns (True, song_name) on success or (False, message) on failure.
    """
    if not zipfile.is_zipfile(src_path):
        return False, "That file is not a valid chart file."

    os.makedirs(rhythms_dir, exist_ok=True)

    try:
        with zipfile.ZipFile(src_path, "r") as z:
            names = z.namelist()

            # Prefer the song name recorded in the manifest; otherwise infer it
            # from whichever .json the archive contains.
            song_name = None
            if MANIFEST_NAME in names:
                try:
                    manifest = json.loads(z.read(MANIFEST_NAME))
                    song_name = manifest.get("song_name")
                except Exception:
                    song_name = None

            json_member = next((n for n in names if n.lower().endswith(".json")), None)
            audio_member = next((n for n in names if n.lower().endswith(".mp3")), None)

            if not json_member or not audio_member:
                return False, "Chart file is missing its data or audio."

            if not song_name:
                song_name = os.path.splitext(os.path.basename(json_member))[0]

            dest_json = os.path.join(rhythms_dir, f"{song_name}.json")
            dest_audio = os.path.join(rhythms_dir, f"{song_name}.mp3")

            if not overwrite and (os.path.exists(dest_json) or os.path.exists(dest_audio)):
                return False, f"A chart named '{song_name}' already exists."

            with z.open(json_member) as src, open(dest_json, "wb") as out:
                out.write(src.read())
            with z.open(audio_member) as src, open(dest_audio, "wb") as out:
                out.write(src.read())
    except Exception as e:
        return False, f"Import failed: {e}"

    return True, song_name
