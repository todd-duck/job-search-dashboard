#!/usr/bin/env python3
"""Pull open jobs from public job-board APIs, prefilter them against config.json,
and write the survivors to data/candidates.json for Claude to score.

Usage:
  fetch_jobs.py                  fetch + filter -> data/candidates.json
  fetch_jobs.py --check-sources  only check that every configured board responds
  fetch_jobs.py --days N         override targeting.max_age_days
"""
import argparse
import concurrent.futures as cf
import csv
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metrics import step  # noqa: E402
import progress  # noqa: E402
import store  # noqa: E402
DATA = os.path.join(ROOT, "data")
UA = {"User-Agent": "Mozilla/5.0 (personal job-search script)"}
TIMEOUT = [25]  # raised for the retry pass in run()
NOW = datetime.now(timezone.utc)


def get(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT[0]) as r:
        return r.read()


def get_json(url, **kw):
    return json.loads(get(url, **kw))


def text(s):
    """HTML -> plain text, collapsed whitespace."""
    s = html.unescape(s or "")
    s = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", s)).strip()


def parse_date(v):
    if v in (None, ""):
        return None
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
        v = v.strip()
        if re.match(r"^\w{3}, \d", v):  # RSS
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(v)
        return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def job(source, company, title, location, url, posted, description="", remote=None, salary=""):
    d = parse_date(posted)
    return {
        "source": source, "company": company.strip(), "title": title.strip(),
        "location": (location or "").strip(), "remote": remote, "url": url,
        "posted_at": d.date().isoformat() if d else "", "salary": salary or "",
        "description": text(description)[:30000],  # trimmed to 6000 when written out
    }


# ---------- sources ----------

def greenhouse(slug, company):
    d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    out = []
    for j in d.get("jobs", []):
        out.append(job("greenhouse", company, j["title"], (j.get("location") or {}).get("name", ""),
                       j["absolute_url"], j.get("first_published") or j.get("updated_at"),
                       j.get("content", "")))
    return out


def lever(slug, company):
    d = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    out = []
    for j in d:
        cat = j.get("categories") or {}
        locs = cat.get("allLocations") or [cat.get("location", "")]
        sal = j.get("salaryRange") or {}
        s = f"{sal.get('min')}-{sal.get('max')} {sal.get('currency', '')}".strip() if sal else ""
        out.append(job("lever", company, j["text"], " / ".join(filter(None, locs)), j["hostedUrl"],
                       j.get("createdAt"), (j.get("descriptionPlain") or "") + "\n" + (j.get("additionalPlain") or ""),
                       remote=(j.get("workplaceType") == "remote") or None, salary=s))
    return out


def ashby(slug, company):
    d = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    out = []
    for j in d.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location", "")] + [a.get("location", "") for a in j.get("secondaryLocations") or []]
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        out.append(job("ashby", company, j["title"], " / ".join(filter(None, locs)), j["jobUrl"],
                       j.get("publishedAt"), j.get("descriptionPlain") or j.get("descriptionHtml", ""),
                       remote=j.get("isRemote") or (j.get("workplaceType") == "Remote") or None, salary=comp))
    return out


def smartrecruiters(slug, company):
    out, offset = [], 0
    while True:
        d = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={offset}")
        for j in d.get("content", []):
            loc = j.get("location") or {}
            where = ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country", "").upper()]))
            out.append(job("smartrecruiters", company, j["name"], where,
                           f"https://jobs.smartrecruiters.com/{slug}/{j['id']}", j.get("releasedDate"),
                           remote=loc.get("remote") or None))
        offset += 100
        if offset >= d.get("totalFound", 0):
            return out


WORKDAY_TERMS = []  # set from config in plan_sources


def workday_posted(s):
    """'Posted Today' / 'Posted Yesterday' / 'Posted 3 Days Ago' / 'Posted 30+ Days Ago' -> datetime."""
    s = (s or "").lower()
    if "today" in s:
        return NOW
    if "yesterday" in s:
        return NOW - timedelta(days=1)
    m = re.search(r"(\d+)\+? days", s)
    return NOW - timedelta(days=int(m.group(1))) if m else None


