#!/bin/bash
#
# 署名なし（CODE_SIGNING_ALLOWED=NO）の Archive のアプリに、プロジェクトの entitlements のファイル（CODE_SIGN_ENTITLEMENTS）を入れる。
# 署名なしの Archive にはこのファイルが入らず、Export は Archive の中のアプリを再署名するだけなので、そのままでは配信ビルドに
# 基本の entitlement（application-identifier など）しか付かず、WeatherKit などが実機で動かない。
# entitlements のファイルでアプリをアドホック署名しておく（本番の署名は Export がする）。対象はアプリ本体だけ（App Extension は入れない）。
# ファイルの中の $(AppIdentifierPrefix) のような変数は、ここでは展開されない。残ったまま書き出されたら verify-exported-entitlements.sh で落ちる。
#
# 使い方（環境変数 APP_KIT_PROJECT・APP_KIT_SCHEME・SDK を読む）:
#   tools/embed-entitlements.sh <.xcarchive のパス>
#
# GITHUB_ENV があれば、entitlements のファイルのパスを ENTITLEMENTS_PATH に書く（無ければ空）。
set -euo pipefail

archive="${1:?usage: $0 <path to .xcarchive>}"
: "${APP_KIT_PROJECT:?}" "${APP_KIT_SCHEME:?}" "${SDK:?}"

# ビルドの設定を読めなかったら止める（パイプにつなぐと失敗が隠れて「ファイルなし」の扱いになり、確かめも飛ばされる）
log=$(mktemp)
if ! settings=$(xcodebuild -showBuildSettings \
  -project "$APP_KIT_PROJECT" \
  -scheme "$APP_KIT_SCHEME" \
  -sdk "$SDK" \
  -configuration Release 2>"$log"); then
  cat "$log"
  echo "::error::ビルドの設定（CODE_SIGN_ENTITLEMENTS）を読めませんでした"
  exit 1
fi

entitlements=$(printf '%s\n' "$settings" | sed -n 's/^ *CODE_SIGN_ENTITLEMENTS = //p' | head -1)
if [[ -n "${GITHUB_ENV:-}" ]]; then
  echo "ENTITLEMENTS_PATH=$entitlements" >> "$GITHUB_ENV"
fi
if [[ -z "$entitlements" ]]; then
  echo "entitlements のファイルはありません"
  exit 0
fi

app_path=$(/usr/libexec/PlistBuddy -c 'Print :ApplicationProperties:ApplicationPath' "$archive/Info.plist")
app="$archive/Products/$app_path"
codesign --force --sign - --entitlements "$entitlements" "$app"
echo "アプリに入れた entitlements (${entitlements}):"
codesign -d --entitlements - --xml "$app" | plutil -p -
