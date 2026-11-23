# Workforce DEI Scorecard

A single-page, browser-only tool that scores companies on workforce **age** and **gender** diversity from employee-profile data, with a separate indicator for **women in STEM roles**.

Everything runs client-side. Data you load never leaves the browser.

## Run it

`index.html` loads `names.json` with `fetch()`, so it must be served over HTTP (opening the file directly with `file://` will not load the name table):

```bash
python3 -m http.server 8000
# open http://localhost:8000
```

### GitHub Pages
Settings → Pages → Deploy from branch → `main` / root. The app will be at `https://<user>.github.io/<repo>/`.

## Input

A CSV with one row per employee. Headers are matched loosely and can be re-mapped in the UI. See `sample/example.csv`.

| Column | Required | Used for |
|---|---|---|
| company | yes | grouping |
| name (or first name) | yes | gender inference |
| ticker | no | display |
| title | no | STEM indicator |
| stem (yes/no) | no | overrides title-based STEM match |
| bachelor_grad_year | no | age estimate |
| first_job_year | no | age estimate if no degree year |
| pronouns | no | gender (overrides name) |
| gender | no | self-reported gender (overrides everything) |

Dates (`2004-05-15`) and ranges (`2000 – 2004`) are accepted; the last year of a degree range and the earliest year of a job are used.

## Getting LinkedIn data through Apify (public companies only)

`scripts/fetch_linkedin_apify.py` runs an Apify actor (default: [`harvestapi/linkedin-company-employees`](https://apify.com/harvestapi/linkedin-company-employees), full-profile mode, no LinkedIn login) for each company and writes a CSV the scorecard loads directly.

```bash
pip install -r requirements.txt
export APIFY_TOKEN=...                       # Apify console → Settings → Integrations
cp companies.example.csv companies.csv       # ticker, linkedin_url, optional display name
python3 scripts/fetch_linkedin_apify.py companies.csv --contact you@example.com \
    --per-company 300 --max-usd 5 --delete-datasets
# then load data/employees.csv in the app
```

- **Public companies only.** Each ticker is checked against the SEC's public-company ticker list (`sec.gov/files/company_tickers.json`, cached for 7 days); anything not on it is skipped. The SEC requires a contact email in the request, hence `--contact`.
- **Current employees only.** A profile is kept only if it shows an open-ended role at the company; `--include-unverified` turns this off.
- **Age inputs.** Bachelor's grad year = end year of the earliest bachelor's-level degree (start + 4 if no end). First job = earliest non-internship start year (`--count-internships` to include internships).
- **Data minimisation.** The CSV holds first name, current title, the two years and pronouns. No last names, URLs, photos or locations. `--delete-datasets` removes the raw run output from Apify; `--keep-raw` saves it locally to `data/raw/` (ignored by git).
- **Cost control.** `--per-company` caps profiles per company, `--max-usd` sets a hard spend cap per run. Full profiles cost about $8 per 1,000 on the default actor. Check the actor page for current pricing.
- **Other actors.** `--actor` and `--mode` swap the actor. The parser accepts common field shapes (`experience`/`experiences`/`positions`, `education`/`educations`, dates as objects, ISO strings or "Aug 2018 - Present"). An actor that returns education only as free text won't yield graduation years.
- **Sampling.** The actor returns LinkedIn's search order, not a random sample, and only people with LinkedIn profiles. Large companies get a non-random slice up to your cap.

### Terms of use
LinkedIn's User Agreement prohibits scraping. In *hiQ Labs v. LinkedIn* (N.D. Cal. 2022) the court held that agreement enforceable against a scraper, even though scraping public pages was found not to violate the CFAA. Running this uses a third-party scraper against LinkedIn; decide whether that risk is acceptable for your use.

## Method

- **Age** = 21 + (as-of year − bachelor's graduation year). If no graduation year, the first job start year is treated as age 21. Estimates under 18 or over 85 are discarded.
  **Age score** = mean of (share 40+ ÷ benchmark) and (share 55+ ÷ benchmark), each capped at 100. Defaults: 40+ benchmark 50% (placeholder), 55+ benchmark 24% (BLS share of employed people 55+, 2019).
- **Gender**, in order of evidence: self-reported gender → pronouns → honorific (Ms./Mr.) → first name → middle name → undetermined.
  A name counts as female if ≥ 90% of US births 1940–2006 with that name were female, male if ≤ 10% (both thresholds adjustable). Names in between (Taylor, Casey, Jordan…) are undetermined unless other evidence settles them.
  **Gender score** = 100 × (non-male share ÷ 50%), capped at 100 — parity scores 100.
- **STEM** roles are identified by job-title keywords (engineer, developer, data scientist, security, DevOps, cloud, IT, CTO/CISO…), excluding business roles (sales, recruiting, marketing, finance, HR, legal; "sales engineer" stays STEM). **STEM score** uses the gender-score formula on STEM staff only.
- **DEI score** = weighted average of age, overall gender and STEM gender (default 40/30/30). Parts with no data are dropped from the average for that company.
- Companies with fewer determined people than the confidence minimum (default 30) are flagged ⚠.

## Known limitations

- Graduation-year ages run young for late graduates and career changers; first-job years run old for people who started working before 21.
- Name-based inference under-counts women with less common or non-Western names (more land in "undetermined") and cannot identify non-binary people without pronouns or self-reported data.
- Scores are a screening signal about an organisation, not a finding about any individual.

## Rebuilding the name table

```bash
pip install gender-guesser
curl -LO https://www.ssa.gov/oact/babynames/names.zip && unzip names.zip -d data/ssa
python3 scripts/build_names.py data/ssa
```

## Data licences

- `names.json` → `s` (US names): derived from Social Security Administration baby-name data, US public domain.
- `names.json` → `g` (international fallback): derived from `nam_dict.txt` by Jörg Michael, distributed with [gender-guesser](https://github.com/lead-ratings/gender-guesser), under the GNU Free Documentation License 1.2 or later. Keep this attribution if you redistribute the file.

Add a `LICENSE` of your choice for the code.