def workday(spec, company):
    """spec = 'tenant.wdN/Site', e.g. 'redhat.wd5/Jobs'. Searches each WORKDAY_TERMS term, then pulls details."""
    host, site = spec.split("/")
    tenant = host.split(".")[0]
    base = f"https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
    paths = {}
    for term in WORKDAY_TERMS:
        for offset in range(0, 100, 20):  # page: Workday caps a page at 20 and big tenants match far more
            body = json.dumps({"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": term}).encode()
            d = get_json(f"{base}/jobs", data=body, headers={"Content-Type": "application/json", "Accept": "application/json"})
            page = d.get("jobPostings", [])
            for p in page:
                if term.split()[-1] in (p.get("title") or "").lower():  # Workday search is fuzzy; keep only real title hits
                    paths[p["externalPath"]] = p
            if len(page) < 20 or offset + 20 >= d.get("total", 0):
                break
    out = []
    for path, p in paths.items():
        try:
            info = get_json(f"{base}{path}", headers={"Accept": "application/json"})["jobPostingInfo"]
        except Exception:
            continue
        locs = [info.get("location", "")] + list(info.get("additionalLocations") or [])
        out.append(job("workday", company, info["title"], " / ".join(filter(None, locs)),
                       info.get("externalUrl") or f"https://{host}.myworkdayjobs.com/{site}{path}",
                       info.get("startDate") or workday_posted(p.get("postedOn")),
                       info.get("jobDescription", ""), remote=(info.get("remoteType") == "Remote") or None))
    return out


def comeet(spec, company):
    """spec = 'companyUID:token' (both are in the comeetvar / COMPANY_UID constants on the careers page)."""
    uid, token = spec.split(":")
    d = get_json(f"https://www.comeet.co/careers-api/2.0/company/{uid}/positions?token={token}&details=true")
    out = []
    for j in d:
        loc = j.get("location") or {}
        where = ", ".join(filter(None, [loc.get("city"), loc.get("state"), loc.get("country")])) or loc.get("name", "")
        desc = "\n".join(x.get("value") or "" for x in j.get("details") or [])
        out.append(job("comeet", company, j["name"], where, j.get("url_active_page") or j.get("url_comeet_hosted_page"),
                       j.get("time_updated"), desc, remote=loc.get("is_remote") or None))
    return out


def teamtailor(slug, company):
    root = ET.fromstring(get(f"https://{slug}.teamtailor.com/jobs.rss"))
    out = []
    for it in root.iter("item"):
        locs = [e.text or "" for e in it.iter() if e.tag.endswith("}city") or e.tag.endswith("}country")]
        out.append(job("teamtailor", company, it.findtext("title") or "", ", ".join(filter(None, locs)),
                       it.findtext("link"), it.findtext("pubDate"), it.findtext("description") or "",
                       remote=(it.findtext("remoteStatus") or "").lower() in ("fully", "remote") or None))
    return out


def remoteok(_):
    d = get_json("https://remoteok.com/api")
    out = []
    for j in d[1:]:
        lo, hi = j.get("salary_min"), j.get("salary_max")
        out.append(job("remoteok", j.get("company", ""), j.get("position", ""), j.get("location") or "Remote",
                       j.get("url"), j.get("epoch"), j.get("description", ""), remote=True,
                       salary=f"{lo}-{hi} USD" if hi else ""))
    return out


def remotive(terms):
    out = []
    for t in terms:
        d = get_json("https://remotive.com/api/remote-jobs?search=" + urllib.parse.quote(t))
        for j in d.get("jobs", []):
            out.append(job("remotive", j["company_name"], j["title"], j.get("candidate_required_location", ""),
                           j["url"], j.get("publication_date"), j.get("description", ""), remote=True,
                           salary=j.get("salary", "")))
    return out


def himalayas(terms):
    out = []
    for t in terms:
        d = get_json("https://himalayas.app/jobs/api/search?q=" + urllib.parse.quote(t))
        for j in d.get("jobs", []):
            lo, hi = j.get("minSalary"), j.get("maxSalary")
            out.append(job("himalayas", j["companyName"], j["title"],
                           ", ".join(j.get("locationRestrictions") or []) or "Remote (worldwide)",
                           j.get("applicationLink") or j.get("guid"), j.get("pubDate"), j.get("description", ""),
                           remote=True, salary=f"{lo}-{hi} {j.get('currency') or ''}".strip() if hi else ""))
    return out


def weworkremotely(cats):
    out = []
    for c in cats:
        root = ET.fromstring(get(f"https://weworkremotely.com/categories/{c}.rss"))
        for it in root.iter("item"):
            raw = it.findtext("title") or ""
            company, _, title = raw.partition(": ")
            out.append(job("weworkremotely", company, title or raw, it.findtext("region") or "Remote",
                           it.findtext("link"), it.findtext("pubDate"), it.findtext("description") or "",
                           remote=True))
    return out


