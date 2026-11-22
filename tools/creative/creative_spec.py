#!/usr/bin/env python3
"""クリエイティブアセットの案（schema/creative-spec.schema.json）を確かめる。

案は AskHub の司令塔が、ワークフローの入力（spec）に JSON の文字列で渡す。public のリポジトリの実行の入力なので、
形・長さ・使える文字をここで確かめてから雛形に渡す（雛形は文字として描くだけで、HTML としては読まない）。

    python3 tools/creative/creative_spec.py spec.json   # 確かめて、問題（直さなくても書き出せるもの）を JSON で出す

形の誤りは SpecError で止める。文言の決まり（URL・価格・記号）と色のコントラストは、書き出しは止めずに problems で返す
（人が AskHub の画面で確かめる。司令塔も送る前に同じことを確かめる）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

#: 雛形の配置の種類
LAYOUTS = {"standard"}
#: 色の名前（必須・任意）
REQUIRED_COLORS = ("background", "accent", "text")
OPTIONAL_COLORS = ("background2", "highlight")
#: 1 つの案に持てる言語の数（App Store Connect の言語は 40 前後）
MAX_LOCALES = 50

LOCALE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8}){0,2}$")
FOLDER = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
SCREEN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
CONTROL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")

#: 文言の長さの上限（文字数）。Apple は「短いフレーズ」とだけ書いているので、長い言語でも収まる程度にする
LIMITS = {
    "appName": 30,
    "header.title": 60,
    "header.subtitle": 90,
    "search.title": 60,
    "search.chips": 30,
}
#: 文言に入れられる改行の数（見出しと一文は 2 行・検索結果の見出しは 3 行まで。アプリ名とチップは 1 行）
NEWLINES = {
    "appName": 0,
    "header.title": 1,
    "header.subtitle": 1,
    "search.title": 2,
    "search.chips": 0,
}

#: Apple の決まりで入れられない文字（価格・URL・著作権の記号など）。見つけたら problems に出す
FORBIDDEN = [
    ("url", re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(com|net|org|jp|app|io)\b)", re.IGNORECASE), "URL"),
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "メールアドレス"),
    ("symbol", re.compile(r"[©®™℗]"), "著作権・商標の記号"),
    ("price", re.compile(r"([¥$€£₩₹]\s?\d|\d\s?(円|ドル|元|원)|\bfree\b|無料)", re.IGNORECASE), "価格"),
]


class SpecError(ValueError):
    """書き出せない案（形の誤り）"""


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise SpecError(message)


def _keys(value: dict, name: str, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> None:
    _expect(isinstance(value, dict), f"{name} はオブジェクトにしてください")
    missing = [key for key in required if key not in value]
    _expect(not missing, f"{name} に {', '.join(missing)} がありません")
    unknown = sorted(set(value) - set(required) - set(optional))
    _expect(not unknown, f"{name} に知らない欄があります: {', '.join(unknown)}")


def _text(value: object, name: str, limit: int, newlines: int, *, allow_empty: bool = False) -> str:
    _expect(isinstance(value, str), f"{name} は文字列にしてください")
    text = value
    _expect(allow_empty or text.strip() != "", f"{name} が空です")
    _expect(len(text) <= limit, f"{name} が長すぎます（{len(text)} 文字。{limit} 文字まで）")
    _expect(not CONTROL.search(text), f"{name} に制御文字があります")
    _expect(text.count("\n") <= newlines, f"{name} の改行が多すぎます（{newlines} つまで）")
    _expect(text.count("*") % 2 == 0, f"{name} の強調の * が閉じていません")
    return text


def _luminance(color: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    """WCAG のコントラスト比"""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def validate(spec: object) -> list[dict]:
    """案を確かめる。形の誤りは SpecError、書き出せる問題は problems（[{code, message}]）で返す"""
    _keys(spec, "案", ("v", "layout", "colors", "screens", "locales"))
    _expect(spec["v"] == 1, f"案の v は 1 にしてください（{spec['v']!r}）")
    _expect(spec["layout"] in LAYOUTS, f"layout は {', '.join(sorted(LAYOUTS))} のどれかにしてください")

    colors = spec["colors"]
    _keys(colors, "colors", REQUIRED_COLORS, OPTIONAL_COLORS)
    for key, value in colors.items():
        _expect(isinstance(value, str) and COLOR.match(value) is not None, f"colors.{key} は #RRGGBB にしてください")

    screens = spec["screens"]
    _keys(screens, "screens", ("header", "search"))
    for key, most in (("header", 3), ("search", 2)):
        names = screens[key]
        _expect(isinstance(names, list) and 1 <= len(names) <= most, f"screens.{key} は 1〜{most} 個の画面にしてください")
        for name in names:
            _expect(isinstance(name, str) and SCREEN.match(name) is not None, f"screens.{key} の画面の名前が不正です: {name!r}")

    locales = spec["locales"]
    _expect(isinstance(locales, list) and 1 <= len(locales) <= MAX_LOCALES, f"locales は 1〜{MAX_LOCALES} 個にしてください")
    seen = set()
    texts: list[tuple[str, str]] = []
    for index, locale in enumerate(locales):
        name = f"locales[{index}]"
        _keys(locale, name, ("locale", "screenshots", "appName", "header", "search"))
        code = locale["locale"]
        _expect(isinstance(code, str) and LOCALE.match(code) is not None, f"{name}.locale が不正です: {code!r}")
        _expect(code not in seen, f"言語 {code} が重なっています")
        seen.add(code)
        folder = locale["screenshots"]
        _expect(isinstance(folder, str) and FOLDER.match(folder) is not None, f"{code} の screenshots が不正です: {folder!r}")
        texts.append((f"{code}.appName", _text(locale["appName"], f"{code}.appName", LIMITS["appName"], NEWLINES["appName"])))

        header = locale["header"]
        _keys(header, f"{code}.header", ("title",), ("subtitle",))
        texts.append((f"{code}.header.title", _text(header["title"], f"{code}.header.title", LIMITS["header.title"], NEWLINES["header.title"])))
        if "subtitle" in header:
            texts.append((f"{code}.header.subtitle",
                          _text(header["subtitle"], f"{code}.header.subtitle", LIMITS["header.subtitle"], NEWLINES["header.subtitle"], allow_empty=True)))

        search = locale["search"]
        _keys(search, f"{code}.search", ("title",), ("chips",))
        texts.append((f"{code}.search.title", _text(search["title"], f"{code}.search.title", LIMITS["search.title"], NEWLINES["search.title"])))
        chips = search.get("chips", [])
        _expect(isinstance(chips, list) and len(chips) <= 3, f"{code}.search.chips は 3 つまでにしてください")
        for chip_index, chip in enumerate(chips):
            label = f"{code}.search.chips[{chip_index}]"
            texts.append((label, _text(chip, label, LIMITS["search.chips"], NEWLINES["search.chips"])))

    problems = []
    for label, text in texts:
        for code, pattern, what in FORBIDDEN:
            if pattern.search(text):
                problems.append({"code": f"forbidden-{code}", "message": f"{label} に{what}らしい文字があります（App Store の決まりで入れられません）"})
    for background in {colors["background"], colors.get("background2", colors["background"])}:
        ratio = contrast(colors["text"], background)
        if ratio < 4.5:
            problems.append({"code": "low-contrast", "message": f"文字の色と背景の色 {background} のコントラストが {ratio:.1f} で、4.5 より低いです"})
    return problems


def main() -> int:
    if len(sys.argv) != 2:
        print("使い方: creative_spec.py <案の JSON>", file=sys.stderr)
        return 2
    try:
        spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        problems = validate(spec)
    except (OSError, json.JSONDecodeError, SpecError) as error:
        print(f"::error::案を読めません: {error}", file=sys.stderr)
        return 1
    print(json.dumps(problems, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
