#!/usr/bin/env python3
"""クリエイティブアセット（プロダクトページのヘッダー・検索結果）を、案と 6.9 inch のスクショから書き出す。

app-creative-assets.yml が macOS のランナーで流す（Chrome・xcrun swiftc が要る）。

    python3 tools/creative/render_creative.py \\
      --spec spec.json \\
      --screenshots build/screenshots/APP_IPHONE_67 \\   # <撮影の言語>/<画面>.png（app-kit の撮影の artifact と同じ形）
      --icon AppIcon.png \\                              # 無ければ省く（検索結果のアプリ名の横に載せない）
      --out build/creative \\                            # <言語>/product-page-header.png・search-results.png を書く
      --report build/creative-report/report.json

文字のはみ出し・安全領域の外の文字・読めない画面は、画像を書き出したうえで report.json に書く（司令塔が AskHub の画面に出す）。
案の形の誤り・Chrome が動かない・画像の寸法が合わないときは、report.json に failure を書いて 1 で終わる。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from creative_spec import SpecError, validate  # noqa: E402

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "creative.html"
REMOVE_ALPHA = HERE.parent / "screenshots" / "remove_alpha.swift"
DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

#: 種類ごとの寸法と、書き出すファイルの名前（司令塔の取り込みと同じ）
KINDS = {
    "productPageHeader": {"size": (3840, 1646), "file": "product-page-header.png"},
    "searchResults": {"size": (3840, 2560), "file": "search-results.png"},
}
#: Chrome の 1 回の起動の待ちの上限（秒）
CHROME_TIMEOUT = 120
REPORT = re.compile(r'data-report="([^"]*)"')


class RenderError(RuntimeError):
    """書き出せなかった（report.json の failure に書く）"""


def png_info(path: Path) -> tuple[int, int, int]:
    """PNG の幅・高さ・色の種類（2 は RGB でアルファなし、6 は RGBA）"""
    with path.open("rb") as file:
        head = file.read(26)
    if len(head) < 26 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise RenderError(f"{path.name} が PNG ではありません")
    width, height = struct.unpack(">II", head[16:24])
    return width, height, head[25]


def chrome(binary: str, profile: Path, url: str, size: tuple[int, int], *extra: str) -> str:
    command = [
        binary, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
        "--disable-extensions", "--mute-audio", "--force-device-scale-factor=1", "--force-color-profile=srgb",
        "--allow-file-access-from-files", f"--user-data-dir={profile}", "--virtual-time-budget=5000",
        f"--window-size={size[0]},{size[1]}", *extra, url,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=CHROME_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RenderError(f"Chrome を動かせません: {error}") from error
    if result.returncode != 0:
        raise RenderError(f"Chrome が {result.returncode} で終わりました: {result.stderr.strip()[-500:]}")
    return result.stdout


def compile_remove_alpha(work: Path) -> Path:
    binary = work / "remove_alpha"
    try:
        subprocess.run(["xcrun", "swiftc", "-O", str(REMOVE_ALPHA), "-o", str(binary)], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        raise RenderError(f"remove_alpha をコンパイルできません: {detail.strip()[-500:]}") from error
    return binary


def prepare(spec: dict, screenshots: Path, icon: Path | None, work: Path) -> dict[str, list[dict]]:
    """雛形・案・画面・アイコンを Chrome で開くフォルダに置く。足りない画面を、撮影の言語ごとの problems で返す"""
    shutil.copy(TEMPLATE, work / "creative.html")
    payload = json.dumps(spec, ensure_ascii=False)
    (work / "spec.js").write_text(
        f"window.CREATIVE_SPEC = {payload};\nwindow.CREATIVE_ICON = {json.dumps(icon is not None)};\n", encoding="utf-8")
    if icon is not None:
        shutil.copy(icon, work / "icon.png")
    missing: dict[str, list[dict]] = {}
    names = sorted(set(spec["screens"]["header"]) | set(spec["screens"]["search"]))
    for folder in sorted({locale["screenshots"] for locale in spec["locales"]}):
        (work / "screens" / folder).mkdir(parents=True, exist_ok=True)
        for name in names:
            source = screenshots / folder / f"{name}.png"
            if source.is_file() and not source.is_symlink():
                shutil.copy(source, work / "screens" / folder / source.name)
            else:
                missing.setdefault(folder, []).append({"code": "image-missing", "message": f"撮影の {folder}/{name}.png がありません"})
    return missing


def render(args: argparse.Namespace) -> dict:
    try:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        spec_problems = validate(spec)
    except (OSError, json.JSONDecodeError) as error:
        raise RenderError(f"案を読めません: {error}") from error
    except SpecError as error:
        raise RenderError(f"案の形が合いません: {error}") from error

    screenshots = Path(args.screenshots)
    icon = Path(args.icon) if args.icon else None
    if icon is not None:
        if not icon.is_file():
            raise RenderError(f"アイコン {icon} がありません")
        png_info(icon)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary) / "page"
        work.mkdir()
        profile = Path(temporary) / "profile"
        remove_alpha = Path(args.remove_alpha) if args.remove_alpha else compile_remove_alpha(Path(temporary))
        missing = prepare(spec, screenshots, icon, work)

        images = []
        for locale in spec["locales"]:
            code = locale["locale"]
            (out / code).mkdir(exist_ok=True)
            for kind, info in KINDS.items():
                size = info["size"]
                url = (work / "creative.html").as_uri() + f"?kind={kind}&locale={code}"
                target = out / code / info["file"]
                chrome(args.chrome, profile, url, size, f"--screenshot={target}")
                dom = chrome(args.chrome, profile, url, size, "--dump-dom")
                match = REPORT.search(dom)
                if match is None:
                    raise RenderError(f"{code} の {kind} の検査の結果を読めません（雛形が終わりまで動いていない）")
                page = json.loads(html.unescape(match.group(1)))
                if not target.is_file():
                    raise RenderError(f"{code} の {kind} の画像が書き出されませんでした")
                subprocess.run([str(remove_alpha), str(target)], check=True)
                width, height, color = png_info(target)
                if (width, height) != size:
                    raise RenderError(f"{target} の寸法が {width}x{height} です（{size[0]}x{size[1]} のはず）")
                if color != 2:
                    raise RenderError(f"{target} にアルファが残っています（PNG の色の種類 {color}）")
                problems = page.get("problems", []) + missing.get(locale["screenshots"], [])
                images.append({
                    "locale": code,
                    "kind": kind,
                    "file": f"{code}/{info['file']}",
                    "width": width,
                    "height": height,
                    "problems": problems,
                    "texts": page.get("texts", []),
                })
                status = "ok" if not problems else f"{len(problems)} 件の問題"
                print(f"{code} {kind}: {status}")
                for item in problems:
                    print(f"::warning::{code} {kind}: {item['message']}")
    return {"v": 1, "problems": spec_problems, "images": images, "failure": None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--screenshots", required=True)
    parser.add_argument("--icon", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--chrome", default=os.environ.get("CHROME") or DEFAULT_CHROME)
    parser.add_argument("--remove-alpha", default="", help="コンパイル済みの remove_alpha（省くとここでコンパイルする）")
    args = parser.parse_args()

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = render(args)
        code = 0
    except (RenderError, subprocess.CalledProcessError) as error:
        print(f"::error::{error}", file=sys.stderr)
        report = {"v": 1, "problems": [], "images": [], "failure": str(error)}
        code = 1
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
