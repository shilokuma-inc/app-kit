#!/usr/bin/env python3
"""Archive の .app と、その中の App Extension などに、プロジェクトの entitlements をアドホック署名で入れる（`app-archive.yml` の iOS・visionOS・macOS）。

書き出した IPA・pkg の各バンドルに、Archive とプロジェクトの entitlements が残ったかも確かめる（`check`）。
shilokuma-inc/ask-hub-apple の `Tools/embed_archive_entitlements.py`（2026-11-09）を移し、v1.5.0 で中のバンドルに広げた
（shariverse/oshikatsu-countdown-ios の `.github/scripts/embed-entitlements.rb` が手本）。

Export は、Archive の各バンドルの実行ファイルの署名にある entitlement だけを引き継いで配布用に署名し直し、profile からは足さない。
そのため署名しないで作った Archive からは、基本の entitlement（application-identifier など）しか無い配布ビルドになり、
WeatherKit・push・ウィジェットの App Groups などが実機で動かない。

- 対象は、Archive の .app（本体）と、その中の .app・.appex・.systemextension・.xpc（App Extension・App Clip・system extension・
  XPC サービスなど。.framework の中は除く）。本体の設定は `-scheme` の `-showBuildSettings` から、中のバンドルの設定は
  `-alltargets` から、製品の名前で選ぶ（`-scheme` には依存先の拡張のターゲットが出ない）。Archive したプラットフォームと違う
  バンドル（watchOS のアプリなど）は、ビルドの設定を正しく読めないので止める
- 深い（内側の）バンドルから署名する。外側の署名は内側の署名を封じるので、内側を署名し直したら外側も署名し直す
- iOS・visionOS は `CODE_SIGNING_ALLOWED=NO` で Archive する（アドホック署名は、push などの entitlement が profile を要するため
  「requires a provisioning profile」で止まる）。署名の無いバンドルを、ビルドの設定（`xcodebuild -showBuildSettings`）で
  `$(VAR)` を展開した `CODE_SIGN_ENTITLEMENTS` でアドホック署名する
- macOS はアドホック署名（`CODE_SIGN_STYLE=Manual`）で Archive する（署名しないと、`ENABLE_APP_SANDBOX` などから作られる
  entitlement が入らず、App Store Connect が App Sandbox の無いアプリとして断る）。本体の `CODE_SIGN_ENTITLEMENTS` はプロジェクトの
  既定の署名（自動）の設定で読み、Archive の署名の entitlement に足して署名し直す。足すものが無ければ署名し直さない。
  push のように profile の要る entitlement は、アドホック署名のビルドが止まるので、アプリの側で自動の署名のときだけ付けておく
  （ask-hub-apple の `Configs/Project.xcconfig`）。ここで足せば Export が引き継ぐ。
  中のバンドルには足さない（v1.5.0 では扱わない）。自動の署名で読んだファイルの項目が中のバンドルの署名に無ければ、配信ビルドから
  抜けるので止める

値は Export が配布用の profile に合わせて書き換える（App Store なら production）。
`--record` は、バンドルごとのソースの entitlements と署名の結果を JSON に書く。`check` はそれも使って確かめる。

    python3 tools/embed_archive_entitlements.py embed build.xcarchive \\
        --project App.xcodeproj --scheme App --sdk iphoneos --configuration Release --record entitlements/archive.json
    python3 tools/embed_archive_entitlements.py mac-requirements build.xcarchive   # macOS の Archive だけ
    python3 tools/embed_archive_entitlements.py check build.xcarchive export \\
        --record entitlements/archive.json --report entitlements/export.json      # Export の後（IPA か pkg のある場所）
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

#: entitlements の値の中の `$(NAME)` / `${NAME}`（Xcode がビルドの設定で展開する書き方）
VARIABLE = re.compile(r"\$[({]([A-Za-z_][A-Za-z0-9_]*)[)}]")

#: entitlements を持てるコードのバンドル（本体の中を辿って探す。.framework の中は除く）
CODE_BUNDLES = (".app", ".appex", ".systemextension", ".xpc")

#: Mac App Store のアプリに要る entitlement
APP_SANDBOX = "com.apple.security.app-sandbox"

#: Xcode が署名のときに決める変数のうち、Archive の前には決められないもの（App ID の接頭辞。古い App ID では Team ID と違う）
UNKNOWN_BEFORE_SIGNING = "AppIdentifierPrefix"


def fail(message: str) -> SystemExit:
    """GitHub Actions の注釈になる形のエラーで止める（`raise fail(...)`）。"""
    return SystemExit(f"::error::{message}")


def expand(value, settings: dict[str, str]):
    """entitlements（plist を読んだもの）の文字列の `$(NAME)` を、ビルドの設定の値に置き換える。

    設定に無い名前があれば止める。Xcode は空にするが、`aps-environment` が空のまま署名されると気づけない。
    """
    if isinstance(value, str):
        missing = sorted({name for name in VARIABLE.findall(value) if name not in settings})
        if missing:
            hint = ""
            if UNKNOWN_BEFORE_SIGNING in missing:
                hint = ("（$(AppIdentifierPrefix) は署名のときに App ID の profile から決まり、Archive の前には分かりません。"
                        "App ID の接頭辞が Team ID と同じなら $(TeamIdentifierPrefix) と書いてください）")
            raise fail(f"entitlements の {', '.join(missing)} がビルドの設定にありません: {value}{hint}")
        return VARIABLE.sub(lambda match: settings[match.group(1)], value)
    if isinstance(value, list):
        return [expand(item, settings) for item in value]
    if isinstance(value, dict):
        return {key: expand(item, settings) for key, item in value.items()}
    return value


def with_signing_prefixes(settings: dict[str, str]) -> dict[str, str]:
    """`$(TeamIdentifierPrefix)` を、ビルドの設定の DEVELOPMENT_TEAM（`<Team ID>.`）で補う。

    Xcode は署名するときにこの値を決めるので、`-showBuildSettings` の結果には無い（App Groups などに使う）。
    `$(AppIdentifierPrefix)` は App ID の接頭辞で、古い App ID では Team ID と違うので補わない（使っていれば expand が止める）。
    DEVELOPMENT_TEAM が無ければ補わない。
    """
    team = settings.get("DEVELOPMENT_TEAM", "")
    if not team:
        return settings
    return {"TeamIdentifierPrefix": f"{team}.", **settings}


def app_build_settings(entries: list[dict], product_name: str) -> dict[str, str]:
    """`xcodebuild -showBuildSettings -json` の結果から、Archive の .app（`App.app`）を作るターゲットの設定を選ぶ。

    Scheme にはテストや App Extension のターゲットも入るので、先頭の設定を読むと別のターゲットの entitlements になることがある。
    """
    matches = [entry["buildSettings"] for entry in entries
               if entry.get("buildSettings", {}).get("FULL_PRODUCT_NAME") == product_name]
    if len(matches) != 1:
        raise fail(f"{product_name} を作るターゲットが 1 つに決まりません（{len(matches)} 件）")
    return matches[0]


def target_settings(entries: list[dict], bundle: Path, sdk: str, native) -> dict[str, str]:
    """`-alltargets` の結果（entries）から、本体の中のバンドル（`Widget.appex` など）を作るターゲットの設定を選ぶ。

    製品の名前で選び、2 つ以上なら Archive のバンドルの Bundle ID で、まだ 2 つ以上ならターゲットのプラットフォームで絞る。
    iOS と macOS の別のターゲットが、同じ名前・同じ Bundle ID のバンドルを作ることがある（kawarin-apple の `Kawarin.app`）。
    `-sdk` を付けた設定では、どのターゲットもそのプラットフォームの値（`SUPPORTED_PLATFORMS` も）になるので、
    プラットフォームは `-sdk` なしの設定（native() が返す）で見る。見つからない・1 つに決まらなければ止める（黙って飛ばさない）。
    """
    candidates: dict[str, dict] = {}
    for entry in entries:
        if entry.get("buildSettings", {}).get("FULL_PRODUCT_NAME") == bundle.name:
            # -alltargets は先頭のターゲットを 2 回出すので、ターゲットの名前で 1 つにまとめる
            candidates.setdefault(entry.get("target", ""), entry)
    matches = list(candidates.values())
    if len(matches) > 1:
        bundle_id = bundle_info(bundle).get("CFBundleIdentifier")
        matches = [entry for entry in matches if entry["buildSettings"].get("PRODUCT_BUNDLE_IDENTIFIER") == bundle_id]
    if len(matches) > 1:
        platforms = {entry.get("target", ""): entry.get("buildSettings", {}).get("SUPPORTED_PLATFORMS", "").split()
                     for entry in native()}
        matches = [entry for entry in matches if sdk in platforms.get(entry.get("target", ""), [])]
    if len(matches) != 1:
        names = "、".join(sorted(candidates)) or "なし"
        raise fail(f"{bundle.name} を作るターゲットが 1 つに決まりません（製品の名前が同じターゲット: {names}）")
    return matches[0]["buildSettings"]


def archived_app(archive: Path) -> Path:
    """Archive の Info.plist の ApplicationPath（`Applications/App.app`）から .app の場所を返す。"""
    info = plistlib.loads((archive / "Info.plist").read_bytes())
    return archive / "Products" / info["ApplicationProperties"]["ApplicationPath"]


def bundle_info(bundle: Path) -> dict:
    """バンドルの Info.plist（macOS は `Contents/Info.plist`）。無ければ空。"""
    for path in (bundle / "Contents/Info.plist", bundle / "Info.plist"):
        if path.is_file():
            return plistlib.loads(path.read_bytes())
    return {}


def nested_bundles(app: Path) -> list[Path]:
    """本体の中のコードのバンドル（CODE_BUNDLES）を、深い（内側の）ものから返す。

    .framework の中（フレームワークが持つヘルパーなど。フレームワークと一緒に署名されている）とシンボリックリンクは辿らない。
    """
    found = []
    for root, directories, _ in os.walk(app):
        directories[:] = [name for name in directories
                          if not name.endswith(".framework") and not (Path(root) / name).is_symlink()]
        found.extend(Path(root) / name for name in directories if name.endswith(CODE_BUNDLES))
    return sorted(found, key=lambda path: (-len(path.relative_to(app).parts), str(path)))


def bundle_label(bundle: Path, app: Path) -> str:
    """注釈・記録に使うバンドルの場所。本体の .app から書く（`App.app/PlugIns/Widget.appex`）。"""
    return str(bundle.relative_to(app.parent))


def signed_entitlements(app: Path) -> dict | None:
    """バンドルの署名にある entitlements。署名が無ければ None。"""
    result = subprocess.run(["codesign", "-d", "--entitlements", "-", "--xml", str(app)],
                            capture_output=True, check=False)
    if result.returncode != 0:
        return None
    return plistlib.loads(result.stdout) if result.stdout.strip() else {}


def merge(signed: dict, added: dict, app_name: str) -> dict:
    """Archive の署名の entitlements に、プロジェクトの entitlements を足す。同じキーで値が違えば止める。"""
    conflicts = sorted(key for key in signed.keys() & added.keys() if signed[key] != added[key])
    if conflicts:
        raise fail(f"{app_name} の署名の {', '.join(conflicts)} が、プロジェクトの entitlements と違います")
    return {**signed, **added}


def build_settings(args: argparse.Namespace, *selection: str) -> list[dict]:
    """`xcodebuild -showBuildSettings -json` の結果（ターゲットごとの設定）。selection は `-scheme App -sdk iphoneos` など。"""
    output = subprocess.run(
        ["xcodebuild", "-showBuildSettings", "-json", "-project", args.project, *selection,
         "-configuration", args.configuration],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(output)


def source_entitlements(settings: dict[str, str], label: str) -> tuple[str, dict]:
    """ターゲットの `CODE_SIGN_ENTITLEMENTS` のファイルを、`$(…)` を展開して読む。ファイルが無い設定なら ("", {})。"""
    path = settings.get("CODE_SIGN_ENTITLEMENTS", "")
    if not path:
        return "", {}
    file = Path(settings["SRCROOT"]) / path
    if not file.is_file():
        raise fail(f"{label} の CODE_SIGN_ENTITLEMENTS のファイルがありません: {path}")
    try:
        return path, expand(plistlib.loads(file.read_bytes()), with_signing_prefixes(settings))
    except SystemExit as error:
        raise fail(f"{label}（{path}）: {str(error).removeprefix('::error::')}") from None


def sign(bundle: Path, entitlements: dict, preserve: bool) -> None:
    """バンドルをアドホック署名し、署名の entitlements が入れたものと同じかを確かめる。

    entitlements が空なら、entitlements なしで署名する（内側を署名し直したので、外側の封をし直すとき）。
    preserve は、署名し直すときに Archive の署名の識別子とフラグ（macOS の Hardened Runtime）を残すか。付けないとフラグが消える。
    """
    command = ["codesign", "--force", "--sign", "-", "--timestamp=none"]
    if preserve:
        command.append("--preserve-metadata=identifier,flags")
    with tempfile.NamedTemporaryFile(suffix=".entitlements") as file:
        if entitlements:
            file.write(plistlib.dumps(entitlements))
            file.flush()
            command += ["--generate-entitlement-der", "--entitlements", file.name]
        subprocess.run([*command, str(bundle)], check=True)
    if (signed_entitlements(bundle) or {}) != entitlements:
        raise fail(f"{bundle.name} の署名の entitlements が、入れようとしたものと違います")


def write_json(path: Path, value: dict) -> None:
    """記録・確かめの結果を JSON に書く（値の data・日付は文字列にする）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def write_summary(lines: list[str]) -> None:
    """GitHub Actions の Job Summary に足す。GITHUB_STEP_SUMMARY が無い（手元で流す）ときは何もしない。"""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n\n")


