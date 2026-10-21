#!/usr/bin/env python3
"""CareerOS orchestrator. Run `python cli.py -h` or see README.md."""
import argparse, csv, json, os, re, shutil, subprocess, sys
from datetime import date
from pathlib import Path
import yaml
from careeros import sot, jd as jdmod, builder, reviewer, tracker, research
from careeros.builder import score_text

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:40] or "untitled"


def document_name(profile, company=None, master=False):
    """Stable, portable filename; user text can never introduce path segments."""
    name = slug(profile.get("name", "candidate")).replace("-", "_")
    return f"{name}_{'Master_CV' if master else 'CV_' + slug(company)}.docx"


def new_version_folder(base):
    """Reserve a unique revision atomically. Existing application outputs stay intact."""
    OUT.mkdir(parents=True, exist_ok=True)
    for revision in range(1, 1000000):
        version = f"{base}-v{revision:03d}"
        folder = OUT / version
        try:
            folder.mkdir()
        except FileExistsError:
            continue
        return version, folder
    raise RuntimeError("No free output revision")


def node_executable():
    configured = os.environ.get("CAREEROS_NODE")
    config = ROOT / ".runtime.json"
    if not configured and config.exists():
        runtime = json.loads(config.read_text())
        configured = runtime.get("node")
    executable = configured or shutil.which("node")
    if not executable:
        raise RuntimeError("Node is unavailable; set CAREEROS_NODE or .runtime.json node")
    return str(executable)


# ---------------------------------------------------------------- rendering
def render(cv, folder, docx):
    (folder / "cv.json").write_text(json.dumps(cv, indent=2, ensure_ascii=False))
    env = os.environ.copy()
    config = ROOT / ".runtime.json"
    if config.exists():
        module_path = json.loads(config.read_text()).get("node_path")
        if module_path:
            env.setdefault("NODE_PATH", str(module_path))
    subprocess.run([node_executable(), str(ROOT / "careeros" / "render_docx.js"), str(folder / "cv.json"), str(docx)], check=True, env=env)


def count_pages(folder, docx):
    for soffice in ("soffice", "libreoffice"):
        try:
            # LibreOffice can leave an old PDF in place while reporting success.
            # Remove only this render's disposable PDF before counting the new one.
            pdf = docx.with_suffix(".pdf")
            pdf.unlink(missing_ok=True)
            subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(folder), str(docx)],
                           check=True, capture_output=True, timeout=120)
            if not pdf.is_file():
                continue
            out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout
            return int(next(l.split()[-1] for l in out.splitlines() if l.startswith("Pages")))
        except Exception:
            continue
    return None


def _unique_terms(cv, bullet):
    """JD terms this bullet covers that nothing else on the CV covers."""
    others = " ".join([cv["summary"]["text"], " ".join(cv["skills"])] +
                      [b["text"] for r in cv["roles"] for b in r["bullets"] if b is not bullet])
    return [h.rstrip("~") for h in bullet["hits"]
            if score_text(others, [], [(h.rstrip("~"), 1)])[0] < 1]


def fit_to_pages(cv, folder, docx, target=1, kws=()):
    """Trim until the CV fits. Each bullet's value = its JD score + the weight of any JD term only it covers,
    so a bullet carrying a unique keyword survives over a slightly higher scorer that repeats others.
    Drops the lowest value. Never goes below a role's minimum, never drops a pinned bullet."""
    w = dict(kws)
    dropped = []
    while True:
        render(cv, folder, docx)
        pages = count_pages(folder, docx)
        if pages is None or pages <= target:
            return pages, dropped
        cands = [(b["score"] + sum(w.get(t, 1) for t in _unique_terms(cv, b)), r, b) for r in cv["roles"]
                 if len(r["bullets"]) > r.get("min", 1) for b in r["bullets"] if b["score"] < 1000]
        if not cands:
            return pages, dropped
        _, r, b = min(cands, key=lambda x: x[0])
        r["bullets"].remove(b)
        dropped.append(b["id"])


