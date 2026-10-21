#!/usr/bin/env python3
"""Make a new allowlisted, anonymised code copy and source-only publication ZIP.

This tool never authenticates, creates a remote repository or pushes source.
It requires PyYAML, the same dependency as the core application.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

import yaml


FILES = (
    "README.md", "requirements.txt", "package.json", "cli.py", "server.py", "build_sheet.py",
    "careeros/__init__.py", "careeros/tracker.py", "careeros/sot.py", "careeros/jd.py",
    "careeros/builder.py", "careeros/reviewer.py", "careeros/research.py", "careeros/render_docx.js",
    "web/index.html", "web/app.js", "web/style.css", "tools/build_tracker.mjs", "tools/WORKBOOK.md",
    "tools/prepare_repository.py", "docs/GITHUB.md", ".github/workflows/tests.yml",
    "tests/test_evidence.py", "tests/test_tracker.py", "tests/test_server.py", "tests/test_workbook.py",
    "examples/seed_demo.py", "examples/runtime.example.json", "examples/sot/master.yaml",
    "examples/sot/personal_context.yaml", "examples/sot/knowledge.yaml", "examples/sot/operating_rules.md",
    "examples/data/applications.csv", "examples/data/network.csv", "examples/data/targets.csv",
)
GITIGNORE = """# Private runtime records stay outside the code repository.
/data/
/sot/
/reference/
/research/
/jobs/
/outputs/
/exports/
/.runtime/
/.venv/
/.runtime.json
/integrations.json
/node_modules/
/CareerOS_Package/
*.zip
__pycache__/
*.pyc
.DS_Store
.env*
*.log
*.pdf
*.docx
*.xlsx
"""
EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
HOME_PATH = re.compile(r"/(?:Users|home)/[^\s\"'<>]+")
SECRET = re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|ya29\.[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")


def private_identifiers(source):
    """Read identifiers for an in-memory exclusion check; never save their values."""
    strings, names = set(), []
    master = source / "sot/master.yaml"
    if master.is_file():
        profile = (yaml.safe_load(master.read_text(encoding="utf-8")) or {}).get("profile", {})
        email = str(profile.get("email", ""))
        # A seeded fictional example is safe to include as an example.
        if not email.endswith(".invalid"):
            for field in ("name", "email", "phone", "linkedin", "portfolio"):
                value = str(profile.get(field, "")).strip()
                if value:
                    strings.add(value)
            names = [token for token in str(profile.get("name", "")).split() if len(token) >= 3]
            strings.update(names)
    for table, fields in (("network", ("Name", "Email", "LinkedIn")), ("targets", ("Organisation",))):
        path = source / "data" / f"{table}.csv"
        if path.is_file():
            with path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    strings.update(row.get(field, "").strip() for field in fields if len(row.get(field, "").strip()) >= 4)
    return strings, names


def anonymise(text, relative, names):
    for name in sorted(names, key=len, reverse=True):
        text = re.sub(r"\b" + re.escape(name) + r"\b", "candidate", text, flags=re.I)
    if relative == "web/index.html":
        text = re.sub(r"<title>[^<]*</title>", "<title>CareerOS · Workspace</title>", text)
        text = re.sub(r'<div class="avatar">[^<]*</div>', '<div class="avatar">CO</div>', text)
        text = re.sub(r'(<div class="profile">.*?<strong>)[^<]*(</strong><small>)[^<]*(</small>)',
                      r'\1CareerOS workspace\2Configure your goal\3', text)
    if relative == "server.py":
        text = re.sub(r'("goal":\s*)("[^"\n]*")',
                      lambda match: match.group(1) + 'context.get("target", ' + match.group(2) + ')', text)
        text = re.sub(r'("history_notice":\s*)"[^"\n]*"',
                      lambda match: match.group(1) + json.dumps("New workspaces start without earlier applications. Existing records have not been merged; import only a reviewed snapshot."), text)
    if relative == "cli.py":
        text = re.sub(r'    o\.add_argument\("--sent", help=[^\n]+',
                      '    o.add_argument("--sent", help="asset or document version actually sent")', text)
    return text


def scan(folder, identifiers):
    issues = []
    paths = sorted(path for path in folder.rglob("*") if path.is_file())
    for path in paths:
        relative = path.relative_to(folder).as_posix()
        if path.is_symlink():
            issues.append({"path": relative, "category": "symlink"})
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            issues.append({"path": relative, "category": "non-text file"})
            continue
        for identifier in identifiers:
            if re.search(r"(?<!\w)" + re.escape(identifier) + r"(?!\w)", content, re.I):
                issues.append({"path": relative, "category": "private identifier"})
                break
        if HOME_PATH.search(content):
            issues.append({"path": relative, "category": "absolute home path"})
        if SECRET.search(content):
            issues.append({"path": relative, "category": "credential pattern"})
        for email in EMAIL.findall(content):
            domain = email.rsplit("@", 1)[1].lower()
            if not (domain.endswith(".invalid") or domain in {"example.com", "example.org", "example.net"}):
                issues.append({"path": relative, "category": "non-example email"})
                break
    return issues


def reserve_directory(requested):
    for number in range(1, 1000000):
        candidate = requested if number == 1 else requested.with_name(requested.name + f"-{number:03d}")
        try:
            candidate.mkdir(parents=True)
        except FileExistsError:
            continue
        return candidate
    raise RuntimeError("No free publication directory")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source = args.source.expanduser().resolve()
    requested = args.output.expanduser().resolve() if args.output else source.parent / "CareerOS-publication"
    if requested == source or source in requested.parents:
        raise SystemExit("Publication must be outside the working source directory")
    identifiers, names = private_identifiers(source)
    # Read every allowlisted source before creating an artifact. Refuse symlinks.
    payload = {}
    for relative in FILES:
        path = source / relative
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(source):
            raise SystemExit("Missing or unsafe allowlisted file: " + relative)
        payload[relative] = anonymise(path.read_text(encoding="utf-8"), relative, names)
    payload[".gitignore"] = GITIGNORE
    destination = reserve_directory(requested)
    for relative, content in payload.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    issues = scan(destination, identifiers)
    if issues:
        print(json.dumps({"status": "BLOCKED", "issues": issues}, indent=2))
        raise SystemExit("Privacy scan failed. No publication ZIP was created.")
    timestamp = datetime.now(timezone.utc).isoformat()
    report = {"status": "passed", "checked_at_utc": timestamp, "files_scanned": len(payload),
              "checks": ["private identifiers", "non-example email addresses", "absolute home paths", "common credential patterns", "text-only allowlisted files"],
              "excluded": ["candidate evidence", "live records", "contacts", "job descriptions", "research", "CVs", "exports", "source archives", "integrations", "credentials", "runtimes"],
              "limitations": "Pattern scanning and an allowlist require human review; they do not prove every future change safe."}
    (destination / "PRIVACY_REPORT.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    entries = []
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            raw = path.read_bytes()
            entries.append({"path": path.relative_to(destination).as_posix(), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    manifest = {"format": 1, "created_at_utc": timestamp, "scope": "code and fictional examples only", "files": entries,
                "unhashed_metadata": ["PUBLICATION_MANIFEST.json"]}
    (destination / "PUBLICATION_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if scan(destination, identifiers):
        raise SystemExit("Final metadata scan failed. No ZIP was created.")
    archive = destination.with_suffix(".zip")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as out:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                out.write(path, (Path(destination.name) / path.relative_to(destination)).as_posix())
    print(json.dumps({"publication": str(destination), "archive": str(archive), "payload_files": len(payload), "privacy": "passed"}, indent=2))


if __name__ == "__main__":
    main()
