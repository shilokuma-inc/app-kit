#!/bin/bash
#
# 呼んだ側のリポジトリの設定（.github/app-kit.json）を読んで確かめ、環境変数の形（KEY=VALUE）で標準出力に書く。
# 再利用ワークフローは、出力を $GITHUB_ENV に足してから使う。形は schema/app-kit.schema.json。
#
# 使い方:
#   tools/read-config.sh <設定のファイルのパス>
#
# 設定は public のリポジトリで誰でも PR に書けるので、xcodebuild の引数やパスになる値は形を確かめる。
# 合わない値があれば、すべての理由を標準エラーに出して 1 で終わる。知らない欄は読み飛ばす（前の版の app-kit に戻したときにも読めるように）。
set -euo pipefail

# app-kit の版ごとの既定の Xcode。ランナーの更新でビルドが変わらないよう固定する
DEFAULT_XCODE_VERSION="26.6"

config="${1:-}"
if [[ -z "$config" ]]; then
  echo "usage: $0 <path to .github/app-kit.json>" >&2
  exit 2
fi
if [[ ! -f "$config" ]]; then
  echo "::error::設定のファイルがありません: $config（app-kit を呼ぶリポジトリには .github/app-kit.json が要ります）" >&2
  exit 1
fi
if [[ ! -s "$config" ]]; then
  echo "::error::設定のファイルが空です: $config" >&2
  exit 1
fi
if ! values=$(jq -s 'length' "$config" 2>/dev/null); then
  echo "::error::設定のファイルを JSON として読めません: $config" >&2
  exit 1
fi
# 空白だけのファイルは値が 0 個、オブジェクトを 2 つ並べたファイルは 2 個になり、どちらも項目の確かめを素通りする
if [[ "$values" != "1" ]]; then
  echo "::error::設定のファイルには JSON の値を 1 つだけ書いてください（今は ${values} 個）: $config" >&2
  exit 1
fi

