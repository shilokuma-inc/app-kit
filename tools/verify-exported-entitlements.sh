#!/bin/bash
#
# entitlements のファイル（環境変数 ENTITLEMENTS_PATH）に書いた項目が、書き出した IPA のアプリにも入っているかを確かめる。
# 欠けたまま配信すると、ビルドも Upload も通るのに、実機でその機能だけ動かない。
# 比べるのは項目の有無だけ（aps-environment のように、Export が値を配信用に書き換える項目があるため）。
# 値は、展開されていない変数 $(…) が残っていないかだけを見る。
#
# 使い方:
#   tools/verify-exported-entitlements.sh <IPA を書き出したフォルダ>
set -euo pipefail

export_dir="${1:?usage: $0 <export directory>}"
if [[ -z "${ENTITLEMENTS_PATH:-}" ]]; then
  echo "entitlements のファイルはありません"
  exit 0
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
ipa=$(find "$export_dir" -maxdepth 1 -name '*.ipa' | head -1)
if [[ -z "$ipa" ]]; then
  echo "::error::書き出した IPA が見つかりません: $export_dir"
  exit 1
fi
unzip -q "$ipa" -d "$work"
app=$(find "$work/Payload" -maxdepth 1 -name '*.app' | head -1)
codesign -d --entitlements - --xml "$app" > "$work/exported.plist"
echo "書き出した IPA の entitlements:"
plutil -p "$work/exported.plist"

python3 - "$ENTITLEMENTS_PATH" "$work/exported.plist" <<'PY'
import plistlib
import sys

with open(sys.argv[1], "rb") as file:
    wanted = plistlib.load(file)
with open(sys.argv[2], "rb") as file:
    exported = plistlib.load(file)
missing = [key for key in wanted if key not in exported]
if missing:
    print("::error::書き出した IPA に入っていない entitlement: " + ", ".join(missing))
    sys.exit(1)
unexpanded = [key for key, value in exported.items() if "$(" in repr(value)]
if unexpanded:
    print("::error::書き出した IPA の entitlement に、展開されていない変数 $(…) が残っています: " + ", ".join(unexpanded))
    sys.exit(1)
print("entitlements のファイルの項目は、すべて入っています: " + ", ".join(wanted))
PY
