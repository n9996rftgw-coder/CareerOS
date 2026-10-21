"""Performance and network layer. Three CSV tables whose columns match the Google Sheet tabs exactly,
so a CSV can be pasted or imported straight into the sheet and back.

  data/applications.csv  one row per role       IDs A001…
  data/network.csv       one row per person     IDs N001…
  data/targets.csv       one row per organisation IDs T001…

Every opportunity gets one ID. Adding the same company + role twice updates the existing row."""
import csv, re, json, os, tempfile, threading, fcntl, functools
from collections import Counter
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
_LOCK = threading.RLock()
_LOCAL = threading.local()

def current_date():
    return datetime.now(ZoneInfo("Europe/London")).date()

def transaction(fn):
    """One writer across dashboard threads and command-line processes."""
    @functools.wraps(fn)
    def guarded(*args, **kwargs):
        with _LOCK:
            if getattr(_LOCAL, "writing", False):
                return fn(*args, **kwargs)
            DATA.mkdir(parents=True, exist_ok=True)
            with (DATA / ".write.lock").open("a") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                _LOCAL.writing = True
                try:
                    return fn(*args, **kwargs)
                finally:
                    _LOCAL.writing = False
                    fcntl.flock(handle, fcntl.LOCK_UN)
    return guarded

TABLES = {
    "applications": {
        "prefix": "A",
        "fields": ["ID", "Date Added", "Company", "Role", "Lane", "Priority", "Level", "Sector", "Source",
                   "JD Link", "Deadline", "Fit %", "Verdict", "CV Version", "Status", "Date Applied",
                   "Last Status Change", "Follow-up Date", "Contact IDs", "Target ID", "Next Best Action", "Notes",
                   "First Response Date", "First Interview Date"],
    },
    "network": {
        "prefix": "N",
        "fields": ["ID", "Name", "Company", "Their Role", "Type", "How Met", "LinkedIn", "Email",
                   "Linked Applications", "Target ID", "Outreach Date", "Channel", "Assets Sent", "Replied Date", "Status",
                   "Last Contact", "Next Action", "Follow-up Date", "Notes"],
    },
    "targets": {
        "prefix": "T",
        "fields": ["ID", "Organisation", "Type", "Lane", "Priority", "Careers URL", "Why Them",
                   "Last Checked", "Research File", "Research Date", "Application IDs", "Contact IDs", "Notes"],
    },
}

# Dropdown values. The Google Sheet uses the same lists.
CHOICES = {
    "Status": ["shortlisted", "drafted", "applied", "screening", "interview_1", "interview_2", "offer",
               "rejected", "no_response", "withdrawn"],
    "Lane": ["Content & Social", "Partnerships & Activation", "Strategy & Insights"],
    "Priority": ["Priority", "Stretch", "Exclude"],
    "Verdict": ["strong", "worth applying", "stretch", "do not bother"],
    "Source": ["LinkedIn", "Company site", "Referral", "Recruiter", "Careers fair", "Job board", "Cold outreach", "Other"],
    "Level": ["graduate", "entry", "executive", "senior executive", "manager"],
    "NetworkStatus": ["to_contact", "contacted", "replied", "meeting", "warm", "cold"],
    "Channel": ["LinkedIn", "Email", "In person", "Referral", "Event", "Other"],
    "ContactType": ["Recruiter", "Hiring manager", "Peer", "Alumni", "Industry", "Mentor"],
    "TargetType": ["Brand", "Agency", "Rights holder", "Club / league", "Broadcaster / media", "Recruiter", "Other"],
}
RESPONDED = {"screening", "interview_1", "interview_2", "offer", "rejected"}
INTERVIEWED = {"interview_1", "interview_2", "offer"}
SENT = {"applied", "screening", "interview_1", "interview_2", "offer", "rejected", "no_response", "withdrawn"}
NO_RESPONSE_DAYS = 21   # applied this long ago with no change -> suggest no_response
FOLLOW_UP_DAYS = 7      # default follow-up after applying or reaching out
MATURE_DAYS = 14        # response rate counts only applications at least this old


def _path(table):
    if table not in TABLES:
        raise ValueError("Unknown table")
    return DATA / f"{table}.csv"