def keys_cell(entitlements: dict) -> str:
    """Job Summary の表の、entitlements のキーの欄。"""
    return "<br>".join(f"`{key}`" for key in sorted(entitlements)) or "なし"


def result_cell(result: dict) -> str:
    """Job Summary の表の、書き出したもののバンドルの確かめの結果の欄。"""
    if result["exported"] is None:
        return "❌ バンドルが無い"
    problems = [f"`{key}` が無い" for key in result["missing"]] + [f"`{key}` に $(…)" for key in result["unexpanded"]]
    return "❌ " + "<br>".join(problems) if problems else "✅"


def embed(args: argparse.Namespace) -> int:
    """Archive の .app と中のバンドルを、`CODE_SIGN_ENTITLEMENTS` を展開した entitlements でアドホック署名する。

    深いバンドルから順に見る。署名済み（macOS のアドホック署名の Archive）の本体は、その署名の entitlements（sandbox など）に
    足して署名し直す（上書きすると Xcode が入れた entitlement が消えるため）。足すものが無ければ署名し直さない。
    中のバンドルを署名し直したら、それを入れている外側のバンドルも、足すものが無くても署名し直す（外側の封が壊れるため）。
    どのバンドルにも `CODE_SIGN_ENTITLEMENTS` が無ければ、何も署名しない。
    """
    app = archived_app(args.archive)
    bundles = [*nested_bundles(app), app]
    mac = args.sdk == "macosx"
    scheme_entries = build_settings(args, "-scheme", args.scheme, "-sdk", args.sdk)
    # 中のバンドルの設定。-scheme には依存先の拡張のターゲットが出ないので、全ターゲットを読む（中のバンドルがあるときだけ）
    all_entries = build_settings(args, "-alltargets", "-sdk", args.sdk) if len(bundles) > 1 else []
    native = functools.cache(lambda: build_settings(args, "-alltargets"))

    resigned: list[Path] = []
    records = []
    for bundle in bundles:
        label = bundle_label(bundle, app)
        platform = bundle_info(bundle).get("DTPlatformName")
        if platform and platform != args.sdk:
            raise fail(f"{label} は {platform} のバンドルです。Archive したプラットフォーム（{args.sdk}）と違うバンドル"
                       "（watchOS のアプリなど）は、ビルドの設定を正しく読めないので扱いません")
        settings = (app_build_settings(scheme_entries, app.name) if bundle == app
                    else target_settings(all_entries, bundle, args.sdk, native))
        path, source = source_entitlements(settings, label)
        signed = signed_entitlements(bundle)
        seals_resigned = any(inner.is_relative_to(bundle) for inner in resigned)

        if mac and bundle != app:
            # macOS の中のバンドルには足さない（v1.5.0 では扱わない）。足りなければ配信ビルドから抜けるので止める
            missing = sorted(set(source) - set(signed or {}))
            if missing:
                raise fail(f"{label} の署名に、{path} の {', '.join(missing)} がありません。macOS の中のバンドルには、"
                           "自動の署名のときだけ付ける entitlement を app-kit が足しません（アドホック署名の Archive に入る形にしてください）")
            wanted = signed or {}
        else:
            wanted = source if signed is None else merge(signed, source, label)
        changed = wanted != signed if signed is not None else bool(wanted)

        if changed or seals_resigned:
            sign(bundle, wanted, preserve=signed is not None)
            resigned.append(bundle)
            for key, value in sorted(wanted.items()):
                print(f"{label} に入れました: {key} = {value}")
            if not wanted:
                print(f"{label}: entitlements なしで署名し直しました（中のバンドルを署名し直したため）")
        elif signed is not None:
            for key, value in sorted(signed.items()):
                print(f"{label} の署名にあります: {key} = {value}")
            print(f"{label} の署名に {path or 'entitlements のファイル'} の項目がすべてあるので、署名し直しません")
        else:
            print(f"{label}: CODE_SIGN_ENTITLEMENTS が無いので、署名しません")
        records.append({
            "path": label,
            "target": settings.get("TARGET_NAME", ""),
            "entitlementsFile": path,
            "source": source,
            "signed": signed_entitlements(bundle) or {},
            "signedByAppKit": bundle in resigned,
        })

    records.reverse()  # 本体から並べる
    if args.record:
        write_json(args.record, {"sdk": args.sdk, "bundles": records})
    write_summary([
        f"### entitlements（Archive・{args.sdk}）",
        "",
        "| バンドル | ターゲット | 署名の entitlements | app-kit が署名した |",
        "| --- | --- | --- | --- |",
        *(f"| `{record['path']}` | {record['target']} | {keys_cell(record['signed'])} | {'はい' if record['signedByAppKit'] else 'いいえ'} |"
          for record in records),
    ])
    return 0