# ---------------------------------------------------------------- source of truth
def cmd_validate(_):
    issues = sot.validate(sot.load_master())
    for s in sot.load_context().get("summaries", []):
        if s.get("status") != "confirmed":
            issues.append(("WARN", f"summary '{s['id']}' is draft — confirm it before it goes out"))
    if not sot.load_master()["profile"].get("portfolio"):
        issues.append(("WARN", "profile.portfolio is empty"))
    issues += research.check()
    if hasattr(tracker, "validate_tables"):
        issues += tracker.validate_tables()
    for level in ("FAIL", "WARN", "INFO"):
        for lv, msg in issues:
            if lv == level:
                print(f"{lv:4}  {msg}")
    fails = sum(1 for lv, _ in issues if lv == "FAIL")
    print(f"\n{fails} FAIL, {sum(1 for lv,_ in issues if lv=='WARN')} WARN, {sum(1 for lv,_ in issues if lv=='INFO')} INFO")
    return 1 if fails else 0


def cmd_master_cv(_):
    master, ctx = sot.load_master(), sot.load_context()
    cv = builder.build(master, ctx, {"keywords": [], "title": "", "must": [], "nice": []}, full=True)
    _, folder = new_version_folder(f"{date.today():%Y%m%d}-master")
    docx = folder / document_name(master["profile"], master=True)
    render(cv, folder, docx)
    print(f"Master CV: {docx}  ({count_pages(folder, docx) or '?'} pages, {sum(len(r['bullets']) for r in cv['roles'])} bullets)")


# ---------------------------------------------------------------- applications
def cmd_tailor(a):
    master, ctx = sot.load_master(), sot.load_context()
    failures = [message for level, message in sot.validate(master) if level == "FAIL"]
    if failures:
        raise ValueError("Master validation failed: " + "; ".join(failures))
    text = Path(a.jd).read_text()
    parsed = jdmod.parse(text, title=a.role)
    split = lambda s: set(filter(None, (s or "").split(",")))
    cv = builder.build(master, ctx, parsed, pin=split(a.pin), drop=split(a.drop),
                       drop_roles=split(a.drop_role), max_projects=a.max_projects)
    base = f"{date.today():%Y%m%d}-{slug(a.company)}-{slug(a.role)[:20]}-{slug(cv['summary']['id'])}"
    version, folder = new_version_folder(base)
    (folder / "jd.txt").write_text(text)
    (folder / "jd_parsed.json").write_text(json.dumps(parsed, indent=2, ensure_ascii=False))

    docx = folder / document_name(master["profile"], a.company)
    cv["compact"] = True
    pages, dropped = fit_to_pages(cv, folder, docx, target=a.pages, kws=parsed["keywords"])
    rep = reviewer.review(cv, master, parsed, ctx, pages=pages, target_pages=a.pages)
    if dropped:
        rep["checks"].append({"level": "INFO", "area": "length", "msg": "Bullets left out to fit the page (still in the master): " + ", ".join(dropped)})
    (folder / "cv.json").write_text(json.dumps(cv, indent=2, ensure_ascii=False))
    (folder / "review.md").write_text(reviewer.to_markdown(rep, parsed, version))

    app_id, created = tracker.upsert_application(
        Company=a.company, Role=a.role, Lane=a.lane, Priority=a.priority, Level=a.level, Sector=a.sector,
        Source=a.source, **{"JD Link": a.link, "Deadline": a.deadline, "Fit %": str(rep["coverage_pct"]),
                            "Verdict": rep["verdict"], "CV Version": version, "Contact IDs": a.contact,
                            "Target ID": a.target})
    if next(r for r in tracker.read("applications") if r["ID"] == app_id)["Status"] == "shortlisted":
        tracker.set_status(app_id, "drafted")
    print(f"{app_id}  {a.company} — {a.role}  ({'new' if created else 'updated, same ID'})")
    print(f"  version   {version}")
    print(f"  coverage  {rep['coverage_pct']}%  verdict: {rep['verdict']}")
    print(f"  pages     {pages if pages else 'not checked'}")
    print(f"  ready     {'YES' if rep['ready'] else 'NO — see review.md'}")
    print(f"  checks    {sum(c['level']=='FAIL' for c in rep['checks'])} FAIL, {sum(c['level']=='WARN' for c in rep['checks'])} WARN")
    print(f"  gaps      {', '.join(rep['gaps'][:8]) or 'none'}")
    print(f"  files     {folder}")


