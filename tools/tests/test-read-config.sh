#!/bin/bash
#
# tools/read-config.sh の確かめ。self-test.yml が ubuntu で流す。手元では `bash tools/tests/test-read-config.sh`。
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
reader="$root/tools/read-config.sh"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

failures=0

# 読めて、出力に期待する行がすべてあること
expect_ok() {
  local name="$1" json="$2"
  shift 2
  printf '%s' "$json" > "$work/config.json"
  local output
  if ! output=$("$reader" "$work/config.json" 2>"$work/stderr"); then
    echo "FAIL $name: 読めなかった: $(cat "$work/stderr")"
    failures=$((failures + 1))
    return
  fi
  local line
  for line in "$@"; do
    if ! grep -qxF -- "$line" <<<"$output"; then
      echo "FAIL $name: 出力に「$line」が無い"
      printf '%s\n' "$output" | sed 's/^/    /'
      failures=$((failures + 1))
      return
    fi
  done
  echo "ok   $name"
}

# 断られて、理由に期待する文字があること
expect_error() {
  local name="$1" json="$2" message="$3"
  printf '%s' "$json" > "$work/config.json"
  if "$reader" "$work/config.json" >"$work/stdout" 2>"$work/stderr"; then
    echo "FAIL $name: 断られなかった: $(cat "$work/stdout")"
    failures=$((failures + 1))
    return
  fi
  if ! grep -qF -- "$message" "$work/stderr"; then
    echo "FAIL $name: 理由に「$message」が無い: $(cat "$work/stderr")"
    failures=$((failures + 1))
    return
  fi
  echo "ok   $name"
}

expect_ok "最小の設定" \
  '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"]}' \
  "APP_KIT_PROJECT=App.xcodeproj" "APP_KIT_SCHEME=App" "APP_KIT_PLATFORMS=iOS" "APP_KIT_TEST_PLATFORM=iOS" \
  "APP_KIT_GENERATE=" "APP_KIT_UI_TESTS=" "APP_KIT_XCODE_VERSION=26.6" "APP_KIT_SWIFTLINT=true" "APP_KIT_SWIFT_PACKAGES=" \
  "APP_KIT_ARCHIVE_PLATFORMS=iOS" 'APP_KIT_ARCHIVE_PLATFORMS_JSON=["iOS"]' "APP_KIT_GOOGLE_SERVICE_INFO="

expect_ok "すべての欄" \
  '{"v":1,"project":"Sub/App.xcodeproj","scheme":"App-iOS","platforms":["macOS","iOS","visionOS"],"generate":"xcodegen","uiTests":"AppUITests","xcodeVersion":"27.1","swiftlint":false,"swiftPackages":["Kit","Packages/Core"],"archive":{"platforms":["iOS","macOS"],"googleServiceInfo":"App/GoogleService-Info.plist"},"unmanaged":[".coderabbit.yaml"]}' \
  "APP_KIT_PROJECT=Sub/App.xcodeproj" "APP_KIT_SCHEME=App-iOS" "APP_KIT_PLATFORMS=macOS iOS visionOS" "APP_KIT_TEST_PLATFORM=macOS" \
  "APP_KIT_GENERATE=xcodegen" "APP_KIT_UI_TESTS=AppUITests" "APP_KIT_XCODE_VERSION=27.1" "APP_KIT_SWIFTLINT=false" "APP_KIT_SWIFT_PACKAGES=Kit Packages/Core" \
  "APP_KIT_ARCHIVE_PLATFORMS=iOS macOS" 'APP_KIT_ARCHIVE_PLATFORMS_JSON=["iOS","macOS"]' "APP_KIT_GOOGLE_SERVICE_INFO=App/GoogleService-Info.plist"

expect_ok "null の欄は省いたのと同じ" \
  '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"generate":null,"uiTests":null,"xcodeVersion":null}' \
  "APP_KIT_GENERATE=" "APP_KIT_UI_TESTS=" "APP_KIT_XCODE_VERSION=26.6"

expect_ok "知らない欄は読み飛ばす" \
  '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"future":true}' \
  "APP_KIT_SCHEME=App"

expect_error "空のファイル" '' "設定のファイルが空です"
rm -f "$work/config.json"
if "$reader" "$work/missing.json" >/dev/null 2>"$work/stderr" || ! grep -qF "設定のファイルがありません" "$work/stderr"; then
  echo "FAIL ファイルが無いときに断る"
  failures=$((failures + 1))
else
  echo "ok   ファイルが無いときに断る"
fi

