"""tools/embed_archive_entitlements.py のテスト。self-test.yml が ubuntu で流す。手元では `python3 tools/tests/test_embed_archive_entitlements.py`。

xcodebuild と codesign は、PATH の先頭に置く偽物（シェルスクリプト）に差し替える（ubuntu のランナーでも流れる）。
偽の codesign は、署名に渡された entitlements をバンドルごとのファイルに残し、`-d` でそれを返す。
shilokuma-inc/ask-hub-apple の `Tools/tests/test_embed_archive_entitlements.py` を移し、app-kit で足した動きのテストを足した。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import plistlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))

import embed_archive_entitlements  # noqa: E402

#: codesign の偽物。バンドル（最後の引数）ごとに、署名の entitlements を $CODESIGN_STATE/<パスの / を _ にしたもの> に残し、
#: 署名の引数を同じ名前の .args に、署名した順を $CODESIGN_LOG に残す。署名が無ければ「署名されていない」で失敗する
FAKE_CODESIGN = r"""#!/bin/bash
for target; do :; done
state="$CODESIGN_STATE/$(printf '%s' "$target" | tr '/' '_')"
if [ "$1" = "-d" ]; then
  if [ ! -e "$state" ]; then
    echo "code object is not signed at all" >&2
    exit 1
  fi
  cat "$state"
  exit 0
fi
printf '%s\n' "$target" >> "$CODESIGN_LOG"
printf '%s\n' "$@" > "$state.args"
entitlements=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--entitlements" ]; then entitlements="$2"; fi
  shift
done
if [ -n "$entitlements" ]; then cp "$entitlements" "$state"; else : > "$state"; fi
"""

#: xcodebuild の偽物。-showBuildSettings -json の結果として、-scheme なら $BUILD_SETTINGS、-alltargets と -sdk なら
#: $ALL_TARGET_SETTINGS、-sdk の無い -alltargets なら $NATIVE_SETTINGS を出す。呼ばれた引数を $XCODEBUILD_LOG に 1 行ずつ残す
FAKE_XCODEBUILD = r"""#!/bin/bash
echo "$*" >> "$XCODEBUILD_LOG"
all=false
sdk=false
for argument; do
  [ "$argument" = -alltargets ] && all=true
  [ "$argument" = -sdk ] && sdk=true
