#!/bin/bash
#
# Archive するビルドの構成を、.github/app-kit.json の archive.configurations とブランチ（か手動の実行で選んだ名前）から決め、
# 環境変数の形（KEY=VALUE）で標準出力に書く。再利用ワークフローは、出力を $GITHUB_ENV に足してから使う。
#
# 使い方:
#   APP_KIT_ARCHIVE_CONFIGURATIONS_JSON=<tools/read-config.sh の出力の値> tools/select-configuration.sh <ブランチ> [<構成の名前>]
#
# 構成の名前を渡したら、その構成を使う（無い名前なら止める）。渡さなければ、並びを上から見て、branches のパターンが
# ブランチに合う最初の構成を使う（* は / もまたぐ。branches の無い構成はどのブランチにも合う）。どれにも合わなければ止める。
#
# 書くもの:
#   APP_KIT_CONFIGURATION                  xcodebuild -configuration に渡す名前
#   APP_KIT_GOOGLE_SERVICE_INFO_PATH       書き出す GoogleService-Info の plist のパス（無ければ空）
#   APP_KIT_GOOGLE_SERVICE_INFO_SECRET     その plist を読む Secret の名前（無ければ空）
#   APP_KIT_GOOGLE_SERVICE_INFO_REQUIRED   Upload で Secret が無ければ止めるか（true / false）
#   APP_KIT_GOOGLE_SERVICE_INFO_OTHERS     ほかの構成の plist のファイル名（空白区切り。アプリに入っていないことを確かめる）
set -euo pipefail

branch="${1:-}"
requested="${2:-}"
configurations="${APP_KIT_ARCHIVE_CONFIGURATIONS_JSON:-}"

if [[ -z "$configurations" ]]; then
  echo "::error::APP_KIT_ARCHIVE_CONFIGURATIONS_JSON がありません（先に tools/read-config.sh の出力を読んでください）" >&2
  exit 1
fi
if ! jq -e 'type == "array" and length > 0' >/dev/null 2>&1 <<<"$configurations"; then
  echo "::error::APP_KIT_ARCHIVE_CONFIGURATIONS_JSON が構成の並びではありません" >&2
  exit 1
fi

names=$(jq -r '[.[].name] | join("・")' <<<"$configurations")
count=$(jq 'length' <<<"$configurations")
chosen=""

if [[ -n "$requested" ]]; then
  # 手動の実行の入力は、誰でも選べる値なので形を確かめてから比べる
  if [[ ! "$requested" =~ ^[A-Za-z0-9_][A-Za-z0-9_.+-]*$ ]]; then
    echo "::error::構成の名前の形が合いません: $requested" >&2
    exit 1
  fi
  chosen=$(jq -r --arg name "$requested" 'to_entries[] | select(.value.name == $name) | .key' <<<"$configurations" | head -1)
  if [[ -z "$chosen" ]]; then
    echo "::error::.github/app-kit.json の archive.configurations に構成 $requested がありません（あるもの: $names）" >&2
    exit 1
  fi
else
  for ((index = 0; index < count; index++)); do
    if jq -e --argjson i "$index" '.[$i].branches == null' >/dev/null <<<"$configurations"; then
      chosen="$index"
      break
    fi
    while IFS= read -r pattern; do
      # パターンの * を、/ もまたぐワイルドカードとして比べる（read-config.sh が * のほかの特別な文字を断っている）
      # shellcheck disable=SC2053
      if [[ -n "$branch" && "$branch" == $pattern ]]; then
        chosen="$index"
        break 2
      fi
    done < <(jq -r --argjson i "$index" '.[$i].branches[]' <<<"$configurations")
  done
  if [[ -z "$chosen" ]]; then
    echo "::error::ブランチ ${branch:-（無し）} に合う構成が archive.configurations にありません（あるもの: $names。どのブランチにも合う構成は、branches を省いて最後に置きます）" >&2
    exit 1
  fi
fi

jq -r --argjson i "$chosen" '
  .[$i] as $c
  | ($c.googleServiceInfo.path // "" | split("/") | last // "") as $own
  | "APP_KIT_CONFIGURATION=\($c.name)",
    "APP_KIT_GOOGLE_SERVICE_INFO_PATH=\($c.googleServiceInfo.path // "")",
    "APP_KIT_GOOGLE_SERVICE_INFO_SECRET=\($c.googleServiceInfo.secret // "")",
    "APP_KIT_GOOGLE_SERVICE_INFO_REQUIRED=\(if $c.googleServiceInfo.required == true then "true" else "false" end)",
    "APP_KIT_GOOGLE_SERVICE_INFO_OTHERS=\([.[] | .googleServiceInfo.path // empty | split("/") | last | select(. != $own)] | unique | join(" "))"
' <<<"$configurations"
