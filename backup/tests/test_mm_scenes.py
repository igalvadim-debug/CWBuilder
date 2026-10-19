"""Regression coverage for duration parsing and lossless scene fitting."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mm_scenes import _fit, parse_length_spec, scene_plan  # noqa: E402


class ScenePlanningTest(unittest.TestCase):
    def test_duration_tokens_preserve_decimal_commas(self):
        for spec, expected in (
            ("5,4", [5.4]), ("5,4+2", [5.4, 2]),
            ("2x5,4+2", [5.4, 5.4, 2]), ("3:5,4", [5, 4, 4]),
            ("3:5,4+2", [5, 4, 4, 2]), ("3 mal 6", [6, 6, 6]),
            ("2x8+2", [8, 8, 2]),
        ):
            with self.subTest(spec=spec):
                self.assertEqual(parse_length_spec(spec), expected)

    def test_invalid_durations_still_raise(self):
        for spec in ("3:5,", "0:5,4", "2:5,-4", "0", "nonsense"):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                parse_length_spec(spec)

    def test_fit_combines_surplus_and_preserves_padding(self):
        for segments, count, expected in (
            (["a", "b", "c", "d"], 2, ["a", "b\n\nc\n\nd"]),
            (["a", "b"], 1, ["a\n\nb"]),
            (["a", "b"], 2, ["a", "b"]),
            (["a", "b"], 3, ["a", "b", "b"]),
            ([], 2, ["fallback", "fallback"]),
        ):
            with self.subTest(segments=segments, count=count):
                original = list(segments)
                self.assertEqual(_fit(segments, count, "fallback"), expected)
                self.assertEqual(segments, original)

    def test_scene_plan_keeps_surplus_for_each_split_style(self):
        for prompt in (
            "SCENE 1: First\nSCENE 2: Second\nSCENE 3: Third",
            "1) First\n2) Second\n3) Third",
            "First\n\nSecond\n\nThird",
            "First. Second. Third.",
        ):
            with self.subTest(prompt=prompt):
                plan = scene_plan(prompt, [5, 4])
                self.assertEqual(len(plan), 2)
                self.assertIn("First", plan[0]["prompt"])
                self.assertIn("Second", plan[1]["prompt"])
                self.assertIn("Third", plan[1]["prompt"])
                self.assertEqual([sc["duration"] for sc in plan], [5, 4])


if __name__ == "__main__":
    unittest.main()
