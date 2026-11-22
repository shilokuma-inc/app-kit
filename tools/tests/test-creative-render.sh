#!/bin/bash
#
# クリエイティブアセットの書き出し（tools/creative/render_creative.py）を、仮の画面と見本の案で確かめる。
# self-test.yml が macOS で流す（Chrome・xcrun swiftc が要る）。手元の Mac でも流せる。
#   - 見本の案は問題なく書き出せる。同じ入力なら、バイト単位で同じ画像になる
#   - はみ出す文言・無い画面・Apple の決まりに合わない文言は、書き出したうえで report.json に出る
#   - 形の合わない案は、failure を書いて 1 で終わる
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
render="$root/tools/creative/render_creative.py"
check="$root/tools/tests/creative/check_report.py"
spec="$root/tools/tests/creative/spec.json"
icon="$root/fixtures/App/FixtureApp/Assets.xcassets/AppIcon.appiconset/AppIcon.png"

python3 "$root/tools/tests/creative/make_screens.py" "$work/screens" ja,en 01_home,02_detail,03_settings
xcrun swiftc -O "$root/tools/screenshots/remove_alpha.swift" -o "$work/remove_alpha"
run() {
  python3 "$render" --remove-alpha "$work/remove_alpha" --screenshots "$work/screens" "$@"
}

echo "== 見本の案"
run --spec "$spec" --icon "$icon" --out "$work/a" --report "$work/a.json" > /dev/null
python3 "$check" "$work/a.json" "$work/a" ja,en-US

echo "== 同じ入力なら同じ画像"
run --spec "$spec" --icon "$icon" --out "$work/b" --report "$work/b.json" > /dev/null
if diff -r "$work/a" "$work/b" > /dev/null; then
  echo "ok   2 回の書き出しがバイト単位で同じ"
else
  echo "FAIL 2 回の書き出しで画像が違う"
  exit 1
fi

echo "== はみ出す文言・無い画面・決まりに合わない文言"
python3 - "$spec" "$work/problems.json" <<'PY'
import json, sys
spec = json.load(open(sys.argv[1], encoding="utf-8"))
english = spec["locales"][1]
english["header"]["title"] = "Pneumonoultramicroscopicsilicovolcanoconiosis wow"
english["search"]["title"] = "Free for everyone"
spec["screens"]["search"] = ["01_home", "09_missing"]
json.dump(spec, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
PY
run --spec "$work/problems.json" --out "$work/c" --report "$work/c.json" > /dev/null
python3 "$check" "$work/c.json" "$work/c" ja,en-US forbidden-price,image-missing,text-overflow

echo "== 形の合わない案"
echo '{"v": 1, "layout": "standard", "colors": {}, "screens": {}, "locales": []}' > "$work/bad.json"
if run --spec "$work/bad.json" --out "$work/d" --report "$work/d.json" > /dev/null 2>&1; then
  echo "FAIL 形の合わない案で 0 で終わった"
  exit 1
fi
if jq -e '.failure | test("案の形が合いません")' "$work/d.json" > /dev/null; then
  echo "ok   形の合わない案は failure を書いて止まる"
else
  echo "FAIL report.json に failure が無い"
  exit 1
fi

echo "すべて合いました"
