"""tools/embed_archive_entitlements.py のテスト。self-test.yml が ubuntu で流す。手元では `python3 tools/tests/test_embed_archive_entitlements.py`。

xcodebuild と codesign は、PATH の先頭に置く偽物（シェルスクリプト）に差し替える（ubuntu のランナーでも流れる）。
偽の codesign は、署名に渡された entitlements をファイルに残し、`-d` でそれを返す。
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

#: codesign の偽物。署名の entitlements を $CODESIGN_STATE に、署名の引数を $CODESIGN_ARGS に残す。無ければ「署名されていない」で失敗する
FAKE_CODESIGN = r"""#!/bin/bash
if [ "$1" = "-d" ]; then
  if [ ! -e "$CODESIGN_STATE" ]; then
    echo "code object is not signed at all" >&2
    exit 1
  fi
  cat "$CODESIGN_STATE"
  exit 0
fi
printf '%s\n' "$@" > "$CODESIGN_ARGS"
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--entitlements" ]; then cp "$2" "$CODESIGN_STATE"; fi
  shift
done
"""

#: xcodebuild の偽物。-showBuildSettings -json の結果として $BUILD_SETTINGS を出す
FAKE_XCODEBUILD = r"""#!/bin/bash
cat "$BUILD_SETTINGS"
"""

ENTITLEMENTS = {"aps-environment": "$(APS_ENVIRONMENT)"}


def settings_entry(product: str, **settings: str) -> dict:
    return {"target": product, "buildSettings": {"FULL_PRODUCT_NAME": product, **settings}}


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
    def test_fills_prefixes_from_team(self):
        # Xcode が署名のときに決める変数は -showBuildSettings に出ないので、DEVELOPMENT_TEAM で補う
        settings = embed_archive_entitlements.with_signing_prefixes({"DEVELOPMENT_TEAM": "ABCDE12345"})
        self.assertEqual(
            embed_archive_entitlements.expand(["$(TeamIdentifierPrefix)group", "$(AppIdentifierPrefix)keychain"], settings),
            ["ABCDE12345.group", "ABCDE12345.keychain"],
        )

    def test_keeps_values_from_build_settings(self):
        settings = embed_archive_entitlements.with_signing_prefixes(
            {"DEVELOPMENT_TEAM": "ABCDE12345", "AppIdentifierPrefix": "LEGACY123."})
        self.assertEqual(settings["AppIdentifierPrefix"], "LEGACY123.")

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
        write_archive(self.archive)
        self.source = self.tmp / "src"
        (self.source / "App").mkdir(parents=True)
        (self.source / "App/App.entitlements").write_bytes(plistlib.dumps(ENTITLEMENTS))

        self.state = self.tmp / "signed.plist"
        self.args = self.tmp / "codesign-args.txt"
        self.settings = self.tmp / "settings.json"
        self.write_settings(CODE_SIGN_ENTITLEMENTS="App/App.entitlements", APS_ENVIRONMENT="production")
        patcher = mock.patch.dict(os.environ, {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "CODESIGN_STATE": str(self.state),
            "CODESIGN_ARGS": str(self.args),
            "BUILD_SETTINGS": str(self.settings),
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_settings(self, **settings: str):
        self.settings.write_text(json.dumps([settings_entry("App.app", SRCROOT=str(self.source), **settings)]))

    def run_main(self) -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            return embed_archive_entitlements.main([
                "embed", str(self.archive), "--project", "App.xcodeproj", "--scheme", "App",
                "--sdk", "iphoneos", "--configuration", "Release",
            ])

    def signed_arguments(self) -> list[str]:
        return self.args.read_text().splitlines()

    def test_signs_with_expanded_entitlements(self):
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(plistlib.loads(self.state.read_bytes()), {"aps-environment": "production"})
        self.assertFalse(any(argument.startswith("--preserve-metadata") for argument in self.signed_arguments()))

    def test_adds_to_signed_entitlements(self):
        # macOS のアドホック署名の Archive。上書きすると Xcode が入れた entitlement（sandbox など）が消えるので、足して署名し直す
        self.state.write_bytes(plistlib.dumps({"com.apple.security.app-sandbox": True}))
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(plistlib.loads(self.state.read_bytes()),
                         {"com.apple.security.app-sandbox": True, "aps-environment": "production"})
        # 署名し直すと Hardened Runtime のフラグが消えるので、Archive の署名から残す
        self.assertIn("--preserve-metadata=identifier,flags", self.signed_arguments())

    def test_signed_entitlements_already_complete_are_left_alone(self):
        # macOS のアドホック署名の Archive に、entitlements のファイルの項目がもう入っているとき（mullion など）は署名し直さない
        signed = {"com.apple.security.app-sandbox": True, "aps-environment": "production"}
        self.state.write_bytes(plistlib.dumps(signed))
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(plistlib.loads(self.state.read_bytes()), signed)
        self.assertFalse(self.args.exists())

    def test_conflicting_signed_entitlement_stops(self):
        self.state.write_bytes(plistlib.dumps({"aps-environment": "development"}))
        with self.assertRaises(SystemExit) as raised:
            self.run_main()
        self.assertIn("aps-environment", str(raised.exception))
        self.assertEqual(plistlib.loads(self.state.read_bytes()), {"aps-environment": "development"})

    def test_no_entitlements_leaves_app_unsigned(self):
        self.write_settings(CODE_SIGN_ENTITLEMENTS="")
        self.assertEqual(self.run_main(), 0)
        self.assertFalse(self.state.exists())


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
    """書き出した IPA・pkg に、Archive の署名の entitlement が残ったか。ditto・pkgutil と codesign は差し替える。"""

    def run_check(self, archived: dict | None, exported: dict | None, package: str = "App.ipa",
                  apps: tuple[str, ...] = ("App.app",), pass_directory: bool = False) -> int:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        archive = tmp / "build.xcarchive"
        archive.mkdir()
        (archive / "Info.plist").write_bytes(
            plistlib.dumps({"ApplicationProperties": {"ApplicationPath": "Applications/App.app"}}))
        export = tmp / "export"
        export.mkdir()
        (export / package).write_bytes(b"")

        def fake_expand(command, check):
            """IPA・pkg を展開した代わりに、展開先に空の .app を作る（IPA は Payload/、pkg は component の Payload/ の下）。"""
            root = Path(command[-1]) / ("App.pkg/Payload" if command[0] == "pkgutil" else "Payload")
            for app in apps:
                (root / app).mkdir(parents=True)

        def fake_signed_entitlements(app: Path):
            """Archive の中の .app には archived を、IPA の .app には exported を返す。"""
            return archived if app.is_relative_to(archive) else exported

        with mock.patch.object(embed_archive_entitlements.subprocess, "run", side_effect=fake_expand), \
                mock.patch.object(embed_archive_entitlements, "signed_entitlements", side_effect=fake_signed_entitlements), \
                contextlib.redirect_stdout(io.StringIO()):
            target = export if pass_directory else export / package
            return embed_archive_entitlements.main(["check", str(archive), str(target)])

    def test_passes_when_exported_keeps_archived_keys(self):
        # 値は Export が profile に合わせて書き換える（development → production）ので、キーだけを比べる
        exported = {"aps-environment": "production", "application-identifier": "TEAM.jp.shilokuma.App"}
        self.assertEqual(self.run_check({"aps-environment": "development"}, exported), 0)

    def test_passes_without_entitlements(self):
        # entitlements のファイルが無い iOS のアプリは、署名の無い Archive になる
        self.assertEqual(self.run_check(None, {"application-identifier": "TEAM.jp.shilokuma.App"}), 0)

    def test_stops_when_export_dropped_entitlement(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_check({"aps-environment": "production"}, {"application-identifier": "TEAM.jp.shilokuma.App"})
        self.assertIn("aps-environment", str(raised.exception))

    def test_stops_when_variable_is_left(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_check({}, {"com.apple.security.application-groups": ["$(TeamIdentifierPrefix)group"]})
        self.assertIn("com.apple.security.application-groups", str(raised.exception))

    def test_checks_app_in_pkg(self):
        # macOS の pkg。入れ子の .app（ヘルパーなど）は数えない。書き出した場所（フォルダ）を渡してもよい
        archived = {"com.apple.developer.aps-environment": "production", "com.apple.security.app-sandbox": True}
        apps = ("App.app", "App.app/Contents/Library/Helper.app")
        self.assertEqual(self.run_check(archived, archived, package="App.pkg", apps=apps, pass_directory=True), 0)
        with self.assertRaises(SystemExit) as raised:
            self.run_check(archived, {"com.apple.security.app-sandbox": True}, package="App.pkg")
        self.assertIn("com.apple.developer.aps-environment", str(raised.exception))

    def test_pkg_without_app_stops(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_check({}, {}, package="App.pkg", apps=())
        self.assertIn("App.pkg", str(raised.exception))

    def test_export_directory_without_package_stops(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        with self.assertRaises(SystemExit) as raised:
            embed_archive_entitlements.exported_package(tmp)
        self.assertIn("0 件", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
