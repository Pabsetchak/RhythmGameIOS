import pygame
import json
import os
import random
from settings import settings
from sound import init_audio, HitSoundBank

# Timing window (seconds) within which a press counts as hitting a note.
# This is also the "area of error": presses outside it score nothing, so
# spam-tapping can never farm points.
HIT_WINDOW = 0.16
# A hold may be released this early (seconds) before its end and still count.
RELEASE_GRACE = 0.12

# Judgment thresholds (seconds from the perfect moment). Tuned so that simply
# landing on a note reads as at least GOOD — BAD is only the thin outer edge,
# which keeps hits from feeling unfairly punished (e.g. with audio latency).
PERFECT_WINDOW = 0.065
GOOD_WINDOW = 0.135
# (anything between GOOD_WINDOW and HIT_WINDOW counts as "BAD")

# Floating per-note judgment popups.
POPUP_LIFE = 0.7         # seconds on screen
POPUP_RISE = 80          # pixels per second the popup drifts upward

# When ghost tapping is OFF, an empty-lane tap is forgiven (no penalty) if a
# real note was hit, or is about to be hit in any lane, within this window.
# This keeps chord/stream play from being punished for incidental extra taps —
# i.e. the mistap penalty is not applied when another note is hit.
CHORD_GRACE = 0.05

# Points awarded per judgment.
SCORE_PERFECT = 300
SCORE_GOOD = 100
SCORE_BAD = 50
# Small bonus per point of combo, rewarding sustained accuracy.
COMBO_BONUS = 2

JUDGE_PERFECT = ("PERFECT", (90, 220, 255))
JUDGE_GOOD = ("GOOD", (120, 255, 140))
JUDGE_BAD = ("BAD", (255, 180, 90))
JUDGE_MISS = ("MISS", (255, 90, 90))

# Count-in before the music/notes begin when playing a chart.
COUNT_IN_SECONDS = 3.0

LANE_NAMES = ["LEFT", "DOWN", "UP", "RIGHT"]
NUM_LANES = 4

# Screen / playfield geometry.
SCREEN_W, SCREEN_H = 800, 600
TARGET_Y = 500           # y of the hit line
NOTE_W = 80
NOTE_H = 28
LANE_X = [200, 300, 400, 500]   # left edge of each lane's note column


class Note:
    """A single playable note, with a randomly assigned lane."""

    def __init__(self, lane, time, is_hold, duration):
        self.lane = lane
        self.time = time              # when the note should be hit (seconds)
        self.is_hold = is_hold
        self.duration = duration      # hold length (seconds); 0 for taps
        self.end = time + duration
        # pending -> active (hold being held) -> hit / missed
        self.state = "pending"


