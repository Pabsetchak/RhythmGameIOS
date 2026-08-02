"""
Road geometry.

The playfield is drawn as a road receding to a vanishing point rather than
as four parallel columns: lanes are trapezoids that narrow toward the top,
and notes shrink and slow as they climb away from the hit line.

Touch targets deliberately do *not* follow that perspective. The road is at
full width where it meets the hit line, so a lane's touch column is simply
its quarter of the screen — the whole column, top to bottom, the way Piano
Tiles works. Aiming at a shrinking trapezoid with a fingertip would be
miserable; aiming at a quarter of the screen is effortless.
"""

from theme import NUM_LANES


class RoadGeometry:
    """
    Maps song-relative distance to screen position.

    `flat` is the distance a note would sit above the hit line with no
    perspective (seconds-until-hit × note speed). `project` converts that to
    a 0..1 depth where 0 is the hit line and 1 is the horizon.
    """

    def __init__(self, layout, perspective, hud_bottom):
        self.layout = layout
        self.perspective = max(0.0, min(1.0, perspective))

        # Vertical extent of the road.
        self.horizon_y = hud_bottom + layout.s(6)
        self.hit_y = layout.content_bottom - layout.s(96)
        self.travel = max(1, self.hit_y - self.horizon_y)

        # Road half-widths at the hit line and at the horizon.
        self.near_half = layout.width * 0.5
        self.far_half = self.near_half * (1.0 - 0.45 * self.perspective)
        self.center_x = layout.width * 0.5

        # Curvature of the depth mapping. 0 is linear; larger values bunch
        # distant notes toward the horizon the way real perspective does.
        self.k = self.perspective * 2.6

        # Where the lane receptors sit, and how tall a tile is at the front.
        self.pad_h = layout.s(74)
        self.tile_h = layout.s(58)

    # ------------------------------------------------------------------ #
    # Depth
    # ------------------------------------------------------------------ #
    def project(self, flat):
        """
        Flat pixel distance above the hit line -> 0..1 depth.

        f(1 + k) / (1 + k·f) keeps both ends anchored (0 -> 0, 1 -> 1) while
        compressing everything in between toward the horizon.
        """
        f = flat / self.travel
        if self.k <= 0:
            return f
        return f * (1.0 + self.k) / (1.0 + self.k * f)

    def y_at(self, depth):
        return self.hit_y - depth * self.travel

    def scale_at(self, depth):
        """How wide the road is at this depth, as a fraction of full width."""
        d = max(0.0, min(1.2, depth))
        return 1.0 - (1.0 - self.far_half / self.near_half) * d

    # ------------------------------------------------------------------ #
    # Lanes
    # ------------------------------------------------------------------ #
    def lane_edges(self, lane, depth):
        """(left_x, right_x) of a lane at the given depth."""
        scale = self.scale_at(depth)
        half = self.near_half * scale
        lane_w = (half * 2.0) / NUM_LANES
        left = self.center_x - half + lane * lane_w
        return left, left + lane_w

    def lane_center(self, lane, depth=0.0):
        left, right = self.lane_edges(lane, depth)
        return (left + right) * 0.5

    def lane_from_x(self, x):
        """
        Which lane a touch belongs to. Uses the full screen width, not the
        drawn road, so the target is always a clean quarter of the display.
        """
        lane = int(x / max(1, self.layout.width) * NUM_LANES)
        return max(0, min(NUM_LANES - 1, lane))

    def touch_top(self):
        """Taps above this y are chrome (pause button), not gameplay."""
        return self.horizon_y

    def quad(self, lane, near_depth, far_depth):
        """Four corners of a lane slice between two depths, clockwise."""
        nl, nr = self.lane_edges(lane, near_depth)
        fl, fr = self.lane_edges(lane, far_depth)
        ny = self.y_at(near_depth)
        fy = self.y_at(far_depth)
        return [(fl, fy), (fr, fy), (nr, ny), (nl, ny)]