done
if [ "$all" = true ] && [ "$sdk" = true ]; then cat "$ALL_TARGET_SETTINGS"
elif [ "$all" = true ]; then cat "$NATIVE_SETTINGS"
else cat "$BUILD_SETTINGS"
fi
"""

ENTITLEMENTS = {"aps-environment": "$(APS_ENVIRONMENT)"}
WIDGET_ENTITLEMENTS = {"com.apple.security.application-groups": ["$(APP_GROUP_IDENTIFIER)"]}


def settings_entry(product: str, target: str | None = None, **settings: str) -> dict:
    """-showBuildSettings -json の 1 つのターゲットの設定。target を省くと製品の名前にする。"""
    return {"target": target or product, "buildSettings": {"FULL_PRODUCT_NAME": product, **settings}}


def write_archive(archive: Path, app_path: str = "Applications/App.app") -> Path:
    """Archive の Info.plist と空の .app を作り、.app の場所を返す。"""
    app = archive / "Products" / app_path
    app.mkdir(parents=True)
    (archive / "Info.plist").write_bytes(plistlib.dumps({"ApplicationProperties": {"ApplicationPath": app_path}}))
    return app


class ExpandTests(unittest.TestCase):
    def test_expands_both_forms_in_nested_values(self):
        value = {"a": "$(APS_ENVIRONMENT)", "b": ["${TEAM}.group", "x"], "c": True}
        self.assertEqual(
            embed_archive_entitlements.expand(value, {"APS_ENVIRONMENT": "production", "TEAM": "ABC"}),
            {"a": "production", "b": ["ABC.group", "x"], "c": True},
        )

    def test_missing_setting_stops(self):
        with self.assertRaises(SystemExit) as raised:
            embed_archive_entitlements.expand({"a": "$(APS_ENVIRONMENT)"}, {})
        self.assertIn("APS_ENVIRONMENT", str(raised.exception))


class SigningPrefixesTests(unittest.TestCase):
    def test_fills_team_prefix_from_team(self):
        # Xcode が署名のときに決める変数は -showBuildSettings に出ないので、DEVELOPMENT_TEAM で補う
        settings = embed_archive_entitlements.with_signing_prefixes({"DEVELOPMENT_TEAM": "ABCDE12345"})
        self.assertEqual(embed_archive_entitlements.expand(["$(TeamIdentifierPrefix)group"], settings),
                         ["ABCDE12345.group"])

    def test_keeps_values_from_build_settings(self):
        settings = embed_archive_entitlements.with_signing_prefixes(
            {"DEVELOPMENT_TEAM": "ABCDE12345", "TeamIdentifierPrefix": "OTHER12345."})
        self.assertEqual(settings["TeamIdentifierPrefix"], "OTHER12345.")

    def test_app_prefix_is_not_guessed(self):
        # App ID の接頭辞は、古い App ID では Team ID と違うので、推し量らずに止める
        settings = embed_archive_entitlements.with_signing_prefixes({"DEVELOPMENT_TEAM": "ABCDE12345"})
        with self.assertRaises(SystemExit) as raised:
            embed_archive_entitlements.expand("$(AppIdentifierPrefix)keychain", settings)
        self.assertIn("$(TeamIdentifierPrefix) と書いてください", str(raised.exception))

    def test_without_team_prefixes_stay_missing(self):
        with self.assertRaises(SystemExit) as raised:
            embed_archive_entitlements.expand("$(TeamIdentifierPrefix)group",
                                              embed_archive_entitlements.with_signing_prefixes({"DEVELOPMENT_TEAM": ""}))
        self.assertIn("TeamIdentifierPrefix", str(raised.exception))


class AppBuildSettingsTests(unittest.TestCase):
    def test_picks_target_that_builds_the_app(self):
        # Scheme の先頭がテストや App Extension のターゲットでも、アプリのターゲットの設定を読む
        entries = [settings_entry("AppTests.xctest"), settings_entry("Widget.appex"),
                   settings_entry("App.app", APS_ENVIRONMENT="production")]
        self.assertEqual(embed_archive_entitlements.app_build_settings(entries, "App.app")["APS_ENVIRONMENT"],
                         "production")

    def test_no_match_stops(self):
        with self.assertRaises(SystemExit):
            embed_archive_entitlements.app_build_settings([settings_entry("Other.app")], "App.app")


class TargetSettingsTests(unittest.TestCase):
    """本体の中のバンドルを作るターゲットを、-alltargets の設定から選ぶ。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def bundle(self, name: str, bundle_id: str = "jp.shilokuma.App.Widget") -> Path:
        bundle = self.tmp / name
        bundle.mkdir()
        (bundle / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": bundle_id}))
        return bundle

    def select(self, entries: list[dict], bundle: Path, native: list[dict] | None = None) -> dict:
        calls = []

        def load_native():
            calls.append(True)
            return native or []

        settings = embed_archive_entitlements.target_settings(entries, bundle, "iphoneos", load_native)
        self.native_calls = len(calls)
        return settings

    def test_picks_by_product_name(self):
        # -alltargets は先頭のターゲットを 2 回出すので、同じターゲットは 1 つに数える
        entries = [settings_entry("App.app"),
                   settings_entry("Widget.appex", CODE_SIGN_ENTITLEMENTS="W.entitlements",
                                  PRODUCT_BUNDLE_IDENTIFIER="jp.shilokuma.App.Widget"),
                   settings_entry("App.app")]
        self.assertEqual(self.select(entries, self.bundle("Widget.appex"))["CODE_SIGN_ENTITLEMENTS"], "W.entitlements")
        self.assertEqual(self.native_calls, 0)

    def test_same_product_name_is_narrowed_by_bundle_identifier(self):
        entries = [settings_entry("Widget.appex", target="WidgetA", PRODUCT_BUNDLE_IDENTIFIER="jp.shilokuma.App.Widget"),
                   settings_entry("Widget.appex", target="WidgetB", PRODUCT_BUNDLE_IDENTIFIER="jp.shilokuma.Other.Widget")]
        self.assertEqual(self.select(entries, self.bundle("Widget.appex"))["PRODUCT_BUNDLE_IDENTIFIER"],
                         "jp.shilokuma.App.Widget")

    def test_single_candidate_with_other_bundle_identifier_stops(self):
        # 同じ製品の名前を作るターゲットが 1 つでも、Bundle ID が違えば別のバンドルなので、その entitlements では署名しない
        entries = [settings_entry("Widget.appex", PRODUCT_BUNDLE_IDENTIFIER="jp.shilokuma.Other.Widget")]
        with self.assertRaises(SystemExit) as raised:
            self.select(entries, self.bundle("Widget.appex"))
        self.assertIn("jp.shilokuma.App.Widget", str(raised.exception))

    def test_bundle_without_identifier_is_picked_by_product_name(self):
        # Info.plist の無いバンドル（単体テストの偽の Archive など）は、Bundle ID を見ずに製品の名前で選ぶ
        bundle = self.tmp / "Widget.appex"
        bundle.mkdir()
        entries = [settings_entry("Widget.appex", CODE_SIGN_ENTITLEMENTS="W.entitlements")]
        self.assertEqual(self.select(entries, bundle)["CODE_SIGN_ENTITLEMENTS"], "W.entitlements")

    def test_same_name_and_bundle_identifier_is_narrowed_by_platform(self):
        # kawarin-apple の iOS と macOS のターゲットのように、同じ名前・同じ Bundle ID のバンドルを作るとき。
        # -sdk を付けた設定はどちらも iphoneos になるので、-sdk なしの設定のプラットフォームで選ぶ
        bundle_id = {"PRODUCT_BUNDLE_IDENTIFIER": "jp.shilokuma.App.Widget"}
        entries = [settings_entry("Widget.appex", target="WidgetMac", SUPPORTED_PLATFORMS="iphoneos", **bundle_id),
                   settings_entry("Widget.appex", target="WidgetiOS", SUPPORTED_PLATFORMS="iphoneos", **bundle_id)]
        native = [settings_entry("Widget.appex", target="WidgetMac", SUPPORTED_PLATFORMS="macosx"),
                  settings_entry("Widget.appex", target="WidgetiOS", SUPPORTED_PLATFORMS="iphoneos iphonesimulator")]
        self.assertEqual(self.select(entries, self.bundle("Widget.appex"), native)["SUPPORTED_PLATFORMS"], "iphoneos")
        self.assertEqual(self.native_calls, 1)

    def test_ambiguous_target_stops_with_candidates(self):
        bundle_id = {"PRODUCT_BUNDLE_IDENTIFIER": "jp.shilokuma.App.Widget"}
        entries = [settings_entry("Widget.appex", target="WidgetA", **bundle_id),
                   settings_entry("Widget.appex", target="WidgetB", **bundle_id)]
        native = [settings_entry("Widget.appex", target="WidgetA", SUPPORTED_PLATFORMS="iphoneos"),
                  settings_entry("Widget.appex", target="WidgetB", SUPPORTED_PLATFORMS="iphoneos")]
        with self.assertRaises(SystemExit) as raised:
            self.select(entries, self.bundle("Widget.appex"), native)
        self.assertIn("WidgetA、WidgetB", str(raised.exception))

    def test_missing_target_stops(self):
        with self.assertRaises(SystemExit) as raised:
            self.select([settings_entry("App.app")], self.bundle("Widget.appex"))
        self.assertIn("Widget.appex", str(raised.exception))


class NestedBundlesTests(unittest.TestCase):
    def test_lists_code_bundles_from_inside_and_skips_frameworks(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        app = tmp / "App.app"
        for path in ("PlugIns/Widget.appex", "PlugIns/Share.appex/PlugIns/Inner.appex", "Extensions/Kit.appex",
                     "AppClips/Clip.app", "Frameworks/Lib.framework/XPCServices/Helper.xpc", "Resources/Data.bundle"):
            (app / path).mkdir(parents=True)
        (app / "Linked.appex").symlink_to(app / "PlugIns/Widget.appex")
        self.assertEqual(
            [str(bundle.relative_to(app)) for bundle in embed_archive_entitlements.nested_bundles(app)],
            ["PlugIns/Share.appex/PlugIns/Inner.appex", "AppClips/Clip.app", "Extensions/Kit.appex",
             "PlugIns/Share.appex", "PlugIns/Widget.appex"],
        )


class EmbedTests(unittest.TestCase):
    def setUp(self):
        """偽の xcodebuild・codesign を PATH の先頭に置き、署名の無い Archive と entitlements のファイルを用意する。"""
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for name, script in (("codesign", FAKE_CODESIGN), ("xcodebuild", FAKE_XCODEBUILD)):
            (bin_dir / name).write_text(script)
            (bin_dir / name).chmod(0o755)

        self.archive = self.tmp / "build.xcarchive"
        self.app = write_archive(self.archive)
        self.source = self.tmp / "src"
        (self.source / "App").mkdir(parents=True)
        (self.source / "App/App.entitlements").write_bytes(plistlib.dumps(ENTITLEMENTS))
        (self.source / "Widget").mkdir()
        (self.source / "Widget/Widget.entitlements").write_bytes(plistlib.dumps(WIDGET_ENTITLEMENTS))

        self.state = self.tmp / "signatures"
        self.state.mkdir()
        self.codesign_log = self.tmp / "codesign.log"
        self.xcodebuild_log = self.tmp / "xcodebuild.log"
        self.settings = self.tmp / "settings.json"
        self.all_targets = self.tmp / "all-targets.json"
        self.native = self.tmp / "native.json"
        self.summary = self.tmp / "summary.md"
        self.record = self.tmp / "record/archive.json"
        self.write_settings(CODE_SIGN_ENTITLEMENTS="App/App.entitlements", APS_ENVIRONMENT="production")
        self.write_all_targets()
        self.native.write_text("[]")
        patcher = mock.patch.dict(os.environ, {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "CODESIGN_STATE": str(self.state),
            "CODESIGN_LOG": str(self.codesign_log),
            "BUILD_SETTINGS": str(self.settings),
            "ALL_TARGET_SETTINGS": str(self.all_targets),
            "NATIVE_SETTINGS": str(self.native),
            "XCODEBUILD_LOG": str(self.xcodebuild_log),
            "GITHUB_STEP_SUMMARY": str(self.summary),
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_settings(self, **settings: str):
        """-scheme の設定（本体だけ）。"""
        self.settings.write_text(json.dumps([settings_entry("App.app", SRCROOT=str(self.source), **settings)]))

    def write_all_targets(self, **widget: str):
        """-alltargets の設定（本体とウィジェット。先頭のターゲットは 2 回出る）。"""
        app = settings_entry("App.app", SRCROOT=str(self.source))
        widget = settings_entry("Widget.appex", SRCROOT=str(self.source), **{
            "CODE_SIGN_ENTITLEMENTS": "Widget/Widget.entitlements", "APP_GROUP_IDENTIFIER": "group.jp.shilokuma.App",
            **widget})
        self.all_targets.write_text(json.dumps([app, widget, app]))

    def add_bundle(self, path: str, **info) -> Path:
        bundle = self.app / path
        bundle.mkdir(parents=True)
        if info:
            (bundle / "Info.plist").write_bytes(plistlib.dumps(info))
        return bundle

    def state_of(self, bundle: Path) -> Path:
        return self.state / str(bundle).replace("/", "_")

    def set_signed(self, bundle: Path, entitlements: dict):
        self.state_of(bundle).write_bytes(plistlib.dumps(entitlements))

    def signed(self, bundle: Path) -> dict | None:
        state = self.state_of(bundle)
        if not state.exists():
            return None
        return plistlib.loads(state.read_bytes()) if state.read_bytes().strip() else {}

    def signed_arguments(self, bundle: Path) -> list[str]:
        return Path(f"{self.state_of(bundle)}.args").read_text().splitlines()

    def sign_order(self) -> list[str]:
        if not self.codesign_log.exists():
            return []
        return [str(Path(line).relative_to(self.app.parent)) for line in self.codesign_log.read_text().splitlines()]

    def run_main(self, sdk: str = "iphoneos") -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            return embed_archive_entitlements.main([
                "embed", str(self.archive), "--project", "App.xcodeproj", "--scheme", "App",
                "--sdk", sdk, "--configuration", "Release", "--record", str(self.record),
            ])

    def test_signs_with_expanded_entitlements(self):
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.signed(self.app), {"aps-environment": "production"})
        self.assertFalse(any(argument.startswith("--preserve-metadata") for argument in self.signed_arguments(self.app)))
        # 中のバンドルが無ければ、-alltargets を読まない（拡張の無いアプリは今までと同じ時間で済む）
        self.assertEqual(len(self.xcodebuild_log.read_text().splitlines()), 1)

    def test_writes_record_and_summary(self):
        self.assertEqual(self.run_main(), 0)
        record = json.loads(self.record.read_text())
        self.assertEqual(record["sdk"], "iphoneos")
        self.assertEqual(record["bundles"], [{
            "path": "App.app", "target": "", "entitlementsFile": "App/App.entitlements",
            "source": {"aps-environment": "production"}, "signed": {"aps-environment": "production"},
            "signedByAppKit": True,
        }])
        self.assertIn("| `App.app` |  | `aps-environment` | はい |", self.summary.read_text())

    def test_adds_to_signed_entitlements(self):
        # macOS のアドホック署名の Archive。上書きすると Xcode が入れた entitlement（sandbox など）が消えるので、足して署名し直す
        self.set_signed(self.app, {"com.apple.security.app-sandbox": True})
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.signed(self.app),
                         {"com.apple.security.app-sandbox": True, "aps-environment": "production"})
        # 署名し直すと Hardened Runtime のフラグが消えるので、Archive の署名から残す
        self.assertIn("--preserve-metadata=identifier,flags", self.signed_arguments(self.app))

    def test_signed_entitlements_already_complete_are_left_alone(self):
        # macOS のアドホック署名の Archive に、entitlements のファイルの項目がもう入っているとき（mullion など）は署名し直さない
        signed = {"com.apple.security.app-sandbox": True, "aps-environment": "production"}
        self.set_signed(self.app, signed)
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.signed(self.app), signed)
        self.assertEqual(self.sign_order(), [])

    def test_conflicting_signed_entitlement_stops(self):
        self.set_signed(self.app, {"aps-environment": "development"})
        with self.assertRaises(SystemExit) as raised:
            self.run_main()
        self.assertIn("aps-environment", str(raised.exception))
        self.assertEqual(self.signed(self.app), {"aps-environment": "development"})

    def test_no_entitlements_leaves_app_unsigned(self):
        self.write_settings(CODE_SIGN_ENTITLEMENTS="")
        self.assertEqual(self.run_main(), 0)
        self.assertIsNone(self.signed(self.app))
        self.assertEqual(json.loads(self.record.read_text())["bundles"][0]["signedByAppKit"], False)

    def test_missing_entitlements_file_stops(self):
        self.write_settings(CODE_SIGN_ENTITLEMENTS="App/Missing.entitlements")
        with self.assertRaises(SystemExit) as raised:
            self.run_main()
        self.assertIn("App/Missing.entitlements", str(raised.exception))

    def test_signs_extension_before_app(self):
        # 外側の署名は内側の署名を封じるので、ウィジェットを先に署名する（oshikatsu-countdown-ios の App Groups）
        widget = self.add_bundle("PlugIns/Widget.appex")
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.sign_order(), ["App.app/PlugIns/Widget.appex", "App.app"])
        self.assertEqual(self.signed(widget), {"com.apple.security.application-groups": ["group.jp.shilokuma.App"]})
        self.assertEqual(self.signed(self.app), {"aps-environment": "production"})
        self.assertEqual([bundle["path"] for bundle in json.loads(self.record.read_text())["bundles"]],
                         ["App.app", "App.app/PlugIns/Widget.appex"])

    def test_reseals_app_when_only_extension_has_entitlements(self):
        # 本体に entitlements が無くても、ウィジェットを署名したら本体も署名し直して封をする
        self.write_settings(CODE_SIGN_ENTITLEMENTS="")
        widget = self.add_bundle("PlugIns/Widget.appex")
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.sign_order(), ["App.app/PlugIns/Widget.appex", "App.app"])
        self.assertEqual(self.signed(self.app), {})
        self.assertNotIn("--entitlements", self.signed_arguments(self.app))
        self.assertIn("com.apple.security.application-groups", self.signed(widget))

    def test_extension_without_entitlements_is_left_unsigned(self):
        self.write_all_targets(CODE_SIGN_ENTITLEMENTS="")
        widget = self.add_bundle("PlugIns/Widget.appex")
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.sign_order(), ["App.app"])
        self.assertIsNone(self.signed(widget))

    def test_bundle_without_target_stops(self):
        self.add_bundle("PlugIns/Other.appex")
        with self.assertRaises(SystemExit) as raised:
            self.run_main()
        self.assertIn("Other.appex", str(raised.exception))
        self.assertEqual(self.sign_order(), [])

    def test_other_platform_bundle_stops(self):
        # watchOS のアプリは SDK が違い、-sdk iphoneos ではビルドの設定を正しく読めない
        self.add_bundle("Watch/Watch.app", DTPlatformName="watchos")
        with self.assertRaises(SystemExit) as raised:
            self.run_main()
        self.assertIn("watchos", str(raised.exception))

    def test_mac_extension_is_left_as_archived(self):
        # macOS の中のバンドルには足さない。本体だけに足して署名し直す（中のバンドルの署名は本体の封にそのまま入る）
        widget = self.add_bundle("Contents/PlugIns/Widget.appex")
        widget_signed = {"com.apple.security.app-sandbox": True,
                         "com.apple.security.application-groups": ["group.jp.shilokuma.App"]}
        self.set_signed(widget, widget_signed)
        self.set_signed(self.app, {"com.apple.security.app-sandbox": True})
        self.assertEqual(self.run_main("macosx"), 0)
        self.assertEqual(self.sign_order(), ["App.app"])
        self.assertEqual(self.signed(widget), widget_signed)
        self.assertEqual(self.signed(self.app), {"com.apple.security.app-sandbox": True, "aps-environment": "production"})

    def test_mac_extension_missing_source_entitlement_stops(self):
        # 自動の署名のときだけ付ける項目が中のバンドルにあると、アドホック署名の Archive に入らず、配信ビルドから抜ける
        self.write_all_targets(CODE_SIGN_ENTITLEMENTS="Widget/Widget.entitlements")
        (self.source / "Widget/Widget.entitlements").write_bytes(plistlib.dumps(
            {**WIDGET_ENTITLEMENTS, "com.apple.developer.weatherkit": True}))
        widget = self.add_bundle("Contents/PlugIns/Widget.appex")
        self.set_signed(widget, {"com.apple.security.app-sandbox": True,
                                 "com.apple.security.application-groups": ["group.jp.shilokuma.App"]})
        self.set_signed(self.app, {"com.apple.security.app-sandbox": True})
        with self.assertRaises(SystemExit) as raised:
            self.run_main("macosx")
        self.assertIn("com.apple.developer.weatherkit", str(raised.exception))
        self.assertEqual(self.sign_order(), [])


