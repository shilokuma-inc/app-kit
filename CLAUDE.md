# app-kit

AskHub で開発する Apple のアプリのリポジトリに配る、CI・リリースの再利用ワークフローと道具（README.md）。
設計の正本は shilokuma-inc/ask-hub-apple の `docs/renewal/app-kit.md`。設計を変えるときは、先にそちらを直す。

## 全員向けの事実

- public のリポジトリ。ここのワークフローは、5 つの organization（shilokuma-inc・shariverse・BeaconFun4・tm-family・shilokuma-vision）のリポジトリから、コミットを固定して呼ばれる
- 再利用ワークフローの中の `github` の値は、呼んだ側のもの。checkout も呼んだ側のリポジトリになる。app-kit の道具は、入力 `app-kit-ref` の版を `$RUNNER_TEMP/app-kit` に取り出して使う
- リポジトリごとの値は、呼んだ側の `.github/app-kit.json` だけから読む（形は `schema/app-kit.schema.json`）。読んだ値は `tools/read-config.sh` で確かめてから使う
- 確かめは `.github/workflows/self-test.yml`（`fixtures/` のアプリ（`App`・`MacApp`・`ExtensionApp`）に対して流す）

## ブランチ・コミット・PR

- 既定のブランチは `develop`。作業はフィーチャーブランチ（`feat/xxx`・`fix/xxx`）で行い、PR は develop 宛て。merge commit でマージする（Squash しない）
- コミット: `[type] 日本語の説明`（type は `feat` / `fix` / `refactor` / `chore` / `docs` / `test` / `style` / `perf` / `ci` / `build`）。AI 帰属行は入れない
- PR タイトル: `【TYPE】タイトル`。Assignee に自分を設定する
- 版のタグは、develop にマージした後に `CHANGELOG.md` に変更点を書いてから付ける

## コードレビュー観点

- **Secrets**: 再利用ワークフローの `secrets` は、使うジョブ（Archive・Upload）にだけ渡す。Build には渡さない。値をログ・Job Summary・artifact に出さない
- **アクションの固定**: `uses:` のアクションは、タグではなくコミット（40 桁）で固定し、横にタグを書く
- **呼んだ側の値**: `.github/app-kit.json` の値は、public のリポジトリで誰でも PR に書ける。`-` で始まる値・`..` を含むパス・決まった値の外のプラットフォームは断る。シェルに渡すときは必ず引用する
- **イベント**: `pull_request_target` と、PR のテキストを式に埋め込む書き方（`${{ github.event.pull_request.title }}` など）は使わない
- **互換**: 入力・Secrets の名前・設定の形を変えるときは、版の major を上げる（呼ぶ側を直さないと動かないため）。`CHANGELOG.md` に書く
