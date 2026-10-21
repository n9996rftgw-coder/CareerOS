"""Export CareerOS CSVs through the bundled Artifact Tool runtime."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--preview-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--test-only", action="store_true", help="Run formula fixtures without exporting")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    sys.path.insert(0, str(root))
    from careeros import tracker
    payload = {"schema": tracker.TABLES, "choices": tracker.CHOICES,
               "rows": {name: tracker.read(name) for name in tracker.TABLES},
               "constants": {name: getattr(tracker, name) for name in
                             ("MATURE_DAYS", "NO_RESPONSE_DAYS", "FOLLOW_UP_DAYS")}}
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
    node = os.environ.get("CAREEROS_NODE") or (str(bundled) if bundled.is_file() else shutil.which("node"))
    if not node:
        raise SystemExit("Node.js is unavailable. Open CareerOS in Codex and run setup again.")
    cmd = [node, str(root / "tools/build_tracker.mjs"), "--output", str(args.output.expanduser().resolve())]
    if args.preview_dir:
        cmd += ["--preview-dir", str(args.preview_dir.expanduser().resolve())]
    if args.self_test:
        cmd += ["--self-test"]
    if args.test_only:
        cmd += ["--self-test", "--test-only"]
    result = subprocess.run(cmd, input=json.dumps(payload), text=True, cwd=root)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
