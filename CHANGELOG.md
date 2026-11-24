# CHANGELOG

版ごとの変更点。AskHub のクライアントの「広げる」の画面に出す。
呼ぶ側を直さないと動かない変更（入力・Secrets の名前・設定の形）は、見出しに「呼ぶ側の直しが要る」と書き、major を上げる。

## Unreleased

## v1.8.0（2026-11-24）

- Build・Archive・Upload の既定の Xcode を、26.6 から 27.1 に上げた。App Store Connect への Upload で altool が警告 90725（iOS 26.5 の SDK でのビルド。2027 年 4 月からは iOS 27 の SDK でないと上げられない）を出していた
- ランナーを、Xcode の major で決めるようにした（27 は `xcode-27`、26 は `macos-26`）。GitHub の `macos-26`（`macos-latest`）には Xcode 27 が無く、Xcode 27 は `xcode-27`（macOS 27）にだけある。今までは `macos-latest` 決め打ちだった
  - Build に、設定を読んでランナーを決める ubuntu のジョブ `plan` を足した（チェックの名前は `build / plan`。必須のチェック `build / build` は変わらない）。設定を読めないときは `build / build` も落ちる
  - 入力 `runs-on` の既定を空にした（空なら Xcode の版から決める。渡せばそのランナー）
- テストの Simulator を、選んだ Xcode の SDK と同じか古いランタイムから選ぶようにした（`xcode-27` の画像には、Xcode 27.1 より新しい iOS 27.2 のランタイムもある）。iPhone Duo（画面の縦横比がほかの iPhone と違う。iOS 27.1 のランタイムは iPhone Duo だけ）は選ばない
- 撮影とクリエイティブアセットのランナーと Xcode は変えていない（撮影の既定は `macos-latest`・26.6）
- 呼ぶ側の直しは要らない。ただし、Xcode 27.1（Swift 6.4）で落ちるコードがあるアプリは Build が落ちるようになる。よくあるのは、`Shape` などの隔離の無いプロトコルへの準拠が `#ConformanceIsolation` で落ちるもので、型に `nonisolated` を付ける（`nonisolated struct LockShape: Shape`。26.6 でも通る）。
  直すまでの間は、`.github/app-kit.json` に `"xcodeVersion": "26.6"` を書けば今までどおり動く

## v1.6.0（2026-11-24）

- Archive・Upload のビルドの構成を、ブランチで切り替えられるようにした。`.github/app-kit.json` の `archive.configurations` に、構成の名前・ブランチのパターン・書き出す `GoogleService-Info` の plist を並べる（上から順に見て最初に合ったもの。`branches` を省いた構成はどのブランチにも合う）。今までは `Release` 決め打ちだった
  - 構成ごとに別の plist を、Secret `GOOGLE_SERVICE_INFO_PLIST_BASE64`・`GOOGLE_SERVICE_INFO_PLIST_DEV`・`GOOGLE_SERVICE_INFO_PLIST_PROD` のどれかから書き出す。`required` が true なら、Upload で Secret が無いと止める
  - Archive の後に、書き出した plist がアプリに入ったか、ほかの構成の plist が入っていないかを確かめる
  - 手動の実行（Archive・Upload）に入力 `configuration` を足した（空ならブランチで決める）
  - `archive.configurations` を書かなければ、今までと同じ（`Release` と `archive.googleServiceInfo`）
- プラットフォームごとのスキームを扱うようにした。`.github/app-kit.json` の `schemes`（プラットフォーム → スキーム）に `scheme` と違うものだけを書く（kawarin-apple の macOS 版の `KawarinMac` など）。Build のテストは先頭のプラットフォームのスキーム、ほかのプラットフォームのビルドと Archive・Upload は、それぞれのスキームで行う。今までは 1 つの `scheme` だけだった
- `archive.crashlytics` が true なら、Upload するときに、書き出した plist で dSYM を Crashlytics に上げるようにした（SPM が取ってきた firebase-ios-sdk の `Crashlytics/upload-symbols`。iOS と macOS）
- 初めての入れ替えで、審査の提出のワークフロー（`.github/workflows/app-store-submit.yml`・`Tools/submit_for_review.py`）があれば、それが読む `Tools/app_store_config.py`・`app_store_connect.py`・`upload_app_info.py`・`upload_metadata.py` を外さないようにした（`manifest.json` の `keepIfPresent`）
- 配る `.swiftlint.yml` の `excluded` に `**/.build` を足した。ローカルの Swift Package を `swift build` すると、その中の `.build` の生成ファイルまで lint されていた（theater-player-app-vision が足していた除外）
- 呼ぶ側の Upload・Archive に、入力 `configuration` と Secrets `GOOGLE_SERVICE_INFO_PLIST_DEV`・`_PROD` を足した。版を上げる PR で置き換わるので、呼ぶ側を手で直す必要は無い（minor）

