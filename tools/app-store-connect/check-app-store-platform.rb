#!/usr/bin/env ruby
# frozen_string_literal: true

#
# App Store Connect のアプリに、指定したプラットフォーム（MAC_OS など）が追加済みかを確認する（読み取りのみ）。
# iOS と macOS を出すアプリで、macOS のプラットフォームをまだ追加していないうちに macOS のビルドを上げると毎回失敗するので、
# Upload の前に確かめる。プラットフォームを追加すると、そのプラットフォームの App Store のバージョン（「提出準備中」など）が
# 作られるので、バージョンが 1 つでもあれば「追加済み」とみなす。
# shilokuma-inc/ask-hub-apple の .github/scripts/check-app-store-platform.rb（2026-11）を、app_store_connect.rb を使う形にしたもの。
#
# 結果は GITHUB_OUTPUT の available（true / false）に書く。
# 追加されていないときは、追加の手順を Job Summary に出して終了コード 0 で終わる（呼び出し側は Upload を飛ばす。
# ほかのプラットフォームの Upload には響かせない）。アプリが無いとき・API の呼び出しに失敗したときは終了コード 1 で終わる。
#
# App Store Connect でのプラットフォームの追加は API で行えないため、追加そのものは Web 画面で行う。
#
# 使い方（環境変数で渡す）:
#   BUNDLE_ID=jp.shilokuma.MyApp PLATFORM=MAC_OS \
#   API_KEY_PATH=AuthKey_XXXXXXXXXX.p8 APPLE_API_KEY_ID=XXXXXXXXXX APPLE_API_ISSUER_ID=xxxxxxxx-... \
#   ruby tools/app-store-connect/check-app-store-platform.rb
#
# Ruby の標準ライブラリだけで動く（gem のインストールは不要）。API の共通処理は app_store_connect.rb にある。

require_relative 'app_store_connect'

ASC = AppStoreConnect

PLATFORM_NAMES = { 'IOS' => 'iOS', 'MAC_OS' => 'macOS', 'VISION_OS' => 'visionOS' }.freeze

def platform_added?(app_id:, platform:, token:)
  json = ASC.request(:get, "/v1/apps/#{app_id}/appStoreVersions", token: token,
                                                                  query: { 'filter[platform]' => platform,
                                                                           'fields[appStoreVersions]' => 'platform',
                                                                           'limit' => '1' })
  json.fetch('data').any? { |version| version.dig('attributes', 'platform') == platform }
end

def write_output(available)
  path = ENV.fetch('GITHUB_OUTPUT', '')
  File.write(path, "available=#{available}\n", mode: 'a') unless path.empty?
end

bundle_id = ASC.env!('BUNDLE_ID')
platform = ASC.env!('PLATFORM')
platform_name = PLATFORM_NAMES.fetch(platform) do
  abort "PLATFORM には #{PLATFORM_NAMES.keys.join(' / ')} のどれかを指定してください（#{platform}）"
end
token = ASC.token_from_env

begin
  app = ASC.find_app(bundle_id: bundle_id, token: token)
  # アプリそのものが無いときは、この前の check-app-store-app.rb が作り方を出して止めている
  abort "::error::App Store Connect に #{bundle_id} のアプリがありません" unless app

  if platform_added?(app_id: app.fetch('id'), platform: platform, token: token)
    puts "App Store Connect の #{app.dig('attributes', 'name')}（#{bundle_id}）には #{platform_name} のプラットフォームがあります"
    write_output(true)
    exit 0
  end
rescue ASC::Error => e
  abort "::error::#{e.message}"
end

guide = <<~MARKDOWN
  ## #{platform_name} の Upload を飛ばしました

  App Store Connect の #{app.dig('attributes', 'name')}（`#{bundle_id}`）に #{platform_name} のプラットフォームがまだ無いため、#{platform_name} のビルドは上げていません（ほかのプラットフォームの Upload には響きません）。

  #{platform_name} 版も上げるときは、[App Store Connect のアプリ一覧](https://appstoreconnect.apple.com/apps) でこのアプリを開き、
  「プラットフォームを追加」（サイドバーのプラットフォームの横の「＋」）から #{platform_name} を追加してから、このワークフローを再実行してください。
  追加すると #{platform_name} のバージョン（提出準備中）が作られ、次の実行から上がります。

  #{platform_name} を上げないままにするときは、`.github/app-kit.json` の `archive.platforms` から #{platform_name} を外すと、Archive ごと飛ばします。
MARKDOWN

puts "::notice::App Store Connect に #{platform_name} のプラットフォームが無いため、#{platform_name} の Upload を飛ばします（手順は Job Summary）"
ASC.write_summary(guide)
write_output(false)