expect_error "JSON でない" '{"v":1,' "JSON として読めません"
expect_error "空白だけ" '  
' "JSON の値を 1 つだけ"
expect_error "値が 2 つ" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"]} {"v":1,"project":"B.xcodeproj","scheme":"B","platforms":["iOS"]}' "JSON の値を 1 つだけ"
expect_error "オブジェクトでない" '[1]' "オブジェクトではありません"
expect_error "v が違う" '{"v":2,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"]}' "v が 1 ではありません"
expect_error "project が無い" '{"v":1,"scheme":"App","platforms":["iOS"]}' "project は"
expect_error "project が .xcodeproj でない" '{"v":1,"project":"App.xcworkspace","scheme":"App","platforms":["iOS"]}' "project は"
expect_error "project が - で始まる" '{"v":1,"project":"-derivedDataPath.xcodeproj","scheme":"App","platforms":["iOS"]}' "project は"
expect_error "project が外を指す" '{"v":1,"project":"Sub/../../App.xcodeproj","scheme":"App","platforms":["iOS"]}' "project は"
expect_error "project が絶対パス" '{"v":1,"project":"/tmp/App.xcodeproj","scheme":"App","platforms":["iOS"]}' "project は"
expect_error "scheme に空白" '{"v":1,"project":"App.xcodeproj","scheme":"My App","platforms":["iOS"]}' "scheme の形"
expect_error "scheme が - で始まる" '{"v":1,"project":"App.xcodeproj","scheme":"-quiet","platforms":["iOS"]}' "scheme の形"
expect_error "platforms が空" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":[]}' "platforms は"
expect_error "知らないプラットフォーム" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["watchOS"]}' "platforms は"
expect_error "プラットフォームが重なる" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS","iOS"]}' "platforms は"
expect_error "generate が違う" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"generate":"tuist"}' "generate は"
# 値にシェルの式を書かれても、形で断る（展開させないため単一引用符のまま渡す）
# shellcheck disable=SC2016
expect_error "uiTests の形" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"uiTests":"$(rm -rf /)"}' "uiTests の形"
expect_error "xcodeVersion の形" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"xcodeVersion":"latest"}' "xcodeVersion の形"
expect_error "swiftlint が文字" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"swiftlint":"yes"}' "swiftlint は"
expect_error "swiftPackages が外を指す" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"swiftPackages":["../Kit"]}' "swiftPackages は"
expect_error "swiftPackages に空白" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"swiftPackages":["My Kit"]}' "swiftPackages は"
expect_ok "Archive の既定は先頭のプラットフォーム" \
  '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["visionOS","iOS"],"archive":{}}' \
  "APP_KIT_ARCHIVE_PLATFORMS=visionOS" 'APP_KIT_ARCHIVE_PLATFORMS_JSON=["visionOS"]'
expect_error "archive がオブジェクトでない" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":true}' "archive はオブジェクト"
expect_error "archive.platforms が空" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"platforms":[]}}' "archive.platforms は"
expect_error "archive.platforms に知らない値" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"platforms":["tvOS"]}}' "archive.platforms は"
expect_error "googleServiceInfo が別のファイル" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"googleServiceInfo":"App/Info.plist"}}' "archive.googleServiceInfo は"
expect_error "googleServiceInfo が外を指す" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"googleServiceInfo":"../x/GoogleService-Info.plist"}}' "archive.googleServiceInfo は"
expect_ok "構成の並びと Crashlytics" \
  '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"configurations":[{"name":"Release","branches":["main","release/*"],"googleServiceInfo":{"path":"App/Firebase/GoogleService-Info-Prod.plist","secret":"GOOGLE_SERVICE_INFO_PLIST_PROD","required":true}},{"name":"Stg","googleServiceInfo":{"path":"App/Firebase/GoogleService-Info-Dev.plist","secret":"GOOGLE_SERVICE_INFO_PLIST_DEV"}}],"crashlytics":true}}' \
  "APP_KIT_CRASHLYTICS=true" "APP_KIT_GOOGLE_SERVICE_INFO=" \
  'APP_KIT_ARCHIVE_CONFIGURATIONS_JSON=[{"name":"Release","branches":["main","release/*"],"googleServiceInfo":{"path":"App/Firebase/GoogleService-Info-Prod.plist","secret":"GOOGLE_SERVICE_INFO_PLIST_PROD","required":true}},{"name":"Stg","branches":null,"googleServiceInfo":{"path":"App/Firebase/GoogleService-Info-Dev.plist","secret":"GOOGLE_SERVICE_INFO_PLIST_DEV","required":false}}]'
expect_ok "構成の並びが無ければ Release と今までの googleServiceInfo" \
  '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"googleServiceInfo":"App/GoogleService-Info.plist"}}' \
  "APP_KIT_CRASHLYTICS=false" \
  'APP_KIT_ARCHIVE_CONFIGURATIONS_JSON=[{"name":"Release","branches":null,"googleServiceInfo":{"path":"App/GoogleService-Info.plist","secret":"GOOGLE_SERVICE_INFO_PLIST_BASE64","required":false}}]'
