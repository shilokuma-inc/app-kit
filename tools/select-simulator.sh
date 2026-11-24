#!/bin/bash
#
# テストに使う Simulator を選び、UDID を標準出力に書く。
# 名前だけの指定は OS:latest を暗黙に要求し、古いランタイムにしか無い機種だと解決できないので、UDID で選ぶ。
#
# 使い方:
#   tools/select-simulator.sh <iOS|visionOS>
#
#   iOS       選んだ Xcode の SDK と同じか古い、最新の iOS のランタイムにある iPhone（iPhone Duo は除く）
#   visionOS  選んだ Xcode の SDK と同じか古い、最新の visionOS のランタイムにある Apple Vision Pro（ランタイムが無ければ、選んだ Xcode に合うものを入れる）
#
# SDK より新しいランタイムは、その Xcode ではテストを流せない（xcode-27 の画像には、既定の Xcode 27.1 より新しい iOS 27.2 のランタイムもある）。
# iPhone Duo は画面の縦横比（1398x2034）がほかの iPhone と違い、iOS 27.1 のランタイムは iPhone Duo だけなので、名前で除く
set -euo pipefail

platform="${1:-}"
case "$platform" in
  iOS)
    runtime_key="SimRuntime.iOS"
    runtime_name="iOS"
    device_prefix="iPhone"
    sdk_name="iphonesimulator"
    ;;
  visionOS)
    runtime_key="SimRuntime.xrOS"
    runtime_name="xrOS"
    device_prefix="Apple Vision Pro"
    sdk_name="xrsimulator"
    ;;
  *)
    echo "usage: $0 <iOS|visionOS>" >&2
    exit 2
    ;;
esac

sdk_version=$(xcrun --sdk "$sdk_name" --show-sdk-version)

find_simulator() {
  xcrun simctl list devices available -j | jq -c \
    --arg key "$runtime_key" --arg name "$runtime_name" --arg prefix "$device_prefix" --arg sdk "$sdk_version" '
      # 版は [major, minor] で比べる（27 のように minor の無い SDK の版は 27.0）
      (($sdk | split(".") | map(tonumber)) + [0] | .[0:2]) as $limit
      | .devices | to_entries
      | map(select(.key | contains($key)))
      | map(. + {version: (.key | capture("\($name)-(?<maj>[0-9]+)-(?<min>[0-9]+)") | [(.maj | tonumber), (.min | tonumber)])})
      | map(select(.version <= $limit))
      | sort_by(.version)
      | reverse
      | map(.value[] | select((.name | startswith($prefix)) and .name != "iPhone Duo"))
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
  echo "::error::$device_prefix の Simulator が、SDK（$sdk_name $sdk_version）と同じか古いランタイムに見つかりません" >&2
  xcrun simctl list devices available >&2
  exit 1
fi

echo "simulator: $(jq -r '"\(.name) (\(.udid))"' <<<"$simulator")（SDK $sdk_name $sdk_version）" >&2
jq -r .udid <<<"$simulator"