def hn_whos_hiring(_):
    """Latest 'Ask HN: Who is hiring?' thread. Comments are free text: 'Company | Role | Location | ...'."""
    hits = get_json("https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&query=who%20is%20hiring")["hits"]
    story = next(h for h in hits if h["title"].lower().startswith("ask hn: who is hiring"))
    thread = get_json(f"https://hn.algolia.com/api/v1/items/{story['objectID']}")
    out = []
    for c in thread.get("children", []):
        body = text(c.get("text") or "")
        if not body:
            continue
        first = body.split("\n", 1)[0]
        parts = [p.strip() for p in first.split("|")]
        out.append(job("hn", parts[0][:80], first[:200], first, f"https://news.ycombinator.com/item?id={c['id']}",
                       c.get("created_at"), body, remote=None))
    return out


IBM_API = "https://www-api.ibm.com/search/api/v2"


def ibm(query, company):
    """IBM careers search (no per-product job boards exist for Turbonomic, Cloudability, Apptio, Kubecost...). US roles mentioning the query."""
    out = []
    for offset in (0, 40):
        body = json.dumps({"appId": "careers", "scopes": ["careers2"], "size": 40, "from": offset,
                           "query": {"bool": {"must": [{"simple_query_string": {"query": query, "fields": ["body", "title"]}}],
                                              "filter": [{"term": {"field_keyword_05": "United States"}}]}},
                           "_source": ["title", "url", "dcdate", "description", "field_keyword_05", "field_keyword_17", "field_keyword_19"]}).encode()
        d = get_json(IBM_API, data=body, headers={"Content-Type": "application/json", "Accept": "application/json"})
        hits = (d.get("hits") or {}).get("hits", [])
        for h in hits:
            x = h.get("_source") or {}
            if not x.get("title") or not x.get("url"):
                continue
            mode = x.get("field_keyword_17") or ""
            loc = f"{x.get('field_keyword_19') or ''}, {x.get('field_keyword_05') or ''}".strip(", ")
            out.append(job("ibm", company, x["title"], f"{loc} ({mode})" if mode else loc, x["url"], x.get("dcdate"),
                           x.get("description", ""), remote=(mode.lower() == "remote") or None))
        if len(hits) < 40:
            break
    return out


def plan_sources(cfg):
    """Returns [(label, fn, arg)]."""
    s = cfg["sources"]
    fns = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "smartrecruiters": smartrecruiters,
           "workday": workday, "comeet": comeet, "teamtailor": teamtailor, "ibm": ibm}
    WORKDAY_TERMS[:] = cfg["targeting"]["workday_search_terms"]
    tasks = []
    for kind, boards in s["ats"].items():
        for slug, company in boards.items():
            tasks.append((f"{kind}:{slug}", lambda a, f=fns[kind], c=company: f(a, c), slug))
    agg = {"remoteok": remoteok, "remotive": remotive, "himalayas": himalayas,
           "weworkremotely": weworkremotely, "hn_whos_hiring": hn_whos_hiring}
    for name, arg in s["aggregators"].items():
        if arg:
            tasks.append((name, agg[name], arg))
    return tasks


# ---------- filtering ----------

ATS_SOURCES = {"greenhouse", "lever", "ashby", "smartrecruiters", "workday", "comeet", "teamtailor", "ibm"}  # configured target companies


def words_re(terms):
    return re.compile(r"\b(" + "|".join(re.escape(t) for t in terms) + r")\b", re.I)


def norm_key(company, title):
    n = lambda s: re.sub(r"[^a-z0-9]+", "", s.lower())
    return f"{n(company)}|{n(title)}"


def load_seen(cfg):
    urls, keys = set(), set()
    p = os.path.join(DATA, "seen.json")
    if os.path.exists(p):
        for k, v in json.load(open(p)).items():
            (urls if k.startswith("http") else keys).add(k)
            if v.get("key"):
                keys.add(v["key"])
    li = os.path.expanduser(cfg.get("linkedin_tracker", ""))
    if li and os.path.exists(li):
        for r in csv.DictReader(open(li)):
            if r.get("JobURL"):
                urls.add(r["JobURL"])
            if r.get("Company") and r.get("Role"):
                keys.add(norm_key(r["Company"], r["Role"]))
    return urls, keys


US_STATES = ("alabama alaska arizona arkansas california colorado connecticut delaware florida georgia hawaii idaho "
             "illinois indiana iowa kansas kentucky louisiana maine maryland massachusetts michigan minnesota "
             "mississippi missouri montana nebraska nevada ohio oklahoma oregon pennsylvania tennessee texas utah "
             "vermont virginia washington wisconsin wyoming").split() + ["new york", "new jersey", "new hampshire",
             "new mexico", "north carolina", "south carolina", "north dakota", "south dakota", "rhode island",
             "west virginia", "new england", "east coast", "west coast", "central us", "district of columbia"]
