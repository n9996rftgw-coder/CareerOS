"""Company research: one markdown file per target, research/<TargetID>-<name>.md.
Every fact line carries (source: URL, YYYY-MM-DD). 'My angle' is opinion and needs no source.
brief and prep read these files; validate flags unsourced facts and stale research."""
import re
from datetime import date
from pathlib import Path

RESEARCH = Path(__file__).resolve().parent.parent / "research"
FACT_SECTIONS = ["Snapshot", "Recent campaigns and content", "Partnerships and sponsors",
                 "Their problems and opportunities", "People"]
OPINION = "My angle"
STALE_DAYS = 30
SOURCE = re.compile(r"\(source:\s*\S+.*?\d{4}-\d{2}-\d{2}\s*\)", re.I)

TEMPLATE = """# Research — {org} ({tid})

Rule: every fact line ends with (source: URL, YYYY-MM-DD). Opinions go under "My angle" only.

## Snapshot
-

## Recent campaigns and content
-

## Partnerships and sponsors
-

## Their problems and opportunities
-

## People
-

## My angle
- What I'd bring, in one line:
- The idea I'd pitch:
"""


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def path_for(target):
    return RESEARCH / f"{target['ID']}-{slug(target['Organisation'])}.md"


def create(target):
    """Make an empty skeleton for a target. Only runs when asked; never fills anything in."""
    RESEARCH.mkdir(exist_ok=True)
    p = path_for(target)
    if not p.exists():
        p.write_text(TEMPLATE.format(org=target["Organisation"], tid=target["ID"]))
    return p


def find(target_id):
    hits = sorted(RESEARCH.glob(f"{target_id}-*.md")) if RESEARCH.exists() else []
    return hits[0] if hits else None


def sections(target_id):
    """{section: [filled bullet lines]} for a target, or {} if there's no research."""
    p = find(target_id) if target_id else None
    if not p:
        return {}
    out, cur = {}, None
    for line in p.read_text().splitlines():
        if line.startswith("## "):
            cur = line[3:].strip(); out[cur] = []
        elif cur and line.strip().startswith("- ") and len(line.strip()) > 2 and not line.strip().endswith(":"):
            out[cur].append(line.strip()[2:])
    return {k: v for k, v in out.items() if v}


def updated(p):
    return date.fromtimestamp(p.stat().st_mtime)


def check():
    """(level, message) for unsourced facts and stale files."""
    issues = []
    if not RESEARCH.exists():
        return issues
    for p in sorted(RESEARCH.glob("*.md")):
        secs = sections(p.name.split("-")[0])
        for sec in FACT_SECTIONS:
            for line in secs.get(sec, []):
                if not SOURCE.search(line):
                    issues.append(("WARN", f"research {p.name} [{sec}]: no source — '{line[:60]}'"))
        age = (date.today() - updated(p)).days
        if age > STALE_DAYS:
            issues.append(("INFO", f"research {p.name} last edited {age} days ago — refresh before using"))
    return issues
