import os
import json
import shutil
from datetime import datetime

class MapExporter:
    """Handles saving completed rhythm maps and managing associated audio files."""

    def __init__(self, rhythms_dir="rhythms"):
        self.rhythms_dir = rhythms_dir

    def export(self, song_name, audio_src_path, notes, duration):
        """
        Exports the chart to a JSON file and copies/renames the audio file.

        Args:
            song_name (str): The name of the song for the output files.
            audio_src_path (str): Path to the original source audio file.
            notes (list): List of note event dictionaries.
            duration (float): Total duration of the track in seconds.
        """
        timestamp = datetime.now().isoformat()

        # 1. Prepare destination paths
        json_filename = f"{song_name}.json"
        audio_filename = f"{song_name}.mp3" # Standardize on mp3 for the rhythm folder
        dest_json_path = os.path.join(self.rhythms_dir, json_filename)
        dest_audio_path = os.path.join(self.rhythms_dir, audio_filename)

        # 2. Create JSON structure
        export_data = {
            "recorded_at": timestamp,
            "audio_file": f"rhythms/{audio_filename}",
            "duration": duration,
            "note_events": notes
        }

        # 3. Write the JSON file
        with open(dest_json_path, "w") as f:
            json.dump(export_data, f, indent=4)

        # 4. Copy and rename audio file.
        # The source may already be the destination (the importer copies the
        # chosen file into rhythms/<name>.mp3 before recording starts), so a
        # copy onto itself is a no-op rather than an error.
        try:
            if os.path.abspath(audio_src_path) != os.path.abspath(dest_audio_path):
                shutil.copy(audio_src_path, dest_audio_path)
        except shutil.SameFileError:
            pass
        except Exception as e:
            print(f"Error copying audio file: {e}")
            return False

        print(f"Successfully exported chart: {song_name}")
        print(f"JSON: {dest_json_path}")
        print(f"Audio: {dest_audio_path}")
        return True