US_RE = re.compile(r"\bu\.s\.(?!\w)|\b(us|usa|united states|americas|north america|n\.?amer|amer|" + "|".join(US_STATES) + r")\b", re.I)
COUNTRY_RE = re.compile(r"\b(us|u\.s\.|usa|united states(?: of america)?|americas|north america|n\.?amer|amer)\b", re.I)  # no states
REMOTE_DESC_RE = re.compile(r"\b(remote|work from home|home[- ]based|distributed|fully remote)\b", re.I)
GENERIC_RE = re.compile(r"\b(remote|anywhere|worldwide|in the world|flexible|global|hybrid|distributed)\b|[-|/,()]", re.I)


def classify_location(j, t):
    """'remote-us', 'home', 'us-check', 'non-us', or 'other' (onsite elsewhere / unknown).
    A remote job counts as US only if its location names the US (or a state) or is a bare 'Remote'/'Anywhere'."""
    loc = j["location"].lower()
    title = j["title"].lower()
    blob = f"{loc} {j['description'][:1500].lower()}" if j["source"] == "hn" else loc
    non_us = words_re(t["non_us_terms"])
    if any(a in blob for a in t.get("home_metro_terms", [])):
        return "home"
    if non_us.search(title) and not US_RE.search(title):
        return "non-us"
    if any(a in title for a in t.get("home_metro_terms", [])):
        return "home"  # city named in the title (e.g. "Customer Engineer - Austin") while the location field is generic
    if j["source"] != "hn" and loc.strip() in ("hybrid", "distributed"):
        if AWAY_RE.search(j["title"]) or STATE_ABBR_RE.search(j["title"]):
            return "other"  # the territory is in the title and it isn't home
        return "us-check"  # label with no place (Cloudflare etc.): the judge confirms US/remote from the posting
    remote = j["remote"] or re.search(r"\b(remote|anywhere|flexible)\b", blob)
    if j["source"] == "hn":
        return "remote-us" if remote and not (non_us.search(blob[:200]) and not US_RE.search(blob[:200])) else "other"
    if US_RE.search(loc):
        if remote or REMOTE_DESC_RE.search(j["description"][:4000]):
            return "remote-us"
        if not GENERIC_RE.sub("", US_RE.sub("", loc)).strip():
            return "us-check"  # only a state/country, no city -- often a field role; Claude confirms on the page
        return "other"
    if remote and not GENERIC_RE.sub("", loc).strip():
        return "remote-us"  # bare "Remote" -- Claude confirms US eligibility from the description
    return "non-us" if remote else "other"


# ---------- territory (remote roles that still require living in a sales region) ----------

NEVER = re.compile(r"(?!x)x")  # matches nothing
ALL_ABBR = ("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY").split()
BASE_AWAY = list(US_STATES) + [
    "nyc", "new york city", "boston", "chicago", "san francisco", "bay area", "seattle", "denver", "dallas", "austin",
    "houston", "los angeles", "cincinnati", "philadelphia", "pacific northwest", "midwest", "mid-atlantic", "southwest",
    "northeast", "north east", "central", "west", "mountain", "great lakes", "tri-state", "dc metro", "southeast", "south east",
    "east coast", "us east", "eastern", "east", "atlanta"]
HOME_RE = NEVER  # territory words that mean "covers where I live"; set by configure_home()
NOT_HOME_EAST_RE = NEVER  # words to ignore first so they don't false-match a home term (targeting.not_home_terms)
AWAY_TERMS = list(BASE_AWAY)
AWAY_RE = NEVER
STATE_ABBR_RE = NEVER


def _words(terms):
    return re.compile(r"\b(" + "|".join(re.escape(x) for x in terms) + r")\b", re.I) if terms else NEVER


def configure_home(t):
    """Derive the home-territory matchers from targeting.home_territory_terms / home_metro_terms / not_home_terms / home_state.
    Anything that names a home place is never treated as 'away'; with no home terms configured nothing counts as home."""
    global HOME_RE, NOT_HOME_EAST_RE, AWAY_TERMS, AWAY_RE, STATE_ABBR_RE
    home = {h.lower() for h in list(t.get("home_territory_terms", [])) + list(t.get("home_metro_terms", []))}
    HOME_RE = _words(sorted(home))
    NOT_HOME_EAST_RE = _words(t.get("not_home_terms", []))
    st = (t.get("home_state") or "").upper()
    AWAY_TERMS = [a for a in BASE_AWAY if a not in home]
    AWAY_RE = _words(AWAY_TERMS)
    STATE_ABBR_RE = re.compile(r"(?:,|-)\s*(" + "|".join(a for a in ALL_ABBR if a != st) + r")\b")


import settings  # noqa: E402

