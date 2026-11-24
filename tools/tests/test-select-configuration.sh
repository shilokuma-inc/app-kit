#!/bin/bash
#
# tools/select-configuration.sh の確かめ。self-test.yml が ubuntu で流す。手元では `bash tools/tests/test-select-configuration.sh`。
# 構成の並びは、tools/read-config.sh が書くものをそのまま使う（読む側と書く側の形をそろえるため）。
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
reader="$root/tools/read-config.sh"
selector="$root/tools/select-configuration.sh"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

failures=0

# 設定を read-config.sh で読み、構成の並びを返す
configurations_of() {
  printf '%s' "$1" > "$work/config.json"
  "$reader" "$work/config.json" | sed -n 's/^APP_KIT_ARCHIVE_CONFIGURATIONS_JSON=//p'
}

# 選べて、出力に期待する行がすべてあること
expect_ok() {
  local name="$1" json="$2" branch="$3" requested="$4"
  shift 4
  local configurations output
  configurations=$(configurations_of "$json")
  if ! output=$(APP_KIT_ARCHIVE_CONFIGURATIONS_JSON="$configurations" "$selector" "$branch" "$requested" 2>"$work/stderr"); then
    echo "FAIL $name: 選べなかった: $(cat "$work/stderr")"
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
  local name="$1" json="$2" branch="$3" requested="$4" message="$5"
  local configurations
  configurations=$(configurations_of "$json")
  if APP_KIT_ARCHIVE_CONFIGURATIONS_JSON="$configurations" "$selector" "$branch" "$requested" >"$work/stdout" 2>"$work/stderr"; then
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

base='"v":1,"project":"App.xcodeproj","scheme":"App","platforms":["iOS"]'
# dokogacha と同じ形（release/* と main は Release・Firebase は prod、ほかは Stg・Firebase は dev）
split="{$base,\"archive\":{\"configurations\":[
  {\"name\":\"Release\",\"branches\":[\"main\",\"release/*\"],\"googleServiceInfo\":{\"path\":\"App/Firebase/GoogleService-Info-Prod.plist\",\"secret\":\"GOOGLE_SERVICE_INFO_PLIST_PROD\",\"required\":true}},
  {\"name\":\"Stg\",\"googleServiceInfo\":{\"path\":\"App/Firebase/GoogleService-Info-Dev.plist\",\"secret\":\"GOOGLE_SERVICE_INFO_PLIST_DEV\"}}
]}}"

expect_ok "configurations が無ければ Release" "{$base}" "develop" "" \
  "APP_KIT_CONFIGURATION=Release" "APP_KIT_GOOGLE_SERVICE_INFO_PATH=" "APP_KIT_GOOGLE_SERVICE_INFO_SECRET=" \
  "APP_KIT_GOOGLE_SERVICE_INFO_REQUIRED=false" "APP_KIT_GOOGLE_SERVICE_INFO_OTHERS="
expect_ok "今までの googleServiceInfo は BASE64 の Secret で Release" \
  "{$base,\"archive\":{\"googleServiceInfo\":\"App/GoogleService-Info.plist\"}}" "release/1.0.0" "" \
  "APP_KIT_CONFIGURATION=Release" "APP_KIT_GOOGLE_SERVICE_INFO_PATH=App/GoogleService-Info.plist" \
  "APP_KIT_GOOGLE_SERVICE_INFO_SECRET=GOOGLE_SERVICE_INFO_PLIST_BASE64" "APP_KIT_GOOGLE_SERVICE_INFO_REQUIRED=false"
expect_ok "develop は branches の無い構成" "$split" "develop" "" \
  "APP_KIT_CONFIGURATION=Stg" "APP_KIT_GOOGLE_SERVICE_INFO_PATH=App/Firebase/GoogleService-Info-Dev.plist" \
  "APP_KIT_GOOGLE_SERVICE_INFO_SECRET=GOOGLE_SERVICE_INFO_PLIST_DEV" "APP_KIT_GOOGLE_SERVICE_INFO_REQUIRED=false" \
  "APP_KIT_GOOGLE_SERVICE_INFO_OTHERS=GoogleService-Info-Prod.plist"
expect_ok "release/ の下は Release" "$split" "release/1.2.0" "" \
  "APP_KIT_CONFIGURATION=Release" "APP_KIT_GOOGLE_SERVICE_INFO_SECRET=GOOGLE_SERVICE_INFO_PLIST_PROD" \
  "APP_KIT_GOOGLE_SERVICE_INFO_REQUIRED=true" "APP_KIT_GOOGLE_SERVICE_INFO_OTHERS=GoogleService-Info-Dev.plist"
expect_ok "* は / もまたぐ" "$split" "release/mobile/1.0" "" "APP_KIT_CONFIGURATION=Release"
expect_ok "main は Release" "$split" "main" "" "APP_KIT_CONFIGURATION=Release"
expect_ok "名前の一部だけ合っても選ばない" "$split" "mainline" "" "APP_KIT_CONFIGURATION=Stg"
expect_ok "作業ブランチは branches の無い構成" "$split" "askhub/01ABC" "" "APP_KIT_CONFIGURATION=Stg"
expect_ok "手動の実行で選んだ名前" "$split" "develop" "Release" "APP_KIT_CONFIGURATION=Release" \
  "APP_KIT_GOOGLE_SERVICE_INFO_SECRET=GOOGLE_SERVICE_INFO_PLIST_PROD"
expect_ok "plist の無い構成" \
  "{$base,\"archive\":{\"configurations\":[{\"name\":\"Debug\",\"branches\":[\"develop\"]},{\"name\":\"Release\"}]}}" "develop" "" \
  "APP_KIT_CONFIGURATION=Debug" "APP_KIT_GOOGLE_SERVICE_INFO_PATH=" "APP_KIT_GOOGLE_SERVICE_INFO_OTHERS="

expect_error "どれにも合わない" \
  "{$base,\"archive\":{\"configurations\":[{\"name\":\"Release\",\"branches\":[\"main\"]}]}}" "develop" "" "合う構成が archive.configurations にありません"
expect_error "無い名前を選んだ" "$split" "develop" "Debug" "構成 Debug がありません"
# 手動の実行の入力に式を書かれても、形で断る（展開させないため単一引用符のまま渡す）
# shellcheck disable=SC2016
expect_error "名前の形が合わない" "$split" "develop" '$(id)' "構成の名前の形が合いません"
if APP_KIT_ARCHIVE_CONFIGURATIONS_JSON="" "$selector" develop >/dev/null 2>"$work/stderr" || ! grep -qF "APP_KIT_ARCHIVE_CONFIGURATIONS_JSON がありません" "$work/stderr"; then
  echo "FAIL 構成の並びが無いときに断る"
  failures=$((failures + 1))
else
  echo "ok   構成の並びが無いときに断る"
fi

if [[ "$failures" -gt 0 ]]; then
  echo "$failures 件が合いませんでした"
  exit 1
fi
echo "すべて合いました"
