"""Reviewer. Checks a built CV against the master and the operating rules.
Separate from the builder on purpose: the builder never marks its own homework."""
import re
from .sot import bullet_index, RETIRED, validate
from .builder import score_text

WEAK_OPENERS = re.compile(r"^(responsible for|helped|assisted with|worked on|involved in|tasked with)", re.I)
DATES = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4} – ((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}|Present)$")
MAX_BULLET_CHARS = 230   # roughly two lines at 11pt on A4
MAX_WORDS = 850          # roughly two pages
PLATFORM_VIEWS = re.compile(r"\b\d+(?:\.\d+)?\s*(?:[BM]|billion|million)\+?\s*(?:social\s+)?views\b", re.I)


def _normal_text(text):
    return " ".join(str(text).split())


def _platform_context(text):
    for match in PLATFORM_VIEWS.finditer(text):
        before = text[max(0, match.start() - 100):match.start()]
        if not re.search(r"(?:campaigns?|channels?|platforms?)\s+(?:(?:that|which)\s+)?(?:generated|recorded|received|totalled)\s*$", before, re.I):
            return False
        if re.match(r"15(?:\.0)?\s*B", match.group(), re.I) and not re.search(r"channels?\s+(?:(?:that|which)\s+)?generated\s*$", before, re.I):
            return False
    return True


def _source_reference(master, reference):
    """Resolve a bullet ID or a master path, such as education.0.award.

    References provide an audit trail. Confirming the wording remains a human
    judgement; the deterministic reviewer cannot prove semantic entailment.
    """
    if not isinstance(reference, str) or not reference:
        return None
    bullets = bullet_index(master)
    if reference in bullets:
        return bullets[reference][1]
    parts = reference.split(".")
    if parts[0] not in {"profile", "education", "skills", "certifications", "awards"}:
        return None
    value = master
    try:
        for part in parts:
            value = value[int(part)] if isinstance(value, list) else value[part]
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return value if value not in (None, "", [], {}) else None