def read(table):
    p = _path(table)
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8-sig") as f:
        return [{k: v or "" for k, v in row.items()} for row in csv.DictReader(f)]


@transaction
def write(table, rows):
    """Atomic replacement with an append-only before/after journal. Call inside a transaction."""
    DATA.mkdir(parents=True, exist_ok=True)
    fields = TABLES[table]["fields"]
    unknown = {k for r in rows for k in r if k not in fields}
    if unknown:
        raise ValueError("Unknown columns: " + ", ".join(unknown))
    rows = [{k: str(r.get(k, "") or "") for k in fields} for r in rows]
    errors = _validate_rows(table, rows)
    errors += _validate_references(table, rows)
    if errors:
        raise ValueError("; ".join(errors))
    previous = read(table)
    old_headers = []
    if _path(table).exists():
        with _path(table).open(newline="", encoding="utf-8-sig") as handle:
            old_headers = next(csv.reader(handle), [])
    if previous == rows and old_headers == fields:
        return
    stamp = datetime.now(ZoneInfo("Europe/London")).isoformat()
    audit = DATA / "events.jsonl"
    # Write the old state first: original content survives a process interruption.
    with audit.open("a", encoding="utf-8") as log:
        log.write(json.dumps({"at": stamp, "table": table, "event": "before_write", "rows": previous}, ensure_ascii=False) + "\n")
        log.flush(); os.fsync(log.fileno())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", dir=DATA, delete=False) as f:
            temporary = f.name
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader(); w.writerows(rows)
            f.flush(); os.fsync(f.fileno())
        os.replace(temporary, _path(table))
        temporary = None
        with audit.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"at": stamp, "table": table, "event": "committed", "rows": rows}, ensure_ascii=False) + "\n")
            log.flush(); os.fsync(log.fileno())
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()


def _next_id(table, rows):
    pre = TABLES[table]["prefix"]
    nums = [int(m.group(1)) for r in rows if (m := re.match(pre + r"(\d+)$", r.get("ID", "")))]
    return f"{pre}{(max(nums) if nums else 0) + 1:03d}"


def _key(*parts):
    return "|".join(re.sub(r"[^a-z0-9]", "", p.lower()) for p in parts)


def _check(field, value):
    lists = {"Status": "Status", "Lane": "Lane", "Priority": "Priority", "Source": "Source", "Level": "Level"}
    if value and field in lists and value not in CHOICES[lists[field]]:
        raise ValueError(f"{field} must be one of {CHOICES[lists[field]]}, got '{value}'")


def _iso(value):
    if not value:
        return None
    parsed = date.fromisoformat(str(value))
    if parsed.isoformat() != value:
        raise ValueError("Dates must be YYYY-MM-DD")
    return parsed


def _validate_rows(table, rows):
    fields, prefix = TABLES[table]["fields"], TABLES[table]["prefix"]
    errors, seen_ids, seen_keys = [], set(), set()
    required = {"applications": ("Company", "Role"), "network": ("Name",), "targets": ("Organisation",)}[table]
    keys = {"applications": ("Company", "Role"), "network": ("Name", "Company"), "targets": ("Organisation",)}[table]
    enums = {"Lane": "Lane", "Priority": "Priority", "Level": "Level", "Source": "Source", "Verdict": "Verdict"}
    enums.update({"Status": "Status"} if table == "applications" else {"Status": "NetworkStatus", "Type": "ContactType", "Channel": "Channel"} if table == "network" else {"Type": "TargetType"})
    for n, row in enumerate(rows, 2):
        rid = row.get("ID", "")
        if not re.fullmatch(prefix + r"\d{3,}", rid) or int(rid[1:] or 0) <= 0:
            errors.append(f"{table} row {n}: invalid ID {rid!r}")
        if rid in seen_ids:
            errors.append(f"{table}: duplicate ID {rid}")
        seen_ids.add(rid)
        if any(not str(row.get(k, "")).strip() for k in required):
            errors.append(f"{rid}: missing {' / '.join(required)}")
        key = _key(*(str(row.get(k, "")) for k in keys))
        if key in seen_keys:
            errors.append(f"{rid}: duplicate opportunity/person/organisation")
        seen_keys.add(key)
        for f, v in row.items():
            if f not in fields:
                errors.append(f"{rid}: unknown column {f}")
            if v and (f.endswith("Date") or f in ("Date Added", "Date Applied", "Deadline", "Last Contact", "Last Checked", "Last Status Change")):
                try:
                    _iso(v)
                except (ValueError, TypeError):
                    errors.append(f"{rid}: {f} must be YYYY-MM-DD")
            if v and f in enums and v not in CHOICES[enums[f]]:
                errors.append(f"{rid}: invalid {f}: {v}")
        value = row.get("Fit %", "")
        if value and (not str(value).isdigit() or not 0 <= int(value) <= 100):
            errors.append(f"{rid}: Fit % must be 0 to 100")
    return errors