class MacRequirementsTests(unittest.TestCase):
    """macOS の Archive に App Sandbox と LSApplicationCategoryType があるか。codesign は差し替える。"""

    def run_requirements(self, entitlements: dict | None, info: dict) -> tuple[int, str]:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        archive = tmp / "build.xcarchive"
        app = write_archive(archive)
        (app / "Contents").mkdir()
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
        output = io.StringIO()
        with mock.patch.object(embed_archive_entitlements, "signed_entitlements", return_value=entitlements), \
                contextlib.redirect_stdout(output):
            code = embed_archive_entitlements.main(["mac-requirements", str(archive)])
        return code, output.getvalue()

    def test_passes_with_sandbox_and_category(self):
        code, _ = self.run_requirements({"com.apple.security.app-sandbox": True},
                                        {"LSApplicationCategoryType": "public.app-category.productivity"})
        self.assertEqual(code, 0)

    def test_stops_without_sandbox(self):
        # 署名なしで Archive すると、ENABLE_APP_SANDBOX から作られる entitlement が入らない
        code, output = self.run_requirements(None, {"LSApplicationCategoryType": "public.app-category.productivity"})
        self.assertEqual(code, 1)
        self.assertIn("com.apple.security.app-sandbox", output)

    def test_stops_without_category_and_reports_all(self):
        code, output = self.run_requirements({"com.apple.security.app-sandbox": False}, {})
        self.assertEqual(code, 1)
        self.assertIn("com.apple.security.app-sandbox", output)
        self.assertIn("LSApplicationCategoryType", output)


