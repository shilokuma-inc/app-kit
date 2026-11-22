# CHANGELOG

版ごとの変更点。AskHub のクライアントの「広げる」の画面に出す。
呼ぶ側を直さないと動かない変更（入力・Secrets の名前・設定の形）は、見出しに「呼ぶ側の直しが要る」と書き、major を上げる。

## Unreleased

- Build の再利用ワークフロー `app-build.yml`（ビルド・SwiftLint・Unit テスト・UI テスト。iOS・macOS・visionOS、XcodeGen、ローカルの Swift Package の `swift test`）
- 各リポジトリの設定 `.github/app-kit.json`（形は `schema/app-kit.schema.json`）と、読んで確かめる `tools/read-config.sh`
- Archive・Upload の再利用ワークフロー `app-archive.yml`（iOS・visionOS。スタブのフレームワークの署名の直し・entitlements を入れて書き出した IPA で確かめる・TestFlight の内部テスター・`GoogleService-Info.plist` の書き出し）。書き出した IPA は artifact に上げない。macOS の Archive はまだ扱わない