def validate_tables():
    issues = [("FAIL", e) for t in TABLES for e in _validate_rows(t, read(t))]
    indexes = {t: {r["ID"] for r in read(t)} for t in TABLES}
    refs = {"applications": {"Contact IDs": "network", "Target ID": "targets"}, "network": {"Linked Applications": "applications", "Target ID": "targets"}, "targets": {"Application IDs": "applications", "Contact IDs": "network"}}
    for table, columns in refs.items():
        for row in read(table):
            for column, foreign in columns.items():
                for rid in filter(None, re.split(r"[,;\s]+", row.get(column, ""))):
                    if rid not in indexes[foreign]:
                        issues.append(("FAIL", f"{row['ID']}: {column} references missing {rid}"))
    return issues


def _validate_references(table, rows):
    refs = {"applications": {"Contact IDs": "network", "Target ID": "targets"}, "network": {"Linked Applications": "applications", "Target ID": "targets"}, "targets": {"Application IDs": "applications", "Contact IDs": "network"}}[table]
    errors = []
    for field, target in refs.items():
        ids = {r["ID"] for r in rows} if target == table else {r["ID"] for r in read(target)}
        for row in rows:
            for ident in filter(None, re.split(r"[,;\s]+", row.get(field, ""))):
                if ident not in ids:
                    errors.append(f"{row['ID']}: {field} references missing {ident}")
    return errors


def _record_status(row, status, when):
    old = row.get("Status")
    old_when = row.get("Last Status Change", "")
    if old in RESPONDED and not row.get("First Response Date") and old_when:
        row["First Response Date"] = old_when
    if old in INTERVIEWED and not row.get("First Interview Date") and old_when:
        row["First Interview Date"] = old_when
    if status in RESPONDED and not row.get("First Response Date"):
        row["First Response Date"] = when
    if status in INTERVIEWED and not row.get("First Interview Date"):
        row["First Interview Date"] = when
    row["Status"] = status
    if old != status:
        row["Last Status Change"] = when


@transaction
def safe_import(table, path):
    """Validate an entire CSV before merging. Blank cells never erase populated values."""
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        if "ID" not in headers or len(set(headers)) != len(headers) or any(h not in TABLES[table]["fields"] for h in headers):
            raise ValueError("CSV headers must be unique known columns including ID")
        incoming = [r for r in reader if any(r.values())]
    rows = read(table)
    existing = {r["ID"]: dict(r) for r in rows}
    seen = set()
    for row in incoming:
        rid = row.get("ID", "")
        if rid in seen:
            raise ValueError(f"Duplicate incoming ID {rid}")
        seen.add(rid)
        base = existing.get(rid, {})
        merged = dict(base)
        merged.update({k: v for k, v in row.items() if v not in (None, "")})
        if table == "applications" and merged.get("Status") != base.get("Status"):
            oldstatus = base.get("Status", "")
            status = merged.get("Status", "")
            merged["Status"] = oldstatus
            _record_status(merged, status, merged.get("Last Status Change") or current_date().isoformat())
        existing[rid] = merged
    errors = _validate_rows(table, list(existing.values()))
    if errors:
        raise ValueError("; ".join(errors))
    # References must point at an existing canonical row, including rows in this batch.
    refs = {"applications": {"Contact IDs": "network", "Target ID": "targets"}, "network": {"Linked Applications": "applications", "Target ID": "targets"}, "targets": {"Application IDs": "applications", "Contact IDs": "network"}}[table]
    for row in existing.values():
        for field, target in refs.items():
            valid = set(existing) if target == table else {r["ID"] for r in read(target)}
            if any(x not in valid for x in filter(None, re.split(r"[,;\s]+", row.get(field, "")))):
                raise ValueError(f"{row['ID']}: unresolved {field}")
    write(table, list(existing.values()))
    return {"merged": len(incoming), "total": len(existing)}


