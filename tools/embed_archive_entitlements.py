#!/usr/bin/env python3
"""Archive の .app に、プロジェクトの entitlements をアドホック署名で入れる（`app-archive.yml` の iOS・visionOS・macOS）。

書き出した IPA・pkg に、Archive の entitlements が残ったかも確かめる（`check`）。
shilokuma-inc/ask-hub-apple の `Tools/embed_archive_entitlements.py`（2026-11-09）を移したもの。

Export は、Archive の実行ファイルの署名にある entitlement だけを引き継いで配布用に署名し直し、profile からは足さない。
そのため署名しないで作った Archive からは、基本の entitlement（application-identifier など）しか無い配布ビルドになり、
WeatherKit・push などが実機で動かない。

- iOS・visionOS は `CODE_SIGNING_ALLOWED=NO` で Archive する（アドホック署名は、push などの entitlement が profile を要するため
  「requires a provisioning profile」で止まる）。署名の無い .app を、ビルドの設定（`xcodebuild -showBuildSettings`）で
  `$(VAR)` を展開した `CODE_SIGN_ENTITLEMENTS` でアドホック署名する
- macOS はアドホック署名（`CODE_SIGN_STYLE=Manual`）で Archive する（署名しないと、`ENABLE_APP_SANDBOX` などから作られる
  entitlement が入らず、App Store Connect が App Sandbox の無いアプリとして断る）。`CODE_SIGN_ENTITLEMENTS` はプロジェクトの既定の
  署名（自動）の設定で読み、Archive の署名の entitlement に足して署名し直す。足すものが無ければ署名し直さない。
  push のように profile の要る entitlement は、アドホック署名のビルドが止まるので、アプリの側で自動の署名のときだけ付けておく
  （ask-hub-apple の `Configs/Project.xcconfig`）。ここで足せば Export が引き継ぐ

値は Export が配布用の profile に合わせて書き換える（App Store なら production）。対象はアプリ本体だけ（App Extension は入れない）。

    python3 tools/embed_archive_entitlements.py embed build.xcarchive \\
        --project App.xcodeproj --scheme App --sdk iphoneos --configuration Release
    python3 tools/embed_archive_entitlements.py mac-requirements build.xcarchive   # macOS の Archive だけ
    python3 tools/embed_archive_entitlements.py check build.xcarchive export        # Export の後（IPA か pkg のある場所）
"""

from __future__ import annotations

import argparse
import json
import plistlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

#: entitlements の値の中の `$(NAME)` / `${NAME}`（Xcode がビルドの設定で展開する書き方）
VARIABLE = re.compile(r"\$[({]([A-Za-z_][A-Za-z0-9_]*)[)}]")

#: Mac App Store のアプリに要る entitlement
APP_SANDBOX = "com.apple.security.app-sandbox"

#: Xcode が署名のときに Team ID から決める変数（App Groups・キーチェーンの共有などに使う）。`-showBuildSettings` には出ない
SIGNING_PREFIXES = ("TeamIdentifierPrefix", "AppIdentifierPrefix")


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
            raise fail(f"entitlements の {', '.join(missing)} がビルドの設定にありません: {value}")
        return VARIABLE.sub(lambda match: settings[match.group(1)], value)
    if isinstance(value, list):
        return [expand(item, settings) for item in value]
    if isinstance(value, dict):
        return {key: expand(item, settings) for key, item in value.items()}
    return value


def with_signing_prefixes(settings: dict[str, str]) -> dict[str, str]:
    """`$(TeamIdentifierPrefix)`・`$(AppIdentifierPrefix)` を、ビルドの設定の DEVELOPMENT_TEAM（`<Team ID>.`）で補う。

    Xcode は署名するときに profile の Team ID でこの 2 つを決めるので、`-showBuildSettings` の結果には無い。
    今の App ID の接頭辞は Team ID と同じ（macOS のアドホック署名の Archive でも、Xcode は Team ID で展開する）。
    DEVELOPMENT_TEAM が無ければ補わない（使っていれば expand が止める）。
    """
    team = settings.get("DEVELOPMENT_TEAM", "")
    if not team:
        return settings
    return {**{name: f"{team}." for name in SIGNING_PREFIXES}, **settings}


def app_build_settings(entries: list[dict], product_name: str) -> dict[str, str]:
    """`xcodebuild -showBuildSettings -json` の結果から、Archive の .app（`App.app`）を作るターゲットの設定を選ぶ。

    Scheme にはテストや App Extension のターゲットも入るので、先頭の設定を読むと別のターゲットの entitlements になることがある。
    """
    matches = [entry["buildSettings"] for entry in entries
               if entry.get("buildSettings", {}).get("FULL_PRODUCT_NAME") == product_name]
    if len(matches) != 1:
        raise fail(f"{product_name} を作るターゲットが 1 つに決まりません（{len(matches)} 件）")
    return matches[0]


def archived_app(archive: Path) -> Path:
    """Archive の Info.plist の ApplicationPath（`Applications/App.app`）から .app の場所を返す。"""
    info = plistlib.loads((archive / "Info.plist").read_bytes())
    return archive / "Products" / info["ApplicationProperties"]["ApplicationPath"]