def mac_requirements(args: argparse.Namespace) -> int:
    """macOS の Archive が、Mac App Store に上げられる形かを、書き出しの前に確かめる。

    App Sandbox が無い・Info.plist に `LSApplicationCategoryType` が無いと、ビルドも書き出しも通るのに、
    App Store Connect への Upload で断られる（iOS には無い決まりなので、iOS だけのアプリから足したときに気づきにくい）。
    """
    app = archived_app(args.archive)
    problems = []
    entitlements = signed_entitlements(app) or {}
    if entitlements.get(APP_SANDBOX) is not True:
        problems.append(f"{app.name} の署名に App Sandbox（{APP_SANDBOX}）がありません。"
                        "Mac App Store のアプリは、ビルドの設定の ENABLE_APP_SANDBOX か entitlements のファイルで有効にしてください")
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    if not info.get("LSApplicationCategoryType"):
        problems.append(f"{app.name} の Info.plist に LSApplicationCategoryType がありません。"
                        "ビルドの設定の INFOPLIST_KEY_LSApplicationCategoryType などでカテゴリを決めてください")
    if problems:
        for problem in problems:
            print(f"::error::{problem}")
        return 1
    print(f"{app.name}: {APP_SANDBOX} = True、LSApplicationCategoryType = {info['LSApplicationCategoryType']}")
    return 0