def review(cv, master, jd, context=None, pages=None, target_pages=1):
    checks = []

    def add(level, area, msg):
        checks.append({"level": level, "area": area, "msg": msg})

    # Schema and duplicate IDs must pass before an ID can prove provenance.
    for level, message in validate(master):
        if level == "FAIL":
            add("FAIL", "master", message)
    if checks:
        return {"checks": checks, "coverage": [], "coverage_pct": 0, "verdict": "do not bother",
                "words": 0, "ready": False, "gaps": [term for term, _ in jd.get("keywords", [])]}
    idx = bullet_index(master)

    words = len(cv["summary"]["text"].split())
    if cv["profile"] != master.get("profile"):
        add("FAIL", "trace", "Profile differs from the master")
    if cv.get("target_title", "") != jd.get("title", ""):
        add("FAIL", "trace", "Target title differs from the supplied job description")
    if cv.get("education") != master.get("education"):
        add("FAIL", "trace", "Education differs from the master")
    for entry in master.get("education", []):
        if entry.get("flag") or entry.get("public") == "pending" or entry.get("status", "confirmed") != "confirmed":
            add("FAIL", "evidence", "Education contains an unresolved or uncleared entry")
    for field in ("certifications", "awards"):
        source = master.get(field, [])
        if cv.get(field) != [entry["text"] for entry in source]:
            add("FAIL", "trace", f"{field.title()} differ from the master")
        for entry in source:
            if entry.get("flag") or entry.get("public") == "pending" or entry.get("status", "confirmed") != "confirmed":
                add("FAIL", "evidence", f"{field.title()}: unresolved or uncleared entry: {entry['text']}")
    for skill in cv.get("skills", []):
        if skill not in master.get("skills", []):
            add("FAIL", "trace", f"Skill is not in the master: {skill}")

    summaries = (context or {}).get("summaries", [])
    matches = [summary for summary in summaries if summary.get("id") == cv["summary"].get("id")]
    if len(matches) != 1:
        add("FAIL", "summary", "Summary does not identify one source variant in personal_context.yaml")
    else:
        summary = matches[0]
        if _normal_text(cv["summary"]["text"]) != _normal_text(summary.get("text", "")):
            add("FAIL", "trace", "Summary text differs from its source variant")
        if summary.get("status") != "confirmed" or cv["summary"].get("status") != summary.get("status"):
            add("FAIL", "summary", f"summary '{summary['id']}' needs candidate's confirmation")
        if summary.get("flag") or summary.get("public") == "pending":
            add("FAIL", "summary", f"summary '{summary['id']}' is unresolved or uncleared for public use")
        evidence = summary.get("evidence", [])
        if not isinstance(evidence, list) or not evidence:
            add("FAIL", "summary", "Summary needs evidence references to master bullet IDs or master paths before it can be ready")
        else:
            for reference in evidence:
                source = _source_reference(master, reference)
                if source is None:
                    add("FAIL", "summary", f"Summary evidence reference is not in the master: {reference}")
                elif isinstance(source, dict) and (source.get("flag") or source.get("public") == "pending" or source.get("status", "confirmed") != "confirmed"):
                    add("FAIL", "summary", f"Summary evidence is unresolved or uncleared: {reference}")
        add("INFO", "summary", "Summary confirmation is a human evidence check; source references are not an automatic semantic fact check")
    if cv.get("left_out_roles"):
        add("INFO", "length", "Projects left out as less relevant (still in the master): " + ", ".join(cv["left_out_roles"]))
    source_roles = {role["id"]: role for role in master["roles"]}
    seen_roles, seen_bullets = set(), set()
    for role in cv["roles"]:
        source_role = source_roles.get(role.get("role_id"))
        if not source_role:
            add("FAIL", "trace", f"Unknown role: {role.get('role_id')}")
        else:
            expected = {"employer": source_role["employer"] + (" " + source_role["lineage"] if source_role.get("lineage") else ""),
                        "title": source_role["title"], "location": source_role["location"],
                        "dates": f"{source_role['start']} – {source_role['end']}",
                        "section": source_role.get("section", "experience")}
            for field, value in expected.items():
                if role.get(field, "experience" if field == "section" else None) != value:
                    add("FAIL", "trace", f"{role.get('role_id')}: {field} differs from the master")
            if source_role.get("flag") or source_role.get("public") == "pending" or source_role.get("status", "confirmed") != "confirmed":
                add("FAIL", "evidence", f"{role['employer']}: role is unresolved or uncleared")
        if role.get("role_id") in seen_roles:
            add("FAIL", "trace", f"Duplicate role on CV: {role.get('role_id')}")
        seen_roles.add(role.get("role_id"))
        if not DATES.match(role["dates"]):
            add("FAIL", "dates", f"{role['employer']}: '{role['dates']}' is not 'Mon YYYY – Mon YYYY'")
        for b in role["bullets"]:
            words += len(b["text"].split())
            src = idx.get(b["id"])
            # 1. traceability
            if not src:
                add("FAIL", "trace", f"{b['id']} is not in the master")
                continue
            m_role, m_b = src
            if m_role["id"] != role.get("role_id"):
                add("FAIL", "trace", f"{b['id']} belongs to another employer role")
            if b["id"] in seen_bullets:
                add("FAIL", "trace", f"Duplicate bullet on CV: {b['id']}")
            seen_bullets.add(b["id"])
            if b["text"] != m_b["text"]:
                add("FAIL", "trace", f"{b['id']} text differs from the master — update the master first")
            # 2. retired claims
            for pat in RETIRED:
                if re.search(pat, b["text"], re.I):
                    add("FAIL", "claims", f"{b['id']} uses a retired claim ('{pat}')")
            # 3. attribution of big numbers
            if not _platform_context(b["text"]):
                add("FAIL", "claims", f"{b['id']} presents a platform figure as personal output")
            # 4. bullet form
            if WEAK_OPENERS.search(b["text"]):
                add("FAIL", "ats", f"{b['id']} opens with a weak phrase")
            if len(b["text"]) > MAX_BULLET_CHARS:
                add("WARN", "ats", f"{b['id']} runs past two lines ({len(b['text'])} chars)")
            # 5. unresolved items
            if m_b.get("flag"):
                add("FAIL", "flag", f"{b['id']}: {m_b['flag']}")
            if m_b.get("public") == "pending":
                add("FAIL", "public", f"{b['id']} names something not yet cleared for public use")
            if m_b.get("status") != "confirmed":
                add("FAIL", "status", f"{b['id']} is draft wording, not yet confirmed by candidate")
        if any(r["id"] == role["role_id"] and r.get("flag") for r in master["roles"]):
            flag = next(r["flag"] for r in master["roles"] if r["id"] == role["role_id"])
            add("FAIL", "flag", f"{role['employer']}: {flag}")

    # Apply retired-claim checks to every printed section, including the summary.
    printed = [cv["summary"]["text"], *cv.get("skills", []), *cv.get("certifications", []), *cv.get("awards", [])]
    printed += [str(entry.get(field, "")) for entry in cv.get("education", []) for field in ("award", "institution", "start", "end", "detail")]
    printed += [str(cv["profile"].get(field, "")) for field in ("name", "city", "phone", "email", "linkedin", "portfolio")]
    printed += [str(role.get(field, "")) for role in cv["roles"] for field in ("employer", "title", "location", "dates")]
    for pattern in RETIRED:
        if any(re.search(pattern, text, re.I) for text in printed):
            add("FAIL", "claims", f"A printed CV section uses a retired claim ('{pattern}')")
    if any(not _platform_context(text) for text in printed):
        add("FAIL", "claims", "A printed CV section presents platform views without explicit campaign or channel attribution")

    words = sum(len(text.split()) for text in printed) + sum(len(b["text"].split()) for role in cv["roles"] for b in role["bullets"])
    if words > MAX_WORDS:
        add("WARN", "length", f"{words} words — likely over two pages")
    if not cv["profile"].get("portfolio"):
        add("INFO", "contact", "No portfolio link yet")
    if not isinstance(pages, int) or isinstance(pages, bool) or pages < 1:
        add("FAIL", "length", "Page count could not be verified; layout review is required before sending")
    elif pages > target_pages:
        add("FAIL", "length", f"CV renders at {pages} pages; target is {target_pages}")

    # keyword coverage
    # Tags help select evidence; an ATS sees only the words actually printed.
    full = " ".join(printed + [b["text"] for role in cv["roles"] for b in role["bullets"]])
    coverage = []
    for term, weight in jd["keywords"]:
        s, _ = score_text(full, [], [(term, 1)])
        coverage.append({"term": term, "weight": weight, "covered": s >= 1, "partial": 0 < s < 1})
    total = sum(c["weight"] for c in coverage) or 1
    got = sum(c["weight"] * (1 if c["covered"] else 0.4 if c["partial"] else 0) for c in coverage)
    pct = round(100 * got / total)

    if pct >= 65:
        verdict = "strong"
    elif pct >= 45:
        verdict = "worth applying"
    elif pct >= 30:
        verdict = "stretch"
    else:
        verdict = "do not bother"

    fails = sum(c["level"] == "FAIL" for c in checks)
    return {"checks": checks, "coverage": coverage, "coverage_pct": pct, "verdict": verdict,
            "words": words, "ready": fails == 0,
            "gaps": [c["term"] for c in coverage if not c["covered"] and not c["partial"]]}