## v1.5.0（2026-11-24）

- Archive に entitlements を入れる手順と、書き出した IPA・pkg の確かめを、本体だけでなく、中のバンドル（App Extension・App Clip・system extension・XPC サービス。`.framework` の中は除く）すべてに広げた。v1.4.0 までは本体しか扱わず、ウィジェットなどの App Groups が配信ビルドから抜けても Upload まで通っていた
  - 中のバンドルのターゲットは、`-alltargets` のビルドの設定から製品の名前で選ぶ（Archive のバンドルと Bundle ID が合うものに絞り、まだ 2 つ以上ならプラットフォームで絞る）。内側から署名し、内側を署名し直したら外側も署名し直す
  - 書き出した IPA・pkg の各バンドルに、Archive の署名のキーと、ソースの entitlements（`CODE_SIGN_ENTITLEMENTS` を展開したもの）のキーがすべてあるかを確かめる。今までは Archive の署名と比べるだけで、Archive に入れ損ねると通っていた
  - macOS の中のバンドルには entitlement を足さない（Archive のアドホック署名のまま）。中のバンドルの entitlements のファイルに、アドホック署名の Archive に入らない項目があれば止める
- バンドルごとの entitlements（Archive と書き出したもの）を、artifact `entitlements-<プラットフォーム>`（JSON。IPA・pkg は上げない）と Job Summary に出すようにした
- スタブのフレームワークの署名の直しを、App Extension の中の `Frameworks/` にも広げた
- 初めての入れ替えで外すファイル（`manifest.json` の `replaces`）に、`.github/scripts/embed-entitlements.rb`（shariverse/oshikatsu-countdown-ios が持つ）を足した
- self-test に、ウィジェットを持つ iOS のアプリ `fixtures/ExtensionApp` の Archive と、`fixtures/MacApp` のウィジェットを足し、Archive のジョブの記録で entitlements を確かめるようにした
- 呼ぶ側の直しは要らない。ただし、中のバンドルにターゲットが見つからないアプリと、watchOS のアプリを含むアプリは、Archive が止まるようになる

## v1.4.0（2026-11-23）

- macOS（Mac App Store）の Archive・`.pkg` の書き出し・App Store Connect への Upload を扱うようにした。`.github/app-kit.json` の `archive.platforms` に `macOS` を書く（v1.3.0 までは plan で断っていた）。Secrets は iOS と同じものを使う
  - Archive はアドホック署名で作る（署名なしでは App Sandbox などの entitlement が入らず、App Store Connect が断るため）。スタブのフレームワークの署名の直しは、macOS では行わない
  - 書き出しの前に、Archive に App Sandbox（`com.apple.security.app-sandbox`）と Info.plist の `LSApplicationCategoryType` があるかを確かめる
  - App Store Connect のアプリに macOS のプラットフォームが無いときは、macOS の Upload だけを飛ばし、追加の手順を Job Summary に出す（ジョブは成功のまま）
- Archive に entitlements を入れる道具を、shilokuma-inc/ask-hub-apple の `Tools/embed_archive_entitlements.py` に寄せた（`tools/embed_archive_entitlements.py`。`embed-entitlements.sh`・`verify-exported-entitlements.sh` は外した）。iOS・visionOS も同じ道具を使う
  - entitlements のファイルの `$(…)` を、ビルドの設定で展開してから入れる（`$(TeamIdentifierPrefix)` は `DEVELOPMENT_TEAM` から作る。`$(AppIdentifierPrefix)` は App ID の接頭辞が Team ID と違うことがあるので、使っていれば止める）。v1.3.0 では展開せず、書き出しの確かめで落ちていた
  - アプリのターゲットの設定を、製品の名前（`App.app`）で選ぶ。v1.3.0 では Scheme の先頭のターゲットの設定を読んでいたので、テストや App Extension のターゲットが先にあると違うファイルを入れていた
  - macOS は、アドホック署名の Archive の entitlement に、プロジェクトの既定の署名（自動）で読んだファイルの項目を足す。足すものが無ければ署名し直さない
  - 書き出した IPA・pkg の確かめは、Archive のアプリの署名の entitlement がすべて残ったかを見る