def exported_package(path: Path) -> Path:
    """書き出した IPA・pkg を返す。書き出した場所（フォルダ）を渡されたら、その中の 1 つを選ぶ。"""
    if path.is_file():
        return path
    packages = sorted(path.glob("*.ipa")) + sorted(path.glob("*.pkg"))
    if len(packages) != 1:
        raise fail(f"{path} の中に、書き出した IPA・pkg が 1 つに決まりません（{len(packages)} 件）")
    return packages[0]


def packaged_app(package: Path, directory: Path) -> Path:
    """書き出した IPA・pkg を directory に展開し、中の .app（入れ子の .app は除く）を返す。"""
    if package.suffix == ".pkg":
        # 展開先は無い場所を指定する（あると pkgutil が止まる）。Payload の中身もファイルに展開される
        expanded = directory / "expanded"
        subprocess.run(["pkgutil", "--expand-full", str(package), str(expanded)], check=True)
        apps = [app for app in expanded.rglob("*.app")
                if not any(parent.suffix == ".app" for parent in app.relative_to(expanded).parents)]
    else:
        subprocess.run(["ditto", "-x", "-k", str(package), str(directory)], check=True)
        apps = list((directory / "Payload").glob("*.app"))
    if len(apps) != 1:
        raise fail(f"{package.name} の中に .app が 1 つに決まりません（{len(apps)} 件）")
    return apps[0]


