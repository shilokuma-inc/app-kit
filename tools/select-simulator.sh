#!/bin/bash
#
# テストに使う Simulator を選び、UDID を標準出力に書く。
# 名前だけの指定は OS:latest を暗黙に要求し、古いランタイムにしか無い機種だと解決できないので、UDID で選ぶ。
#
# 使い方:
#   tools/select-simulator.sh <iOS|visionOS>
#
#   iOS       最新の iOS のランタイムにある iPhone
#   visionOS  最新の visionOS のランタイムにある Apple Vision Pro（ランタイムが無ければ、選んだ Xcode に合うものを入れる）
set -euo pipefail

platform="${1:-}"
case "$platform" in
  iOS)
    runtime_key="SimRuntime.iOS"
    runtime_name="iOS"
    device_prefix="iPhone"
    ;;
  visionOS)
    runtime_key="SimRuntime.xrOS"
    runtime_name="xrOS"
    device_prefix="Apple Vision Pro"
    ;;
  *)
    echo "usage: $0 <iOS|visionOS>" >&2
    exit 2
    ;;
esac

find_simulator() {
  xcrun simctl list devices available -j | jq -c \
    --arg key "$runtime_key" --arg name "$runtime_name" --arg prefix "$device_prefix" '
      .devices | to_entries
      | map(select(.key | contains($key)))
      | sort_by(.key | capture("\($name)-(?<maj>[0-9]+)-(?<min>[0-9]+)") | [(.maj | tonumber), (.min | tonumber)])
      | reverse
      | map(.value[] | select(.name | startswith($prefix)))
      | .[0] // empty'
}

simulator=$(find_simulator)
if [[ -z "$simulator" && "$platform" == "visionOS" ]]; then
  # ランナーのイメージから visionOS のランタイムが外れたときに備える
  echo "visionOS の Simulator が見つからないため、ランタイムをダウンロードします" >&2
  xcodebuild -downloadPlatform visionOS >&2
  simulator=$(find_simulator)
fi
if [[ -z "$simulator" ]]; then
  echo "::error::$device_prefix の Simulator が見つかりません" >&2
  xcrun simctl list devices available >&2
  exit 1
fi

echo "simulator: $(jq -r '"\(.name) (\(.udid))"' <<<"$simulator")" >&2
jq -r .udid <<<"$simulator"