expect_error "archive.crashlytics が文字" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"crashlytics":"yes"}}' "archive.crashlytics は"
expect_error "configurations が空" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"configurations":[]}}' "archive.configurations は 1 つ以上"
expect_error "configurations と googleServiceInfo の両方" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"googleServiceInfo":"App/GoogleService-Info.plist","configurations":[{"name":"Release"}]}}' "両方は書けません"
expect_error "構成の名前が重なる" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"configurations":[{"name":"Release","branches":["main"]},{"name":"Release"}]}}' "name が重なっています"
expect_error "構成の名前が - で始まる" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"configurations":[{"name":"-quiet"}]}}' "archive.configurations[0].name の形"
expect_error "branches を省いた構成が 2 つ" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"configurations":[{"name":"A"},{"name":"B"}]}}' "branches を省けるのは 1 つだけ"
expect_error "branches を省いた構成が最後でない" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"configurations":[{"name":"Stg"},{"name":"Release","branches":["main"]}]}}' "最後に置いてください"
expect_error "branches に ? を使う" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"configurations":[{"name":"Release","branches":["release/?"]}]}}' "archive.configurations[0].branches は"
expect_error "branches が空" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"configurations":[{"name":"Release","branches":[]}]}}' "archive.configurations[0].branches は"
expect_error "plist のファイル名が違う" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"configurations":[{"name":"Release","googleServiceInfo":{"path":"App/Info.plist","secret":"GOOGLE_SERVICE_INFO_PLIST_PROD"}}]}}' "googleServiceInfo.path は"
expect_error "plist が外を指す" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"configurations":[{"name":"Release","googleServiceInfo":{"path":"../GoogleService-Info.plist","secret":"GOOGLE_SERVICE_INFO_PLIST_PROD"}}]}}' "googleServiceInfo.path は"
expect_error "知らない Secret" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"configurations":[{"name":"Release","googleServiceInfo":{"path":"App/GoogleService-Info.plist","secret":"APPLE_API_KEY_BASE64"}}]}}' "googleServiceInfo.secret は"
expect_error "required が文字" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"configurations":[{"name":"Release","googleServiceInfo":{"path":"App/GoogleService-Info.plist","secret":"GOOGLE_SERVICE_INFO_PLIST_PROD","required":"yes"}}]}}' "googleServiceInfo.required は"
expect_error "構成がオブジェクトでない" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"archive":{"configurations":["Release"]}}' "archive.configurations[0] はオブジェクト"
expect_ok "schemes が無ければどのプラットフォームも scheme" \
  '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS","macOS"]}' \
  'APP_KIT_SCHEMES_JSON={"iOS":"App","macOS":"App"}' "APP_KIT_TEST_SCHEME=App"
expect_ok "プラットフォームごとのスキーム" \
  '{"v":1,"project":"Kawarin.xcodeproj","scheme":"Kawarin","schemes":{"macOS":"KawarinMac"},"platforms":["iOS","macOS"]}' \
  "APP_KIT_SCHEME=Kawarin" 'APP_KIT_SCHEMES_JSON={"iOS":"Kawarin","macOS":"KawarinMac"}' "APP_KIT_TEST_SCHEME=Kawarin"
expect_ok "先頭のプラットフォームのスキームでテストする" \
  '{"v":1,"project":"Kawarin.xcodeproj","scheme":"Kawarin","schemes":{"macOS":"KawarinMac"},"platforms":["macOS","iOS"]}' \
  "APP_KIT_TEST_SCHEME=KawarinMac"
expect_ok "Archive だけのプラットフォームにもスキームがある" \
  '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"schemes":{"macOS":"AppMac"},"archive":{"platforms":["iOS","macOS"]}}' \
  'APP_KIT_SCHEMES_JSON={"iOS":"App","macOS":"AppMac"}'
expect_error "schemes がオブジェクトでない" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"schemes":["AppMac"]}' "schemes はプラットフォームから"
expect_error "schemes に platforms に無いプラットフォーム" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"],"schemes":{"macOS":"AppMac"}}' 'schemes の "macOS" は platforms・archive.platforms にある'
expect_error "schemes のスキームが - で始まる" '{"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS","macOS"],"schemes":{"macOS":"-quiet"}}' "schemes の macOS のスキームの形"
expect_error "理由をすべて出す" '{"v":1,"project":"App","scheme":"","platforms":["iOS"]}' "scheme の形"

if [[ "$failures" -gt 0 ]]; then
  echo "$failures 件が合いませんでした"
  exit 1
fi
echo "すべて合いました"
