#!/bin/bash
#
# 署名なしの Archive の中の、同梱のフレームワーク（本体と App Extension の Frameworks/）の署名の識別子を、Info.plist の CFBundleIdentifier に直す。
# 静的な xcframework（Firebase・Google Mobile Ads など）は、Xcode が同梱するときにバイナリを外して空のスタブを差し込む。
# スタブはリンカーの仮の署名のままで識別子が arm64-apple になり、Export がこの識別子のまま再署名するので、
# App Store Connect が Invalid Signature で弾く。識別子が違うものを、正しい識別子でアドホック署名し直す（本番の署名は Export がする）。
#
# 使い方:
#   tools/fix-stub-framework-signatures.sh <.xcarchive のパス>
set -euo pipefail

archive="${1:?usage: $0 <path to .xcarchive>}"
app_path=$(/usr/libexec/PlistBuddy -c 'Print :ApplicationProperties:ApplicationPath' "$archive/Info.plist")
app="$archive/Products/$app_path"

# Frameworks/ の直下のフレームワーク（本体と、PlugIns/ などの中の App Extension のもの）。フレームワークの中は辿らない
frameworks=()
while IFS= read -r -d '' framework; do
  frameworks+=("$framework")
done < <(find "$app" -type d -name '*.framework' -prune -path '*/Frameworks/*' -print0)
if [[ ${#frameworks[@]} -eq 0 ]]; then
  echo "同梱のフレームワークはありません"
  exit 0
fi

fixed=0
for framework in "${frameworks[@]}"; do
  bundle_id=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$framework/Info.plist")
  identifier=$(codesign -dv "$framework" 2>&1 | sed -n 's/^Identifier=//p')
  if [[ "$identifier" != "$bundle_id" ]]; then
    codesign --force --sign - --identifier "$bundle_id" "$framework"
    echo "${framework#"$app"/}: 署名の識別子を ${identifier:-（署名なし）} から $bundle_id に直しました"
    fixed=$((fixed + 1))
  fi
done
echo "署名の識別子を直したフレームワーク: ${fixed} 個"
