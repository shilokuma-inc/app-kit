#!/usr/bin/env python3
"""撮影の matrix（app_store_config.py の display-types）の確かめ。self-test.yml が ubuntu で流す。

手元では `python3 tools/tests/test-screenshot-matrix.py`。max_parallel と、撮る表示サイズ・言語の数の組み合わせで、
撮影のジョブの数が max_parallel を超えないこと、言語の分け方、artifact の名前、merge の対象を確かめる。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "screenshots" / "app_store_config.py"

# template と同じ並び（6.3 inch は 6.9 inch を縮めて作る。撮るのは iPhone Duo・6.9 inch・iPad の順）
DISPLAY_TYPES = {
    "APP_IPHONE_61": {"label": "iPhone 6.3 inch", "deriveFrom": "APP_IPHONE_67", "sizes": ["1206x2622"]},
    "APP_IPHONE_DUO": {"label": "iPhone Duo", "devices": ["iPhone Duo"], "sizes": ["1398x2034"], "runsOn": "xcode-27", "xcodeVersion": "27.1"},
    "APP_IPHONE_67": {"label": "iPhone 6.9 inch", "devices": ["iPhone 17 Pro Max"], "sizes": ["1320x2868"]},
    "APP_IPAD_PRO_3GEN_129": {"label": "iPad 13 inch", "devices": ["iPad Pro 13-inch (M5)"], "sizes": ["2064x2752"]},
}


def language(code: str) -> dict:
    return {"language": code, "appleLanguage": code, "appleLocale": code, "storeLocale": code}


class ScreenshotMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        (self.root / "AppStore").mkdir()
        (self.root / "AppStore" / "app.json").write_text("{}", encoding="utf-8")
        self.write(languages=["ja", "en"])

    def write(self, languages: list[str], display_types: dict | None = None) -> None:
        store = self.root / "AppStore"
        (store / "languages.json").write_text(json.dumps({"languages": [language(code) for code in languages]}), encoding="utf-8")
        (store / "screenshots.json").write_text(
            json.dumps({"scenes": [{"file": "01_home", "scene": "home"}], "displayTypes": display_types or DISPLAY_TYPES}),
            encoding="utf-8",
        )

    def run_config(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CONFIG), "display-types", *arguments],
            capture_output=True,
            text=True,
            env={"APP_STORE_ROOT": str(self.root), "PATH": "/usr/bin:/bin"},
            check=False,
        )

    def matrix(self, *arguments: str) -> dict:
        result = self.run_config(*arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def jobs(self, matrix: dict) -> list[tuple[str, str, str]]:
        return [(job["display_type"], job["languages"], job["artifact"]) for job in matrix["capture"]]

    def test_default_is_one_at_a_time_without_splitting(self) -> None:
        matrix = self.matrix("")
        self.assertEqual(matrix["max_parallel"], 1)
        self.assertEqual(matrix["merge"], [])
        self.assertEqual(self.jobs(matrix), [
            ("APP_IPHONE_67", "", "screenshots-APP_IPHONE_67"),
            ("APP_IPHONE_DUO", "", "screenshots-APP_IPHONE_DUO"),
            ("APP_IPAD_PRO_3GEN_129", "", "screenshots-APP_IPAD_PRO_3GEN_129"),
        ])
        self.assertEqual([job["label"] for job in matrix["capture"]], ["iPhone 6.9 inch", "iPhone Duo", "iPad 13 inch"])
        self.assertEqual([entry["display_type"] for entry in matrix["derive"]], ["APP_IPHONE_61"])

    def test_up_to_the_number_of_display_types_does_not_split(self) -> None:
        matrix = self.matrix("", "--max-parallel", "3", "--languages", "ja")
        self.assertEqual(matrix["max_parallel"], 3)
        self.assertEqual(matrix["merge"], [])
        # 分けないときの言語は入力のまま
        self.assertEqual([job["languages"] for job in matrix["capture"]], ["ja", "ja", "ja"])

    def test_spare_slots_split_languages_in_screenshots_json_order(self) -> None:
        self.write(languages=[f"l{index:02}" for index in range(12)])
        # 入力の順（司令塔は名前の順に並べて送る）ではなく、screenshots.json の順（iPhone Duo → 6.9 inch → iPad）に配る
        matrix = self.matrix("APP_IPAD_PRO_3GEN_129,APP_IPHONE_61,APP_IPHONE_67,APP_IPHONE_DUO", "--max-parallel", "5")
        first, second = ",".join(f"l{index:02}" for index in range(6)), ",".join(f"l{index:02}" for index in range(6, 12))
        self.assertEqual(self.jobs(matrix), [
            ("APP_IPAD_PRO_3GEN_129", "", "screenshots-APP_IPAD_PRO_3GEN_129"),
            ("APP_IPHONE_67", first, "screenshots-APP_IPHONE_67-part1"),
            ("APP_IPHONE_67", second, "screenshots-APP_IPHONE_67-part2"),
            ("APP_IPHONE_DUO", first, "screenshots-APP_IPHONE_DUO-part1"),
            ("APP_IPHONE_DUO", second, "screenshots-APP_IPHONE_DUO-part2"),
        ])
        self.assertEqual([entry["display_type"] for entry in matrix["merge"]], ["APP_IPHONE_67", "APP_IPHONE_DUO"])
        self.assertEqual(matrix["capture"][1]["label"], "iPhone 6.9 inch 1/2")

    def test_never_more_jobs_than_max_parallel(self) -> None:
        for count in (1, 2, 5, 12):
            self.write(languages=[f"l{index}" for index in range(count)])
            for max_parallel in range(1, 6):
                with self.subTest(languages=count, max_parallel=max_parallel):
                    matrix = self.matrix("", "--max-parallel", str(max_parallel))
                    self.assertLessEqual(len(matrix["capture"]), max(max_parallel, 3))
                    if max_parallel >= 3:
                        # 枠が足りていれば、言語の数を超えない範囲で枠を使い切る
                        self.assertEqual(len(matrix["capture"]), min(max_parallel, 3 * count))
                    # 表示サイズごとに、どの言語もちょうど 1 回ずつ撮る
                    for name in ("APP_IPHONE_67", "APP_IPHONE_DUO", "APP_IPAD_PRO_3GEN_129"):
                        groups = [job["languages"] for job in matrix["capture"] if job["display_type"] == name]
                        codes = [code for group in groups for code in group.split(",") if code]
                        self.assertEqual(codes, [] if groups == [""] else [f"l{index}" for index in range(count)])

    def test_uneven_languages_put_the_extra_one_first(self) -> None:
        self.write(languages=["a", "b", "c", "d", "e"], display_types={"APP_IPHONE_67": DISPLAY_TYPES["APP_IPHONE_67"]})
        matrix = self.matrix("", "--max-parallel", "2")
        self.assertEqual([job["languages"] for job in matrix["capture"]], ["a,b,c", "d,e"])

    def test_one_display_type_can_use_all_slots(self) -> None:
        self.write(languages=[f"l{index}" for index in range(12)])
        # 6.3 inch だけを頼んでも、元の 6.9 inch を撮る。撮る表示サイズは 1 つなので、5 本の枠で言語を 5 つに分ける
        matrix = self.matrix("APP_IPHONE_61", "--max-parallel", "5")
        self.assertEqual([job["artifact"] for job in matrix["capture"]], [f"screenshots-APP_IPHONE_67-part{index}" for index in range(1, 6)])
        self.assertEqual([job["languages"].count(",") + 1 for job in matrix["capture"]], [3, 3, 2, 2, 2])
        self.assertEqual([entry["display_type"] for entry in matrix["derive"]], ["APP_IPHONE_61"])

    def test_selected_languages_are_split(self) -> None:
        self.write(languages=["ja", "en", "fr", "de"], display_types={"APP_IPHONE_67": DISPLAY_TYPES["APP_IPHONE_67"]})
        matrix = self.matrix("", "--max-parallel", "2", "--languages", "fr,ja")
        self.assertEqual([job["languages"] for job in matrix["capture"]], ["fr", "ja"])

    def test_rejects_out_of_range(self) -> None:
        for value in ("0", "6"):
            with self.subTest(max_parallel=value):
                result = self.run_config("", "--max-parallel", value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("max_parallel は 1〜5", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
