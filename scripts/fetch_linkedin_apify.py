#!/usr/bin/env python3
"""Pull employee profiles for US public companies from LinkedIn via an Apify actor
and write a minimal CSV that the scorecard (index.html) can load.

Only companies whose ticker is in the SEC's list of public-company tickers are fetched.

Setup:
    pip install apify-client requests
    export APIFY_TOKEN=...            # https://console.apify.com/settings/integrations

Usage:
    python3 scripts/fetch_linkedin_apify.py companies.csv --contact you@example.com
    python3 scripts/fetch_linkedin_apify.py companies.csv --per-company 300 --max-usd 5 --out data/employees.csv

companies.csv needs a `ticker` column and ideally a `linkedin_url` column
(https://www.linkedin.com/company/<slug>/). Without a URL the SEC company name is
sent as a search keyword, which can match the wrong company.

What is written (data minimisation): company, ticker, first name, current title,
bachelor's grad year, first job start year, pronouns. Last names, profile URLs,
photos, locations and full histories are NOT written. Raw actor output stays in
your Apify account; delete those datasets when done (--delete-datasets does it).
"""
import argparse, csv, json, os, re, sys, time
from datetime import date

SEC_URL = "https://www.sec.gov/files/company_tickers.json"
DEFAULT_ACTOR = "harvestapi/linkedin-company-employees"

# ---------------------------------------------------------------- SEC: public-company check
def load_sec_tickers(contact, cache="data/sec_company_tickers.json", max_age_days=7):
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < max_age_days * 86400:
        raw = json.load(open(cache))
    else:
        import requests
        # The SEC requires a User-Agent that identifies you with a contact address.
        r = requests.get(SEC_URL, headers={"User-Agent": f"workforce-dei-scorecard {contact}"}, timeout=30)
        r.raise_for_status()
        raw = r.json()
        json.dump(raw, open(cache, "w"))
    return {v["ticker"].upper(): v["title"] for v in raw.values()}

# ---------------------------------------------------------------- profile normalisation
BACHELOR = re.compile(
    r"bachelor|baccalaur|undergrad|\bb\.?\s?(a|s|sc|eng|e|tech|com|bus|fa|ba|ed|arch|ee|se|sn)\b\.?|\ba\.?b\.?\b|\bs\.?b\.?\b|licenciatura|license",
    re.I)
NOT_BACHELOR = re.compile(r"master|mba|ph\.?d|doctor|\bm\.?\s?(s|a|sc|eng|ba)\b|j\.?d\b|associate|diploma|certificate|high school|exchange|executive", re.I)
INTERN = re.compile(r"\bintern(ship)?\b|co-?op\b|summer (analyst|associate)|student|trainee|apprentice|volunteer|teaching assistant|research assistant", re.I)
CORP = re.compile(r"[,.]|\b(inc|incorporated|corp|corporation|co|company|ltd|plc|llc|holdings?|group|the|class [a-z])\b", re.I)

def first(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, "", [], {}):
            return d[k]
    return default

def years_in(v):
    """Return years found in a date value (dict with year, ISO string, 'Aug 2018 - May 2022', int)."""
    if v is None:
        return []
    if isinstance(v, (int, float)):
        return [int(v)]
    if isinstance(v, dict):
        y = first(v, "year", "y")
        if y:
            return [int(y)]
        return years_in(first(v, "text", "date"))
    return [int(y) for y in re.findall(r"\b(19[4-9]\d|20[0-4]\d)\b", str(v))]

def is_open_ended(entry):
    end = first(entry, "endDate", "end_date", "ends_at", "end")
    if end is None:
        per = str(first(entry, "period", "dateRange", "duration", "date_range", default=""))
        return bool(re.search(r"present|current|now", per, re.I)) or not years_in(per)[1:]
    return bool(re.search(r"present|current", json.dumps(end), re.I))