configure_home(settings.load().get("targeting", {}))
RESIDENCY_RE = re.compile(
    r"(?:must|should|required to|need to|will need to)\s+(?:be\s+)?(?:reside|live|located|based)\b[^.\n]{0,150}"
    r"|(?:candidates?|applicants?)\s+(?:must|should)\s+be\s+(?:located|based)\b[^.\n]{0,150}"
    r"|open to candidates (?:located |based )?in\b[^.\n]{0,120}"
    r"|this (?:role|position) (?:is|will be) based (?:in|out of)\b[^.\n]{0,120}"
    r"|^\s*location:\s*[^\n]{0,80}", re.I | re.M)


OFFICE_RE = re.compile(r"[^\n.]{0,80}\b(hybrid|in[- ]office|on[- ]?site|days?\s*(?:/|a|per)\s*week in)\b[^\n.]{0,80}", re.I)


def is_home(s):
    return bool(HOME_RE.search(NOT_HOME_EAST_RE.sub("", s)))


def territory(j):
    """('favored'|'ok'|'unclear'|'drop', evidence). your home territory = favored; another region = drop;
    a remote job whose location field names another state = unclear (Claude checks the page)."""
    title = j["title"]
    for m in OFFICE_RE.finditer(j["description"]):
        c = m.group(0).strip()
        if AWAY_RE.search(c) and not is_home(c):
            return "drop", f"office requirement: {c[:150]}"
    seg = " ".join(re.split(r"\s[-–—]\s|,|\(|\)|\|", title)[1:])  # territory usually follows the role name
    if seg and is_home(seg):
        return "favored", f"title: {title}"
    if seg and AWAY_RE.search(seg):
        return "drop", f"title territory: {title}"
    clauses = [m.group(0).strip() for m in RESIDENCY_RE.finditer(j["description"])]
    for c in clauses:
        if is_home(c):
            return "favored", c[:160]
    for c in clauses:
        if AWAY_RE.search(US_RE.sub(lambda m: m.group(0) if m.group(0).lower() in AWAY_TERMS else "", c)):
            return "drop", c[:160]
    loc = j["location"]
    if is_home(loc) or re.search(r"(?:^|[\s,/-])GA\b", loc):
        return "favored", f"location: {loc}"
    parts = [p for p in re.split(r"\s/\s|;", loc) if p.strip()]
    if any(not GENERIC_RE.sub("", COUNTRY_RE.sub("", p)).strip() for p in parts) and len(parts) > 1:
        return "ok", f"location includes plain US remote: {loc[:80]}"
    if AWAY_RE.search(loc) or STATE_ABBR_RE.search(loc):
        return "unclear", f"location: {loc}"
    return "ok", ""


# ---------- salary ----------

AMOUNT = r"\$?\s?\d[\d,]*(?:\.\d+)?\s?[kK]?"
RANGE_RE = re.compile(rf"({AMOUNT})(?:\s*USD)?\s*(?:-|–|—|to|and)\s*({AMOUNT})(\s*USD)?")


def money(s):
    s = s.replace("$", "").replace(",", "").strip()
    k = s[-1:] in "kK"
    try:
        v = float(s.rstrip("kK").strip())
    except ValueError:
        return None
    return v * 1000 if k else v


def _range_matches(src):
    """RANGE_RE matches that are plausible pay ranges. An implausible match ("3, and 184,000 USD") must not swallow the real one after it."""
    pos = 0
    while True:
        m = RANGE_RE.search(src, pos)
        if not m:
            return
        lo, hi = money(m.group(1)), money(m.group(2))
        if lo and hi and 40000 <= lo <= hi <= 1500000:
            yield m
            pos = m.end()
        else:
            pos = m.start() + 1


