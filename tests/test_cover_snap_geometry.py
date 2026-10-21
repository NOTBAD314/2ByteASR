import unittest

from twobyteasr.cover.cover_snap.geometry import snap_axis


class SnapAxisTests(unittest.TestCase):
    def test_near_edges_and_exact_corrections(self):
        self.assertEqual(snap_axis(7, 100, 640, 1).position, 0)
        self.assertEqual(snap_axis(535, 100, 640, 1).position, 540)
        self.assertIsNone(snap_axis(300, 100, 640, 1))

    def test_threshold_is_in_view_pixels(self):
        for scale in (.1, .5, 1, 2, 8):
            self.assertIsNotNone(snap_axis(7.9/scale, 100, 640, scale))
            self.assertIsNone(snap_axis(8.1/scale, 100, 640, scale))

    def test_hysteresis_releases_beyond_twelve_pixels(self):
        previous = snap_axis(5, 100, 640, 1)
        self.assertEqual(snap_axis(11, 100, 640, 1, previous), previous)
        self.assertIsNone(snap_axis(13, 100, 640, 1, previous))

    def test_large_images_keep_negative_coordinates(self):
        result = snap_axis(-355, 1000, 640, 1)
        self.assertEqual((result.position, result.edge), (-360, 640))
        self.assertIsNone(snap_axis(-200, 1000, 640, 1))

    def test_outside_canvas_is_not_clamped(self):
        self.assertIsNone(snap_axis(-90, 100, 640, 1))
        self.assertIsNone(snap_axis(720, 100, 640, 1))

    def test_nearest_target_and_stable_tie(self):
        self.assertEqual(snap_axis(7, 630, 640, 1).position, 10)
        self.assertEqual(snap_axis(5, 630, 640, 1).position, 0)


if __name__ == '__main__':
    unittest.main()