def check(args: argparse.Namespace) -> int:
    """書き出した IPA・pkg の各バンドルの署名に、Archive とプロジェクトの entitlement がすべて残っているかを確かめる。

    Archive の本体と中のバンドルごとに、書き出したものの同じ場所のバンドルを探し、Archive の署名のキーと、
    `embed` の記録（`--record`）のソースのキーがすべてあるかを見る。記録のキーも見るのは、`embed` が入れ損ねたとき
    （Archive の署名にも無いとき）に、比べるだけでは通ってしまうため。
    配布用の profile に無い entitlement（App ID の capability が無効など）を Export が落とすと、
    その機能が動かなくなって初めて気づくことになるので、App Store Connect に上げる前に止める。
    比べるのはキーだけ（`aps-environment` のように、Export が値を配信用に書き換える項目があるため）。
    値は、展開されていない変数 `$(…)` が残っていないかだけを見る。合わないものは、すべて出してから止める。
    """
    package = exported_package(args.export)
    app = archived_app(args.archive)
    bundles = [app, *reversed(nested_bundles(app))]
    labels = [bundle_label(bundle, app) for bundle in bundles]
    sources = None
    problems = []
    if args.record:
        sources = {record["path"]: record["source"] for record in json.loads(args.record.read_text())["bundles"]}
        problems += [f"{label} が embed の記録にありません（embed が見ていないバンドルです）"
                     for label in labels if label not in sources]
        problems += [f"embed の記録の {label} が Archive にありません" for label in sources if label not in labels]

    results = []
    with tempfile.TemporaryDirectory() as directory:
        exported_app = packaged_app(package, Path(directory))
        for bundle, label in zip(bundles, labels):
            exported_bundle = exported_app / bundle.relative_to(app)
            if not exported_bundle.is_dir():
                problems.append(f"{package.name} に {label} がありません")
                results.append({"path": label, "exported": None, "missing": [], "unexpanded": []})
                continue
            archived = signed_entitlements(bundle) or {}
            exported = signed_entitlements(exported_bundle) or {}
            for key, value in sorted(exported.items()):
                print(f"{package.name}: {label}: {key} = {value}")
            expected = set(archived) | set((sources or {}).get(label, {}))
            missing = sorted(expected - set(exported))
            if missing:
                problems.append(f"{package.name} の {label} に {', '.join(missing)} がありません。"
                                "配布用の profile に入っているか（App ID の capability が有効か）を確かめてください")
            unexpanded = sorted(key for key, value in exported.items() if VARIABLE.search(repr(value)))
            if unexpanded:
                problems.append(f"{package.name} の {label} の entitlement に、展開されていない変数 $(…) が残っています: "
                                f"{', '.join(unexpanded)}")
            results.append({"path": label, "exported": exported, "missing": missing, "unexpanded": unexpanded})

    if args.report:
        write_json(args.report, {"package": package.name, "bundles": results})
    write_summary([
        f"### entitlements（{package.name}）",
        "",
        "| バンドル | 書き出したものの entitlements | 結果 |",
        "| --- | --- | --- |",
        *(f"| `{result['path']}` | {'—' if result['exported'] is None else keys_cell(result['exported'])} | {result_cell(result)} |"
          for result in results),
    ])
    if problems:
        raise SystemExit("\n".join(f"::error::{problem}" for problem in problems))
    return 0