@transaction
def upsert_application(**kw):
    """Add a role, or update it if the same company + role already exists. Returns (id, created)."""
    if "ID" in kw:
        raise ValueError("IDs are assigned by CareerOS")
    if any(f not in TABLES["applications"]["fields"] for f in kw):
        raise ValueError("Unknown application field")
    rows, today = read("applications"), current_date().isoformat()
    for f, v in kw.items():
        _check(f, v)
    k = _key(kw["Company"], kw["Role"])
    for r in rows:
        if _key(r["Company"], r["Role"]) == k:
            requested_status = kw.get("Status")
            for f, v in kw.items():
                if v not in (None, "") and f not in ("Company", "Role", "Status", "ID"):
                    r[f] = v
            if requested_status:
                _record_status(r, requested_status, today)
            write("applications", rows)
            return r["ID"], False
    new = {"ID": _next_id("applications", rows), "Date Added": today, "Status": "drafted",
           "Last Status Change": today, **{f: v for f, v in kw.items() if v not in (None, "")}}
    rows.append(new)
    write("applications", rows)
    return new["ID"], True


@transaction
def set_status(app_id, status, notes=None, on=None):
    _check("Status", status)
    rows, today = read("applications"), on or current_date().isoformat()
    _iso(today)
    for r in rows:
        if r["ID"] == app_id:
            _record_status(r, status, today)
            if status == "applied" and not r.get("Date Applied"):
                r["Date Applied"] = today
                r["Follow-up Date"] = (date.fromisoformat(today) + timedelta(days=FOLLOW_UP_DAYS)).isoformat()
            elif status in ("offer", "rejected", "withdrawn", "no_response"):
                r["Follow-up Date"] = ""
            if notes:
                r["Notes"] = (r["Notes"] + " | " if r.get("Notes") else "") + f"{today}: {notes}"
            write("applications", rows)
            return r
    raise KeyError(app_id)


@transaction
def add_row(table, key_fields, **kw):
    """Generic add-or-update for network and targets. key_fields decide what counts as the same row."""
    if "ID" in kw or any(f not in TABLES[table]["fields"] for f in kw):
        raise ValueError("IDs are assigned by CareerOS; fields must match the table")
    rows = read(table)
    k = _key(*(kw.get(f, "") for f in key_fields))
    for r in rows:
        if _key(*(r.get(f, "") for f in key_fields)) == k:
            for f, v in kw.items():
                if v not in (None, ""):
                    r[f] = v
            write(table, rows)
            return r["ID"], False
    new = {"ID": _next_id(table, rows), **{f: v for f, v in kw.items() if v not in (None, "")}}
    rows.append(new)
    write(table, rows)
    return new["ID"], True


@transaction
def log_outreach(contact_id, channel=None, replied=False, next_action=None, notes=None, sent=None, on=None):
    rows, today = read("network"), on or current_date().isoformat()
    _iso(today)
    for r in rows:
        if r["ID"] == contact_id:
            if replied:
                r["Replied Date"], r["Status"] = today, "replied"
                r["Follow-up Date"] = ""
            else:
                r["Outreach Date"] = r.get("Outreach Date") or today
                r["Status"] = "contacted" if r.get("Status") in ("", "to_contact", None) else r["Status"]
                if channel:
                    r["Channel"] = channel
                if sent:
                    r["Assets Sent"] = (r["Assets Sent"] + " | " if r.get("Assets Sent") else "") + f"{today}: {sent}"
                r["Follow-up Date"] = (date.fromisoformat(today) + timedelta(days=FOLLOW_UP_DAYS)).isoformat()
            if sent and replied:
                r["Assets Sent"] = (r["Assets Sent"] + " | " if r.get("Assets Sent") else "") + f"{today}: {sent}"
            r["Last Contact"] = today
            if next_action:
                r["Next Action"] = next_action
            if notes:
                r["Notes"] = (r["Notes"] + " | " if r.get("Notes") else "") + f"{today}: {notes}"
            write("network", rows)
            return r
    raise KeyError(contact_id)


