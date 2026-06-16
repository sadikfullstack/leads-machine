# North Star Clips Lead Scout

North Star Clips Lead Scout is a local Python CLI companion for finding public B2B leads, crawling their websites, extracting contact methods, scoring quality, and generating a simple personalized short-form video demo angle.

It uses free sources by default:

- OpenStreetMap Overpass API for city and niche discovery.
- Configurable public directory connectors.
- Optional Google Custom Search, SerpApi, Brave Search, and Yelp only when API keys are present.

It does not use OpenAI, browser automation, Google result-page scraping, captcha bypassing, logged-in scraping, social scraping behind login, or email sending.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

API keys are optional. Overpass mode works without them.

## Quick Runs

```bash
python lead_scout.py --mode overpass --niche law --cities "Miami,Houston,New York,Los Angeles,Chicago" --target 500 --output law_leads.csv
python lead_scout.py --mode overpass --niche dental --cities "Miami,Dallas,Houston,Los Angeles,Phoenix" --target 500 --output dental_leads.csv
python lead_scout.py --mode overpass --niche real_estate --cities "Miami,Beverly Hills,Manhattan,Austin,Scottsdale" --target 500 --output real_estate_leads.csv
python lead_scout.py --mode directories --niche agencies --target 500 --output agency_leads.csv
python lead_scout.py --mode hybrid --niche agencies --cities "Miami,New York,Los Angeles,Houston,Dallas" --target 500 --output agency_leads.csv
python lead_scout.py --mode hybrid --all --target 1500 --output all_leads.csv
python lead_scout.py --mode hybrid --niche dental --cities "Miami,Dallas,Houston,Los Angeles,Phoenix,Atlanta,Chicago" --target 1000 --max-runtime-minutes 360 --output dental_leads.csv --resume
```

For a no-network planning check:

```bash
python lead_scout.py --mode hybrid --niche dental --cities "Miami,Dallas" --target 20 --dry-run --verbose
```

## Outputs

Each run now writes into a dedicated folder under `runs/` by default. For example:

```bash
python lead_scout.py --mode overpass --niche dental --cities "Miami,Dallas" --target 100 --output dental_leads.csv
```

creates:

```text
runs/dental-leads/
```

Use `--run-name` to choose the folder name, or `--results-dir` to move all run folders somewhere else:

```bash
python lead_scout.py --mode overpass --niche dental --cities "Miami" --target 50 --output leads.csv --run-name miami_dental_test
python lead_scout.py --mode hybrid --niche law --cities "Miami,Houston" --target 200 --results-dir saved_runs --output law_leads.csv
```

Each run folder continuously writes:

- `leads_qualified.csv`
- `leads_maybe.csv`
- `leads_rejected.csv`
- The combined `--output` CSV.
- `leads_clean.csv` - compact review columns for easier scanning.
- `lead_brief.md` - a human-readable brief with counts, skips, and top lead details.
- `run_report.json`
- `discovered_domains.txt`
- `errors.log`

Run state is saved under `.cache/runs/`. Use `--resume` to continue a matching run after interruption.

Duplicate history is shared across runs in `.cache/lead_history.jsonl`. By default, domains already processed by previous runs are skipped. Active domain lock files under `.cache/locks/` also help two terminal instances avoid crawling the same domain at the same time. Use `--ignore-history` only when you intentionally want to recrawl previously processed domains.

## How Overpass Mode Works

Overpass mode queries city-level bounding boxes from `cities.json`, never the whole country. It uses niche-specific OSM tags, caches raw Overpass responses under `.cache/overpass/`, extracts public tags, and skips no-website POIs unless a public email is present.

Default endpoint:

```text
https://overpass-api.de/api/interpreter
```

To use another endpoint, set this in `.env`:

```text
OVERPASS_URL=https://your-overpass-endpoint.example/api/interpreter
```

If a city is missing, either add an entry to `cities.json` or pass a one-off bbox:

```bash
python lead_scout.py --mode overpass --niche dental --cities "Example City" --bbox "25.0,-81.0,26.0,-80.0" --target 25 --output example_city.csv
```

To add a reusable city, edit `cities.json`:

```json
{
  "name": "Example City",
  "state": "FL",
  "aliases": ["Example City, FL"],
  "bbox": { "south": 25.0, "west": -81.0, "north": 26.0, "east": -80.0 }
}
```

Bounding boxes use south, west, north, east.

## How Directory Mode Works

Directory mode reads `connectors.json`. Default entries are disabled placeholders so the tool will not crawl fake sites.

Add a connector like this:

```json
{
  "name": "my_public_agency_directory",
  "niche": "agencies",
  "enabled": true,
  "start_urls": ["https://directory.example/agencies/marketing"],
  "allowed_domains": ["directory.example"],
  "max_pages": 50,
  "extract_official_links": true
}
```

The crawler fetches public directory pages politely, follows pagination-like internal links, and extracts outbound official business websites. Social platforms, job boards, government sites, universities, PDFs, and common aggregators are rejected as lead websites.

## Optional Search API Mode

Search mode is a quality booster, not the main engine. It runs only when keys exist in `.env`:

```text
GOOGLE_API_KEY=
GOOGLE_CSE_ID=
SERPAPI_KEY=
BRAVE_API_KEY=
YELP_API_KEY=
```

Queries come from `queries.json`. The tool uses provider JSON APIs only; it does not scrape Google search result HTML.

## Lead Scoring

Scores run from 0 to 10.

Positive signals include:

- Strong niche match.
- Public email.
- Contact form.
- Decision maker.
- Useful asset such as blog, service page, case study, listing, testimonial, FAQ, or long-form video.
- Premium/high-ticket signals.
- Short-form opportunity.
- Multiple useful pages.
- US/Canada location confidence.

Negative signals include:

- Directory or generic aggregator vibe.
- Unclear business type.
- No contact method.
- Thin, parked, or broken website.
- No useful asset.
- Non-US/Canada market for direct businesses.
- Corporate/franchise page with no reachable local contact.

Statuses:

- `qualified`: score is at least `--min-score` and no reject reason exists.
- `maybe`: score is 4 or 5 and a contact method exists.
- `rejected`: score below 4 or a reject reason exists.

## Overnight Usage

Use conservative city batches and a delay of at least 2 seconds:

```bash
python lead_scout.py --mode hybrid --niche dental --cities "Miami,Dallas,Houston,Los Angeles,Phoenix,Atlanta,Chicago" --target 1000 --delay 2.5 --max-runtime-minutes 360 --output dental_leads.csv --resume
```

Tips:

- Keep `--max-pages-per-domain` near the default 8.
- Use `--resume` for long runs.
- Do not run many copies against the same domains.
- Add real directory connectors gradually and test them with small targets first.
- Use the CSV for personalized, respectful outreach. This tool does not send emails.

## Troubleshooting

- Missing dependencies: run `pip install -r requirements.txt`.
- Overpass rate limits: increase `--delay`, lower city count, and retry with `--resume`.
- City not found: add it to `cities.json` with a bbox.
- Directory mode finds nothing: confirm the connector is enabled, the allowed domain matches, and the page has visible outbound official website links.
- Search mode finds nothing: confirm API keys are in `.env` and `queries.json` has templates for the niche.
- Too many rejected leads: narrow the city/niche, add better directory sources, or inspect `leads_rejected.csv` reject reasons.

## Landing Page Files

This repo also contains the North Star Clips static landing page:

- `index.html` - page markup.
- `styles.css` - responsive styling.
- `assets/north-star-clips-studio.jpg` - local hero image asset.

Preview it directly by opening `index.html`, or run:

```bash
python -m http.server 8000
```

Then visit `http://localhost:8000`.