def main(argv: list[str]) -> int:
    """`embed`・`mac-requirements`・`check` を流す（使い方はモジュールの説明）。"""
    parser = argparse.ArgumentParser(description="Archive の .app と中のバンドルに entitlements を入れ、書き出した IPA・pkg に残ったかを確かめる")
    commands = parser.add_subparsers(dest="command", required=True)
    embed_parser = commands.add_parser("embed", help="Archive の .app と中のバンドルに entitlements をアドホック署名で入れる")
    embed_parser.add_argument("archive", type=Path, help="xcodebuild archive で作った .xcarchive")
    embed_parser.add_argument("--project", required=True)
    embed_parser.add_argument("--scheme", required=True)
    embed_parser.add_argument("--sdk", required=True)
    embed_parser.add_argument("--configuration", required=True)
    embed_parser.add_argument("--record", type=Path, help="バンドルごとのソースの entitlements と署名の結果を書く JSON")
    embed_parser.set_defaults(handler=embed)
    requirements_parser = commands.add_parser("mac-requirements", help="macOS の Archive に App Sandbox とカテゴリがあるかを確かめる")
    requirements_parser.add_argument("archive", type=Path)
    requirements_parser.set_defaults(handler=mac_requirements)
    check_parser = commands.add_parser("check", help="書き出した IPA・pkg に Archive の entitlements が残ったかを確かめる")
    check_parser.add_argument("archive", type=Path)
    check_parser.add_argument("export", type=Path, help="書き出した IPA・pkg か、それを書き出したフォルダ")
    check_parser.add_argument("--record", type=Path, help="embed の --record の JSON（ソースの entitlements のキーも確かめる）")
    check_parser.add_argument("--report", type=Path, help="書き出したもののバンドルごとの entitlements を書く JSON")
    check_parser.set_defaults(handler=check)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
