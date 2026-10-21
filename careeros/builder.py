"""CV builder. Selects and orders master content against a JD. Never writes new claims:
every bullet in the output is copied verbatim from master.yaml and carries its source id."""
import re
from .jd import norm


def _tokens(s):
    return set(w for w in norm(s).split() if len(w) > 2)


def score_text(text, tags, kws):
    hay = " " + " ".join(norm(text + " " + " ".join(tags)).split()) + " "
    score, hits = 0.0, []
    for term, weight in kws:
        needle = " ".join(norm(term).split())
        if needle and re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", hay):
            score += weight
            hits.append(term)
        else:
            # partial credit for shared tokens (e.g. "partnership" vs "partnerships")
            tt = _tokens(term)
            if tt and len(tt & _tokens(hay)) / len(tt) >= 0.5:
                score += weight * 0.4
                hits.append(term + "~")
    return score, hits


def bullets_per_role(rank):
    return [5, 4, 3, 3, 2, 2, 2, 2, 2][min(rank, 8)]


def build(master, context, jd, max_roles=20, full=False, pin=(), drop=(), drop_roles=(), max_projects=2,
          project_floor=0.3):
    """Experience roles are always kept (no unexplained timeline gaps). Live Industry Projects are kept only
    when relevant: top bullet scores at least project_floor x the best bullet on the CV, capped at
    max_projects. Pinned bullets force their role in."""
    kws = jd["keywords"]
    roles_out, used_terms = [], set()
    ranks = {"experience": 0, "projects": 0}
    for role in master["roles"][:max_roles]:
        if role["id"] in drop_roles:
            continue
        sec = role.get("section", "experience")
        rank = ranks[sec]; ranks[sec] += 1
        scored = []
        for b in role["bullets"]:
            if b["id"] in drop:
                continue
            s, hits = score_text(b["text"], b.get("tags", []), kws)
            if b["id"] in pin:
                s += 1000   # curated: always kept, never trimmed for length
            scored.append((s, b, hits))
        keep = len(role["bullets"]) if full else (role.get("cv_bullets") or bullets_per_role(rank))
        chosen = scored if full else sorted(scored, key=lambda x: -x[0])[:max(keep, sum(1 for x in scored if x[0] >= 1000))]
        for _, _, hits in chosen:
            used_terms.update(h.rstrip("~") for h in hits)
        roles_out.append({
            "role_id": role["id"],
            "section": role.get("section", "experience"),
            "min": role.get("cv_min", 1),
            "employer": role["employer"] + (" " + role["lineage"] if role.get("lineage") else ""),
            "title": role["title"],
            "location": role["location"],
            "dates": f"{role['start']} – {role['end']}",
            "bullets": [{"id": b["id"], "text": b["text"], "score": round(s, 1), "hits": h}
                        for s, b, h in chosen],
            "top": max((s for s, _, _ in scored), default=0),
        })

    left_out_roles = []
    if not full:
        best_any = max((r["top"] for r in roles_out if r["top"] < 1000), default=0) or 1
        projects = [r for r in roles_out if r["section"] == "projects"]
        keep = [r for r in projects if r["top"] >= 1000 or r["top"] >= project_floor * best_any]
        keep = sorted(keep, key=lambda r: -r["top"])[:max(max_projects, sum(r["top"] >= 1000 for r in keep))]
        for r in projects:
            if r not in keep:
                roles_out.remove(r)
                left_out_roles.append(r["role_id"])

    # summary: variant with best keyword overlap
    best = context["summaries"][0] if full else max(context["summaries"],
               key=lambda v: score_text(v["text"], v.get("keywords", []), kws)[0])

    # skills: JD-matched first, then fill to 12
    skill_scores = sorted(master["skills"],
                          key=lambda sk: -score_text(sk, [], kws)[0])
    skills = master["skills"] if full else skill_scores[:12]

    return {
        "profile": master["profile"],
        "target_title": jd["title"],
        "summary": {"id": best["id"], "status": best.get("status", "draft"), "text": " ".join(best["text"].split())},
        "left_out_roles": left_out_roles,
        "skills": skills,
        "roles": roles_out,
        "education": master["education"],
        "certifications": [c["text"] for c in master["certifications"]],
        "awards": [a["text"] for a in master["awards"]],
    }
