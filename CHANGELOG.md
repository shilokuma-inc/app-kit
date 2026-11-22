# CHANGELOG

版ごとの変更点。AskHub のクライアントの「広げる」の画面に出す。
呼ぶ側を直さないと動かない変更（入力・Secrets の名前・設定の形）は、見出しに「呼ぶ側の直しが要る」と書き、major を上げる。

## Unreleased

## v1.1.0（2026-11-23）

- 撮影の再利用ワークフローに、入力 `max_parallel`（撮影に同時に使う macOS ランナーの数。1〜5、既定 1）を足した。既定のままなら、今までと同じく表示サイズを 1 本ずつ撮る
  - 撮る表示サイズの数より多ければ、余った枠を `AppStore/screenshots.json` に書いた順に配り、配った表示サイズは言語を分けて撮る。撮影のジョブの数は `max_parallel` を超えない
  - 言語を分けた表示サイズは `screenshots-<表示サイズ>-part<n>` に上げ、ubuntu の merge のジョブが `screenshots-<表示サイズ>` にまとめ直す（取り込む artifact の名前と中身は変わらない）。6.3 inch の derive は merge の後に動く
- 呼ぶ側の撮影のワークフローに、入力 `max_parallel` を足した（AskHub の司令塔が、同じ owner のほかの撮影と時間帯を見て決める）

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