def _days_since(d):
    try:
        return (current_date() - date.fromisoformat(d)).days
    except (TypeError, ValueError):
        return None


def stats():
    apps, net = read("applications"), read("network")
    sent = [r for r in apps if r.get("Date Applied") and (_days_since(r.get("Date Applied")) is not None and _days_since(r["Date Applied"]) >= 0)]
    mature = [r for r in sent if (_days_since(r.get("Date Applied")) or 0) >= MATURE_DAYS]
    resp = [r for r in mature if r.get("First Response Date") or r["Status"] in RESPONDED]
    inter = [r for r in sent if r.get("First Interview Date") or r["Status"] in INTERVIEWED]
    out = [r for r in net if r.get("Outreach Date")]
    replies = [r for r in out if r.get("Replied Date")]
    pct = lambda a, b: round(100 * len(a) / len(b)) if b else None
    def by(field):
        result = {}
        for key in sorted({r.get(field, "") for r in sent}):
            group = [r for r in sent if r.get(field, "") == key]
            mature_group = [r for r in mature if r.get(field, "") == key]
            responses = [r for r in resp if r.get(field, "") == key]
            interviews = [r for r in inter if r.get(field, "") == key]
            result[key or "untagged"] = {"sent": len(group), "interviews": len(interviews), "mature": len(mature_group), "responses": len(responses), "response_rate_pct": pct(responses, mature_group), "interview_rate_pct": pct(interviews, group)}
        return result
    return {
        "definitions": {
            "response_rate": f"responses ÷ applications sent at least {MATURE_DAYS} days ago",
            "interview_rate": "interview_1 or later ÷ all applications sent",
            "outreach_reply_rate": "contacts who replied ÷ contacts reached out to",
        },
        "roles_logged": len(apps),
        "sent": len(sent),
        "mature": len(mature),
        "responses": len(resp),
        "interviews": len(inter),
        "response_rate_pct": pct(resp, mature),
        "interview_rate_pct": pct(inter, sent),
        "outreach_sent": len(out),
        "outreach_replies": len(replies),
        "outreach_reply_rate_pct": pct(replies, out),
        "by_status": dict(Counter(r["Status"] for r in apps)),
        "by_lane": by("Lane"),
        "by_cv_version": by("CV Version"),
        "by_source": by("Source"),
    }


def today_list(horizon=7):
    """What needs doing: deadlines, follow-ups, stale applications, contacts due."""
    apps, net, t = read("applications"), read("network"), current_date()
    def _d(d):
        try:
            return date.fromisoformat(d)
        except (TypeError, ValueError):
            return None
    soon = lambda d: _d(d) is not None and 0 <= (_d(d) - t).days <= horizon
    due = lambda d: _d(d) is not None and _d(d) <= t
    out = []
    for r in apps:
        if r["Status"] in ("shortlisted", "drafted") and soon(r.get("Deadline")):
            out.append(("deadline", r["Deadline"], f"{r['ID']} {r['Company']} — {r['Role']} ({r['Status']})"))
        if r["Status"] in ("applied", "screening", "interview_1", "interview_2") and due(r.get("Follow-up Date")):
            out.append(("follow-up", r["Follow-up Date"], f"{r['ID']} {r['Company']} — {r['Role']}: chase or find a contact"))
        if r["Status"] == "applied" and (_days_since(r.get("Last Status Change")) or 0) >= NO_RESPONSE_DAYS:
            out.append(("stale", r["Last Status Change"], f"{r['ID']} {r['Company']}: {NO_RESPONSE_DAYS}+ days silent — mark no_response?"))
    for r in net:
        if r.get("Status") in ("contacted", "warm", "to_contact", "replied", "meeting") and due(r.get("Follow-up Date")):
            out.append(("contact", r["Follow-up Date"], f"{r['ID']} {r['Name']} ({r['Company']}): {r.get('Next Action') or 'follow up'}"))
    return sorted(out, key=lambda x: x[1])
