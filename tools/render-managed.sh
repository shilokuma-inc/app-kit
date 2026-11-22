#!/bin/bash
#
# 写すファイル（managed/）に版を埋めて、出力のフォルダに書く。AskHub の司令塔が各リポジトリに出す PR の中身と同じになる
# （司令塔は Swift で同じことをする。人の Claude Code のセッションで手で入れ替えるときにも使う）。
#
# 使い方:
#   tools/render-managed.sh <版のコミット（40 桁）> <版のタグ（v1.0.0 など）> <出力のフォルダ>
set -euo pipefail

ref="${1:-}"
version="${2:-}"
out="${3:-}"
if [[ ! "$ref" =~ ^[0-9a-f]{40}$ || ! "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ || -z "$out" ]]; then
  echo "usage: $0 <commit (40 hex)> <version (vX.Y.Z)> <output directory>" >&2
  exit 2
fi

root="$(cd "$(dirname "$0")/.." && pwd)"
jq -r '.managed[]' "$root/manifest.json" | while IFS= read -r path; do
  mkdir -p "$out/$(dirname "$path")"
  sed -e "s/{{APP_KIT_REF}}/$ref/g" -e "s/{{APP_KIT_VERSION}}/$version/g" "$root/managed/$path" > "$out/$path"
  echo "$path"
done