def entry_years(entry, which):
    k = ("startDate", "start_date", "starts_at", "start") if which == "start" else ("endDate", "end_date", "ends_at", "end")
    ys = years_in(first(entry, *k))
    if not ys:
        per = years_in(first(entry, "period", "dateRange", "date_range", "duration"))
        if per:
            ys = [per[0]] if which == "start" else ([per[-1]] if len(per) > 1 else [])
    return ys

def norm_co(s):
    return re.sub(r"\s+", " ", CORP.sub(" ", str(s or "").lower())).strip()

def bachelor_grad_year(profile):
    edu = first(profile, "education", "educations", "schools", default=[]) or []
    best = None
    for e in edu if isinstance(edu, list) else []:
        deg = " ".join(str(first(e, k, default="")) for k in ("degree", "degreeName", "degree_name", "title", "fieldOfStudy"))
        if not BACHELOR.search(deg) or NOT_BACHELOR.search(deg):
            continue
        end = entry_years(e, "end")
        if end:
            y = end[0]
        else:
            start = entry_years(e, "start")
            y = start[0] + 4 if start else None
        if y and (best is None or y < best):
            best = y           # earliest bachelor's if more than one
    return best

def experiences(profile):
    exp = first(profile, "experience", "experiences", "positions", "workExperience", default=[]) or []
    out = []
    for e in exp if isinstance(exp, list) else []:
        # Some actors nest several roles under one company entry.
        sub = first(e, "positions", "roles", "subComponents", default=None)
        if isinstance(sub, list) and sub and isinstance(sub[0], dict):
            for s in sub:
                s = dict(s)
                s.setdefault("companyName", first(e, "companyName", "company", "company_name"))
                out.append(s)
        else:
            out.append(e)
    return out

def first_job_year(profile, count_internships=False):
    ys = []
    for e in experiences(profile):
        title = str(first(e, "position", "title", "jobTitle", default=""))
        if not count_internships and INTERN.search(title):
            continue
        s = entry_years(e, "start")
        if s:
            ys.append(s[0])
    return min(ys) if ys else None

def current_role(profile, company_names):
    """Return (title, is_current_at_company). company_names: normalised name variants."""
    exps = experiences(profile)
    for e in exps:
        co = norm_co(first(e, "companyName", "company", "company_name", default=""))
        if co and is_open_ended(e) and any(n and (n in co or co in n) for n in company_names):
            return first(e, "position", "title", "jobTitle", default=""), True
    title = first(profile, "currentPosition", "occupation", "jobTitle", "designation", "headline", default="")
    if isinstance(title, list):
        title = first(title[0], "position", "title", default="") if title else ""
    if isinstance(title, dict):
        title = first(title, "position", "title", default="")
    return str(title or ""), (not exps)   # no history at all: can't verify, keep

def first_name_of(profile):
    fn = first(profile, "firstName", "first_name", "firstname")
    if fn:
        return str(fn).strip()
    full = str(first(profile, "fullName", "name", "full_name", default="")).strip()
    parts = full.split()
    return " ".join(parts[:-1]) if len(parts) > 1 else full

def pronouns_of(profile):
    p = first(profile, "pronoun", "pronouns")
    if isinstance(p, dict):
        p = first(p, "text", "value", default="")
    return str(p or "")

def normalise(profile, company, ticker, name_variants, count_internships=False, require_current=True):
    title, current = current_role(profile, name_variants)
    if require_current and not current:
        return None
    fn = first_name_of(profile)
    if not fn:
        return None
    return {
        "company": company, "ticker": ticker, "name": fn, "title": title,
        "bachelor_grad_year": bachelor_grad_year(profile) or "",
        "first_job_year": first_job_year(profile, count_internships) or "",
        "pronouns": pronouns_of(profile),
    }

