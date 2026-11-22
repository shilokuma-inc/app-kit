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
| `schema/` | 各リポジトリの設定（`.github/app-kit.json`）の形 |
| `fixtures/` | 確かめ用の小さなアプリ |

## 呼ぶ側

版は、タグではなくコミット（40 桁）で固定する。同じコミットを `app-kit-ref` にも渡す（再利用ワークフローには、呼ばれた版を知る組み込みの値が無いため）。
Secrets は名前を並べて渡す。`secrets: inherit` は、同じ organization か同じ enterprise の中でしか効かない。

## 開発

- AskHub のワーカーのトークンは Workflows の権限を持たないので、このリポジトリは AskHub の対象に入れず、人の Claude Code のセッションで直す
- 既定のブランチは `develop`。直しは PR で入れ、merge commit でマージする
- タグ `v<major>.<minor>.<patch>` は、develop にマージした後に、[CHANGELOG.md](CHANGELOG.md) に変更点を書いてから付ける。タグは動かせない・消せない（ルールセット）
- 呼ぶ側を直さないと動かない変更（入力・Secrets の名前・設定の形）は major を上げる