def to_markdown(rep, jd, cv_version):
    L = [f"# Review — {jd['title']}", "",
         f"CV version: `{cv_version}`  ",
         f"Keyword coverage: **{rep['coverage_pct']}%**, verdict: **{rep['verdict']}**  ",
         f"Ready to send: **{'YES' if rep['ready'] else 'NO — fix the FAILs below'}**  ",
         f"Approximate length: {rep['words']} words", ""]
    for level in ("FAIL", "WARN", "INFO"):
        items = [c for c in rep["checks"] if c["level"] == level]
        if items:
            L.append(f"## {level} ({len(items)})")
            L += [f"- [{c['area']}] {c['msg']}" for c in items]
            L.append("")
    L += ["## Keyword coverage", "", "| JD term | Weight | Covered |", "|---|---|---|"]
    for c in rep["coverage"]:
        mark = "yes" if c["covered"] else "partial" if c["partial"] else "**no**"
        L.append(f"| {c['term']} | {c['weight']} | {mark} |")
    L += ["", "## Gap report (genuine gap / addressable by rewording / disqualifying: mark by hand)", ""]
    L += [f"- {g}" for g in rep["gaps"]] or ["- none"]
    if jd["must"]:
        L += ["", "## Must-haves to check by hand", ""] + [f"- {m}" for m in jd["must"]]
    return "\n".join(L) + "\n"
