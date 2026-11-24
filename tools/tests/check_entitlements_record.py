"""Archive のジョブが上げた entitlements の記録（`embed --record` の JSON）を、self-test で確かめる。

    python3 tools/tests/check_entitlements_record.py <archive.json> 'App.app=キー,キー' 'App.app/PlugIns/Widget.appex=キー'

記録のバンドルが引数のバンドルとちょうど同じで、各バンドルの署名に、引数のキーがちょうどあるかを見る（`App.app=` は entitlements なし）。
値に展開されていない `$(…)` が残っていないかも見る。合わないものをすべて出して 1 で終わる。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    record = json.loads(Path(argv[0]).read_text())
    expected = {}
    for argument in argv[1:]:
        path, _, keys = argument.partition("=")
        expected[path] = sorted(key for key in keys.split(",") if key)
    bundles = {bundle["path"]: bundle for bundle in record["bundles"]}
    problems = []
    if sorted(bundles) != sorted(expected):
        problems.append(f"記録のバンドルが違います: {sorted(bundles)}（期待: {sorted(expected)}）")
    for path, keys in expected.items():
        signed = bundles.get(path, {}).get("signed", {})
        print(f"{path}: {json.dumps(signed, ensure_ascii=False)}")
        if sorted(signed) != keys:
            problems.append(f"{path} の署名の entitlements のキーが違います: {sorted(signed)}（期待: {keys}）")
        if "$(" in json.dumps(signed) or "${" in json.dumps(signed):
            problems.append(f"{path} の署名に、展開されていない変数が残っています")
    for problem in problems:
        print(f"::error::{problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