# ---------------------------------------------------------------- Apify
def run_actor(client, actor, company_input, per_company, mode, max_usd):
    run_input = {"companies": [company_input], "maxItems": per_company}
    if mode:
        run_input["profileScraperMode"] = mode
    kw = {"run_input": run_input}
    if max_usd:
        from decimal import Decimal
        kw["max_total_charge_usd"] = Decimal(str(max_usd))
    run = client.actor(actor).call(**kw)
    if run is None:
        raise RuntimeError("actor run did not return")
    ds = getattr(run, "default_dataset_id", None) or (run.get("defaultDatasetId") if isinstance(run, dict) else None)
    status = getattr(run, "status", None) or (run.get("status") if isinstance(run, dict) else None)
    return ds, str(status)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("companies_csv")
    ap.add_argument("--contact", required=True, help="your email, sent to the SEC as required for its ticker file")
    ap.add_argument("--out", default="data/employees.csv")
    ap.add_argument("--actor", default=DEFAULT_ACTOR)
    ap.add_argument("--mode", default="Full ($8 per 1k)", help="profileScraperMode value; must be a full-profile mode (check the actor's Input tab)")
    ap.add_argument("--per-company", type=int, default=300, help="max profiles per company (cost control)")
    ap.add_argument("--max-usd", type=float, default=None, help="hard spending cap per company run")
    ap.add_argument("--count-internships", action="store_true", help="let internships count as a first job")
    ap.add_argument("--include-unverified", action="store_true", help="keep profiles not shown as currently at the company")
    ap.add_argument("--keep-raw", action="store_true", help="also save raw actor output to data/raw/ (contains full profiles)")
    ap.add_argument("--delete-datasets", action="store_true", help="delete each run's dataset from Apify after reading it")
    a = ap.parse_args()

    token = os.environ.get("APIFY_TOKEN")
    if not token:
        sys.exit("Set APIFY_TOKEN first.")
    from apify_client import ApifyClient
    client = ApifyClient(token)

    sec = load_sec_tickers(a.contact)
    rows = list(csv.DictReader(open(a.companies_csv, newline="", encoding="utf-8-sig")))
    targets, skipped = [], []
    for r in rows:
        t = (r.get("ticker") or "").strip().upper()
        if t in sec:
            targets.append((t, sec[t], (r.get("linkedin_url") or "").strip(), (r.get("name") or "").strip()))
        elif t:
            skipped.append(t)
    if skipped:
        print(f"Not public (no SEC ticker match), skipped: {', '.join(skipped)}")
    if not targets:
        sys.exit("No public-company tickers to fetch.")

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    fields = ["company", "ticker", "name", "title", "bachelor_grad_year", "first_job_year", "pronouns"]
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for ticker, sec_name, url, alias in targets:
            display = alias or sec_name.title() if sec_name.isupper() else (alias or sec_name)
            variants = {norm_co(sec_name), norm_co(alias), norm_co(display)}
            if url:
                slug = re.search(r"/company/([^/?#]+)", url)
                if slug:
                    variants.add(norm_co(slug.group(1).replace("-", " ")))
            variants.discard("")
            src = url or sec_name
            if not url:
                print(f"[{ticker}] no linkedin_url; searching by name '{sec_name}' (check results)")
            print(f"[{ticker}] running {a.actor} for {src} (up to {a.per_company})…")
            try:
                ds, status = run_actor(client, a.actor, src, a.per_company, a.mode, a.max_usd)
            except Exception as e:
                print(f"[{ticker}] failed: {e}")
                continue
            kept = dropped = 0
            raw = []
            for item in client.dataset(ds).iterate_items():
                if a.keep_raw:
                    raw.append(item)
                rec = normalise(item, display, ticker, variants, a.count_internships, not a.include_unverified)
                if rec:
                    w.writerow(rec); kept += 1
                else:
                    dropped += 1
            if a.keep_raw:
                os.makedirs("data/raw", exist_ok=True)
                json.dump(raw, open(f"data/raw/{ticker}.json", "w"))
            if a.delete_datasets:
                try:
                    client.dataset(ds).delete()
                except Exception as e:
                    print(f"[{ticker}] could not delete dataset {ds}: {e}")
            print(f"[{ticker}] {status}: kept {kept}, dropped {dropped} (not current / no name)")
    print(f"\nWrote {a.out}. Load it in the scorecard. It contains first names: keep it out of git (data/ is ignored).")

if __name__ == "__main__":
    main()
