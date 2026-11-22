#!/usr/bin/env python3
"""tools/creative/creative_spec.py の確かめ。self-test.yml が ubuntu で流す。

    python3 tools/tests/test_creative_spec.py
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "creative"))
from creative_spec import SpecError, contrast, validate  # noqa: E402

SAMPLE = json.loads((ROOT / "tools" / "tests" / "creative" / "spec.json").read_text(encoding="utf-8"))


def sample() -> dict:
    return copy.deepcopy(SAMPLE)


class ValidateTests(unittest.TestCase):
    def test_sample_has_no_problems(self) -> None:
        self.assertEqual(validate(sample()), [])

    def test_optional_fields_can_be_omitted(self) -> None:
        spec = sample()
        del spec["colors"]["background2"]
        del spec["colors"]["highlight"]
        del spec["locales"][0]["header"]["subtitle"]
        del spec["locales"][0]["search"]["chips"]
        self.assertEqual(validate(spec), [])

    def test_rejects_unknown_fields(self) -> None:
        spec = sample()
        spec["css"] = "body { display: none }"
        with self.assertRaisesRegex(SpecError, "知らない欄"):
            validate(spec)
        spec = sample()
        spec["locales"][0]["header"]["html"] = "<b>x</b>"
        with self.assertRaisesRegex(SpecError, "知らない欄"):
            validate(spec)

    def test_rejects_bad_shapes(self) -> None:
        cases = [
            (lambda s: s.update(v=2), "v は 1"),
            (lambda s: s.update(layout="fancy"), "layout"),
            (lambda s: s["colors"].update(text="white"), "#RRGGBB"),
            (lambda s: s["colors"].pop("accent"), "accent がありません"),
            (lambda s: s["screens"].update(header=[]), "1〜3 個"),
            (lambda s: s["screens"].update(search=["a", "b", "c"]), "1〜2 個"),
            (lambda s: s["screens"].update(header=["../etc/passwd"]), "画面の名前が不正"),
            (lambda s: s.update(locales=[]), "1〜50 個"),
            (lambda s: s["locales"][0].update(locale="ja jp"), "locale が不正"),
            (lambda s: s["locales"][0].update(screenshots="../ja"), "screenshots が不正"),
            (lambda s: s["locales"].append(copy.deepcopy(s["locales"][0])), "重なっています"),
            (lambda s: s["locales"][0]["header"].update(title=""), "空です"),
            (lambda s: s["locales"][0]["header"].update(title="あ" * 61), "長すぎます"),
            (lambda s: s["locales"][0]["header"].update(title="a\tb"), "制御文字"),
            (lambda s: s["locales"][0]["header"].update(title="a\nb\nc\nd"), "改行が多すぎます"),
            (lambda s: s["locales"][0]["header"].update(title="*強調"), "閉じていません"),
            (lambda s: s["locales"][0]["search"].update(chips=["a", "b", "c", "d"]), "3 つまで"),
            (lambda s: s["locales"][0].update(appName=3), "文字列"),
        ]
        for change, message in cases:
            with self.subTest(message=message):
                spec = sample()
                change(spec)
                with self.assertRaisesRegex(SpecError, message):
                    validate(spec)

    def test_reports_forbidden_text_without_failing(self) -> None:
        spec = sample()
        spec["locales"][1]["search"]["title"] = "Free at example.com"
        spec["locales"][0]["header"]["subtitle"] = "© 2026 ¥120"
        codes = sorted(problem["code"] for problem in validate(spec))
        self.assertEqual(codes, ["forbidden-price", "forbidden-price", "forbidden-symbol", "forbidden-url"])

    def test_reports_free_in_japanese_sentence(self) -> None:
        spec = sample()
        spec["locales"][0]["search"]["title"] = "ずっと無料で使える"
        self.assertEqual([problem["code"] for problem in validate(spec)], ["forbidden-price"])

    def test_reports_low_contrast(self) -> None:
        spec = sample()
        spec["colors"]["text"] = "#202040"
        codes = [problem["code"] for problem in validate(spec)]
        self.assertIn("low-contrast", codes)

    def test_contrast(self) -> None:
        self.assertAlmostEqual(contrast("#FFFFFF", "#000000"), 21.0, places=1)
        self.assertAlmostEqual(contrast("#777777", "#777777"), 1.0, places=1)


if __name__ == "__main__":
    unittest.main()
