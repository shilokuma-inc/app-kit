# CHANGELOG

版ごとの変更点。AskHub のクライアントの「広げる」の画面に出す。
呼ぶ側を直さないと動かない変更（入力・Secrets の名前・設定の形）は、見出しに「呼ぶ側の直しが要る」と書き、major を上げる。

## Unreleased

- クリエイティブアセット（App Store のプロダクトページのヘッダー・検索結果の画像）を書き出す再利用ワークフロー `app-creative-assets.yml` と、呼ぶ側 `app-store-creative.yml` を足した。AskHub の司令塔が案（文言・色・使う画面）を入力で渡して起動し、artifact `creative-assets`・`creative-report` を取り込む。画像はリポジトリにコミットしない（ask-hub-apple の `docs/renewal/creative-assets.md`）
- 書き出しの雛形と道具（`tools/creative/`）と、案の形（`schema/creative-spec.schema.json`）を足した。文字は安全領域に収め、はみ出し・安全領域の外の文字・Apple の決まりに合わない文言を `report.json` に出す

## v1.0.1（2026-11-22）

- 撮影で、同じ表示サイズを重ねて指定されても、同じジョブと artifact を 2 つ作らないようにした
- 呼ぶ側の撮影のワークフローに、撮影の設定（プロジェクト・Scheme・画面・表示サイズ・言語）は `AppStore/` の JSON で決めることを書いた

## v1.0.0（2026-11-22）

最初の版。template-app-ios の 2026-11-22 の `_build.yml`・`_archive.yml`・`app-store-screenshots.yml` と道具を、各リポジトリから呼べる形にした。

- Build の再利用ワークフロー `app-build.yml`（ビルド・SwiftLint・Unit テスト・UI テスト。iOS・macOS・visionOS、XcodeGen、ローカルの Swift Package の `swift test`）
- 各リポジトリの設定 `.github/app-kit.json`（形は `schema/app-kit.schema.json`）と、読んで確かめる `tools/read-config.sh`
- Archive・Upload の再利用ワークフロー `app-archive.yml`（iOS・visionOS。スタブのフレームワークの署名の直し・entitlements を入れて書き出した IPA で確かめる・TestFlight の内部テスター・`GoogleService-Info.plist` の書き出し）。書き出した IPA は artifact に上げない。macOS の Archive はまだ扱わない
- スクショを撮るだけの再利用ワークフロー `app-store-screenshots.yml`（入力と artifact `screenshots-<表示サイズ>` は template-app-ios のものと同じ。App Store Connect には上げない。`upload: true` なら止める）
- 写すファイル `managed/`（呼ぶ側の `build.yml`・`upload.yml`・`archive.yml`・`app-store-screenshots.yml`、`.swiftlint.yml`、`.coderabbit.yaml`、Issue・PR のテンプレート）と、写すファイル・初めての入れ替えで外すファイルの一覧 `manifest.json`。版を埋める `tools/render-managed.sh`
