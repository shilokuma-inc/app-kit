#!/usr/bin/env python3
"""撮影の matrix（app_store_config.py の display-types）の確かめ。self-test.yml が ubuntu で流す。

手元では `python3 tools/tests/test-screenshot-matrix.py`。max_parallel と、撮る表示サイズ・言語の数の組み合わせで、
撮影のジョブの数が max_parallel を超えないこと、言語の分け方、artifact の名前、merge の対象を確かめる。
表示サイズから決める Simulator のプラットフォーム（iOS / visionOS）と、撮れない表示サイズを断ることも確かめる。
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

# template-app-visionos と同じ（表示サイズは Apple Vision Pro の 1 つだけ）
VISION_DISPLAY_TYPES = {
    "APP_APPLE_VISION_PRO": {"label": "Apple Vision Pro", "devices": ["Apple Vision Pro"], "sizes": ["3840x2160"]},
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

    def run_config(self, *arguments: str, command: str = "display-types") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CONFIG), command, *arguments],
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

    def test_iphone_and_ipad_are_captured_on_ios(self) -> None:
        matrix = self.matrix("", "--max-parallel", "5")
        self.assertEqual({job["platform"] for job in matrix["capture"]}, {"iOS"})

    def test_apple_vision_pro_is_captured_on_visionos(self) -> None:
        self.write(languages=["ja", "en"], display_types=VISION_DISPLAY_TYPES)
        matrix = self.matrix("")
        self.assertEqual(matrix["capture"], [{
            "display_type": "APP_APPLE_VISION_PRO",
            "platform": "visionOS",
            "runs_on": "macos-latest",
            "xcode_version": "26.6",
            "label": "Apple Vision Pro",
            "languages": "",
            "artifact": "screenshots-APP_APPLE_VISION_PRO",
        }])
        self.assertEqual(matrix["derive"], [])
        # 表示サイズが 1 つなので、余った枠で言語を分ける（iOS と同じ）
        matrix = self.matrix("", "--max-parallel", "2")
        self.assertEqual(
            [(job["platform"], job["languages"], job["artifact"]) for job in matrix["capture"]],
            [
                ("visionOS", "ja", "screenshots-APP_APPLE_VISION_PRO-part1"),
                ("visionOS", "en", "screenshots-APP_APPLE_VISION_PRO-part2"),
            ],
        )

    def test_platform_command(self) -> None:
        self.write(languages=["ja"], display_types={**DISPLAY_TYPES, **VISION_DISPLAY_TYPES})
        for name, expected in (("APP_IPHONE_67", "iOS"), ("APP_IPAD_PRO_3GEN_129", "iOS"), ("APP_APPLE_VISION_PRO", "visionOS")):
            with self.subTest(display_type=name):
                result = self.run_config(name, command="platform")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)

    def test_rejects_display_types_that_cannot_be_captured(self) -> None:
        # Mac などは撮れないので、撮影（macOS のランナー）の前に plan で止める
        self.write(languages=["ja"], display_types={
            **DISPLAY_TYPES,
            "APP_DESKTOP": {"label": "Mac", "devices": ["Mac"], "sizes": ["2880x1800"]},
        })
        for arguments in (("",), ("APP_DESKTOP",)):
            with self.subTest(display_types=arguments[0]):
                result = self.run_config(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("APP_DESKTOP は撮れない表示サイズ", result.stderr)
        # 撮れる表示サイズだけを指定すれば撮れる
        self.assertEqual([job["display_type"] for job in self.matrix("APP_IPHONE_67")["capture"]], ["APP_IPHONE_67"])

    def test_rejects_out_of_range(self) -> None:
        for value in ("0", "6"):
            with self.subTest(max_parallel=value):
                result = self.run_config("", "--max-parallel", value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("max_parallel は 1〜5", result.stderr)

    def write_entries(self, entries: list[dict]) -> None:
        (self.root / "AppStore" / "languages.json").write_text(json.dumps({"languages": entries}), encoding="utf-8")

    def test_assets_from_languages_are_not_captured(self) -> None:
        # ninjacord-ios と同じ形（en-GB・es-MX は en の画像を流用し、appleLanguage・appleLocale を持たない）
        self.write_entries([
            language("ja"),
            language("en"),
            {"language": "en-GB", "storeLocale": "en-GB", "assetsFrom": "en"},
            {"language": "es-MX", "storeLocale": "es-MX", "assetsFrom": "en"},
        ])
        result = self.run_config("", command="languages")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([line.split("\t")[0] for line in result.stdout.splitlines()], ["ja", "en"])
        # 流用する言語だけを指定したら、流用元を撮る
        result = self.run_config("en-GB,es-MX", command="languages")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([line.split("\t")[0] for line in result.stdout.splitlines()], ["en"])
        # 撮影の matrix の言語の分け方も、撮る言語（ja・en）で数える
        matrix = self.matrix("APP_IPHONE_67", "--max-parallel", "2")
        self.assertEqual([job["languages"] for job in matrix["capture"]], ["ja", "en"])

    def test_selected_languages_do_not_check_other_languages(self) -> None:
        # 一部の言語を撮り直すときは、撮らない言語の設定の不備で止めない（全言語のときは止める）
        self.write_entries([
            language("ja"),
            language("en"),
            {"language": "fr", "storeLocale": "fr-FR"},
            {"language": "en-GB", "storeLocale": "en-GB", "assetsFrom": "en-US"},
        ])
        result = self.run_config("ja,en", command="languages")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([line.split("\t")[0] for line in result.stdout.splitlines()], ["ja", "en"])
        result = self.run_config("", command="languages")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fr に appleLanguage, appleLocale がありません", result.stderr)
        self.assertIn("en-GB の assetsFrom（en-US）が", result.stderr)

    def test_rejects_wrong_assets_from(self) -> None:
        cases = {
            "流用元が無い": ([language("ja"), {"language": "en-GB", "storeLocale": "en-GB", "assetsFrom": "en"}], "en-GB の assetsFrom（en）が"),
            "流用元も流用する": ([
                language("en"),
                {"language": "en-GB", "storeLocale": "en-GB", "assetsFrom": "en"},
                {"language": "en-AU", "storeLocale": "en-AU", "assetsFrom": "en-GB"},
            ], "en-AU の assetsFrom（en-GB）も流用する言語"),
            "流用する言語に撮影の設定": ([language("en"), {"language": "en-GB", "storeLocale": "en-GB", "assetsFrom": "en", "appleLocale": "en_GB"}],
                                     "en-GB は en の画像を流用するので appleLocale は書かない"),
            "撮る言語に撮影の設定が無い": ([{"language": "ja", "storeLocale": "ja"}], "ja に appleLanguage, appleLocale がありません"),
        }
        for name, (entries, message) in cases.items():
            with self.subTest(name):
                self.write_entries(entries)
                result = self.run_config("", command="languages")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