def parse_salary(j):
    """Returns {'base_lo', 'base_hi', 'ote_lo', 'ote_hi', 'text'} from the salary field or description; None if none."""
    found, levels = {}, {}
    for src in (j["salary"], j["description"]):
        for m in _range_matches(src or ""):
            raw = m.group(0)
            if "$" not in raw and "usd" not in raw.lower() and not re.search(r"\d\s?[kK]", raw):
                continue
            lo, hi = money(m.group(1)), money(m.group(2))
            if not lo or not hi or not (40000 <= lo <= hi <= 1500000):
                continue
            ctx = (src[max(0, m.start() - 140):m.start()]).lower()
            if re.search(r"variable|commission range|bonus range", ctx[-60:]):
                continue
            kind = "ote_hi" if re.search(r"\bote\b|on[- ]target", ctx) else "base_hi"
            found.setdefault(kind, hi)
            found.setdefault(kind.replace("_hi", "_lo"), lo)
            found.setdefault("text", raw.strip())
            if re.match(r"\s*(?:for|\(|,|-|:)?\s*(?:level|lvl|l|ic|t)\s?-?\d\b", src[m.end():m.end() + 30], re.I):
                levels.setdefault(kind, []).append((lo, hi, raw.strip()))
        if found:
            break
    if "base_hi" in found and "ote_hi" not in found:  # a bare salary field can be OTE: the description labels the same figures
        desc = j["description"] or ""
        for m in _range_matches(desc):
            if (money(m.group(1)), money(m.group(2))) == (found["base_lo"], found["base_hi"]) \
                    and re.search(r"\bote\b|on[- ]target", desc[max(0, m.start() - 140):m.start()].lower()):
                found["ote_hi"], found["ote_lo"] = found.pop("base_hi"), found.pop("base_lo")
                break
    for kind, bands in levels.items():  # bands labelled by level (e.g. "... for Level 3, and ... for Level 4"): the candidate is hired at the senior band
        if len(bands) >= 2:
            lo, hi, raw = max(bands)
            found[kind], found[kind.replace("_hi", "_lo")] = hi, lo
            found["text"] = f"{raw} (highest of {len(bands)} level bands)"
    return found or None


OTE_BASE_PCT = 0.70  # usual 70/30 base/variable split for quota-carrying roles


def salary_label(j, pct=OTE_BASE_PCT):
    """Salary text for the log. An OTE range is tagged OTE with an estimated base so it isn't read as base pay."""
    sal = j.get("salary_parsed") or {}
    text = sal.get("text") or j.get("salary") or ""
    if text and "ote_hi" in sal and "base_hi" not in sal:
        k = lambda v: f"${round(v * pct / 1000):d}K"
        return f"{text} OTE (est. base {k(sal['ote_lo'])}-{k(sal['ote_hi'])} @ {round(pct * 100)}/{round(100 - pct * 100)})"
    return text


def prescore(j, t, sc, strong):
    """Deterministic part of the rubric. Claude adds judgment (post-sales -2, people manager, learned prefs)."""
    pts, why = sc["core_title"], ["core title +3"]
    if words_re(t["seniority_bonus"]).search(j["title"]):
        pts += sc["seniority"]; why.append(f"seniority +{sc['seniority']}")
    hits = j["strong_hits"]
    h = min(len(hits), sc["domain_hit_max"]) * sc["domain_hit_each"]
    if h:
        pts += h; why.append(f"themes +{h} ({', '.join(hits[:5])})")
    if j["location_class"] in ("remote-us", "home"):
        pts += sc.get("remote_or_home", 1); why.append(f"{j['location_class']} +1")
    terr = j["territory"]
    if terr == "favored":
        pts += sc["territory_home"]; why.append(f"home territory +{sc['territory_home']}")
    elif terr == "unclear":
        pts += sc["territory_unclear"]; why.append(f"territory unclear {sc['territory_unclear']}")
    sal = j.get("salary_parsed") or {}
    if sal.get("base_hi", 0) >= t["salary_bonus_at"] or (not sal.get("base_hi") and sal.get("ote_hi", 0) * OTE_BASE_PCT >= t["salary_bonus_at"]):
        pts += sc["salary_top_at_or_above_bonus"]; why.append("salary +1")
    if not hits:
        tier = "C"; why.append("no must-match theme -> C")
    else:
        tier = "A" if pts >= sc["a_tier"] else "B" if pts >= sc["b_tier"] else "C"
    return {"points": pts, "tier": tier, "breakdown": why}


def record_funnel(out, rejects, keep_days=90):
    """Persist what the prefilter threw away, so the criteria can be judged against real titles.
    data/funnel.jsonl: one line per run (counts by drop reason). the `rejected` table in data/jobsearch.db: one row per
    rejected posting URL (company, title, location, source, latest reason, first/last seen), pruned after keep_days."""
    today = NOW.date().isoformat()
    with open(os.path.join(DATA, "funnel.jsonl"), "a") as f:
        f.write(json.dumps({"ts": out["fetched_at"], "fetched": out["total_fetched"], "candidates": len(out["candidates"]),
                            "dropped": out["dropped"], "failed_sources": len(out["failures"])}) + "\n")
    store.record_rejects(DATA, rejects, today, (NOW - timedelta(days=keep_days)).date().isoformat())


def prior_applications(company, cfg):
    """the candidate's earlier applications at this company: application folders + LinkedIn tracker submissions.
    Flagged in the job's gaps, never dropped (a learned rule)."""
    import log_jobs  # local import: log_jobs owns the folder lookup
    out = [os.path.basename(f) for f in log_jobs.existing_folders(company)]
    li = os.path.expanduser(cfg.get("linkedin_tracker", ""))
    if li and os.path.exists(li):
        slug = log_jobs.company_slug(company)
        out += [f"LinkedIn: {r['Role']} ({r['Date']})" for r in csv.DictReader(open(li))
                if r.get("Status") == "Submitted" and log_jobs.company_slug(r.get("Company", "")) == slug]
    return out