class CheckTests(unittest.TestCase):
    """書き出した IPA・pkg の各バンドルに、Archive と記録の entitlement が残ったか。ditto・pkgutil と codesign は差し替える。"""

    def run_check(self, archived: dict, exported: dict, package: str = "App.ipa", exported_bundles=None,
                  record: dict | None = None, pass_directory: bool = False) -> int:
        """archived・exported は、バンドルの場所（`App.app/PlugIns/Widget.appex`）ごとの署名の entitlements（None は署名なし）。"""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        archive = tmp / "build.xcarchive"
        applications = archive / "Products/Applications"
        for bundle in archived:
            (applications / bundle).mkdir(parents=True, exist_ok=True)
        (archive / "Info.plist").write_bytes(
            plistlib.dumps({"ApplicationProperties": {"ApplicationPath": "Applications/App.app"}}))
        export = tmp / "export"
        export.mkdir()
        (export / package).write_bytes(b"")
        self.report = tmp / "report/export.json"
        self.summary = tmp / "summary.md"
        arguments = ["--report", str(self.report)]
        if record is not None:
            (tmp / "archive.json").write_text(json.dumps(
                {"sdk": "iphoneos", "bundles": [{"path": path, "source": source} for path, source in record.items()]}))
            arguments += ["--record", str(tmp / "archive.json")]

        def fake_expand(command, check):
            """IPA・pkg を展開した代わりに、展開先に空のバンドルを作る（IPA は Payload/、pkg は component の Payload/ の下）。"""
            root = Path(command[-1]) / ("App.pkg/Payload" if command[0] == "pkgutil" else "Payload")
            for bundle in (exported if exported_bundles is None else exported_bundles):
                (root / bundle).mkdir(parents=True, exist_ok=True)

        def fake_signed_entitlements(bundle: Path):
            """Archive の中のバンドルには archived を、書き出したもののバンドルには exported を返す。"""
            if bundle.is_relative_to(archive):
                return archived.get(str(bundle.relative_to(applications)))
            parts = bundle.parts
            return exported.get("/".join(parts[parts.index("Payload") + 1:]))

        with mock.patch.object(embed_archive_entitlements.subprocess, "run", side_effect=fake_expand), \
                mock.patch.object(embed_archive_entitlements, "signed_entitlements", side_effect=fake_signed_entitlements), \
                mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(self.summary)}), \
                contextlib.redirect_stdout(io.StringIO()):
            target = export if pass_directory else export / package
            return embed_archive_entitlements.main(["check", str(archive), str(target), *arguments])

    def test_passes_when_exported_keeps_archived_keys(self):
        # 値は Export が profile に合わせて書き換える（development → production）ので、キーだけを比べる
        exported = {"aps-environment": "production", "application-identifier": "TEAM.jp.shilokuma.App"}
        self.assertEqual(self.run_check({"App.app": {"aps-environment": "development"}}, {"App.app": exported}), 0)

    def test_passes_without_entitlements(self):
        # entitlements のファイルが無い iOS のアプリは、署名の無い Archive になる
        self.assertEqual(self.run_check({"App.app": None}, {"App.app": {"application-identifier": "TEAM.jp.shilokuma.App"}}), 0)

    def test_stops_when_export_dropped_entitlement(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_check({"App.app": {"aps-environment": "production"}},
                           {"App.app": {"application-identifier": "TEAM.jp.shilokuma.App"}})
        self.assertIn("aps-environment", str(raised.exception))

    def test_stops_when_variable_is_left(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_check({"App.app": {}}, {"App.app": {"com.apple.security.application-groups": ["$(TeamIdentifierPrefix)group"]}})
        self.assertIn("com.apple.security.application-groups", str(raised.exception))

    def test_checks_extensions(self):
        groups = {"com.apple.security.application-groups": ["group.jp.shilokuma.App"]}
        bundles = {"App.app": groups, "App.app/PlugIns/Widget.appex": groups}
        self.assertEqual(self.run_check(bundles, bundles), 0)
        report = json.loads(self.report.read_text())
        self.assertEqual([bundle["path"] for bundle in report["bundles"]], ["App.app", "App.app/PlugIns/Widget.appex"])
        self.assertIn("| `App.app/PlugIns/Widget.appex` | `com.apple.security.application-groups` | ✅ |", self.summary.read_text())

    def test_stops_when_export_dropped_extension_entitlement(self):
        # v1.4.0 は本体しか見ず、ウィジェットの App Groups が抜けても Upload まで通っていた
        groups = {"com.apple.security.application-groups": ["group.jp.shilokuma.App"]}
        with self.assertRaises(SystemExit) as raised:
            self.run_check({"App.app": groups, "App.app/PlugIns/Widget.appex": groups},
                           {"App.app": groups, "App.app/PlugIns/Widget.appex": {}})
        self.assertIn("App.app/PlugIns/Widget.appex に com.apple.security.application-groups がありません", str(raised.exception))
        self.assertEqual(json.loads(self.report.read_text())["bundles"][1]["missing"],
                         ["com.apple.security.application-groups"])

    def test_stops_when_extension_is_missing_in_export(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_check({"App.app": {}, "App.app/PlugIns/Widget.appex": {}}, {"App.app": {}})
        self.assertIn("App.app/PlugIns/Widget.appex がありません", str(raised.exception))

    def test_stops_when_source_entitlement_is_in_neither(self):
        # embed が入れ損ねると、Archive の署名にも書き出したものにも無いので、比べるだけでは通ってしまう
        groups = {"com.apple.security.application-groups": ["group.jp.shilokuma.App"]}
        with self.assertRaises(SystemExit) as raised:
            self.run_check({"App.app": {}, "App.app/PlugIns/Widget.appex": {}},
                           {"App.app": {}, "App.app/PlugIns/Widget.appex": {}},
                           record={"App.app": {}, "App.app/PlugIns/Widget.appex": groups})
        self.assertIn("Widget.appex に com.apple.security.application-groups", str(raised.exception))

    def test_stops_when_bundle_is_not_in_record(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_check({"App.app": {}, "App.app/PlugIns/Widget.appex": {}},
                           {"App.app": {}, "App.app/PlugIns/Widget.appex": {}}, record={"App.app": {}})
        self.assertIn("App.app/PlugIns/Widget.appex が embed の記録にありません", str(raised.exception))

    def test_reports_all_problems(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_check({"App.app": {"aps-environment": "production"}, "App.app/PlugIns/Widget.appex": {}},
                           {"App.app": {}})
        self.assertIn("aps-environment", str(raised.exception))
        self.assertIn("Widget.appex がありません", str(raised.exception))

    def test_checks_app_in_pkg(self):
        # macOS の pkg。書き出したものだけにある入れ子の .app（ヘルパーなど）は、Archive に無いので見ない。書き出した場所（フォルダ）を渡してもよい
        archived = {"com.apple.developer.aps-environment": "production", "com.apple.security.app-sandbox": True}
        extension = {"com.apple.security.app-sandbox": True}
        bundles = {"App.app": archived, "App.app/Contents/PlugIns/Widget.appex": extension}
        self.assertEqual(self.run_check(bundles, bundles, package="App.pkg", pass_directory=True,
                                        exported_bundles=[*bundles, "App.app/Contents/Library/Helper.app"]), 0)
        with self.assertRaises(SystemExit) as raised:
            self.run_check(bundles, {"App.app": archived, "App.app/Contents/PlugIns/Widget.appex": {}}, package="App.pkg")
        self.assertIn("com.apple.security.app-sandbox", str(raised.exception))

    def test_pkg_without_app_stops(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_check({"App.app": {}}, {}, package="App.pkg")
        self.assertIn("App.pkg", str(raised.exception))

    def test_export_directory_without_package_stops(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        with self.assertRaises(SystemExit) as raised:
            embed_archive_entitlements.exported_package(tmp)
        self.assertIn("0 件", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