# 合わない値の理由を 1 行ずつ出す
problems=$(jq -r '
  def name_pattern: "^[A-Za-z0-9_][A-Za-z0-9_.+-]*$";
  def path_pattern: "^[A-Za-z0-9_][A-Za-z0-9_.+/-]*$";
  def has_parent: split("/") | any(. == ".." or . == "");
  def is_name: type == "string" and test(name_pattern);
  def is_path: type == "string" and test(path_pattern) and (has_parent | not);
  # ブランチのパターン（* だけを特別な文字にする。? や [ は使わせない）
  def is_branches: type == "array" and length > 0
    and all(.[]; type == "string" and test("^[A-Za-z0-9_.*][A-Za-z0-9_.*/-]*$") and (has_parent | not));
  def is_google_service_info_path: is_path and (split("/") | last | test("^GoogleService-Info[A-Za-z0-9_.+-]*\\.plist$"));
  def google_service_info_secrets: ["GOOGLE_SERVICE_INFO_PLIST_BASE64", "GOOGLE_SERVICE_INFO_PLIST_DEV", "GOOGLE_SERVICE_INFO_PLIST_PROD"];
  # 構成 1 つの理由（at は理由に出す場所の名前）
  def configuration_problems($at; $c):
    if ($c | type != "object") then "\($at) はオブジェクトにしてください（\($c | tojson)）" else
      (if ($c.name | is_name) | not then "\($at).name の形が合いません（\($c.name | tojson)）" else empty end),
      (if $c.branches != null and (($c.branches | is_branches) | not)
        then "\($at).branches は、ブランチのパターン（英数字と _ . - / *）の 1 つ以上の並びにしてください（\($c.branches | tojson)）" else empty end),
      (if $c.googleServiceInfo == null then empty
       elif ($c.googleServiceInfo | type != "object") then "\($at).googleServiceInfo はオブジェクトにしてください（\($c.googleServiceInfo | tojson)）"
       else
        (if ($c.googleServiceInfo.path | is_google_service_info_path) | not
          then "\($at).googleServiceInfo.path は、ファイル名が GoogleService-Info で始まる .plist のパスにしてください（\($c.googleServiceInfo.path | tojson)）" else empty end),
        (if ([$c.googleServiceInfo.secret] | inside(google_service_info_secrets)) | not
          then "\($at).googleServiceInfo.secret は \(google_service_info_secrets | join("・")) のどれかにしてください（\($c.googleServiceInfo.secret | tojson)）" else empty end),
        (if $c.googleServiceInfo.required != null and ($c.googleServiceInfo.required | type != "boolean")
          then "\($at).googleServiceInfo.required は true か false にしてください（\($c.googleServiceInfo.required | tojson)）" else empty end)
       end)
    end;
  if type != "object" then "設定がオブジェクトではありません" else
  [
    (if .v != 1 then "v が 1 ではありません（\(.v | tojson)）" else empty end),
    (if (.project | is_path and endswith(".xcodeproj")) | not then "project は .xcodeproj のパスにしてください（\(.project | tojson)）" else empty end),
    (if (.scheme | is_name) | not then "scheme の形が合いません（\(.scheme | tojson)）" else empty end),
    (if .schemes != null and (.schemes | type != "object")
      then "schemes はプラットフォームからスキームへのオブジェクトにしてください（\(.schemes | tojson)）" else empty end),
    (if (.schemes | type == "object") then
      ([.platforms, .archive.platforms] | map(if type == "array" then .[] else empty end)) as $platforms
      | .schemes | to_entries[]
      | (if ([.key] | inside($platforms)) | not
          then "schemes の \(.key | tojson) は platforms・archive.platforms にあるプラットフォームにしてください" else empty end),
        (if (.value | is_name) | not then "schemes の \(.key) のスキームの形が合いません（\(.value | tojson)）" else empty end)
     else empty end),
    (if (.platforms | type == "array" and length > 0 and all(.[]; . == "iOS" or . == "macOS" or . == "visionOS") and (unique | length) == length) | not
      then "platforms は iOS・macOS・visionOS のうち 1 つ以上の重ならない並びにしてください（\(.platforms | tojson)）" else empty end),
    (if .generate != null and .generate != "xcodegen" then "generate は null か \"xcodegen\" にしてください（\(.generate | tojson)）" else empty end),
    (if .uiTests != null and ((.uiTests | is_name) | not) then "uiTests の形が合いません（\(.uiTests | tojson)）" else empty end),
    (if .xcodeVersion != null and ((.xcodeVersion | type == "string" and test("^[0-9]+(\\.[0-9]+){0,2}$")) | not) then "xcodeVersion の形が合いません（\(.xcodeVersion | tojson)）" else empty end),
    (if .swiftlint != null and (.swiftlint | type != "boolean") then "swiftlint は true か false にしてください（\(.swiftlint | tojson)）" else empty end),
    (if .swiftPackages != null and ((.swiftPackages | type == "array" and all(.[]; is_path) and (unique | length) == length) | not)
      then "swiftPackages はリポジトリの中のパスの並びにしてください（\(.swiftPackages | tojson)）" else empty end),
    (if .archive != null and (.archive | type != "object") then "archive はオブジェクトにしてください（\(.archive | tojson)）" else empty end),
    (if (.archive | type == "object") and .archive.platforms != null
        and ((.archive.platforms | type == "array" and length > 0 and all(.[]; . == "iOS" or . == "macOS" or . == "visionOS") and (unique | length) == length) | not)
      then "archive.platforms は iOS・macOS・visionOS のうち 1 つ以上の重ならない並びにしてください（\(.archive.platforms | tojson)）" else empty end),
    (if (.archive | type == "object") and .archive.googleServiceInfo != null
        and ((.archive.googleServiceInfo | is_path and endswith("/GoogleService-Info.plist")) | not)
      then "archive.googleServiceInfo は、アプリのフォルダの中の GoogleService-Info.plist のパスにしてください（\(.archive.googleServiceInfo | tojson)）" else empty end),
    (if (.archive | type == "object") and .archive.crashlytics != null and (.archive.crashlytics | type != "boolean")
      then "archive.crashlytics は true か false にしてください（\(.archive.crashlytics | tojson)）" else empty end),
    (if (.archive | type == "object") and .archive.configurations != null then
      .archive as $archive
      | if ($archive.configurations | type != "array" or length == 0)
        then "archive.configurations は 1 つ以上の構成の並びにしてください（\($archive.configurations | tojson)）"
        else
          (if $archive.googleServiceInfo != null
            then "archive.configurations と archive.googleServiceInfo は両方は書けません（構成ごとの googleServiceInfo に書いてください）" else empty end),
          (if ([$archive.configurations[] | objects | .name] | (unique | length) != length) then "archive.configurations の name が重なっています" else empty end),
          (if ([$archive.configurations[] | objects | select(.branches == null)] | length) > 1
            then "archive.configurations で branches を省けるのは 1 つだけです" else empty end),
          (if ($archive.configurations[:-1] | any(type == "object" and .branches == null))
            then "archive.configurations の branches を省いた構成は、最後に置いてください（どのブランチにも合うため）" else empty end),
          ($archive.configurations | to_entries[] | configuration_problems("archive.configurations[\(.key)]"; .value))
        end
     else empty end)
  ] | .[] end
' "$config")
if [[ -n "$problems" ]]; then
  while IFS= read -r problem; do
    echo "::error::.github/app-kit.json: $problem" >&2
  done <<<"$problems"
  exit 1
fi

jq -r --arg default_xcode "$DEFAULT_XCODE_VERSION" '
  "APP_KIT_PROJECT=\(.project)",
  "APP_KIT_SCHEME=\(.scheme)",
  # プラットフォームごとのスキーム（schemes に無いプラットフォームは scheme）。テストは先頭のプラットフォームのスキームで流す
  "APP_KIT_SCHEMES_JSON=\(.scheme as $scheme | (.schemes // {}) as $schemes
    | [.platforms[], (.archive.platforms // [])[]] | unique | map({key: ., value: ($schemes[.] // $scheme)}) | from_entries | tojson)",
  "APP_KIT_TEST_SCHEME=\((.schemes // {})[.platforms[0]] // .scheme)",
  "APP_KIT_PLATFORMS=\(.platforms | join(" "))",
  "APP_KIT_TEST_PLATFORM=\(.platforms[0])",
  "APP_KIT_GENERATE=\(.generate // "")",
  "APP_KIT_UI_TESTS=\(.uiTests // "")",
  "APP_KIT_XCODE_VERSION=\(.xcodeVersion // $default_xcode)",
  "APP_KIT_SWIFTLINT=\(if .swiftlint == false then "false" else "true" end)",
  "APP_KIT_SWIFT_PACKAGES=\((.swiftPackages // []) | join(" "))",
  "APP_KIT_ARCHIVE_PLATFORMS=\((.archive.platforms // [.platforms[0]]) | join(" "))",
  "APP_KIT_ARCHIVE_PLATFORMS_JSON=\((.archive.platforms // [.platforms[0]]) | tojson)",
  "APP_KIT_GOOGLE_SERVICE_INFO=\(.archive.googleServiceInfo // "")",
  "APP_KIT_CRASHLYTICS=\(if .archive.crashlytics == true then "true" else "false" end)",
  # 構成の並び（tools/select-configuration.sh が読む）。configurations が無ければ、今までと同じ Release と archive.googleServiceInfo
  "APP_KIT_ARCHIVE_CONFIGURATIONS_JSON=\(
    if .archive.configurations != null then
      [.archive.configurations[] | {
        name,
        branches: (.branches // null),
        googleServiceInfo: (if .googleServiceInfo == null then null
          else {path: .googleServiceInfo.path, secret: .googleServiceInfo.secret, required: (.googleServiceInfo.required // false)} end)
      }]
    else
      [{name: "Release", branches: null,
        googleServiceInfo: (if .archive.googleServiceInfo == null then null
          else {path: .archive.googleServiceInfo, secret: "GOOGLE_SERVICE_INFO_PLIST_BASE64", required: false} end)}]
    end | tojson)"
' "$config"
