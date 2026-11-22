#!/usr/bin/env python3
"""書き出しの結果（report.json と画像）を確かめる。self-test.yml と test-creative-render.sh が使う。

    python3 tools/tests/creative/check_report.py <report.json> <画像のフォルダ> <言語,…> [期待する問題のコード,…]

すべての言語に 2 枚の画像（寸法どおり・アルファなし）があり、failure が無く、問題のコードが期待どおりかを確かめる。
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

SIZES = {"product-page-header.png": (3840, 1646), "search-results.png": (3840, 2560)}
#: ファイルの名前 → report.json の種類（AskHub の司令塔が読む形）
KINDS = {"product-page-header.png": "productPageHeader", "search-results.png": "searchResults"}


def main() -> int:
    report_path, out, locales = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3].split(",")
    expected = sorted(filter(None, sys.argv[4].split(","))) if len(sys.argv) > 4 else []
    report = json.loads(report_path.read_text(encoding="utf-8"))
    failures = []
    if report.get("failure"):
        failures.append(f"failure: {report['failure']}")
    for locale in locales:
        for name, size in SIZES.items():
            path = out / locale / name
            if not path.is_file():
                failures.append(f"{locale}/{name} がありません")
                continue
            records = [image for image in report.get("images", [])
                       if image.get("locale") == locale and image.get("kind") == KINDS[name] and image.get("file") == f"{locale}/{name}"]
            if len(records) != 1:
                failures.append(f"report.json に {locale}/{name} の記録が 1 つでない（{len(records)} 個）")
            head = path.read_bytes()[:26]
            width, height = struct.unpack(">II", head[16:24])
            if (width, height) != size or head[25] != 2:
                failures.append(f"{locale}/{name} が {width}x{height}・色の種類 {head[25]} です")
    codes = sorted({problem["code"] for problem in report.get("problems", [])} |
                   {problem["code"] for image in report.get("images", []) for problem in image.get("problems", [])})
    if codes != expected:
        failures.append(f"問題のコードが {codes} です（期待は {expected}）")
    for failure in failures:
        print(f"FAIL {failure}")
    if failures:
        return 1
    print(f"ok   {len(locales)} 言語・{len(locales) * len(SIZES)} 枚。問題 {codes or 'なし'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
