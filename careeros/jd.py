"""Parse a job description into keywords and requirements. Deterministic, no AI."""
import re
from collections import Counter

# Marketing / media vocabulary the ATS is likely to match on. Extend freely.
LEXICON = [
    "content strategy", "content creation", "content production", "content calendar", "content planning",
    "social media", "social-first", "paid social", "organic social", "community management",
    "campaign", "campaign planning", "integrated campaigns", "brand", "brand awareness", "brand activation",
    "brand partnerships", "partnerships", "sponsorship", "sponsorship activation", "commercial partners",
    "partner", "rights", "fan engagement", "fans", "experiential", "events", "activation",
    "influencer", "creator", "talent", "pr", "media relations", "communications", "copywriting",
    "storytelling", "video", "editing", "photography", "design", "creative", "creative strategy",
    "go-to-market", "gtm", "market research", "consumer insight", "insights", "competitor analysis",
    "analytics", "data", "kpis", "reporting", "seo", "paid search", "ppc", "email marketing", "crm",
    "digital marketing", "marketing strategy", "media planning", "stakeholder management",
    "project management", "budget", "agency", "account management", "client", "new business",
    "pitch", "presentation", "tiktok", "instagram", "youtube", "linkedin", "x", "facebook",
    "adobe", "premiere pro", "after effects", "photoshop", "canva", "figma", "google analytics", "ga4",
    "sport", "sports", "football", "cricket", "tennis", "entertainment", "broadcast", "fmcg",
    "retail", "graduate", "fast-paced", "deadlines", "attention to detail",
]

STOP = set("""a an the and or of to in for on with at by from as is are be will you your our we us this that
it its into across within their they them who what which role team work working including such also well
can may must able should would per any all more other new about over up out years year experience""".split())

MUST_CUES = re.compile(r"\b(must|essential|required|requirement|you will have|you'll have|you have|proven|minimum|degree)\b", re.I)
NICE_CUES = re.compile(r"\b(desirable|nice to have|bonus|ideally|preferred|advantage|plus)\b", re.I)


def norm(text):
    return re.sub(r"[^a-z0-9+\- ]", " ", text.lower())


def keywords(text, top=25):
    t = " " + norm(text) + " "
    found = Counter()
    for term in LEXICON:
        n = len(re.findall(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", t))
        if n:
            found[term] += n
    # frequent bigrams not already covered
    words = [w for w in t.split() if w not in STOP and len(w) > 2]
    bigrams = Counter(" ".join(p) for p in zip(words, words[1:]))
    for bg, n in bigrams.items():
        lex_words = {w for k in found for w in k.split()}
        if n >= 2 and not any(bg in k or k in bg for k in found) and not (set(bg.split()) & lex_words):
            found[bg] += n
    # drop sub-terms swallowed by longer matched terms with equal count
    terms = sorted(found, key=lambda k: (-found[k], -len(k)))
    return [(k, found[k]) for k in terms[:top]]


def requirements(text):
    lines = [l.strip(" -•*\t") for l in text.splitlines() if l.strip()]
    must = [l for l in lines if MUST_CUES.search(l) and not NICE_CUES.search(l)]
    nice = [l for l in lines if NICE_CUES.search(l)]
    return must, nice


def parse(text, title=None):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    must, nice = requirements(text)
    return {
        "title": title or (lines[0] if lines else "Unknown role"),
        "keywords": keywords(text),
        "must": must,
        "nice": nice,
        "level_flags": [w for w in ("graduate", "junior", "assistant", "executive", "manager", "senior", "head")
                        if re.search(r"\b" + w + r"\b", text, re.I)],
    }
