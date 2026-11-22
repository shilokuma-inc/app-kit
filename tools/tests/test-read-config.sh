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
  "APP_KIT_GENERATE=" "APP_KIT_UI_TESTS=" "APP_KIT_XCODE_VERSION=26.6" "APP_KIT_SWIFTLINT=true" "APP_KIT_SWIFT_PACKAGES="

expect_ok "すべての欄" \
  '{"v":1,"project":"Sub/App.xcodeproj","scheme":"App-iOS","platforms":["macOS","iOS","visionOS"],"generate":"xcodegen","uiTests":"AppUITests","xcodeVersion":"27.1","swiftlint":false,"swiftPackages":["Kit","Packages/Core"],"archive":{},"unmanaged":[".coderabbit.yaml"]}' \
  "APP_KIT_PROJECT=Sub/App.xcodeproj" "APP_KIT_SCHEME=App-iOS" "APP_KIT_PLATFORMS=macOS iOS visionOS" "APP_KIT_TEST_PLATFORM=macOS" \
  "APP_KIT_GENERATE=xcodegen" "APP_KIT_UI_TESTS=AppUITests" "APP_KIT_XCODE_VERSION=27.1" "APP_KIT_SWIFTLINT=false" "APP_KIT_SWIFT_PACKAGES=Kit Packages/Core"

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
expect_error "理由をすべて出す" '{"v":1,"project":"App","scheme":"","platforms":["iOS"]}' "scheme の形"

if [[ "$failures" -gt 0 ]]; then
  echo "$failures 件が合いませんでした"
  exit 1
fi
echo "すべて合いました"