def signed_entitlements(app: Path) -> dict | None:
    """.app の署名にある entitlements。署名が無ければ None。"""
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


def embed(args: argparse.Namespace) -> int:
    """Archive の .app を、`CODE_SIGN_ENTITLEMENTS` を展開した entitlements でアドホック署名する。

    署名済み（macOS のアドホック署名の Archive）なら、その署名の entitlements（sandbox など）に足して署名し直す。
    上書きすると Xcode が入れた entitlement が消えるため。足すものが無ければ署名し直さない。
    `CODE_SIGN_ENTITLEMENTS` が空なら何もしない。署名の後に、入れた entitlements と署名の中身が同じかを確かめる。
    """
    app = archived_app(args.archive)
    signed = signed_entitlements(app)

    output = subprocess.run(
        ["xcodebuild", "-showBuildSettings", "-json", "-project", args.project, "-scheme", args.scheme,
         "-sdk", args.sdk, "-configuration", args.configuration],
        capture_output=True, text=True, check=True,
    ).stdout
    settings = with_signing_prefixes(app_build_settings(json.loads(output), app.name))
    path = settings.get("CODE_SIGN_ENTITLEMENTS", "")
    if not path:
        print(f"{app.name} の CODE_SIGN_ENTITLEMENTS が空なので、入れずに終わります")
        return 0
    entitlements = expand(plistlib.loads((Path(settings["SRCROOT"]) / path).read_bytes()), settings)
    if signed is not None:
        entitlements = merge(signed, entitlements, app.name)
        if entitlements == signed:
            for key, value in sorted(entitlements.items()):
                print(f"{app.name} の署名にあります: {key} = {value}")
            print(f"{app.name} の署名に {path} の項目がすべてあるので、署名し直しません")
            return 0
    # 署名し直すときは、Archive の署名の識別子とフラグ（macOS の Hardened Runtime）を残す。付けないとフラグが消える
    preserve = [] if signed is None else ["--preserve-metadata=identifier,flags"]

    with tempfile.NamedTemporaryFile(suffix=".entitlements") as file:
        file.write(plistlib.dumps(entitlements))
        file.flush()
        subprocess.run(["codesign", "--force", "--sign", "-", "--timestamp=none", "--generate-entitlement-der", *preserve,
                        "--entitlements", file.name, str(app)], check=True)

    if signed_entitlements(app) != entitlements:
        raise fail(f"{app.name} の署名の entitlements が、入れようとしたものと違います")
    for key, value in sorted(entitlements.items()):
        print(f"{app.name} に入れました: {key} = {value}")
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
    """書き出した IPA・pkg の署名に、Archive の署名の entitlement がすべて残っているかを確かめる。

    配布用の profile に無い entitlement（App ID の capability が無効など）を Export が落とすと、
    その機能が動かなくなって初めて気づくことになるので、App Store Connect に上げる前に止める。
    比べるのはキーだけ（`aps-environment` のように、Export が値を配信用に書き換える項目があるため）。
    値は、展開されていない変数 `$(…)` が残っていないかだけを見る。
    """
    package = exported_package(args.export)
    archived = signed_entitlements(archived_app(args.archive)) or {}
    with tempfile.TemporaryDirectory() as directory:
        exported = signed_entitlements(packaged_app(package, Path(directory))) or {}
    for key, value in sorted(exported.items()):
        print(f"{package.name}: {key} = {value}")
    missing = sorted(set(archived) - set(exported))
    if missing:
        raise fail(f"{package.name} に {', '.join(missing)} がありません。"
                   "配布用の profile に入っているか（App ID の capability が有効か）を確かめてください")
    unexpanded = sorted(key for key, value in exported.items() if VARIABLE.search(repr(value)))
    if unexpanded:
        raise fail(f"{package.name} の entitlement に、展開されていない変数 $(…) が残っています: {', '.join(unexpanded)}")
    return 0


def main(argv: list[str]) -> int:
    """`embed`・`mac-requirements`・`check` を流す（使い方はモジュールの説明）。"""
    parser = argparse.ArgumentParser(description="Archive の .app に entitlements を入れ、書き出した IPA・pkg に残ったかを確かめる")
    commands = parser.add_subparsers(dest="command", required=True)
    embed_parser = commands.add_parser("embed", help="Archive の .app に entitlements をアドホック署名で入れる")
    embed_parser.add_argument("archive", type=Path, help="xcodebuild archive で作った .xcarchive")
    embed_parser.add_argument("--project", required=True)
    embed_parser.add_argument("--scheme", required=True)
    embed_parser.add_argument("--sdk", required=True)
    embed_parser.add_argument("--configuration", required=True)
    embed_parser.set_defaults(handler=embed)
    requirements_parser = commands.add_parser("mac-requirements", help="macOS の Archive に App Sandbox とカテゴリがあるかを確かめる")
    requirements_parser.add_argument("archive", type=Path)
    requirements_parser.set_defaults(handler=mac_requirements)
    check_parser = commands.add_parser("check", help="書き出した IPA・pkg に Archive の entitlements が残ったかを確かめる")
    check_parser.add_argument("archive", type=Path)
    check_parser.add_argument("export", type=Path, help="書き出した IPA・pkg か、それを書き出したフォルダ")
    check_parser.set_defaults(handler=check)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