- TestFlight の内部テスターの設定は、`archive.platforms` の先頭のジョブだけで行う（グループはアプリに 1 つなので、2 つのジョブが同時に作らないように）
- App Store Connect にアプリが無いときの作り方の「プラットフォーム」に、そのジョブのプラットフォームを出す（今までは iOS 決め打ち）
- self-test に macOS だけのアプリ `fixtures/MacApp` の Build と Archive（書き出しの手前まで）を足した
- 初めての入れ替えで外すファイル（`manifest.json` の `replaces`）に、古い 3 本立ての `.github/workflows/archive-develop.yml` を足した（quick-key-assistant-macos が持つ）
- 呼ぶ側の直しは要らない。macOS のアプリは、入れ替えるときに `.github/app-kit.json` の `platforms`・`archive.platforms` に `macOS` を書く（スクショとクリエイティブは `unmanaged` に入れる）

## v1.3.0（2026-11-23）

- 撮影で Apple Vision Pro（表示サイズ `APP_APPLE_VISION_PRO`、3840x2160）を撮れるようにした。プラットフォームは表示サイズの名前で決め、visionOS は `xrsimulator` の SDK と visionOS のランタイムで撮る（ランタイムが無ければ `xcodebuild -downloadPlatform visionOS` で入れる）。visionOS にはステータスバーと Dynamic Island が無いので、上書きも重ねもしない。iPhone・iPad の撮り方は変わらない
- 撮影の plan の matrix に、撮る Simulator のプラットフォーム（`platform`）を足した
- 撮れない表示サイズ（Mac・Apple TV・Apple Watch など）は、撮影の前に plan で止めるようにした（今までは撮影のジョブで Simulator を作れずに落ちていた）
- 呼ぶ側の直しは要らない。visionOS のアプリ（template-app-visionos など）は、`.github/app-kit.json` の `unmanaged` から `.github/workflows/app-store-screenshots.yml` を外すと、撮影のワークフローが配られる

## v1.2.0（2026-11-23）

- クリエイティブアセット（App Store のプロダクトページのヘッダー・検索結果の画像）を書き出す再利用ワークフロー `app-creative-assets.yml` と、呼ぶ側 `app-store-creative.yml` を足した。AskHub の司令塔が案（文言・色・使う画面）を入力で渡して起動し、artifact `creative-assets`・`creative-report` を取り込む。画像はリポジトリにコミットしない（ask-hub-apple の `docs/renewal/creative-assets.md`）
- 書き出しの雛形と道具（`tools/creative/`）と、案の形（`schema/creative-spec.schema.json`）を足した。文字は安全領域に収め、はみ出し・安全領域の外の文字・Apple の決まりに合わない文言を `report.json` に出す

## v1.1.1（2026-11-23）

- 呼ぶ側の撮影のワークフローで、入力 `max_parallel` を数にして（`fromJSON`）再利用ワークフローに渡すようにした。v1.1.0 では、API で起動すると number の入力が文字列のまま渡り、実行がジョブを作れずに「Unexpected value '1'」で落ちていた（`max_parallel` を送らないときも）
- 写すファイルの確かめに、呼ぶ側の number の入力を `fromJSON` で渡しているかを足した

## v1.1.0（2026-11-23）

- 撮影の再利用ワークフローに、入力 `max_parallel`（撮影に同時に使う macOS ランナーの数。1〜5、既定 1）を足した。既定のままなら、今までと同じく表示サイズを 1 本ずつ撮る
  - 撮る表示サイズの数より多ければ、余った枠を `AppStore/screenshots.json` に書いた順に配り、配った表示サイズは言語を分けて撮る。撮影のジョブの数は `max_parallel` を超えない
  - 言語を分けた表示サイズは `screenshots-<表示サイズ>-part<n>` に上げ、ubuntu の merge のジョブが `screenshots-<表示サイズ>` にまとめ直す（取り込む artifact の名前と中身は変わらない）。6.3 inch の derive は merge の後に動く
- 呼ぶ側の撮影のワークフローに、入力 `max_parallel` を足した（AskHub の司令塔が、同じ owner のほかの撮影と時間帯を見て決める）
- 撮影で `working-directory` にサブディレクトリを指定すると、plan の入力の確かめ（checkout の前）がディレクトリが無くて失敗していたのを直した

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
