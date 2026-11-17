import os
import unittest

import radar_live
from radar_gui import BG, CX, CY, FADE_S, MAX_RANGE_M, R, point_colour, prune, to_canvas

HERE = os.path.dirname(os.path.abspath(__file__))


class MappingTest(unittest.TestCase):
    def test_boresight_point_is_straight_above_sensor(self):
        px, py = to_canvas(0, 5, CX, CY, R)
        self.assertAlmostEqual(px, CX)
        self.assertLess(py, CY)

    def test_lateral_point_is_on_horizontal_through_sensor(self):
        # (5, 0) is bearing +90 deg at half the range, so halfway to the right edge
        px, py = to_canvas(5, 0, CX, CY, R)
        self.assertAlmostEqual(py, CY)
        self.assertAlmostEqual(px, CX + R * 5 / MAX_RANGE_M)

    def test_max_range_lateral_point_is_right_edge(self):
        px, py = to_canvas(MAX_RANGE_M, 0, CX, CY, R)
        self.assertAlmostEqual(px, CX + R)
        self.assertAlmostEqual(py, CY)

    def test_outside_sector_maps_to_none(self):
        self.assertIsNone(to_canvas(0, -1, CX, CY, R))          # behind the sensor
        self.assertIsNone(to_canvas(0, MAX_RANGE_M + 0.1, CX, CY, R))
        self.assertIsNone(to_canvas(7, 8, CX, CY, R))           # range about 10.6 m


class ColourTest(unittest.TestCase):
    def test_static_approaching_receding_differ(self):
        static = point_colour(0.0, 1.0)
        approaching = point_colour(-4.0, 1.0)
        receding = point_colour(4.0, 1.0)
        self.assertEqual(len({static, approaching, receding}), 3)

    def test_zero_fade_is_background(self):
        bg = "#%02x%02x%02x" % BG
        self.assertEqual(point_colour(-4.0, 0.0), bg)
        self.assertEqual(point_colour(0.0, 0.0), bg)


class PruneTest(unittest.TestCase):
    def test_drops_old_points_and_keeps_new(self):
        now = 100.0
        old = (now - FADE_S - 0.5, 1.0, 5.0, 0.0)
        new = (now - 0.5, 2.0, 5.0, 0.0)
        self.assertEqual(prune([old, new], now), [new])


class DataTest(unittest.TestCase):
    def test_clean_capture_decodes_and_maps_inside_sector(self):
        parser = radar_live.FrameParser()
        frames = []
        for chunk in radar_live.read_file(os.path.join(HERE, "data_clean.bin")):
            frames += parser.feed(chunk)
        self.assertEqual(len(frames), 100)
        inside = [p for f in frames for p in f.points
                  if to_canvas(p.x, p.y, CX, CY, R) is not None]
        self.assertGreater(len(inside), 0)


if __name__ == "__main__":
    unittest.main()