def cmd_shortlist(a):
    app_id, created = tracker.upsert_application(
        Company=a.company, Role=a.role, Lane=a.lane, Priority=a.priority, Level=a.level, Sector=a.sector,
        Source=a.source, **{"JD Link": a.link, "Deadline": a.deadline, "Target ID": a.target, "Notes": a.notes})
    if created:
        tracker.set_status(app_id, "shortlisted")
        print(f"{app_id}  {a.company} — {a.role}: shortlisted")
    else:
        print(f"{app_id} already logged — details updated, status left as it was")


def cmd_status(a):
    r = tracker.set_status(a.id, a.status, a.notes)
    print(f"{r['ID']}  {r['Company']} — {r['Role']}: {r['Status']}" + (f"  (follow up {r['Follow-up Date']})" if r.get("Follow-up Date") else ""))


# ---------------------------------------------------------------- network and targets
def cmd_target(a):
    tid, created = tracker.add_row("targets", ["Organisation"], Organisation=a.org, Type=a.type, Lane=a.lane,
                                   Priority=a.priority, **{"Careers URL": a.url, "Why Them": a.why, "Notes": a.notes})
    print(f"{tid}  {a.org} ({'new' if created else 'updated'})")


def cmd_contact(a):
    nid, created = tracker.add_row("network", ["Name", "Company"], Name=a.name, Company=a.company,
                                   Type=a.type, LinkedIn=a.linkedin, Email=a.email, Status=a.status or None,
                                   **{"Their Role": a.role, "How Met": a.how_met, "Linked Applications": a.apps,
                                      "Target ID": a.target, "Next Action": a.next, "Notes": a.notes})
    if created and not a.status:
        tracker.add_row("network", ["Name", "Company"], Name=a.name, Company=a.company, Status="to_contact")
    print(f"{nid}  {a.name}, {a.company} ({'new' if created else 'updated'})")


def cmd_outreach(a):
    r = tracker.log_outreach(a.id, channel=a.channel, replied=a.replied, next_action=a.next, notes=a.notes, sent=a.sent)
    print(f"{r['ID']}  {r['Name']}: {r['Status']}" + (f"  (follow up {r['Follow-up Date']})" if not a.replied else ""))


def sync_research():
    """Mirror research files into the Targets table (file path and last-edited date)."""
    rows, changed = tracker.read("targets"), False
    for r in rows:
        p = research.find(r["ID"])
        f, d = (str(p.relative_to(ROOT)), research.updated(p).isoformat()) if p else ("", "")
        if (r.get("Research File", ""), r.get("Research Date", "")) != (f, d):
            r["Research File"], r["Research Date"], changed = f, d, True
    if changed:
        tracker.write("targets", rows)


def cmd_research(a):
    t = next((r for r in tracker.read("targets") if r["ID"] == a.id), None)
    if not t:
        sys.exit(f"{a.id} not found — add it with `target` first")
    p = research.find(a.id) or research.create(t)
    sync_research()
    print(f"Research file: {p}")


def _research_block(target_id, wanted):
    secs = research.sections(target_id)
    L = []
    for name in wanted:
        if secs.get(name):
            flag = lambda x: x if name not in research.FACT_SECTIONS or research.SOURCE.search(x) else x + "  **[UNSOURCED — don't use]**"
            L += [f"**{name}**"] + [f"- {flag(x)}" for x in secs[name]] + [""]
    return L


# ---------------------------------------------------------------- daily view and performance
def cmd_today(a):
    items = tracker.today_list(a.days)
    if not items:
        print("Nothing due.")
    for kind, when, msg in items:
        print(f"{when}  {kind:9} {msg}")


def cmd_stats(_):
    print(json.dumps(tracker.stats(), indent=2, ensure_ascii=False))


def cmd_import(a):
    """Validate the complete import; blank cells cannot erase the local history."""
    result = tracker.safe_import(a.table, a.csv)
    print(f"{a.table}: {result['merged']} rows merged, {result['total']} total")


# ---------------------------------------------------------------- interview prep and outreach briefs
def _all_bullets(master):
    return [(r, b) for r in master["roles"] for b in r["bullets"]]