def prefilter(jobs, cfg, days, rejects=None):
    """rejects: optional list; every dropped job is appended as (job, reason) so main() can persist what was filtered out."""
    t = cfg["targeting"]
    sc = cfg["scoring"]
    must = words_re(t["title_must_match_one"])
    skip = words_re(t["title_skip"])
    strong = words_re(t["domain_strong"])
    domain = words_re(t["domain_strong"] + t["domain_weak"])
    auto_dropped = []
    agencies = [a.lower() for a in t["staffing_agencies"]]
    excluded = words_re(t["excluded_companies"]) if t.get("excluded_companies") else None
    cutoff = (NOW - timedelta(days=days)).date().isoformat()
    feed_cutoff = (NOW - timedelta(days=t["max_age_days_feeds"])).date().isoformat()
    seen_urls, seen_keys = load_seen(cfg)
    kept, reasons, batch_keys = [], {}, set()

    cur = [None]

    def drop(r):
        reasons[r] = reasons.get(r, 0) + 1
        if rejects is not None:
            rejects.append((cur[0], r))

    for j in jobs:
        cur[0] = j
        title = j["title"]
        if j["source"] == "hn":
            # HN 'title' is the whole first line; need role + some domain signal anywhere in the post.
            if not must.search(title) or not domain.search(j["description"]):
                drop("title/domain"); continue
        else:
            if not must.search(title):
                drop("title"); continue
            if skip.search(re.sub(r"technical (customer )?(account|success) manager", "", title, flags=re.I)):
                drop("title skip word"); continue
        if excluded and (excluded.search(j["company"]) or excluded.search(urllib.parse.urlparse(j["url"] or "").netloc)):
            drop("excluded company"); continue
        if any(a in j["company"].lower() for a in agencies):
            drop("staffing agency"); continue
        if j["posted_at"] and j["posted_at"] < (feed_cutoff if j["source"] in ATS_SOURCES else cutoff):
            drop("too old"); continue
        where = classify_location(j, t)
        if where in ("non-us", "other"):
            drop(f"location {where}"); continue
        blob = f"{title} {j['description']}"
        hits = sorted({m.lower() for m in strong.findall(blob)})
        if j["source"] not in ATS_SOURCES and not hits:
            drop("no strong theme (aggregator)"); continue
        key = norm_key(j["company"], title)
        if j["url"] in seen_urls or key in seen_keys:
            drop("already seen"); continue
        if key in batch_keys:
            drop("duplicate this run"); continue
        batch_keys.add(key)
        j["key"] = key
        j["location_class"] = where
        j["strong_hits"] = hits
        j["weak_hits"] = sorted({m.lower() for m in domain.findall(blob)} - set(hits))
        j["territory"], j["territory_evidence"] = territory(j)
        if j["territory"] == "drop":
            drop("territory elsewhere")
            auto_dropped.append({"company": j["company"], "title": title, "reason": j["territory_evidence"]})
            continue
        j["salary_parsed"] = parse_salary(j)
        sal = j["salary_parsed"] or {}
        top = sal.get("base_hi") or sal.get("ote_hi")  # floor applies to the TOP end of the range: keep any posting whose range reaches it
        floor = t["salary_floor"] if "base_hi" in sal else t.get("ote_floor", t["salary_floor"])
        if top and top < floor:
            drop("salary below floor")
            auto_dropped.append({"company": j["company"], "title": title,
                                 "reason": f"salary {sal.get('text')} ({'OTE' if 'base_hi' not in sal else 'base'}) top end < floor"})
            continue
        j["prescore"] = prescore(j, t, sc, strong)
        j["prior_applications"] = prior_applications(j["company"], cfg)
        kept.append(j)
    return kept, reasons, auto_dropped


# ---------- main ----------

