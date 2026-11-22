#!/bin/bash
#
# manifest.json と managed/ が合うか、版を埋めると目印が残らないかを確かめる。self-test.yml が ubuntu で流す。
# 引数に出力のフォルダを渡すと、版を埋めたファイルをそこに残す（self-test がワークフローを actionlint で確かめるため）。
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
out="${1:-$(mktemp -d)}"
failures=0

listed=$(jq -r '.managed[]' "$root/manifest.json" | sort)
actual=$(cd "$root/managed" && find . -type f | sed 's#^\./##' | sort)
if [[ "$listed" != "$actual" ]]; then
  echo "FAIL manifest.json の managed と managed/ のファイルが合わない"
  diff <(echo "$listed") <(echo "$actual") || true
  failures=$((failures + 1))
else
  echo "ok   manifest.json の managed と managed/ のファイルが合う"
fi

if jq -e '.replaces[] | select(.path | IN($managed[]))' --argjson managed "$(jq '.managed' "$root/manifest.json")" "$root/manifest.json" >/dev/null; then
  echo "FAIL 外すファイル（replaces）に写すファイルが入っている"
  failures=$((failures + 1))
else
  echo "ok   外すファイルと写すファイルが重ならない"
fi

"$root/tools/render-managed.sh" 0123456789abcdef0123456789abcdef01234567 v9.9.9 "$out" >/dev/null
if grep -rn '{{APP_KIT_' "$out"; then
  echo "FAIL 版を埋めた後に目印が残っている"
  failures=$((failures + 1))
else
  echo "ok   版を埋めると目印が残らない"
fi
pinned=true
for workflow in "$out"/.github/workflows/*.yml; do
  # app-kit を呼ぶジョブ（uses:）ごとに、uses: と app-kit-ref の 2 か所に同じ版のコミットがあること
  uses_lines=$(grep -c 'uses: shilokuma-inc/app-kit/' "$workflow" || true)
  ref_lines=$(grep -c '0123456789abcdef0123456789abcdef01234567' "$workflow" || true)
  if [[ "$uses_lines" -lt 1 || "$ref_lines" -ne $((uses_lines * 2)) ]]; then
    echo "FAIL $(basename "$workflow"): app-kit を呼ぶ $uses_lines か所の uses: と app-kit-ref に版のコミットがそろっていない（$ref_lines か所）"
    failures=$((failures + 1))
    pinned=false
  fi
done
[[ "$pinned" == true ]] && echo "ok   呼ぶ側のワークフローは uses: と app-kit-ref に同じ版を持つ"

# workflow_dispatch の number の入力は、API で起動すると文字列で届く。そのまま再利用ワークフローの number の入力に渡すと
# 「Unexpected value '1'」で実行がジョブを作れずに落ちるので、fromJSON で数にして渡す（v1.1.0 の撮影で起きた）
numbers=true
for workflow in "$out"/.github/workflows/*.yml; do
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    if ! grep -qF "$name: \${{ fromJSON(inputs.$name) }}" "$workflow"; then
      echo "FAIL $(basename "$workflow"): number の入力 $name を fromJSON(inputs.$name) で渡していない"
      failures=$((failures + 1))
      numbers=false
    fi
  done < <(awk '/^on:/{on=1} /^[a-z]/ && !/^on:/{on=0} on && /^      [A-Za-z0-9_-]+:$/{name=$1; sub(":", "", name)} on && /^        type: number$/{print name}' "$workflow")
done
[[ "$numbers" == true ]] && echo "ok   呼ぶ側のワークフローは number の入力を fromJSON で数にして渡す"

if [[ "$failures" -gt 0 ]]; then
  echo "$failures 件が合いませんでした"
  exit 1
fi
echo "すべて合いました"
