import pygame
import os
import time
from map_exporter import MapExporter
from sound import init_audio

# A key must be held at least this long (in seconds) to count as a hold note.
# Anything shorter is logged as a single "quickPress" so that normal taps are
# never mistaken for holds.
HOLD_THRESHOLD = 0.15

# Number of seconds counted down before the music starts and capturing begins.
COUNTDOWN_SECONDS = 3


class MapCreator:
    def __init__(self, song_name):
        """
        Initializes the MapCreator.
        :param song_name: The name of the song being recorded (without extension).
        """
        self.song_name = song_name
        self.audio_path = os.path.join("rhythms", f"{song_name}.mp3")
        self.exporter = MapExporter("rhythms")

        # Captured note events, ready to hand to the exporter.
        self.note_events = []
        # Keys currently held down: key_name -> press timestamp (seconds).
        self.held_keys = {}
        self.duration = 0.0

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _key_name(self, event):
        """Return a readable name for any keyboard key (e.g. 'a', 'left')."""
        try:
            return pygame.key.name(event.key)
        except Exception:
            return None

    def _register_release(self, key_name, release_time):
        """Turn a held key into either a hold note or a quick press."""
        if key_name not in self.held_keys:
            return
        press_time = self.held_keys.pop(key_name)
        held_for = release_time - press_time

        if held_for >= HOLD_THRESHOLD:
            self.note_events.append({
                "type": "hold",
                "key": key_name,
                "timestamp": press_time,
                "duration": held_for,
            })
        else:
            self.note_events.append({
                "type": "quickPress",
                "key": key_name,
                "timestamp": press_time,
            })

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #
    def run(self):
        init_audio()      # low-latency mixer so playback timing is tight
        pygame.init()
        screen = pygame.display.set_mode((800, 600))
        pygame.display.set_caption(f"Capturing: {self.song_name}")
        clock = pygame.time.Clock()

        font_big = pygame.font.SysFont("Arial", 110, bold=True)
        font = pygame.font.SysFont("Arial", 28)
        font_small = pygame.font.SysFont("Arial", 20)

        # Figure out how long the song is so we know when to stop.
        try:
            self.duration = pygame.mixer.Sound(self.audio_path).get_length()
        except Exception as e:
            print(f"Could not read audio length: {e}")
            self.duration = 0.0

        aborted = self._countdown(screen, clock, font_big, font)
        if aborted:
            pygame.quit()
            return

        self._capture(screen, clock, font, font_small)

        pygame.quit()

        # Hand the recorded chart to the exporter. The audio already lives in
        # rhythms/<name>.mp3, so the exporter simply writes the JSON beside it.
        if self.note_events:
            self.note_events.sort(key=lambda e: e["timestamp"])
            self.exporter.export(
                self.song_name, self.audio_path, self.note_events, self.duration
            )
        else:
            print("No notes were recorded; chart not saved.")

    # ------------------------------------------------------------------ #
    # Phases
    # ------------------------------------------------------------------ #
    def _countdown(self, screen, clock, font_big, font):
        """Show a short countdown. Returns True if the user aborted."""
        start = time.perf_counter()
        while True:
            remaining = COUNTDOWN_SECONDS - (time.perf_counter() - start)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return True
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    return True

            if remaining <= 0:
                return False

            screen.fill((15, 15, 25))
            num = str(int(remaining) + 1)
            text = font_big.render(num, True, (255, 255, 255))
            screen.blit(text, text.get_rect(center=(400, 270)))
            sub = font.render("Get ready... press any keys to the beat!",
                              True, (180, 180, 200))
            screen.blit(sub, sub.get_rect(center=(400, 400)))
            pygame.display.flip()
            clock.tick(60)

    def _capture(self, screen, clock, font, font_small):
        """Play the song and record key presses/holds until it ends or the
        user exits."""
        try:
            pygame.mixer.music.load(self.audio_path)
            pygame.mixer.music.play()
        except Exception as e:
            print(f"Could not play audio: {e}")

        start_time = time.perf_counter()
        capturing = True

        while capturing:
            now = time.perf_counter() - start_time

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    capturing = False
                    break

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        # Exit early: keep everything captured so far.
                        capturing = False
                        break
                    key_name = self._key_name(event)
                    # Ignore auto-repeat / duplicate downs for an already-held key.
                    if key_name and key_name not in self.held_keys:
                        self.held_keys[key_name] = now

                elif event.type == pygame.KEYUP:
                    key_name = self._key_name(event)
                    if key_name:
                        self._register_release(key_name, now)

            # Stop automatically when the song is over.
            if self.duration and now >= self.duration:
                capturing = False

            self._draw_capture(screen, font, font_small, now)
            clock.tick(120)

        # Release any keys still held at the moment we stop, so they still
        # become notes.
        final_now = time.perf_counter() - start_time
        for key_name in list(self.held_keys.keys()):
            self._register_release(key_name, final_now)

        pygame.mixer.music.stop()

        # If we never learned the real duration, fall back to when we stopped.
        if self.duration <= 0:
            self.duration = final_now

    # ------------------------------------------------------------------ #
    # Drawing
    # ------------------------------------------------------------------ #
    def _draw_capture(self, screen, font, font_small, now):
        screen.fill((15, 15, 25))

        # Progress bar.
        if self.duration > 0:
            pct = max(0.0, min(1.0, now / self.duration))
            pygame.draw.rect(screen, (40, 40, 60), (100, 60, 600, 24))
            pygame.draw.rect(screen, (90, 200, 140), (100, 60, int(600 * pct), 24))

        title = font.render(f"Recording: {self.song_name}", True, (235, 235, 245))
        screen.blit(title, title.get_rect(center=(400, 130)))

        if self.duration > 0:
            time_text = f"{now:0.1f}s / {self.duration:0.1f}s"
        else:
            time_text = f"{now:0.1f}s"
        t = font.render(time_text, True, (180, 180, 200))
        screen.blit(t, t.get_rect(center=(400, 180)))

        count = font.render(f"Notes captured: {len(self.note_events)}",
                            True, (180, 180, 200))
        screen.blit(count, count.get_rect(center=(400, 230)))

        # Show which keys are currently held.
        if self.held_keys:
            held = "Holding: " + "  ".join(sorted(self.held_keys.keys()))
        else:
            held = "Holding: -"
        h = font.render(held, True, (255, 210, 120))
        screen.blit(h, h.get_rect(center=(400, 300)))

        hint = font_small.render("Press ESC (or close the window) to finish "
                                 "and save your chart.", True, (140, 140, 160))
        screen.blit(hint, hint.get_rect(center=(400, 560)))

        pygame.display.flip()