def run(tasks, workers=8):
    """Fetch every source; then retry failures one more time, fewer at once and with a longer timeout
    (big boards like Datadog/Elastic time out when the network is slow)."""
    results, failures = {}, {}

    def attempt(batch, n, what):
        with cf.ThreadPoolExecutor(n) as ex:
            futs = {ex.submit(fn, arg): label for label, fn, arg in batch}
            for i, f in enumerate(cf.as_completed(futs), 1):
                progress.update("fetch", i / len(batch) * 0.9 if what == "first" else 0.9 + 0.1 * i / len(batch),
                                f"{i} of {len(batch)} sources" if what == "first" else f"retrying slow sources: {i} of {len(batch)}")
                label = futs[f]
                try:
                    results[label] = f.result()
                    failures.pop(label, None)
                except Exception as e:
                    failures[label] = f"{type(e).__name__}: {e}"[:120]

    attempt(tasks, workers, "first")
    if failures:
        TIMEOUT[0] = 75
        attempt([t for t in tasks if t[0] in failures], 3, "retry")
        TIMEOUT[0] = 25
    return results, failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-sources", action="store_true")
    ap.add_argument("--days", type=int)
    a = ap.parse_args()
    cfg = settings.load()
    with step("fetch_feeds", sources=len(plan_sources(cfg))):
        results, failures = run(plan_sources(cfg))

    if a.check_sources:
        for label in sorted(results):
            n = len(results[label])
            print(f"{'OK ' if n else 'EMPTY'} {label}: {n} jobs")
        for label, err in sorted(failures.items()):
            print(f"FAIL {label}: {err}")
        sys.exit(1 if failures else 0)

    for label, js in results.items():
        for j in js:
            j["source_label"] = label
    alljobs = [j for js in results.values() for j in js]
    with step("prefilter", jobs=len(alljobs)):
        rejects = []
        kept, reasons, auto_dropped = prefilter(alljobs, cfg, a.days or cfg["targeting"]["max_age_days"], rejects)
    kept.sort(key=lambda j: (j["prescore"]["tier"] != "C", j["prescore"]["points"], j["posted_at"]), reverse=True)
    for j in kept:
        j["description"] = j["description"][:6000]
    os.makedirs(DATA, exist_ok=True)
    out = {"fetched_at": NOW.isoformat(timespec="seconds"), "total_fetched": len(alljobs),
           "per_source": {k: len(v) for k, v in sorted(results.items())},
           "failures": failures, "dropped": reasons, "auto_dropped": auto_dropped,
           "posting_check": posting_check(alljobs, results), "candidates": kept}
    json.dump(out, open(os.path.join(DATA, "candidates.json"), "w"), indent=1)
    record_funnel(out, rejects)

    print(f"Fetched {len(alljobs)} jobs from {len(results)} sources; {len(kept)} candidates -> data/candidates.json")
    print("Dropped:", ", ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])))
    for d in auto_dropped:
        print(f"  auto-dropped: {d['company']} | {d['title'][:60]} | {d['reason'][:90]}")
    gone = out["posting_check"]["gone"]
    if gone:
        print(f"Postings removed since logged: {len(gone)} (run log_jobs.py --reconcile)")
    if failures:
        print("Failed sources:", "; ".join(f"{k} ({v})" for k, v in failures.items()))
    for j in kept:
        p = j["prescore"]
        sal = (j.get("salary_parsed") or {}).get("text", "")
        print(f"- [{p['tier']} {p['points']}] {j['company']} | {j['title'][:60]} | {j['location'][:35]} | "
              f"terr={j['territory']} | {sal} | {j['posted_at']}")


FULL_FEEDS = {"greenhouse", "lever", "ashby", "smartrecruiters", "comeet", "teamtailor"}  # list every open job


def workday_removed(url):
    """True only when Workday says the posting no longer exists (404, or the 403 'permission denied' it returns for pulled jobs)."""
    m = re.match(r"https://(([a-z0-9-]+)\.wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)(/job/.+)$", url)
    if not m:
        return False
    host, tenant, site, path = m.groups()
    try:
        urllib.request.urlopen(urllib.request.Request(f"https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{path}",
                               headers={"Accept": "application/json", **UA}), timeout=20)
    except urllib.error.HTTPError as e:
        return e.code in (403, 404)
    except Exception:
        return False
    return False


def posting_check(alljobs, results):
    """For jobs.md rows still New/Apply: which postings are still live (with their source), and which are gone.
    'Gone' only counts when the job came from a feed that lists every open job AND that feed loaded this run."""
    p = os.path.join(DATA, "seen.json")
    seen = json.load(open(p)) if os.path.exists(p) else {}
    live_urls = {j["url"]: j["source_label"] for j in alljobs}
    live, gone = {}, []
    for url, v in seen.items():
        if v.get("status") not in ("New", "Apply"):
            continue
        if url in live_urls:
            live[url] = live_urls[url]
        elif (v.get("source_label") or "").split(":")[0] in FULL_FEEDS and results.get(v["source_label"]):  # non-empty feed only
            gone.append(url)
        elif "myworkdayjobs.com" in url and workday_removed(url):  # Workday is searched by term, not a full feed: check the posting itself
            gone.append(url)
    return {"live": live, "gone": gone}


if __name__ == "__main__":
    main()
