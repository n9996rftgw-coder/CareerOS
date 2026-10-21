"""Load and validate the source of truth."""
import re
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
SOT = ROOT / "sot"

DATE_RE = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}$|^Present$|^TBC$")
RETIRED = [r"mckinsey", r"distinction"]


def load_master():
    return yaml.safe_load((SOT / "master.yaml").read_text())


def load_context():
    return yaml.safe_load((SOT / "personal_context.yaml").read_text())


def bullet_index(master):
    """id -> (role, bullet)"""
    idx = {}
    for role in master.get("roles", []):
        if not isinstance(role, dict):
            continue
        for b in role.get("bullets", []):
            if isinstance(b, dict) and b.get("id"):
                idx[b["id"]] = (role, b)
    return idx


def validate(master):
    """Return list of (level, message). level in FAIL / WARN / INFO."""
    out, seen, role_ids = [], set(), set()
    if not isinstance(master, dict):
        return [("FAIL", "master must be a mapping")]
    if not isinstance(master.get("profile"), dict):
        out.append(("FAIL", "profile must be a mapping"))
    else:
        for field in ("name", "city", "email"):
            if not isinstance(master["profile"].get(field), str) or not master["profile"][field].strip():
                out.append(("FAIL", f"profile.{field} must be nonempty text"))
    for field in ("roles", "education", "skills", "certifications", "awards"):
        if not isinstance(master.get(field), list):
            out.append(("FAIL", f"{field} must be a list"))
    if any(level == "FAIL" for level, _ in out):
        return out
    for role in master["roles"]:
        if not isinstance(role, dict):
            out.append(("FAIL", "Every role must be a mapping"))
            continue
        rid = role.get("id") if isinstance(role.get("id"), str) else "<invalid ID>"
        for field in ("id", "employer", "title", "location", "start", "end"):
            if not isinstance(role.get(field), str) or not role[field].strip():
                out.append(("FAIL", f"{rid}: {field} must be nonempty text"))
        if rid in role_ids:
            out.append(("FAIL", f"duplicate role id {rid}"))
        role_ids.add(rid)
        if role.get("section", "experience") not in ("experience", "projects"):
            out.append(("FAIL", f"{rid}: section must be experience or projects"))
        for key in ("start", "end"):
            if not DATE_RE.match(str(role.get(key, ""))):
                out.append(("FAIL", f"{rid}: bad {key} date '{role.get(key)}' (use 'Mon YYYY')"))
            elif role.get(key) == "TBC":
                out.append(("WARN", f"{rid}: {key} date is TBC"))
        if role.get("start") == "Present":
            out.append(("FAIL", f"{rid}: start cannot be Present"))
        if all(DATE_RE.match(str(role.get(key, ""))) and role.get(key) not in ("Present", "TBC") for key in ("start", "end")):
            from datetime import datetime
            try:
                if datetime.strptime(role["start"], "%b %Y") > datetime.strptime(role["end"], "%b %Y"):
                    out.append(("FAIL", f"{rid}: start date is after end date"))
            except ValueError:
                out.append(("FAIL", f"{rid}: invalid calendar year in role dates"))
        if role.get("flag"):
            out.append(("WARN", f"{rid} ({role.get('employer', '')}): {role['flag']}"))
        if not isinstance(role.get("bullets"), list):
            out.append(("FAIL", f"{rid}: bullets must be a list"))
            continue
        for b in role["bullets"]:
            if not isinstance(b, dict) or not isinstance(b.get("id"), str) or not isinstance(b.get("text"), str) or not b.get("id") or not b.get("text"):
                out.append(("FAIL", f"{rid}: every bullet needs a nonempty id and text"))
                continue
            if not isinstance(b.get("tags", []), list) or not all(isinstance(tag, str) for tag in b.get("tags", [])):
                out.append(("FAIL", f"{b['id']}: tags must be a list of text"))
            if b["id"] in seen:
                out.append(("FAIL", f"duplicate bullet id {b['id']}"))
            seen.add(b["id"])
            for pat in RETIRED:
                if re.search(pat, b["text"], re.I):
                    out.append(("FAIL", f"{b['id']}: retired claim matches '{pat}'"))
            if re.search(r"\d", b["text"]) and not b.get("number_note") and re.search(r"\d+[\d,.]*\s*[BMK+%]", b["text"]):
                out.append(("WARN", f"{b['id']}: contains a figure but no number_note"))
            if b.get("flag"):
                out.append(("WARN", f"{b['id']}: {b['flag']}"))
            if b.get("status") != "confirmed":
                out.append(("INFO", f"{b['id']}: status {b.get('status')} — awaiting candidate's wording"))
    if not all(isinstance(skill, str) and skill.strip() for skill in master["skills"]):
        out.append(("FAIL", "skills must contain nonempty text"))
    for i, entry in enumerate(master["education"]):
        if not isinstance(entry, dict) or not all(isinstance(entry.get(key), str) and entry[key].strip() for key in ("institution", "award", "start", "end")):
            out.append(("FAIL", f"education.{i} needs institution, award, start and end text"))
    for c in master.get("certifications", []) + master.get("awards", []):
        if not isinstance(c, dict) or not isinstance(c.get("text"), str) or not c["text"].strip():
            out.append(("FAIL", "Every certification and award needs nonempty text"))
            continue
        if c.get("flag"):
            out.append(("WARN", f"{c['text']}: {c['flag']}"))
        for pat in RETIRED:
            if re.search(pat, c["text"], re.I):
                out.append(("FAIL", f"retired claim in certifications/awards: {c['text']}"))
    return out