def _flatten(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _flatten(v, f"{path}/{k}" if path else k)
    elif isinstance(node, list):
        for v in node:
            yield from _flatten(v, path)
    elif node not in (None, ""):
        yield path, str(node)


def _app(app_id):
    app = next((r for r in tracker.read("applications") if r["ID"] == app_id), None)
    if not app:
        sys.exit(f"{app_id} not found")
    return app


def cmd_prep(a):
    """Interview pack built only from the master, evidence bank and knowledge bank. Writes no new claims:
    Situation and Result lines the master doesn't hold are left for candidate to fill from memory."""
    app = _app(a.id)
    folder = OUT / app["CV Version"]
    if not (folder / "jd_parsed.json").exists():
        sys.exit(f"No tailored CV for {a.id} yet — run tailor first")
    parsed = json.loads((folder / "jd_parsed.json").read_text())
    master = sot.load_master()
    knowledge = yaml.safe_load((sot.SOT / "knowledge.yaml").read_text())
    bullets = _all_bullets(master)

    L = [f"# Interview prep — {app['Company']}, {app['Role']}", "",
         f"Application {app['ID']} · fit {app.get('Fit %')}% ({app.get('Verdict')}) · CV `{app['CV Version']}`", "",
         "Every Action line below is your confirmed master wording. Situation, Task and Result are yours to fill",
         "from memory; if a number isn't in the master or evidence bank, don't use it.", ""]

    L += ["## Their must-haves → your strongest evidence", ""]
    for m in parsed["must"] or [k for k, _ in parsed["keywords"][:6]]:
        kws = [(k, 1) for k, _ in jdmod.keywords(m, top=8)] or [(w, 1) for w in jdmod.norm(m).split() if len(w) > 3]
        ranked = sorted(((score_text(b["text"], b.get("tags", []), kws)[0], r, b) for r, b in bullets),
                        key=lambda x: -x[0])[:3]
        L.append(f"**{m}**")
        if re.search(r"\bdegree|graduate|qualification", m, re.I):
            L += [f"- Education: {e['award']}, {e['institution']}" for e in master["education"]] + [""]
            continue
        L += [f"- `{b['id']}` {r['employer']}: {b['text']}" for s, r, b in ranked if s > 0] or ["- no master evidence — prepare an honest bridge answer"]
        L.append("")

    tid = app.get("Target ID") or next((t["ID"] for t in tracker.read("targets")
                                        if jdmod.norm(t["Organisation"]).strip() == jdmod.norm(app["Company"]).strip()), "")
    world = _research_block(tid, ["Snapshot", "Recent campaigns and content", "Their problems and opportunities",
                                  "Partnerships and sponsors", "People", "My angle"])
    L += ["## Their world (from research)", ""] + (world or [f"- no research file yet: run `python cli.py research {tid or '<target id>'}` and fill it with sourced facts", ""])
    L += ["## STAR stories (top 5 for this role)", "",
          "Frame each Result around one of their problems or campaigns above: what you did, and why it matters to them.", ""]
    top = sorted(((score_text(b["text"], b.get("tags", []), parsed["keywords"])[0], r, b) for r, b in bullets),
                 key=lambda x: -x[0])[:5]
    for _, r, b in top:
        L += [f"### {r['employer']} — `{b['id']}`",
              "- Situation: ",
              "- Task: ",
              f"- Action (master): {b['text']}",
              f"- Result: {('figure source: ' + b['number_note']) if b.get('number_note') else '(no figure in master — describe the outcome, not a number)'}",
              ""]

    terms = [k for k, _ in parsed["keywords"]]
    ev = [(p, t) for p, t in _flatten(master.get("evidence_bank", {}))
          if any(re.search(r"\b" + re.escape(k) + r"\b", t, re.I) for k in terms)]
    notes = [(p, t) for p, t in _flatten(master.get("evidence_bank", {})) if p.endswith("interview_note")]
    if ev:
        L += ["## Context from the evidence bank (context, never personal output)", ""] + [f"- {t}" for _, t in ev[:12]] + [""]
    if notes:
        L += ["## Know these before the interview", ""] + [f"- {t}" for _, t in notes] + [""]

    models = [m for _, m in _flatten(knowledge.get("categories", {}))]
    applied = knowledge.get("applied_in", {})
    hits = [m for m in models if any(k in m.lower() for k in terms if len(k) > 3)]
    L += ["## Frameworks to name-check", ""]
    L += [f"- {m}" + (f" — applied in {applied[m]}" if m in applied else "") for m in hits[:8]] or ["- none matched directly"]
    L += [f"- {m} — applied in {w}" for m, w in applied.items() if m not in hits][:4]

    review = (folder / "review.md").read_text()
    gaps = re.findall(r"^- (.+)$", review.split("## Gap report")[1].split("##")[0], re.M) if "## Gap report" in review else []
    L += ["", "## Likely probes on your gaps", ""] + [f"- {g}: what's the closest thing you've done, and how fast would you get up to speed?" for g in gaps if g != "none"]
    L += ["", "## Questions to ask them", "", "- (write two that show you've read their last three campaigns)", ""]

    out = folder / "interview_prep.md"
    out.write_text("\n".join(L) + "\n")
    print(f"Interview pack: {out}")


def cmd_brief(a):
    """Outreach brief for a contact: who they are, the linked role, your three most relevant bullets.
    A brief for drafting, not a message. Nothing is sent without candidate's consent."""
    c = next((r for r in tracker.read("network") if r["ID"] == a.id), None)
    if not c:
        sys.exit(f"{a.id} not found")
    master = sot.load_master()
    apps = [r for r in tracker.read("applications") if r["ID"] in (c.get("Linked Applications") or "").replace(" ", "").split(",")]
    kws = []
    for app in apps:
        p = OUT / app.get("CV Version", "") / "jd_parsed.json"
        if app.get("CV Version") and p.exists():
            kws += json.loads(p.read_text())["keywords"]
    kws = kws or [(w, 1) for w in jdmod.norm(" ".join([c.get("Company", ""), c.get("Their Role", ""), c.get("Notes", "")])).split() if len(w) > 3]
    top = sorted(((score_text(b["text"], b.get("tags", []), kws)[0], r, b) for r, b in _all_bullets(master)),
                 key=lambda x: -x[0])[:3]
    tid = c.get("Target ID")
    if not tid:
        tid = next((t["ID"] for t in tracker.read("targets") if jdmod.norm(t["Organisation"]).strip() == jdmod.norm(c["Company"]).strip()), "")
    same_org = [r for r in tracker.read("network") if r["ID"] != c["ID"] and r.get("Assets Sent")
                and ((tid and r.get("Target ID") == tid) or jdmod.norm(r["Company"]) == jdmod.norm(c["Company"]))]
    L = [f"# Outreach brief — {c['Name']}, {c.get('Their Role','')} at {c['Company']}", "",
         f"Contact {c['ID']} · status {c.get('Status','')} · how met: {c.get('How Met') or '—'} · last contact {c.get('Last Contact') or 'never'}", "",
         "## Linked roles", ""] + ([f"- {r['ID']} {r['Role']} ({r['Status']})" for r in apps] or ["- none: this is a relationship ask, not a role ask"]) + [
         "", "## Your three most relevant proof points (master wording)", ""] + [f"- `{b['id']}` {r['employer']}: {b['text']}" for _, r, b in top] + [
         "", "## Their world (from research — cite, don't embellish)", ""] + (
         _research_block(tid, ["My angle", "Recent campaigns and content", "Their problems and opportunities", "Partnerships and sponsors"])
         or ["- no research file yet: run `python cli.py research " + (tid or "<target id>") + "`, fill it with sourced facts, then rerun this brief", ""]) + [
         "## Already sent to this person", ""] + ([f"- {x}" for x in c["Assets Sent"].split(" | ")] if c.get("Assets Sent") else ["- nothing yet"]) + [
         "", "## Already sent to others at this organisation (don't send the same thing twice)", ""] + (
         [f"- {r['Name']}: {r['Assets Sent']}" for r in same_org] or ["- nothing yet"]) + [
         "", "## Rules for the draft", "",
         "- One specific reason you're writing to *them*; one proof point; one small ask (15 minutes, a pointer, a referral).",
         "- Under 120 words on LinkedIn, under 180 by email.",
         "- Decks: no attachment on first contact. Lead with the one-line idea and a link; send the deck when they say yes.",
         "- Every claim about their company comes from the research file. If it isn't there, it isn't in the message.",
         "- Draft only. candidate approves and sends.", ""]
    OUT.mkdir(exist_ok=True)
    out = OUT / "briefs" / f"{c['ID']}-{slug(c['Name'])}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(L))
    print(f"Outreach brief: {out}")


# ---------------------------------------------------------------- parser
def main():
    C = tracker.CHOICES
    p = argparse.ArgumentParser(description="CareerOS")
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("validate", help="check the master and summaries").set_defaults(f=cmd_validate)
    sp.add_parser("master-cv", help="full CV, every role and bullet").set_defaults(f=cmd_master_cv)

    def role_opts(x):
        x.add_argument("--company", required=True); x.add_argument("--role", required=True)
        x.add_argument("--lane", choices=C["Lane"]); x.add_argument("--priority", choices=C["Priority"])
        x.add_argument("--level", choices=C["Level"]); x.add_argument("--source", choices=C["Source"])
        for o in ("sector", "deadline", "link", "target"):
            x.add_argument(f"--{o}")

    t = sp.add_parser("tailor", help="one-page CV + review for a job description")
    t.add_argument("jd"); role_opts(t)
    t.add_argument("--contact"); t.add_argument("--pages", type=int, default=1)
    t.add_argument("--pin", help="bullet ids to always keep"); t.add_argument("--drop", help="bullet ids to leave out")
    t.add_argument("--drop-role", help="role ids to leave out, e.g. rwm"); t.add_argument("--max-projects", type=int, default=2)
    t.set_defaults(f=cmd_tailor)

    s = sp.add_parser("shortlist", help="log a role before tailoring"); role_opts(s); s.add_argument("--notes")
    s.set_defaults(f=cmd_shortlist)

    st = sp.add_parser("status", help="move an application through the pipeline")
    st.add_argument("id"); st.add_argument("status", choices=C["Status"]); st.add_argument("--notes")
    st.set_defaults(f=cmd_status)

    tg = sp.add_parser("target", help="add or update a target organisation")
    tg.add_argument("org"); tg.add_argument("--type", choices=C["TargetType"]); tg.add_argument("--lane", choices=C["Lane"])
    tg.add_argument("--priority", choices=C["Priority"]); tg.add_argument("--url"); tg.add_argument("--why"); tg.add_argument("--notes")
    tg.set_defaults(f=cmd_target)

    ct = sp.add_parser("contact", help="add or update a person")
    ct.add_argument("name"); ct.add_argument("--company", required=True); ct.add_argument("--role")
    ct.add_argument("--type", choices=C["ContactType"]); ct.add_argument("--how-met"); ct.add_argument("--linkedin")
    ct.add_argument("--email"); ct.add_argument("--apps", help="linked application IDs, e.g. A001,A004")
    ct.add_argument("--target"); ct.add_argument("--status", choices=C["NetworkStatus"]); ct.add_argument("--next"); ct.add_argument("--notes")
    ct.set_defaults(f=cmd_contact)

    o = sp.add_parser("outreach", help="log a message sent, or a reply")
    o.add_argument("id"); o.add_argument("--channel", choices=C["Channel"]); o.add_argument("--replied", action="store_true")
    o.add_argument("--next"); o.add_argument("--notes")
    o.add_argument("--sent", help="asset or document version actually sent")
    rs = sp.add_parser("research", help="create (if missing) and locate the research file for a target")
    rs.add_argument("id"); rs.set_defaults(f=cmd_research)
    o.set_defaults(f=cmd_outreach)

    td = sp.add_parser("today", help="deadlines, follow-ups and stale applications"); td.add_argument("--days", type=int, default=7)
    td.set_defaults(f=cmd_today)
    sp.add_parser("stats", help="performance with exact definitions").set_defaults(f=cmd_stats)

    im = sp.add_parser("import", help="merge a CSV downloaded from the Google Sheet")
    im.add_argument("table", choices=list(tracker.TABLES)); im.add_argument("csv")
    im.set_defaults(f=cmd_import)

    pr = sp.add_parser("prep", help="interview pack for an application"); pr.add_argument("id"); pr.set_defaults(f=cmd_prep)
    br = sp.add_parser("brief", help="outreach brief for a contact"); br.add_argument("id"); br.set_defaults(f=cmd_brief)

    a = p.parse_args()
    sys.exit(a.f(a) or 0)


if __name__ == "__main__":
    main()