class RhythmGame:
    def __init__(self, song_name):
        # Low-latency mixer first, so hit sounds line up with key presses.
        init_audio()
        pygame.init()
        self.song_name = song_name
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption(f"Playing: {song_name}")
        self.clock = pygame.time.Clock()

        self.font = pygame.font.SysFont("Arial", 28)
        self.font_small = pygame.font.SysFont("Arial", 20)
        self.font_big = pygame.font.SysFont("Arial", 60, bold=True)
        self.font_popup = pygame.font.SysFont("Arial", 22, bold=True)

        # Game state.
        self.running = True
        self.score = 0
        self.combo = 0
        self.max_combo = 0
        self.start_ticks = 0

        # Per-judgment tallies.
        self.counts = {"PERFECT": 0, "GOOD": 0, "BAD": 0, "MISS": 0}
        self.mistaps = 0                # empty-lane taps penalised (ghost off)

        # Ghost tapping: when ON, pressing a lane with no note in range is free
        # (no penalty). When OFF, such a press is a penalised mistap.
        self.ghost_tapping = bool(settings.get("GHOST_TAPPING", True))
        self.last_hit_time = -999.0     # time of the most recent successful hit

        # Latency compensation (seconds). AUDIO shifts judgment to match when
        # the player actually taps; VISUAL shifts the note graphics.
        self.audio_offset = float(settings.get("AUDIO_OFFSET", 0.0))
        self.visual_offset = float(settings.get("VISUAL_OFFSET", 0.0))

        # Floating per-note judgment popups: each is [text, color, x, start_time].
        self.popups = []

        # Hit sounds: a bank with distinct timbres per judgment plus
        # round-robin pitch variants, so feedback carries accuracy info and
        # doesn't fatigue.
        self.hit_sounds = None
        try:
            self.hit_sounds = HitSoundBank(float(settings.get("HIT_VOLUME", 0.5)))
        except Exception as e:
            print(f"Could not load hit sounds: {e}")

        # Lane colors.
        self.colors = {name: settings.get(name) for name in LANE_NAMES}

        # Map lane index -> pygame key constant from settings.
        defaults = {
            "LEFT_BUTTON": "K_a", "DOWN_BUTTON": "K_s",
            "UP_BUTTON": "K_UP", "RIGHT_BUTTON": "K_RIGHT",
        }
        self.key_to_lane = {}
        for lane, name in enumerate(LANE_NAMES):
            key_const_name = settings.get(f"{name}_BUTTON", defaults[f"{name}_BUTTON"])
            key = getattr(pygame, key_const_name, None)
            if key is not None:
                self.key_to_lane[key] = lane

        self.pps = settings.get("NOTE_SPEED", 700)   # falling speed, pixels/second

        self.load_assets()
        self.notes = self.build_notes()

    # ------------------------------------------------------------------ #
    # Loading
    # ------------------------------------------------------------------ #
    def load_assets(self):
        self.duration = 0.0
        try:
            self.duration = pygame.mixer.Sound(
                os.path.join("rhythms", f"{self.song_name}.mp3")
            ).get_length()
        except Exception as e:
            print(f"Could not read audio length: {e}")

        map_path = os.path.join("rhythms", f"{self.song_name}.json")
        self.note_events = []
        if os.path.exists(map_path):
            try:
                with open(map_path, "r") as f:
                    data = json.load(f)
                self.note_events = data.get("note_events", [])
                if data.get("duration"):
                    self.duration = data["duration"]
            except (json.JSONDecodeError, OSError) as e:
                print(f"Could not load map: {e}")

    def build_notes(self):
        """
        Assign each recorded event to a random lane. Preferences are applied as
        a cascade of soft filters — each is honoured only while it leaves at
        least one option, so overlaps happen strictly as a last resort:

          1. Never use a lane an active hold still occupies.
          2. Never put two notes in the same lane on the same "row" (same moment).
          3. Avoid the lane(s) used by the immediately previous row, so notes
             don't appear right after each other in the same lane.
        """
        events = sorted(self.note_events, key=lambda e: e.get("timestamp", 0.0))
        notes = []

        ROW_EPS = 0.03                       # events within this are "same row"
        lane_free_at = [0.0] * NUM_LANES     # when each lane is free of a hold
        prev_time = None
        used_this_row = set()
        prev_row_lanes = set()               # lanes used by the previous row

        def prefer(candidates, avoid):
            """Drop 'avoid' lanes, but only if something is left."""
            kept = [c for c in candidates if c not in avoid]
            return kept if kept else candidates

        for e in events:
            t = e.get("timestamp", 0.0)
            is_hold = e.get("type") == "hold"
            dur = float(e.get("duration", 0.0)) if is_hold else 0.0

            # Starting a new row? Remember the lanes the last one used.
            if prev_time is None or abs(t - prev_time) > ROW_EPS:
                if used_this_row:
                    prev_row_lanes = set(used_this_row)
                used_this_row = set()
            prev_time = t

            # 1. Lanes not occupied by a hold (fall back to all if none free).
            free = [l for l in range(NUM_LANES) if lane_free_at[l] <= t + 1e-6]
            choices = free if free else list(range(NUM_LANES))

            # 2. Avoid stacking within the same row.
            choices = prefer(choices, used_this_row)
            # 3. Avoid repeating the previous row's lane(s).
            choices = prefer(choices, prev_row_lanes)

            lane = random.choice(choices)
            used_this_row.add(lane)
            if is_hold:
                lane_free_at[lane] = t + dur

            notes.append(Note(lane, t, is_hold, dur))

        return notes

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #
    def run(self):
        # The song clock starts at -COUNT_IN_SECONDS and counts up. The music
        # (and the song proper) begins when it reaches 0, so notes already
        # falling get their full approach time and the player gets a "3-2-1".
        self.start_ticks = pygame.time.get_ticks()
        self.music_started = False

        while self.running:
            now = (pygame.time.get_ticks() - self.start_ticks) / 1000.0 - COUNT_IN_SECONDS

            # Kick off the music exactly when the count-in finishes.
            if not self.music_started and now >= 0:
                try:
                    pygame.mixer.music.load(
                        os.path.join("rhythms", f"{self.song_name}.mp3"))
                    pygame.mixer.music.play()
                except Exception as e:
                    print(f"Could not play audio: {e}")
                self.music_started = True

            # Lock the game clock to the AUDIO clock. music.get_pos() is
            # driven by the audio callback (the pygame equivalent of an audio
            # context's currentTime), so nudging our wall-clock anchor toward
            # it absorbs music start latency and any drift between the two
            # clocks — notes and judgments stay in sync with what you HEAR.
            if self.music_started:
                mpos = pygame.mixer.music.get_pos()
                if mpos >= 0:
                    err = mpos / 1000.0 - now
                    if abs(err) > 0.002:
                        corr = max(-0.004, min(0.004, err * 0.15))
                        self.start_ticks -= corr * 1000.0
                        now += corr

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.running = False
                    elif event.key in self.key_to_lane:
                        # press_lane plays the judgment-matched click at its
                        # top — the note search takes microseconds, so the
                        # sound is still effectively on the key press.
                        self.press_lane(self.key_to_lane[event.key], now)
                elif event.type == pygame.KEYUP:
                    if event.key in self.key_to_lane:
                        self.release_lane(self.key_to_lane[event.key], now)

            self.update(now)
            self.draw(now)

            # End once the song is over and every note has resolved.
            if self.music_started:
                song_over = self.duration and now >= self.duration + 1.0
                if song_over and self.all_resolved():
                    self.running = False

            self.clock.tick(settings.get("FPS", 120))

        self.show_results()
        pygame.mixer.music.stop()
        pygame.quit()

    def all_resolved(self):
        return all(n.state in ("hit", "missed") for n in self.notes)

    # ------------------------------------------------------------------ #
    # Input handling
    # ------------------------------------------------------------------ #
    def judge_and_score(self, diff):
        """Map a timing error (seconds) to a (judgment, points) pair."""
        if diff <= PERFECT_WINDOW:
            return JUDGE_PERFECT, SCORE_PERFECT
        if diff <= GOOD_WINDOW:
            return JUDGE_GOOD, SCORE_GOOD
        return JUDGE_BAD, SCORE_BAD

    def add_popup(self, judge, lane, now):
        """Spawn a floating judgment popup over the given lane."""
        text, color = judge
        x = LANE_X[lane] + NOTE_W // 2
        self.popups.append([text, color, x, now])

    def play_hit_sound(self, kind="good"):
        if self.hit_sounds:
            self.hit_sounds.play(kind)

    def register_hit(self, judge, points, now, lane):
        """Apply a successful note hit: score, combo, tally, popup. The click
        is played on the key press (in the event loop), not here, so it stays
        tight and never fires on a hold's release/auto-completion."""
        self.add_popup(judge, lane, now)
        self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        self.score += points + self.combo * COMBO_BONUS
        self.counts[judge[0]] += 1
        self.last_hit_time = now

    def register_miss(self, now, lane):
        """A note that was never hit (or a hold released early)."""
        self.play_hit_sound("miss")     # soft low thud — audible accuracy info
        self.add_popup(JUDGE_MISS, lane, now)
        self.counts["MISS"] += 1
        self.combo = 0

    def near_real_hit(self, now):
        """
        True if a real note was just hit, or is about to be hit in any lane,
        within CHORD_GRACE. Used so an empty-lane tap during chord/stream play
        isn't penalised — the mistap penalty is not applied when another note
        is (or is about to be) hit.
        """
        if now - self.last_hit_time <= CHORD_GRACE:
            return True
        for n in self.notes:
            if n.state == "pending" and abs(n.time - now) <= CHORD_GRACE:
                return True
        return False

    def press_lane(self, lane, now):
        """Try to hit the nearest pending note in this lane."""
        judge_now = now - self.audio_offset      # latency-compensated timing
        best = None
        best_diff = HIT_WINDOW
        for n in self.notes:
            if n.lane == lane and n.state == "pending":
                diff = abs(n.time - judge_now)
                if diff <= best_diff:
                    best_diff = diff
                    best = n

        if best is None:
            # Empty-lane tap (a "ghost tap") — tiny neutral tick, so every
            # press still gives tactile feedback without claiming a hit.
            if self.ghost_tapping:
                self.play_hit_sound("ghost")
                return                      # allowed, no penalty
            if self.near_real_hit(now):
                self.play_hit_sound("ghost")
                return                      # forgive incidental chord taps
            # Penalised mistap: break combo (no score, doesn't count as a
            # note miss for accuracy purposes).
            self.play_hit_sound("miss")
            self.add_popup(JUDGE_MISS, lane, now)
            self.combo = 0
            self.mistaps += 1
            return

        judge, points = self.judge_and_score(best_diff)
        # Sound first — timbre matches the judgment (accuracy through the
        # ears), still effectively instant with the key press.
        self.play_hit_sound(judge[0].lower())
        if best.is_hold:
            # Begin holding; the head is judged now, completion adds a bonus.
            best.state = "active"
            self.register_hit(judge, points, now, lane)
        else:
            best.state = "hit"
            self.register_hit(judge, points, now, lane)

    def release_lane(self, lane, now):
        """Releasing a held note: early = miss, near/after end = clears it."""
        judge_now = now - self.audio_offset
        for n in self.notes:
            if n.lane == lane and n.state == "active":
                if judge_now < n.end - RELEASE_GRACE:
                    n.state = "missed"      # released too early
                    self.register_miss(now, lane)
                else:
                    n.state = "hit"
                    self.register_hit(JUDGE_PERFECT, SCORE_PERFECT, now, lane)
                break

    # ------------------------------------------------------------------ #
    # Update
    # ------------------------------------------------------------------ #
    def update(self, now):
        judge_now = now - self.audio_offset
        for n in self.notes:
            if n.state == "pending" and judge_now - n.time > HIT_WINDOW:
                # Never pressed in time.
                n.state = "missed"
                self.register_miss(now, n.lane)
            elif n.state == "active" and judge_now >= n.end:
                # Held all the way through (the player need not release it).
                n.state = "hit"
                self.register_hit(JUDGE_PERFECT, SCORE_PERFECT, now, n.lane)

    # ------------------------------------------------------------------ #
    # Drawing
    # ------------------------------------------------------------------ #
    def draw(self, now):
        self.screen.fill((10, 10, 18))

        # Lane separators / target receptors.
        for lane, name in enumerate(LANE_NAMES):
            x = LANE_X[lane]
            pygame.draw.rect(self.screen, (30, 30, 45),
                             (x, 0, NOTE_W, SCREEN_H))
            color = self.colors[name]
            pygame.draw.rect(self.screen, color,
                             (x, TARGET_Y, NOTE_W, NOTE_H), 3)

        # Notes — drawn on the latency-compensated timeline so they cross the
        # hit line exactly when a perfect tap is expected (plus visual offset).
        vis_now = now - self.audio_offset + self.visual_offset
        for n in self.notes:
            if n.state in ("hit", "missed"):
                continue
            self.draw_note(n, vis_now)

        # Floating per-note judgment popups (rise and fade out).
        self.draw_popups(now)

        # HUD.
        self.screen.blit(
            self.font.render(f"Score: {self.score}", True, (255, 255, 255)),
            (20, 20))
        self.screen.blit(
            self.font.render(f"Combo: {self.combo}", True, (255, 220, 120)),
            (20, 55))

        # Count-in overlay before the song starts.
        if now < 0:
            count = min(int(COUNT_IN_SECONDS), int(-now) + 1)
            num = self.font_big.render(str(count), True, (255, 255, 255))
            self.screen.blit(num, num.get_rect(center=(SCREEN_W // 2, SCREEN_H // 2 - 30)))
            sub = self.font.render("Get ready...", True, (200, 200, 215))
            self.screen.blit(sub, sub.get_rect(center=(SCREEN_W // 2, SCREEN_H // 2 + 40)))

        pygame.display.flip()

    def draw_popups(self, now):
        """Draw each note's judgment text rising and fading, then drop the
        expired ones."""
        alive = []
        for popup in self.popups:
            text, color, x, start = popup
            elapsed = now - start
            if elapsed >= POPUP_LIFE:
                continue
            alive.append(popup)
            y = (TARGET_Y - 24) - elapsed * POPUP_RISE
            surf = self.font_popup.render(text, True, color)
            surf.set_alpha(int(255 * (1.0 - elapsed / POPUP_LIFE)))
            self.screen.blit(surf, surf.get_rect(center=(int(x), int(y))))
        self.popups = alive

    def draw_note(self, n, now):
        x = LANE_X[n.lane]
        color = self.colors[LANE_NAMES[n.lane]]

        if n.is_hold:
            y_head = TARGET_Y - (n.time - now) * self.pps   # leading edge
            y_tail = TARGET_Y - (n.end - now) * self.pps     # trailing edge (higher up)

            if n.state == "active":
                # The head has been hit and is consumed; only the remaining
                # tail is shown, shrinking down into the hit line as it's held.
                top = y_tail
                bottom = TARGET_Y
            else:
                top = y_tail
                bottom = y_head

            if bottom > -50 and top < SCREEN_H + 50:
                height = max(NOTE_H, bottom - top)
                pygame.draw.rect(self.screen, color,
                                 (x, top, NOTE_W, height), border_radius=8)
                if n.state == "active":
                    # Outline to show it's being held.
                    pygame.draw.rect(self.screen, (255, 255, 255),
                                     (x, top, NOTE_W, height), 2, border_radius=8)
                else:
                    # Brighter cap on the leading head while it falls.
                    pygame.draw.rect(self.screen, (255, 255, 255),
                                     (x, y_head - NOTE_H, NOTE_W, NOTE_H),
                                     2, border_radius=8)
        else:
            y = TARGET_Y - (n.time - now) * self.pps
            if -50 < y < SCREEN_H + 50:
                pygame.draw.rect(self.screen, color,
                                 (x, y, NOTE_W, NOTE_H), border_radius=8)

    # ------------------------------------------------------------------ #
    # Results
    # ------------------------------------------------------------------ #
    def show_results(self):
        c = self.counts
        total = c["PERFECT"] + c["GOOD"] + c["BAD"] + c["MISS"]
        # Accuracy weighted by judgment quality.
        weighted = c["PERFECT"] * 1.0 + c["GOOD"] * 0.66 + c["BAD"] * 0.33
        acc = (weighted / total * 100.0) if total else 0.0

        waiting = True
        while waiting:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    waiting = False
                elif event.type == pygame.KEYDOWN:
                    waiting = False

            self.screen.fill((10, 10, 18))
            title = self.font_big.render("Results", True, (255, 255, 255))
            self.screen.blit(title, title.get_rect(center=(400, 90)))

            score_surf = self.font.render(f"Score: {self.score}", True, (255, 255, 255))
            self.screen.blit(score_surf, score_surf.get_rect(center=(400, 165)))

            # Judgment breakdown, each in its own color.
            rows = [
                (JUDGE_PERFECT, c["PERFECT"]),
                (JUDGE_GOOD, c["GOOD"]),
                (JUDGE_BAD, c["BAD"]),
                (JUDGE_MISS, c["MISS"]),
            ]
            for i, ((label, col), n) in enumerate(rows):
                surf = self.font.render(f"{label}: {n}", True, col)
                self.screen.blit(surf, surf.get_rect(center=(400, 220 + i * 40)))

            extra = [
                f"Max Combo: {self.max_combo}",
                f"Accuracy: {acc:0.1f}%",
            ]
            if not self.ghost_tapping:
                extra.append(f"Mistaps: {self.mistaps}")
            for i, line in enumerate(extra):
                surf = self.font.render(line, True, (220, 220, 230))
                self.screen.blit(surf, surf.get_rect(center=(400, 400 + i * 40)))

            hint = self.font_small.render("Press any key to return.",
                                          True, (140, 140, 160))
            self.screen.blit(hint, hint.get_rect(center=(400, 555)))
            pygame.display.flip()
            self.clock.tick(60)
