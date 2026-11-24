# app-kit

AskHub で開発する Apple のアプリのリポジトリに、CI・リリースのワークフローと道具を配る共通リポジトリ。
設計は [shilokuma-inc/ask-hub-apple の docs/renewal/app-kit.md](https://github.com/shilokuma-inc/ask-hub-apple/blob/develop/docs/renewal/app-kit.md)。

- 各リポジトリには、ここの再利用ワークフローを呼ぶ薄いワークフローと、リポジトリごとの設定（`.github/app-kit.json`）だけを置く
- 呼ぶ側のワークフロー・SwiftLint・CodeRabbit・Issue/PR のテンプレートは、AskHub の司令塔が版の中身に置き換える PR を出してそろえる
- 版を上げるときは、人が AskHub のクライアントで変更点（[CHANGELOG.md](CHANGELOG.md)）を見て「広げる」を押す

## 置くもの

| 場所 | 中身 |
| --- | --- |
| `.github/workflows/app-*.yml` | 各リポジトリが呼ぶ再利用ワークフロー |
| `.github/workflows/self-test.yml` | app-kit 自身の確かめ（`fixtures/` のアプリに再利用ワークフローを流す） |
| `tools/` | 再利用ワークフローが、呼ばれた版の app-kit を取り出して使う道具 |
| `schema/` | 各リポジトリの設定（`.github/app-kit.json`）と、クリエイティブアセットの案（`creative-spec.schema.json`）の形 |
| `fixtures/` | 確かめ用の小さなアプリ（iOS の `App`・macOS の `MacApp`・ウィジェットを持つ iOS の `ExtensionApp`） |
| `managed/` | 各リポジトリに写すファイル（置き場所と同じ並び）。呼ぶ側のワークフローは版を `{{APP_KIT_REF}}`・`{{APP_KIT_VERSION}}` の目印で持つ |
| `manifest.json` | 写すファイルの一覧（`managed`）と、初めての入れ替えで外すファイル（`replaces`。`keepIfPresent` のファイルがあれば外さない） |

## Xcode とランナー

Build・Archive・Upload は、既定では Xcode 27.1 で流す（v1.8.0。v1.7.0 までは 26.6）。ランナーは Xcode の major で決まる。

| Xcode | ランナー |
| --- | --- |
| 27.x（既定） | `xcode-27`（macOS 27。GitHub の macOS の画像は、Xcode 27 から Xcode の major ごとになった） |
| 26.x | `macos-26`（Xcode 26.x だけが入っている） |

- 既定と違う Xcode を使うときだけ、`.github/app-kit.json` の `xcodeVersion` に書く。Xcode 27 で落ちるコードを直すまでの間は `"xcodeVersion": "26.6"` にすると、今までどおり `macos-26` の 26.6 で流れる
  （2027 年 4 月から、App Store Connect は iOS 27 の SDK でビルドしたものしか受け付けない。altool の警告 90725）
- テストの Simulator は、選んだ Xcode の SDK と同じか古い、最新のランタイムの iPhone（iPhone Duo は除く）か Apple Vision Pro
- 撮影（`AppStore/screenshots.json` の `runsOn`・`xcodeVersion`）とクリエイティブアセットのランナーは、この既定と別に決まる（撮影の既定は `macos-latest`・26.6）

## クリエイティブアセット

App Store のプロダクトページのヘッダー（3840x1646）と検索結果の画像（3840x2560）は、`app-store-creative.yml` が書き出す（上げない）。
AskHub の司令塔が、案（文言・色・使う画面。`schema/creative-spec.schema.json`）を入力 `spec` に入れて起動し、artifact を取り込んで、人が AskHub で確かめた後に App Store Connect に上げる。

- 端末に載せる画面は、6.9 inch の撮影の artifact `screenshots-APP_IPHONE_67`。入力 `screenshots_run` に前の実行の id を渡すと、撮り直さずにその画面を使う
- 雛形は `tools/creative/creative.html`。文字は安全領域に収め、はみ出しなどは `creative-report` の `report.json` に出す
- 手元で書き出しを確かめる: `bash tools/tests/test-creative-render.sh`（Chrome と Xcode が要る）

## entitlements と App Extension

Archive の後に、本体と中のバンドル（App Extension・App Clip・system extension・XPC サービス。`.framework` の中は除く）へ、
各ターゲットの `CODE_SIGN_ENTITLEMENTS` のファイル（`$(…)` をビルドの設定で展開したもの）を、内側から順にアドホック署名で入れる。
Export は Archive の各バンドルの署名にある entitlement だけを引き継ぐので、署名なしの Archive のままでは、ウィジェットの App Groups などが配信ビルドから抜ける。

- 中のバンドルのターゲットは、`-alltargets` のビルドの設定から製品の名前（`FULL_PRODUCT_NAME`）で選ぶ。見つからない・1 つに決まらないときは止める。
  watchOS のアプリ（Archive したプラットフォームと違うバンドル）は、ビルドの設定を正しく読めないので止める
- 書き出した IPA・pkg の各バンドルに、Archive の署名とソースの entitlements のキーが残ったかを確かめ、抜けていれば Upload の前に止める
- バンドルごとの entitlements（Archive と書き出したもの）を、artifact `entitlements-<プラットフォーム>`（JSON）と Job Summary に出す。IPA・pkg は上げない
- macOS の中のバンドルには足さない（Archive のアドホック署名のまま）。下の「自動の署名のときだけ付ける」形は本体にだけ使える。
  中のバンドルの entitlements のファイルに、アドホック署名の Archive に入らない項目があれば止める

## macOS のアプリ

`.github/app-kit.json` の `platforms`・`archive.platforms` に `macOS` を書く。Mac App Store に上げる `.pkg` を、iOS と同じ Secrets（`EXPORT_OPTIONS`・API キー）で書き出す。
iOS と macOS を出すアプリは `archive.platforms` に両方を書く（プラットフォームごとに別のジョブになり、macOS が落ちても iOS は上がる）。

- Archive はアドホック署名で作る（署名なしだと `ENABLE_APP_SANDBOX` などのビルドの設定から作られる entitlement が入らない）。本番の署名は Export がする
- push（`com.apple.developer.aps-environment`）のように provisioning profile の要る entitlement は、アドホック署名のビルドが止まるので、
  entitlements のファイルを自動の署名のときだけ付ける（`CODE_SIGN_ENTITLEMENTS = $(APP_ENTITLEMENTS_$(CODE_SIGN_STYLE))` のように、`CODE_SIGN_STYLE` が `Manual` なら外す。`APP_ENTITLEMENTS_Automatic`・`APP_ENTITLEMENTS_Manual` はアプリの xcconfig で決める名前で、`fixtures/MacApp/Configs/Project.xcconfig` では `FIXTURE_ENTITLEMENTS_`）。
  Archive の後に、自動の署名で読んだファイルの項目を app-kit が足す
- App Sandbox と Info.plist の `LSApplicationCategoryType` が無いと App Store Connect が断るので、書き出しの前に確かめて止める
- App Store Connect のアプリに macOS のプラットフォームがまだ無いときは、macOS の Upload だけを飛ばし、追加の手順を Job Summary に出す
- macOS のスクショ・クリエイティブアセットは扱わない（撮れない表示サイズは撮影の plan が止める）。macOS だけのアプリは、`unmanaged` に `.github/workflows/app-store-screenshots.yml`・`.github/workflows/app-store-creative.yml` を入れる

## プラットフォームごとのスキーム

プラットフォームでスキームが違うアプリ（iOS 版が `Kawarin`、macOS 版が別のターゲットの `KawarinMac` など）は、`schemes` に `scheme` と違うものだけを書く（v1.6.0）。

```json
{ "project": "Kawarin.xcodeproj", "scheme": "Kawarin", "schemes": { "macOS": "KawarinMac" }, "platforms": ["iOS", "macOS"], "archive": { "platforms": ["iOS", "macOS"] } }
```

- Build: テストは先頭のプラットフォームのスキームで流す（`uiTests` もそのスキームのもの）。2 つ目からのプラットフォームは、それぞれのスキームでビルドだけを確かめる。パッケージの解決と SwiftLint は `scheme` で行う
- Archive・Upload: プラットフォームごとのジョブが、そのプラットフォームのスキームで Archive し、entitlements もそのスキームの設定で入れる

## 構成の切り替えと Firebase

Archive・Upload は、既定では `Release` で作り、`archive.googleServiceInfo` があれば Secret `GOOGLE_SERVICE_INFO_PLIST_BASE64` を書き出す。
ブランチで構成を変えるアプリ（develop の TestFlight は Stg、`release/**` と main は Release など）は、`archive.configurations` を書く（v1.6.0）。

```json
"archive": {
  "configurations": [
    {
      "name": "Release",
      "branches": ["main", "release/*"],
      "googleServiceInfo": { "path": "App/Firebase/GoogleService-Info-Prod.plist", "secret": "GOOGLE_SERVICE_INFO_PLIST_PROD", "required": true }
    },
    { "name": "Stg", "googleServiceInfo": { "path": "App/Firebase/GoogleService-Info-Dev.plist", "secret": "GOOGLE_SERVICE_INFO_PLIST_DEV" } }
  ],
  "crashlytics": true
}
```

- 上から順に見て、`branches` のパターン（`*` は `/` もまたぐ）がブランチに合う最初の構成で Archive する。`branches` を省いた構成はどのブランチにも合う（最後に 1 つだけ置ける）
- 手動の実行（Archive・Upload）は、入力 `configuration` で構成の名前を選べる（空ならブランチで決める）
- `secret` は `GOOGLE_SERVICE_INFO_PLIST_BASE64`・`GOOGLE_SERVICE_INFO_PLIST_DEV`・`GOOGLE_SERVICE_INFO_PLIST_PROD` のどれか。`required` が true なら、Upload で Secret が無いと止める（false なら注釈を出して Firebase につながないビルドを作る）
- Archive の後に、書き出した plist がアプリに入ったか、ほかの構成の plist が入っていないかを確かめる。ほかの構成の plist は、構成ごとの `EXCLUDED_SOURCE_FILE_NAMES` でアプリから外しておく
- `crashlytics` が true なら、Upload するときに、SPM が取ってきた firebase-ios-sdk の `Crashlytics/upload-symbols` で dSYM を上げる（iOS と macOS。失敗しても Upload は止めない）

## 呼ぶ側

版は、タグではなくコミット（40 桁）で固定する。同じコミットを `app-kit-ref` にも渡す（再利用ワークフローには、呼ばれた版を知る組み込みの値が無いため）。
Secrets は名前を並べて渡す。`secrets: inherit` は、同じ organization か同じ enterprise の中でしか効かない。

## 写すファイルを手で入れる

AskHub の司令塔ができるまで（と、司令塔を通さずに試すとき）は、版を埋めたファイルを作って、アプリのリポジトリに置く。

```bash
tools/render-managed.sh <版のコミット> <版のタグ> <アプリのリポジトリ>
```

`.github/app-kit.json` は別に書く（形は `schema/app-kit.schema.json`）。`manifest.json` の `replaces` のファイルは外す（`keepIfPresent` のファイルがあれば残す）。

## 開発

- AskHub のワーカーのトークンは Workflows の権限を持たないので、このリポジトリは AskHub の対象に入れず、人の Claude Code のセッションで直す
- 既定のブランチは `develop`。直しは PR で入れ、merge commit でマージする
- タグ `v<major>.<minor>.<patch>` は、develop にマージした後に、[CHANGELOG.md](CHANGELOG.md) に変更点を書いてから付ける。タグは動かせない・消せない（ルールセット）
- 呼ぶ側を直さないと動かない変更（入力・Secrets の名前・設定の形）は major を上げる
