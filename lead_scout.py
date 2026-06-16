#!/usr/bin/env python3
"""
North Star Clips Lead Scout

A zero-budget local CLI for discovering, crawling, scoring, and exporting
public B2B leads for personalized short-form video outreach.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib import robotparser

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

try:
    import tldextract

    TLD_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
except Exception:  # pragma: no cover - fallback for partial installs
    TLD_EXTRACT = None


APP_NAME = "North Star Clips Lead Scout"
USER_AGENT = (
    "NorthStarClipsLeadScout/1.0 "
    "(local research tool; respects robots.txt; no email sending)"
)
CSV_COLUMNS = [
    "business_name",
    "niche",
    "qualified_status",
    "lead_score",
    "website",
    "domain",
    "city_state",
    "country_guess",
    "source_mode",
    "source_provider",
    "source_query_or_connector",
    "best_email",
    "emails_found",
    "phone",
    "contact_form_url",
    "decision_maker_names",
    "social_links",
    "best_asset_url",
    "best_asset_type",
    "demo_angle",
    "shortform_opportunity",
    "reject_reason",
    "pages_crawled",
    "osm_id",
    "osm_type",
    "lat",
    "lon",
]

NICHES = ("agencies", "law", "dental", "real_estate")
MODES = ("overpass", "directories", "search", "hybrid", "manual")

BAD_EMAIL_PREFIXES = {
    "noreply",
    "no-reply",
    "do-not-reply",
    "donotreply",
    "example",
    "privacy",
    "abuse",
    "dns",
    "webmaster",
    "hosting",
    "godaddy",
    "sentry",
    "wordpress",
}

BAD_EMAIL_SUBSTRINGS = {
    "support@wix",
    "support@squarespace",
    "example.com",
    "domain.com",
    "email.com",
    "yourdomain",
    "your-domain",
}

PREFERRED_EMAIL_PREFIXES = {
    "general": [
        "info",
        "hello",
        "contact",
        "team",
        "marketing",
        "office",
        "admin",
    ],
    "law": ["intake", "info", "contact", "attorney", "lawyer", "office"],
    "agencies": ["hello", "contact", "founder", "director", "growth", "team"],
    "real_estate": ["team", "info", "hello", "contact", "sales"],
    "dental": ["office", "info", "appointments", "appointment", "contact", "admin"],
}

REJECT_DOMAINS_EXACT = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "pinterest.com",
    "yelp.com",
    "google.com",
    "goo.gl",
    "maps.google.com",
    "apple.com",
    "bing.com",
    "indeed.com",
    "ziprecruiter.com",
    "glassdoor.com",
    "monster.com",
    "craigslist.org",
    "wikipedia.org",
    "bbb.org",
    "chamberofcommerce.com",
    "yellowpages.com",
    "manta.com",
    "mapquest.com",
    "foursquare.com",
    "opencorporates.com",
    "findlaw.com",
    "avvo.com",
    "justia.com",
    "lawyers.com",
    "martindale.com",
    "zillow.com",
    "realtor.com",
    "redfin.com",
    "trulia.com",
    "homes.com",
    "apartments.com",
    "healthgrades.com",
    "zocdoc.com",
    "webmd.com",
    "ratemds.com",
}

REJECT_DOMAIN_PARTS = (
    ".gov",
    ".edu",
    "facebook.",
    "instagram.",
    "linkedin.",
    "twitter.",
    "tiktok.",
    "youtube.",
    "job",
    "career",
    "news",
    "press",
)

SOCIAL_HOSTS = (
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "pinterest.com",
)

PAGINATION_HINTS = (
    "next",
    "page",
    "p=",
    "pg=",
    "pagination",
    "paged=",
    "/page/",
)

CONTACT_HINTS = (
    "contact",
    "contact-us",
    "free-consultation",
    "consultation",
    "schedule",
    "book",
    "inquiry",
    "get-started",
    "appointment",
    "request-appointment",
)

PAGE_PRIORITY_HINTS = (
    "contact",
    "about",
    "team",
    "services",
    "work",
    "case-studies",
    "case-study",
    "blog",
    "resources",
    "listings",
    "properties",
    "attorneys",
    "lawyers",
    "practice-areas",
    "testimonials",
    "results",
    "faq",
    "free-consultation",
    "consultation",
    "book",
    "schedule",
)

NICHE_KEYWORDS = {
    "agencies": [
        "marketing agency",
        "digital marketing",
        "seo",
        "ppc",
        "web design",
        "social media marketing",
        "gohighlevel",
        "go high level",
        "ghl",
        "lead generation",
        "content marketing",
        "law firm marketing",
        "real estate marketing",
        "dental marketing",
        "med spa marketing",
        "white label",
        "agency",
        "growth agency",
        "client campaigns",
        "paid media",
    ],
    "law": [
        "immigration lawyer",
        "immigration attorney",
        "green card",
        "visa",
        "uscis",
        "asylum",
        "deportation",
        "removal defense",
        "citizenship",
        "naturalization",
        "family immigration",
        "employment immigration",
        "marriage visa",
        "work permit",
        "adjustment of status",
        "consular processing",
        "immigration law",
        "law firm",
        "attorney",
        "lawyer",
    ],
    "dental": [
        "dentist",
        "dental implants",
        "cosmetic dentistry",
        "veneers",
        "invisalign",
        "orthodontics",
        "oral surgery",
        "smile makeover",
        "dental clinic",
        "patient education",
        "before and after",
        "implants",
        "implant dentistry",
        "dental practice",
        "sedation dentistry",
        "dds",
        "dmd",
    ],
    "real_estate": [
        "real estate agent",
        "realtor",
        "broker",
        "brokerage",
        "luxury real estate",
        "homes for sale",
        "listings",
        "properties",
        "condo",
        "buyers",
        "sellers",
        "compass",
        "sotheby's",
        "sothebys",
        "coldwell banker",
        "keller williams",
        "re/max",
        "remax",
        "luxury homes",
        "waterfront",
        "penthouse",
    ],
}

PREMIUM_KEYWORDS = (
    "luxury",
    "attorney",
    "lawyer",
    "clinic",
    "consulting",
    "enterprise",
    "implant",
    "cosmetic",
    "orthodontic",
    "high net worth",
    "waterfront",
    "penthouse",
    "private client",
    "case study",
    "white label",
)

PARKED_OR_THIN_HINTS = (
    "domain is for sale",
    "buy this domain",
    "parked free",
    "coming soon",
    "under construction",
    "this site is under construction",
    "website coming soon",
    "future home of",
    "default page",
    "index of /",
)

COUNTRY_HINTS_US_CA = (
    "united states",
    "usa",
    "u.s.",
    "canada",
    "fl ",
    "ny ",
    "ca ",
    "tx ",
    "il ",
    "ga ",
    "az ",
    "wa ",
    "ma ",
)


@dataclass
class Candidate:
    business_name: str = ""
    website: str = ""
    domain: str = ""
    niche: str = ""
    city_state: str = ""
    country_guess: str = ""
    source_mode: str = ""
    source_provider: str = ""
    source_query_or_connector: str = ""
    source_title: str = ""
    source_snippet: str = ""
    source_tags: Dict[str, Any] = field(default_factory=dict)
    source_email: str = ""
    source_phone: str = ""
    osm_id: str = ""
    osm_type: str = ""
    lat: str = ""
    lon: str = ""

    def key(self) -> str:
        if self.domain:
            return self.domain
        if self.website:
            return normalize_domain(self.website) or stable_slug(self.website)
        if self.source_email:
            return f"email:{self.source_email.lower()}"
        if self.business_name and self.city_state:
            return f"name:{stable_slug(self.business_name)}:{stable_slug(self.city_state)}"
        return stable_slug(json.dumps(asdict(self), sort_keys=True))


@dataclass
class PageData:
    url: str
    status_code: int = 0
    title: str = ""
    meta_description: str = ""
    headings: List[str] = field(default_factory=list)
    text: str = ""
    html: str = ""
    internal_links: List[str] = field(default_factory=list)
    external_links: List[str] = field(default_factory=list)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source_provider: str
    query: str


class Log:
    def __init__(self, verbose: bool = False, errors_path: Optional[Path] = None) -> None:
        self.verbose = verbose
        self.errors_path = errors_path

    def info(self, message: str) -> None:
        print(message, flush=True)

    def debug(self, message: str) -> None:
        if self.verbose:
            print(message, flush=True)

    def error(self, message: str) -> None:
        print(message, flush=True)
        if self.errors_path:
            self.errors_path.parent.mkdir(parents=True, exist_ok=True)
            with self.errors_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{utc_now()} {message}\n")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stable_slug(value: str, max_len: int = 80) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value[:max_len] or "item"


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=True, indent=2)
    tmp.replace(path)


def clean_text(value: str) -> str:
    value = unescape(value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_url(url: str, default_scheme: str = "https") -> str:
    if not url:
        return ""
    url = clean_text(url)
    if url.startswith("//"):
        url = f"{default_scheme}:{url}"
    if not re.match(r"^https?://", url, flags=re.I):
        url = f"{default_scheme}://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ""
    netloc = parsed.netloc.lower()
    if "@" in netloc:
        netloc = netloc.split("@", 1)[1]
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path or "/"
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
    ]
    query = urlencode(query_pairs)
    return urlunparse((parsed.scheme.lower(), netloc, path, "", query, ""))


def normalize_domain(url_or_domain: str) -> str:
    if not url_or_domain:
        return ""
    value = url_or_domain.strip().lower()
    if "@" in value and not value.startswith("http"):
        value = value.split("@")[-1]
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    parsed = urlparse(value)
    host = parsed.netloc or parsed.path
    host = host.split("@")[-1].split(":")[0].lower()
    host = host.strip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return ""
    if TLD_EXTRACT:
        extracted = TLD_EXTRACT(host)
        registered = ".".join(part for part in [extracted.domain, extracted.suffix] if part)
        if registered and "." in registered:
            return registered.lower()
    return host


def is_probably_pdf_or_file(url: str) -> bool:
    path = urlparse(url).path.lower()
    return bool(
        re.search(
            r"\.(pdf|doc|docx|xls|xlsx|ppt|pptx|zip|rar|jpg|jpeg|png|gif|webp|svg|mp4|mov|mp3|wav)$",
            path,
        )
    )


def is_rejected_domain(domain: str) -> bool:
    if not domain:
        return True
    domain = domain.lower()
    if domain in REJECT_DOMAINS_EXACT:
        return True
    if any(domain.endswith("." + d) for d in REJECT_DOMAINS_EXACT):
        return True
    return any(part in domain for part in REJECT_DOMAIN_PARTS)


def is_social_domain(domain: str) -> bool:
    return any(domain == host or domain.endswith("." + host) for host in SOCIAL_HOSTS)


def extract_emails_from_text(text: str) -> Set[str]:
    emails: Set[str] = set()
    if not text:
        return emails
    normalized = unescape(text)
    normalized = re.sub(r"\s*\[\s*at\s*\]\s*", "@", normalized, flags=re.I)
    normalized = re.sub(r"\s*\(\s*at\s*\)\s*", "@", normalized, flags=re.I)
    normalized = re.sub(r"\s+\bat\b\s+", "@", normalized, flags=re.I)
    normalized = re.sub(r"\s*\[\s*@\s*\]\s*", "@", normalized, flags=re.I)
    normalized = re.sub(r"\s*\[\s*dot\s*\]\s*", ".", normalized, flags=re.I)
    normalized = re.sub(r"\s*\(\s*dot\s*\)\s*", ".", normalized, flags=re.I)
    normalized = re.sub(r"\s+\bdot\b\s+", ".", normalized, flags=re.I)
    normalized = re.sub(r"\s*\[\s*\.\s*\]\s*", ".", normalized, flags=re.I)
    for match in re.findall(
        r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,24}\b",
        normalized,
        flags=re.I,
    ):
        email = match.strip(".,;:()[]{}<>").lower()
        if is_good_email(email):
            emails.add(email)
    return emails


def is_good_email(email: str) -> bool:
    if not email or "@" not in email:
        return False
    email = email.lower().strip()
    local, domain = email.split("@", 1)
    if not local or not domain or "." not in domain:
        return False
    if local in BAD_EMAIL_PREFIXES:
        return False
    if any(local.startswith(prefix + "+") for prefix in BAD_EMAIL_PREFIXES):
        return False
    if any(bad in email for bad in BAD_EMAIL_SUBSTRINGS):
        return False
    if re.search(r"\.(png|jpg|jpeg|gif|webp|svg)$", email):
        return False
    return True


def pick_best_email(emails: Iterable[str], niche: str, domain: str = "") -> str:
    unique = sorted({email.lower() for email in emails if is_good_email(email)})
    if not unique:
        return ""

    preferred = PREFERRED_EMAIL_PREFIXES.get(niche, []) + PREFERRED_EMAIL_PREFIXES["general"]

    def score(email: str) -> Tuple[int, int, str]:
        local, email_domain = email.split("@", 1)
        points = 0
        if domain and normalize_domain(email_domain) == domain:
            points += 5
        if local in preferred:
            points += 4
        if any(local.startswith(prefix) for prefix in preferred):
            points += 2
        if "." in local and not re.search(r"\d{3,}", local):
            points += 2
        if local in {"sales", "support", "customerservice", "service"}:
            points -= 1
        return (-points, len(email), email)

    return sorted(unique, key=score)[0]


def extract_phone(text: str) -> str:
    if not text:
        return ""
    matches = re.findall(
        r"(?:\+?1[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]?)\d{3}[\s.\-]?\d{4}",
        text,
    )
    for match in matches:
        digits = re.sub(r"\D", "", match)
        if len(digits) == 10 or (len(digits) == 11 and digits.startswith("1")):
            return clean_text(match)
    return ""


def join_pipe(values: Iterable[str], max_items: int = 20) -> str:
    cleaned: List[str] = []
    seen: Set[str] = set()
    for value in values:
        value = clean_text(str(value))
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value)
        if len(cleaned) >= max_items:
            break
    return " | ".join(cleaned)


def split_cities(raw: str) -> List[str]:
    if not raw:
        return []
    return [city.strip() for city in raw.split(",") if city.strip()]


def parse_bbox(raw: str) -> Optional[Tuple[float, float, float, float]]:
    if not raw:
        return None
    try:
        parts = [float(part.strip()) for part in raw.split(",")]
    except ValueError:
        return None
    if len(parts) != 4:
        return None
    south, west, north, east = parts
    if south >= north or west >= east:
        return None
    return south, west, north, east


def load_cities(path: Path) -> Dict[str, Dict[str, Any]]:
    data = read_json(path, [])
    cities: Dict[str, Dict[str, Any]] = {}
    if isinstance(data, dict):
        iterable = data.get("cities", [])
    else:
        iterable = data
    for entry in iterable:
        name = entry.get("name", "")
        state = entry.get("state", "")
        aliases = entry.get("aliases", [])
        keys = {name, f"{name}, {state}".strip(", "), *aliases}
        for key in keys:
            if key:
                cities[key.lower()] = entry
    return cities


def city_label(entry: Dict[str, Any]) -> str:
    name = entry.get("name", "")
    state = entry.get("state", "")
    return f"{name}, {state}".strip(", ")


class RobotsCache:
    def __init__(self, session: requests.Session, delay: float, log: Log) -> None:
        self.session = session
        self.delay = delay
        self.log = log
        self.parsers: Dict[str, Optional[robotparser.RobotFileParser]] = {}
        self.last_fetch_by_domain: Dict[str, float] = {}

    def allowed(self, url: str) -> bool:
        domain = normalize_domain(url)
        if not domain:
            return False
        if domain not in self.parsers:
            robots_url = f"https://{domain}/robots.txt"
            parser = robotparser.RobotFileParser()
            parser.set_url(robots_url)
            try:
                response = self.session.get(
                    robots_url,
                    timeout=8,
                    headers={"User-Agent": USER_AGENT},
                    allow_redirects=True,
                )
                if response.status_code < 400:
                    parser.parse(response.text.splitlines())
                    self.parsers[domain] = parser
                else:
                    self.parsers[domain] = None
            except requests.RequestException:
                self.parsers[domain] = None
        parser = self.parsers.get(domain)
        if parser is None:
            return True
        try:
            return parser.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    def wait(self, domain: str, minimum: Optional[float] = None) -> None:
        if not domain:
            return
        minimum = self.delay if minimum is None else minimum
        last = self.last_fetch_by_domain.get(domain, 0)
        elapsed = time.time() - last
        wait_for = max(0.0, minimum - elapsed)
        if wait_for > 0:
            time.sleep(wait_for)
        self.last_fetch_by_domain[domain] = time.time()


class Fetcher:
    def __init__(self, delay: float, log: Log) -> None:
        self.delay = delay
        self.log = log
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.robots = RobotsCache(self.session, delay=delay, log=log)

    def get(
        self,
        url: str,
        timeout: int = 15,
        retries: int = 1,
        respect_robots: bool = True,
        min_delay: Optional[float] = None,
    ) -> Optional[requests.Response]:
        url = normalize_url(url)
        if not url or is_probably_pdf_or_file(url):
            return None
        domain = normalize_domain(url)
        if respect_robots and not self.robots.allowed(url):
            self.log.debug(f"[ROBOTS] disallowed url={url}")
            return None
        for attempt in range(retries + 1):
            try:
                self.robots.wait(domain, min_delay)
                response = self.session.get(
                    url,
                    timeout=timeout,
                    allow_redirects=True,
                    headers={"User-Agent": USER_AGENT},
                )
                if response.status_code in {429, 503, 504} and attempt < retries:
                    sleep_for = min(60, (2 ** attempt) * self.delay + random.uniform(0.5, 2.0))
                    self.log.debug(f"[BACKOFF] status={response.status_code} sleep={sleep_for:.1f}s url={url}")
                    time.sleep(sleep_for)
                    continue
                return response
            except requests.RequestException as exc:
                if attempt >= retries:
                    self.log.debug(f"[FETCH_ERROR] {url} {exc}")
                    return None
                sleep_for = min(60, (2 ** attempt) * self.delay + random.uniform(0.5, 2.0))
                time.sleep(sleep_for)
        return None


def parse_page(url: str, html: str, status_code: int = 0) -> PageData:
    soup = BeautifulSoup(html or "", "html.parser")
    for element in soup(["script", "style", "noscript", "template", "svg"]):
        element.decompose()
    title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    meta_description = ""
    meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    if meta and meta.get("content"):
        meta_description = clean_text(meta["content"])
    headings = [
        clean_text(node.get_text(" ", strip=True))
        for node in soup.find_all(re.compile("^h[1-3]$"))
        if clean_text(node.get_text(" ", strip=True))
    ][:20]
    text = clean_text(soup.get_text(" ", strip=True))
    internal_links: List[str] = []
    external_links: List[str] = []
    base_domain = normalize_domain(url)
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = normalize_url(urljoin(url, href))
        if not absolute:
            continue
        if is_probably_pdf_or_file(absolute):
            continue
        link_domain = normalize_domain(absolute)
        if link_domain == base_domain:
            internal_links.append(absolute)
        else:
            external_links.append(absolute)
    return PageData(
        url=url,
        status_code=status_code,
        title=title,
        meta_description=meta_description,
        headings=headings,
        text=text,
        html=html or "",
        internal_links=list(dict.fromkeys(internal_links)),
        external_links=list(dict.fromkeys(external_links)),
    )


def mailto_emails_from_html(html: str) -> Set[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    emails: Set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if href.lower().startswith("mailto:"):
            email = href.split(":", 1)[1].split("?", 1)[0]
            emails.update(extract_emails_from_text(email))
    return emails


class OutputManager:
    def __init__(self, output_path: Path, cache_dir: Path, args: argparse.Namespace, log: Log) -> None:
        self.output_path = output_path
        self.output_dir = output_path.parent if output_path.parent != Path("") else Path(".")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = cache_dir
        self.args = args
        self.log = log
        self.qualified_path = self.output_dir / "leads_qualified.csv"
        self.maybe_path = self.output_dir / "leads_maybe.csv"
        self.rejected_path = self.output_dir / "leads_rejected.csv"
        self.report_path = self.output_dir / "run_report.json"
        self.discovered_path = self.output_dir / "discovered_domains.txt"
        self.errors_path = self.output_dir / "errors.log"
        self.state_path = cache_dir / "runs" / f"{stable_slug(output_path.stem)}_{stable_slug(args.mode)}_{stable_slug(args.niche or 'all')}.json"
        self.state = self._initial_state()

    def _initial_state(self) -> Dict[str, Any]:
        return {
            "started_at": utc_now(),
            "finished_at": "",
            "mode": self.args.mode,
            "niche": self.args.niche or "all",
            "cities": split_cities(self.args.cities or ""),
            "target": self.args.target,
            "total_queries_run": 0,
            "total_search_results_collected": 0,
            "total_overpass_results_collected": 0,
            "unique_domains_found": 0,
            "processed_domains": 0,
            "qualified_count": 0,
            "maybe_count": 0,
            "rejected_count": 0,
            "duplicate_domains_skipped": 0,
            "provider_errors": [],
            "crawl_errors": [],
            "top_qualified_leads": [],
            "processed_keys": [],
            "discovered_domains": [],
            "rows": [],
        }

    def load_or_reset(self, resume: bool) -> None:
        if resume and self.state_path.exists():
            self.state = read_json(self.state_path, self._initial_state())
            self.log.info(
                f"[RESUME] loaded processed={len(self.state.get('processed_keys', []))} "
                f"rows={len(self.state.get('rows', []))}"
            )
        else:
            self.state = self._initial_state()
            self.save_state()
            self.write_csvs()
            self.discovered_path.write_text("", encoding="utf-8")
            self.errors_path.write_text("", encoding="utf-8")

    @property
    def processed_keys(self) -> Set[str]:
        return set(self.state.setdefault("processed_keys", []))

    @property
    def discovered_domains(self) -> Set[str]:
        return set(self.state.setdefault("discovered_domains", []))

    def save_state(self) -> None:
        write_json(self.state_path, self.state)

    def add_provider_error(self, message: str) -> None:
        self.state.setdefault("provider_errors", []).append(message)
        self.save_state()

    def add_crawl_error(self, message: str) -> None:
        self.state.setdefault("crawl_errors", []).append(message)
        self.save_state()

    def increment(self, key: str, amount: int = 1) -> None:
        self.state[key] = int(self.state.get(key, 0)) + amount

    def mark_discovered(self, candidate: Candidate) -> bool:
        key = candidate.domain or normalize_domain(candidate.website) or candidate.key()
        if not key:
            return False
        discovered = self.discovered_domains
        if key in discovered:
            if key not in self.processed_keys:
                return True
            self.increment("duplicate_domains_skipped")
            return False
        discovered.add(key)
        self.state["discovered_domains"] = sorted(discovered)
        self.state["unique_domains_found"] = len(discovered)
        with self.discovered_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{key}\n")
        self.save_state()
        return True

    def mark_processed(self, key: str) -> None:
        processed = self.processed_keys
        processed.add(key)
        self.state["processed_keys"] = sorted(processed)
        self.state["processed_domains"] = len(processed)

    def add_row(self, row: Dict[str, Any]) -> None:
        normalized = {column: row.get(column, "") for column in CSV_COLUMNS}
        normalized["lead_score"] = str(normalized.get("lead_score", ""))
        self.state.setdefault("rows", []).append(normalized)
        self.recount_rows()
        self.write_csvs()
        self.save_state()
        self.log.info(
            f"[RESULT] {normalized['qualified_status']} score={normalized['lead_score']} "
            f"reason=\"{normalized['reject_reason']}\""
        )
        self.log.info("[SAVE] wrote partial outputs")

    def recount_rows(self) -> None:
        rows = self.state.get("rows", [])
        self.state["qualified_count"] = sum(1 for row in rows if row.get("qualified_status") == "qualified")
        self.state["maybe_count"] = sum(1 for row in rows if row.get("qualified_status") == "maybe")
        self.state["rejected_count"] = sum(1 for row in rows if row.get("qualified_status") == "rejected")
        qualified = [row for row in rows if row.get("qualified_status") == "qualified"]
        qualified.sort(key=lambda row: int(row.get("lead_score") or 0), reverse=True)
        self.state["top_qualified_leads"] = qualified[:10]

    def write_csv(self, path: Path, rows: Sequence[Dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})

    def write_csvs(self) -> None:
        rows = self.state.get("rows", [])
        self.write_csv(self.qualified_path, [row for row in rows if row.get("qualified_status") == "qualified"])
        self.write_csv(self.maybe_path, [row for row in rows if row.get("qualified_status") == "maybe"])
        self.write_csv(self.rejected_path, [row for row in rows if row.get("qualified_status") == "rejected"])
        if self.output_path.name not in {
            self.qualified_path.name,
            self.maybe_path.name,
            self.rejected_path.name,
        }:
            self.write_csv(self.output_path, rows)

    def write_report(self, finished: bool = False) -> None:
        if finished:
            self.state["finished_at"] = utc_now()
        self.recount_rows()
        report = {
            key: value
            for key, value in self.state.items()
            if key not in {"processed_keys", "discovered_domains", "rows"}
        }
        write_json(self.report_path, report)
        self.save_state()


def build_overpass_queries(niche: str, bbox: Tuple[float, float, float, float], timeout: int) -> List[Tuple[str, str]]:
    south, west, north, east = bbox
    bbox_str = f"{south},{west},{north},{east}"
    selectors = {
        "law": [
            ('office=lawyer', f'nwr["office"="lawyer"]({bbox_str});'),
            ('amenity=lawyer', f'nwr["amenity"="lawyer"]({bbox_str});'),
        ],
        "dental": [
            ('amenity=dentist', f'nwr["amenity"="dentist"]({bbox_str});'),
            ('healthcare=dentist', f'nwr["healthcare"="dentist"]({bbox_str});'),
            ('healthcare=clinic', f'nwr["healthcare"="clinic"]({bbox_str});'),
        ],
        "real_estate": [
            ('office=estate_agent', f'nwr["office"="estate_agent"]({bbox_str});'),
            ('shop=estate_agent', f'nwr["shop"="estate_agent"]({bbox_str});'),
        ],
        "agencies": [
            ('office=advertising_agency', f'nwr["office"="advertising_agency"]({bbox_str});'),
            ('office=company', f'nwr["office"="company"]({bbox_str});'),
        ],
    }
    queries: List[Tuple[str, str]] = []
    for label, selector in selectors.get(niche, []):
        ql = f"[out:json][timeout:{timeout}];({selector});out center tags;"
        queries.append((label, ql))
    return queries


def discover_overpass(
    args: argparse.Namespace,
    niche: str,
    cities: Dict[str, Dict[str, Any]],
    output: OutputManager,
    log: Log,
) -> List[Candidate]:
    selected_cities = split_cities(args.cities or "")
    if not selected_cities:
        selected_cities = ["Miami", "New York", "Los Angeles", "Houston", "Dallas"]
    endpoint = os.getenv("OVERPASS_URL", "").strip() or "https://overpass-api.de/api/interpreter"
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    candidates: List[Candidate] = []
    cache_dir = Path(args.cache_dir) / "overpass"
    cache_dir.mkdir(parents=True, exist_ok=True)

    for raw_city in selected_cities:
        city_entry = cities.get(raw_city.lower())
        if not city_entry:
            manual_bbox = parse_bbox(args.bbox or "")
            if manual_bbox:
                city_entry = {
                    "name": raw_city,
                    "state": "",
                    "aliases": [],
                    "bbox": {
                        "south": manual_bbox[0],
                        "west": manual_bbox[1],
                        "north": manual_bbox[2],
                        "east": manual_bbox[3],
                    },
                }
                log.info(f"[OVERPASS] using manual bbox for city=\"{raw_city}\"")
            else:
                log.error(
                    f"[OVERPASS] city=\"{raw_city}\" not found in {args.city_file}. "
                    "Add it to cities.json or pass --bbox south,west,north,east."
                )
                output.add_provider_error(f"Missing city bbox: {raw_city}")
                continue
        bbox_obj = city_entry.get("bbox", {})
        try:
            bbox = (
                float(bbox_obj["south"]),
                float(bbox_obj["west"]),
                float(bbox_obj["north"]),
                float(bbox_obj["east"]),
            )
        except (KeyError, ValueError, TypeError):
            output.add_provider_error(f"Invalid bbox for city: {raw_city}")
            continue

        for label, ql in build_overpass_queries(niche, bbox, args.overpass_timeout):
            output.increment("total_queries_run")
            log.info(f"[OVERPASS] city={city_entry.get('name')} query={label}")
            if args.dry_run:
                log.info(f"[DRY-RUN] would query Overpass endpoint={endpoint}")
                continue
            cache_key = f"{stable_slug(niche)}_{stable_slug(city_label(city_entry))}_{stable_slug(label)}_{hash_text(ql)}.json"
            cache_path = cache_dir / cache_key
            data: Dict[str, Any] = {}
            if cache_path.exists():
                data = read_json(cache_path, {})
                log.debug(f"[CACHE] overpass {cache_path}")
            else:
                data = fetch_overpass(session, endpoint, ql, args.delay, log)
                if data:
                    write_json(cache_path, data)
                time.sleep(args.delay)
            elements = data.get("elements", []) if isinstance(data, dict) else []
            output.increment("total_overpass_results_collected", len(elements))
            log.info(f"[FOUND] {len(elements)} raw POIs")
            for element in elements:
                candidate = candidate_from_overpass(element, niche, city_entry, label)
                if not candidate.website and not candidate.source_email:
                    continue
                if candidate.website and is_rejected_domain(candidate.domain):
                    continue
                if output.mark_discovered(candidate):
                    candidates.append(candidate)
            log.info(f"[DISCOVERED] {len(candidates)} candidate websites")
    return candidates


def fetch_overpass(
    session: requests.Session,
    endpoint: str,
    query: str,
    delay: float,
    log: Log,
    retries: int = 3,
) -> Dict[str, Any]:
    for attempt in range(retries):
        try:
            response = session.post(endpoint, data={"data": query}, timeout=60)
            if response.status_code in {429, 504, 503}:
                sleep_for = min(180, (2 ** attempt) * max(delay, 2.0) + random.uniform(1, 5))
                log.info(f"[OVERPASS] rate/timeout status={response.status_code} backoff={sleep_for:.1f}s")
                time.sleep(sleep_for)
                continue
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            sleep_for = min(180, (2 ** attempt) * max(delay, 2.0) + random.uniform(1, 5))
            log.error(f"[OVERPASS_ERROR] attempt={attempt + 1} error={exc}")
            time.sleep(sleep_for)
    return {}


def candidate_from_overpass(
    element: Dict[str, Any],
    niche: str,
    city_entry: Dict[str, Any],
    label: str,
) -> Candidate:
    tags = element.get("tags", {}) or {}
    website = (
        tags.get("website")
        or tags.get("contact:website")
        or tags.get("url")
        or tags.get("contact:url")
        or ""
    )
    website = normalize_url(website)
    domain = normalize_domain(website)
    email = tags.get("email") or tags.get("contact:email") or ""
    email = pick_best_email(extract_emails_from_text(email), niche, domain)
    phone = tags.get("phone") or tags.get("contact:phone") or tags.get("contact:mobile") or ""
    city_state = city_label(city_entry)
    lat = str(element.get("lat") or element.get("center", {}).get("lat") or "")
    lon = str(element.get("lon") or element.get("center", {}).get("lon") or "")
    return Candidate(
        business_name=tags.get("name", ""),
        website=website,
        domain=domain,
        niche=niche,
        city_state=city_state,
        country_guess="US",
        source_mode="overpass",
        source_provider="overpass",
        source_query_or_connector=label,
        source_tags=tags,
        source_email=email,
        source_phone=clean_text(phone),
        osm_id=str(element.get("id", "")),
        osm_type=str(element.get("type", "")),
        lat=lat,
        lon=lon,
    )


def discover_directories(
    args: argparse.Namespace,
    niche: str,
    output: OutputManager,
    fetcher: Fetcher,
    log: Log,
) -> List[Candidate]:
    connectors = read_json(Path(args.connector_file), [])
    candidates: List[Candidate] = []
    if not isinstance(connectors, list):
        output.add_provider_error("connectors.json should contain a list")
        return candidates
    active = [
        connector
        for connector in connectors
        if connector.get("niche") in {niche, "all"}
        and connector.get("enabled", True)
        and connector.get("start_urls")
    ]
    if not active:
        log.info(f"[DIRECTORIES] no enabled connectors for niche={niche}")
        return candidates

    for connector in active:
        name = connector.get("name", "directory")
        allowed_domains = {
            normalize_domain(domain)
            for domain in connector.get("allowed_domains", [])
            if normalize_domain(domain)
        }
        max_pages = int(connector.get("max_pages", 50))
        queue: deque[str] = deque(normalize_url(url) for url in connector.get("start_urls", []) if normalize_url(url))
        seen_pages: Set[str] = set()
        pages_fetched = 0
        log.info(f"[DIRECTORIES] connector={name} pages<= {max_pages}")
        while queue and pages_fetched < max_pages:
            page_url = queue.popleft()
            if page_url in seen_pages:
                continue
            page_domain = normalize_domain(page_url)
            if allowed_domains and page_domain not in allowed_domains:
                continue
            seen_pages.add(page_url)
            output.increment("total_queries_run")
            if args.dry_run:
                log.info(f"[DRY-RUN] would fetch directory page={page_url}")
                continue
            response = fetcher.get(page_url, timeout=20, retries=1, min_delay=max(args.delay, 2.0))
            pages_fetched += 1
            if not response or response.status_code >= 400 or "text/html" not in response.headers.get("content-type", ""):
                continue
            page = parse_page(response.url, response.text, response.status_code)
            for link in page.external_links:
                domain = normalize_domain(link)
                if not domain or is_rejected_domain(domain) or is_social_domain(domain):
                    continue
                candidate = Candidate(
                    business_name="",
                    website=normalize_url(link),
                    domain=domain,
                    niche=niche,
                    source_mode="directories",
                    source_provider="directory",
                    source_query_or_connector=name,
                    source_snippet=page.title,
                )
                if output.mark_discovered(candidate):
                    candidates.append(candidate)
            for link in page.internal_links:
                if len(queue) + len(seen_pages) >= max_pages:
                    break
                href_text = link.lower()
                if any(hint in href_text for hint in PAGINATION_HINTS):
                    if link not in seen_pages:
                        queue.append(link)
            log.info(f"[DISCOVERED] {len(candidates)} candidate websites")
    return candidates


class SearchProvider:
    name = "base"

    def enabled(self) -> bool:
        return False

    def search(self, query: str, limit: int = 10) -> List[SearchResult]:
        raise NotImplementedError


class GoogleCSEProvider(SearchProvider):
    name = "google_cse"

    def __init__(self) -> None:
        self.api_key = os.getenv("GOOGLE_API_KEY", "").strip()
        self.cse_id = os.getenv("GOOGLE_CSE_ID", "").strip()
        self.session = requests.Session()

    def enabled(self) -> bool:
        return bool(self.api_key and self.cse_id)

    def search(self, query: str, limit: int = 10) -> List[SearchResult]:
        response = self.session.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": self.api_key, "cx": self.cse_id, "q": query, "num": min(limit, 10)},
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("items", []):
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("link", ""),
                    snippet=item.get("snippet", ""),
                    source_provider=self.name,
                    query=query,
                )
            )
        return results


class SerpApiProvider(SearchProvider):
    name = "serpapi"

    def __init__(self) -> None:
        self.api_key = os.getenv("SERPAPI_KEY", "").strip()
        self.session = requests.Session()

    def enabled(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, limit: int = 10) -> List[SearchResult]:
        response = self.session.get(
            "https://serpapi.com/search.json",
            params={"engine": "google", "q": query, "api_key": self.api_key, "num": min(limit, 10)},
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("organic_results", [])[:limit]:
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("link", ""),
                    snippet=item.get("snippet", ""),
                    source_provider=self.name,
                    query=query,
                )
            )
        return results


class BraveSearchProvider(SearchProvider):
    name = "brave"

    def __init__(self) -> None:
        self.api_key = os.getenv("BRAVE_API_KEY", "").strip()
        self.session = requests.Session()

    def enabled(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, limit: int = 10) -> List[SearchResult]:
        response = self.session.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": min(limit, 20)},
            headers={"Accept": "application/json", "X-Subscription-Token": self.api_key, "User-Agent": USER_AGENT},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("web", {}).get("results", [])[:limit]:
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("description", ""),
                    source_provider=self.name,
                    query=query,
                )
            )
        return results


class YelpProvider(SearchProvider):
    name = "yelp"

    def __init__(self) -> None:
        self.api_key = os.getenv("YELP_API_KEY", "").strip()
        self.session = requests.Session()

    def enabled(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, limit: int = 10) -> List[SearchResult]:
        # Yelp Fusion does not reliably expose official websites. Returning Yelp
        # listing URLs lets the normal filter reject them unless a future endpoint
        # or connector provides official links.
        response = self.session.get(
            "https://api.yelp.com/v3/businesses/search",
            params={"term": query, "location": "United States", "limit": min(limit, 20)},
            headers={"Authorization": f"Bearer {self.api_key}", "User-Agent": USER_AGENT},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("businesses", [])[:limit]:
            results.append(
                SearchResult(
                    title=item.get("name", ""),
                    url=item.get("url", ""),
                    snippet=", ".join(item.get("categories", [{}])[0].get("title", "") for _ in [0]),
                    source_provider=self.name,
                    query=query,
                )
            )
        return results


class ManualProvider(SearchProvider):
    name = "manual"

    def __init__(self, urls: Sequence[str]) -> None:
        self.urls = list(urls)

    def enabled(self) -> bool:
        return bool(self.urls)

    def search(self, query: str, limit: int = 10) -> List[SearchResult]:
        return [
            SearchResult(title="", url=url, snippet="", source_provider=self.name, query="manual")
            for url in self.urls[:limit]
        ]


def discover_search(
    args: argparse.Namespace,
    niche: str,
    output: OutputManager,
    log: Log,
) -> List[Candidate]:
    queries_config = read_json(Path(getattr(args, "query_file", "queries.json")), {})
    query_templates = queries_config.get(niche, []) if isinstance(queries_config, dict) else []
    cities = split_cities(args.cities or "")
    if not cities:
        cities = ["Miami", "New York", "Los Angeles", "Houston", "Dallas"]
    providers: List[SearchProvider] = [
        GoogleCSEProvider(),
        SerpApiProvider(),
        BraveSearchProvider(),
        YelpProvider(),
    ]
    manual_urls = []
    if getattr(args, "manual_url", None):
        manual_urls.extend(args.manual_url)
    if getattr(args, "manual_file", ""):
        manual_path = Path(args.manual_file)
        if manual_path.exists():
            manual_urls.extend(
                line.strip()
                for line in manual_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            )
    providers.append(ManualProvider(manual_urls))

    enabled = [provider for provider in providers if provider.enabled()]
    if not enabled:
        log.info("[SEARCH] no optional search providers enabled; add API keys to .env to use search mode")
        return []

    candidates: List[Candidate] = []
    per_provider_queries = 0
    for provider in enabled:
        per_provider_queries = 0
        for city in cities:
            for template in query_templates:
                if args.max_queries_per_provider and per_provider_queries >= args.max_queries_per_provider:
                    break
                query = template.replace("{city}", city)
                output.increment("total_queries_run")
                per_provider_queries += 1
                log.info(f"[SEARCH] provider={provider.name} query=\"{query}\"")
                if args.dry_run:
                    log.info("[DRY-RUN] would call optional search provider")
                    continue
                try:
                    results = provider.search(query, limit=10)
                    output.increment("total_search_results_collected", len(results))
                except Exception as exc:
                    message = f"{provider.name}: {exc}"
                    log.error(f"[PROVIDER_ERROR] {message}")
                    output.add_provider_error(message)
                    continue
                for result in results:
                    url = normalize_url(result.url)
                    domain = normalize_domain(url)
                    if not url or is_probably_pdf_or_file(url) or is_rejected_domain(domain):
                        continue
                    candidate = Candidate(
                        business_name=result.title,
                        website=url,
                        domain=domain,
                        niche=niche,
                        city_state=city,
                        source_mode="search",
                        source_provider=result.source_provider,
                        source_query_or_connector=query,
                        source_title=result.title,
                        source_snippet=result.snippet,
                    )
                    if output.mark_discovered(candidate):
                        candidates.append(candidate)
                time.sleep(args.delay)
    return candidates


class Crawler:
    def __init__(self, args: argparse.Namespace, output: OutputManager, fetcher: Fetcher, log: Log) -> None:
        self.args = args
        self.output = output
        self.fetcher = fetcher
        self.log = log
        self.cache_dir = Path(args.cache_dir) / "crawl"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def crawl(self, candidate: Candidate) -> Tuple[List[PageData], str]:
        if not candidate.website:
            return [], "" if candidate.source_email else "no website"
        domain = candidate.domain or normalize_domain(candidate.website)
        if is_rejected_domain(domain):
            return [], "rejected seed domain"
        cache_path = self.cache_dir / f"{stable_slug(domain)}.json"
        if cache_path.exists():
            cached = read_json(cache_path, {})
            pages = [
                PageData(
                    url=item.get("url", ""),
                    status_code=int(item.get("status_code", 0) or 0),
                    title=item.get("title", ""),
                    meta_description=item.get("meta_description", ""),
                    headings=item.get("headings", []),
                    text=item.get("text", ""),
                    html=item.get("html", ""),
                    internal_links=item.get("internal_links", []),
                    external_links=item.get("external_links", []),
                )
                for item in cached.get("pages", [])
            ]
            if pages:
                return pages, ""

        homepage = normalize_url(candidate.website)
        queue: deque[str] = deque([homepage])
        seen: Set[str] = set()
        pages: List[PageData] = []
        error = ""

        while queue and len(pages) < self.args.max_pages_per_domain:
            url = queue.popleft()
            if url in seen:
                continue
            seen.add(url)
            if normalize_domain(url) != domain:
                continue
            response = self.fetcher.get(url, timeout=15, retries=1)
            if not response:
                if not pages:
                    error = "broken site"
                continue
            content_type = response.headers.get("content-type", "").lower()
            if response.status_code >= 400:
                if not pages:
                    error = f"http {response.status_code}"
                continue
            if "text/html" not in content_type and content_type:
                continue
            page = parse_page(response.url, response.text, response.status_code)
            pages.append(page)
            prioritized = sorted(
                page.internal_links,
                key=lambda link: (internal_link_priority(link), len(link)),
            )
            for link in prioritized:
                if len(queue) + len(pages) >= self.args.max_pages_per_domain * 4:
                    break
                if link not in seen and normalize_domain(link) == domain:
                    if any(hint in urlparse(link).path.lower() for hint in PAGE_PRIORITY_HINTS):
                        queue.append(link)

        if pages:
            write_json(
                cache_path,
                {
                    "domain": domain,
                    "crawled_at": utc_now(),
                    "pages": [
                        {
                            "url": page.url,
                            "status_code": page.status_code,
                            "title": page.title,
                            "meta_description": page.meta_description,
                            "headings": page.headings,
                            "text": page.text[:30000],
                            "html": page.html[:50000],
                            "internal_links": page.internal_links[:200],
                            "external_links": page.external_links[:200],
                        }
                        for page in pages
                    ],
                },
            )
        return pages, error


def internal_link_priority(url: str) -> int:
    path = urlparse(url).path.lower()
    for index, hint in enumerate(PAGE_PRIORITY_HINTS):
        if hint in path:
            return index
    return 999


def extract_social_links(pages: Sequence[PageData]) -> List[str]:
    links: List[str] = []
    seen: Set[str] = set()
    for page in pages:
        for link in page.external_links:
            domain = normalize_domain(link)
            if is_social_domain(domain):
                normalized = normalize_url(link)
                if normalized not in seen:
                    seen.add(normalized)
                    links.append(normalized)
    return links[:10]


def detect_contact_form(pages: Sequence[PageData]) -> str:
    candidates: List[Tuple[int, str]] = []
    for page in pages:
        path = urlparse(page.url).path.lower()
        html_lower = page.html.lower()
        score = 0
        if any(hint in path for hint in CONTACT_HINTS):
            score += 3
        if "<form" in html_lower:
            score += 2
        if any(word in page.text.lower() for word in ["contact us", "schedule", "appointment", "consultation"]):
            score += 1
        if score:
            candidates.append((-score, page.url))
    return sorted(candidates)[0][1] if candidates else ""


def detect_decision_makers(pages: Sequence[PageData]) -> List[str]:
    title_words = (
        "Founder",
        "Owner",
        "Managing Partner",
        "Principal",
        "Attorney",
        "Lawyer",
        "Realtor",
        "Broker",
        "Marketing Director",
        "CEO",
        "Creative Director",
        "Doctor",
        "DDS",
        "DMD",
        "Practice Owner",
        "Office Manager",
    )
    title_pattern = "|".join(re.escape(word) for word in title_words)
    name_pattern = r"[A-Z][a-z]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-z]+){1,2}"
    makers: List[str] = []
    seen: Set[str] = set()
    relevant_pages = [
        page
        for page in pages
        if any(hint in urlparse(page.url).path.lower() for hint in ("about", "team", "attorney", "lawyer", "doctor"))
    ] or list(pages[:3])
    for page in relevant_pages:
        text = page.text
        patterns = [
            rf"({name_pattern})\s*,?\s*(?:-|–|,)?\s*({title_pattern})",
            rf"({title_pattern})\s*(?:-|–|,|:)?\s*({name_pattern})",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                groups = [clean_text(group) for group in match.groups()]
                if len(groups) < 2:
                    continue
                if re.search(title_pattern, groups[0]):
                    title, name = groups[0], groups[1]
                else:
                    name, title = groups[0], groups[1]
                if not plausible_name(name):
                    continue
                value = f"{name} ({title})"
                key = value.lower()
                if key not in seen:
                    seen.add(key)
                    makers.append(value)
                    if len(makers) >= 5:
                        return makers
    return makers


def plausible_name(name: str) -> bool:
    bad = {"Contact Us", "Learn More", "Read More", "Privacy Policy", "Terms Conditions"}
    if name in bad:
        return False
    words = name.split()
    return 2 <= len(words) <= 4 and all(word[0].isupper() for word in words if word)


def classify_keyword_score(niche: str, text: str) -> int:
    text_l = text.lower()
    score = 0
    for keyword in NICHE_KEYWORDS.get(niche, []):
        if keyword.lower() in text_l:
            score += 2 if " " in keyword else 1
    return score


def wrong_niche(niche: str, keyword_score: int, text: str, candidate: Candidate) -> bool:
    source_blob = " ".join(
        [
            candidate.business_name,
            candidate.source_title,
            candidate.source_snippet,
            json.dumps(candidate.source_tags),
        ]
    ).lower()
    blob = (text + " " + source_blob).lower()
    if niche == "law":
        return not any(
            word in blob
            for word in (
                "immigration",
                "green card",
                "visa",
                "uscis",
                "asylum",
                "deportation",
                "citizenship",
                "naturalization",
                "law firm",
                "attorney",
                "lawyer",
            )
        )
    if niche == "agencies":
        return not any(
            word in blob
            for word in (
                "marketing",
                "seo",
                "web design",
                "agency",
                "lead generation",
                "gohighlevel",
                "white label",
                "ppc",
            )
        )
    if niche == "dental":
        return not any(word in blob for word in ("dentist", "dental", "orthodont", "implant", "dds", "dmd"))
    if niche == "real_estate":
        return not any(
            word in blob
            for word in ("real estate", "realtor", "broker", "brokerage", "homes for sale", "property", "listings")
        )
    return keyword_score < 2


def detect_asset_type(page: PageData, niche: str) -> str:
    path = urlparse(page.url).path.lower()
    blob = f"{path} {page.title} {page.meta_description} {' '.join(page.headings)} {page.text[:2000]}".lower()
    if any(word in blob for word in ("case-study", "case studies", "case study", "client results")):
        return "case_study"
    if any(word in blob for word in ("testimonial", "reviews", "results", "success stories")):
        return "testimonial"
    if any(word in blob for word in ("faq", "frequently asked")):
        return "faq"
    if any(word in blob for word in ("video", "podcast", "webinar", "youtube.com/embed", "vimeo")):
        return "long_form_video"
    if niche == "real_estate" and any(word in blob for word in ("listing", "property", "homes-for-sale", "homes for sale")):
        return "listing"
    if niche == "law" and any(word in blob for word in ("practice-area", "practice areas", "immigration", "visa", "green card")):
        return "practice_area"
    if any(word in blob for word in ("blog", "resource", "article", "insight", "guide", "news")):
        return "blog"
    if any(
        word in blob
        for word in (
            "service",
            "services",
            "treatment",
            "dental implants",
            "cosmetic",
            "seo",
            "marketing",
            "luxury",
        )
    ):
        return "service_page"
    path_clean = path.strip("/")
    if not path_clean:
        return "homepage"
    return "unknown"


def pick_best_asset(pages: Sequence[PageData], niche: str) -> Tuple[str, str]:
    priority = {
        "blog": 1,
        "service_page": 2,
        "practice_area": 2,
        "case_study": 3,
        "testimonial": 4,
        "listing": 5,
        "faq": 6,
        "long_form_video": 7,
        "homepage": 8,
        "unknown": 99,
    }
    ranked: List[Tuple[int, int, str, str]] = []
    for index, page in enumerate(pages):
        asset_type = detect_asset_type(page, niche)
        ranked.append((priority.get(asset_type, 99), index, page.url, asset_type))
    if not ranked:
        return "", "unknown"
    best = sorted(ranked)[0]
    return best[2], best[3]


def has_shortform_opportunity(niche: str, asset_type: str, text: str) -> bool:
    if asset_type in {"blog", "service_page", "practice_area", "listing", "case_study", "testimonial", "faq", "long_form_video"}:
        return True
    blob = text.lower()
    if niche == "agencies":
        return any(word in blob for word in ("case study", "client", "campaign", "service"))
    if niche == "law":
        return any(word in blob for word in ("visa", "green card", "immigration", "faq", "consultation"))
    if niche == "dental":
        return any(word in blob for word in ("implant", "cosmetic", "invisalign", "smile", "patient"))
    if niche == "real_estate":
        return any(word in blob for word in ("listing", "property", "neighborhood", "luxury", "buyer"))
    return False


def generate_shortform_opportunity(niche: str, asset_type: str, text: str) -> str:
    blob = text.lower()
    if niche == "law":
        if any(word in blob for word in ("visa", "green card", "uscis")):
            return "Has visa/green card service pages that can become applicant education shorts."
        return "Has immigration blog/practice pages that can become frustration-based legal mistake clips."
    if niche == "dental":
        if any(word in blob for word in ("implant", "cosmetic", "veneers", "invisalign")):
            return "Has high-ticket treatment pages that can become trust-building short-form content."
        return "Has dental service pages that can become patient education clips."
    if niche == "real_estate":
        if asset_type == "listing" or "luxury" in blob:
            return "Has luxury listings with strong visuals that can become lifestyle-driven property shorts."
        return "Has neighborhood/listing pages that can become buyer-focused short-form clips."
    if niche == "agencies":
        if "short-form" not in blob and "short form" not in blob:
            return "Agency serves high-ticket clients but does not clearly offer short-form production."
        return "Agency has case studies/service pages that can support a white-label short-form offer."
    return "Has public assets that can be repurposed into short-form clips."


def generate_demo_angle(niche: str, asset_type: str, text: str, city_state: str = "") -> str:
    blob = text.lower()
    city = city_state.split(",")[0].strip() if city_state else "this market"
    if niche == "law":
        if "denial" in blob or "deportation" in blob or "removal" in blob:
            return "Turn their visa/deportation page into: 'The mistake that makes officers doubt your application.'"
        return "Turn their immigration service page into a 35-second clip: 'Why qualified applicants still get delayed.'"
    if niche == "dental":
        if "implant" in blob:
            return "Turn their dental implant page into a patient education clip: 'The question patients are scared to ask before implants.'"
        return "Turn their cosmetic dentistry page into: 'What patients misunderstand before choosing veneers.'"
    if niche == "real_estate":
        if asset_type == "listing" or "luxury" in blob:
            return "Turn their luxury listing into a lifestyle short: 'What this property lets the buyer stop worrying about.'"
        return f"Turn their neighborhood page into: 'Why buyers are moving to this part of {city}.'"
    if niche == "agencies":
        if asset_type == "case_study":
            return "Offer a white-label sample using one of their client case studies or service pages."
        return "Position short-form as an add-on they can resell to current clients."
    return "Turn a strong service page into a concise client education short."


def infer_business_name(candidate: Candidate, pages: Sequence[PageData]) -> str:
    if candidate.business_name:
        return clean_text(candidate.business_name)
    if pages:
        first = pages[0]
        candidates = []
        if first.headings:
            candidates.append(first.headings[0])
        if first.title:
            candidates.append(re.split(r"\s+[|\-–]\s+", first.title)[0])
        for value in candidates:
            value = clean_text(value)
            if 2 <= len(value) <= 80 and not re.search(r"\b(home|welcome|contact)\b", value, re.I):
                return value
    return candidate.domain or normalize_domain(candidate.website)


def infer_country(candidate: Candidate, text: str) -> str:
    if candidate.country_guess:
        return candidate.country_guess
    blob = f"{candidate.city_state} {text[:5000]}".lower()
    if any(hint in blob for hint in COUNTRY_HINTS_US_CA):
        if "canada" in blob:
            return "CA"
        return "US"
    if candidate.city_state:
        return "US"
    return ""


def reject_reason_for(
    candidate: Candidate,
    pages: Sequence[PageData],
    text: str,
    keyword_score: int,
    best_email: str,
    contact_form_url: str,
    best_asset_type: str,
    country_guess: str,
) -> str:
    domain = candidate.domain or normalize_domain(candidate.website)
    if not candidate.website and not candidate.source_email:
        return "no website and no email"
    if candidate.website and is_rejected_domain(domain):
        return "government/education/news/social/directory domain"
    if candidate.website and not pages:
        return "broken site"
    blob = text.lower()
    if any(hint in blob for hint in PARKED_OR_THIN_HINTS):
        return "parked or under construction"
    if pages and len(blob) < 500:
        return "mostly empty/thin website"
    if wrong_niche(candidate.niche, keyword_score, text, candidate):
        return "clearly wrong niche"
    if not best_email and not contact_form_url and not candidate.source_phone:
        return "no contact method"
    if not candidate.website and candidate.source_email:
        return ""
    has_service_offer = any(word in blob for word in ("service", "services", "practice", "treatment", "listing", "case study"))
    if best_asset_type in {"unknown", ""} and not has_service_offer:
        return "no useful asset or visible service offer"
    if country_guess and country_guess not in {"US", "CA"}:
        return "outside US/Canada"
    if "franchise opportunities" in blob and not best_email and not contact_form_url:
        return "corporate/franchise page with no reachable local decision maker"
    return ""


def score_lead(
    candidate: Candidate,
    pages: Sequence[PageData],
    text: str,
    keyword_score: int,
    best_email: str,
    contact_form_url: str,
    decision_makers: Sequence[str],
    best_asset_type: str,
    country_guess: str,
    shortform: bool,
    reject_reason: str,
) -> int:
    score = 0
    domain = candidate.domain or normalize_domain(candidate.website)
    if keyword_score >= 4 or not wrong_niche(candidate.niche, keyword_score, text, candidate):
        score += 2
    if best_email:
        score += 1
    if contact_form_url:
        score += 1
    if decision_makers:
        score += 1
    if best_asset_type not in {"unknown", "", "homepage"}:
        score += 1
    if any(word in text.lower() for word in PREMIUM_KEYWORDS):
        score += 1
    if shortform:
        score += 1
    if len(pages) >= 3:
        score += 1
    if country_guess in {"US", "CA"} or candidate.city_state or candidate.lat:
        score += 1

    if is_rejected_domain(domain):
        score -= 2
    if keyword_score < 2:
        score -= 2
    if not best_email and not contact_form_url and not candidate.source_phone:
        score -= 2
    if best_asset_type in {"unknown", "", "homepage"}:
        score -= 1
    if pages and len(text) < 1200:
        score -= 1
    if country_guess and country_guess not in {"US", "CA"}:
        score -= 1
    if "franchise opportunities" in text.lower():
        score -= 1
    if reject_reason:
        score = min(score, 3)
    return max(0, min(10, score))


def qualify_status(score: int, reject_reason: str, has_contact: bool, min_score: int) -> str:
    if reject_reason:
        return "rejected"
    if score >= min_score:
        return "qualified"
    if 4 <= score <= 5 and has_contact:
        return "maybe"
    return "rejected"


def row_from_candidate(
    candidate: Candidate,
    pages: Sequence[PageData],
    crawl_error: str,
    args: argparse.Namespace,
) -> Dict[str, Any]:
    page_text = " ".join(
        [
            candidate.business_name,
            candidate.source_title,
            candidate.source_snippet,
            json.dumps(candidate.source_tags, ensure_ascii=True),
            *[page.title for page in pages],
            *[page.meta_description for page in pages],
            *[" ".join(page.headings) for page in pages],
            *[page.text for page in pages],
        ]
    )
    domain = candidate.domain or normalize_domain(candidate.website)
    emails = set()
    if candidate.source_email:
        emails.add(candidate.source_email)
    for page in pages:
        emails.update(extract_emails_from_text(page.text))
        emails.update(mailto_emails_from_html(page.html))
    best_email = pick_best_email(emails, candidate.niche, domain)
    phone = candidate.source_phone or extract_phone(page_text)
    contact_form_url = detect_contact_form(pages)
    decision_makers = detect_decision_makers(pages)
    social_links = extract_social_links(pages)
    best_asset_url, best_asset_type = pick_best_asset(pages, candidate.niche)
    keyword_score = classify_keyword_score(candidate.niche, page_text)
    country_guess = infer_country(candidate, page_text)
    shortform = has_shortform_opportunity(candidate.niche, best_asset_type, page_text)
    shortform_opportunity = generate_shortform_opportunity(candidate.niche, best_asset_type, page_text) if shortform else ""
    demo_angle = generate_demo_angle(candidate.niche, best_asset_type, page_text, candidate.city_state) if shortform else ""
    reject_reason = crawl_error or reject_reason_for(
        candidate,
        pages,
        page_text,
        keyword_score,
        best_email,
        contact_form_url,
        best_asset_type,
        country_guess,
    )
    lead_score = score_lead(
        candidate,
        pages,
        page_text,
        keyword_score,
        best_email,
        contact_form_url,
        decision_makers,
        best_asset_type,
        country_guess,
        shortform,
        reject_reason,
    )
    has_contact = bool(best_email or contact_form_url or phone)
    status = qualify_status(lead_score, reject_reason, has_contact, args.min_score)
    return {
        "business_name": infer_business_name(candidate, pages),
        "niche": candidate.niche,
        "qualified_status": status,
        "lead_score": lead_score,
        "website": candidate.website,
        "domain": domain,
        "city_state": candidate.city_state,
        "country_guess": country_guess,
        "source_mode": candidate.source_mode,
        "source_provider": candidate.source_provider,
        "source_query_or_connector": candidate.source_query_or_connector,
        "best_email": best_email,
        "emails_found": join_pipe(sorted(emails), max_items=20),
        "phone": phone,
        "contact_form_url": contact_form_url,
        "decision_maker_names": join_pipe(decision_makers, max_items=5),
        "social_links": join_pipe(social_links, max_items=10),
        "best_asset_url": best_asset_url,
        "best_asset_type": best_asset_type,
        "demo_angle": demo_angle,
        "shortform_opportunity": shortform_opportunity,
        "reject_reason": reject_reason,
        "pages_crawled": len(pages),
        "osm_id": candidate.osm_id,
        "osm_type": candidate.osm_type,
        "lat": candidate.lat,
        "lon": candidate.lon,
    }


def dedupe_candidates(candidates: Iterable[Candidate], output: OutputManager) -> List[Candidate]:
    seen: Set[str] = set()
    unique: List[Candidate] = []
    for candidate in candidates:
        key = candidate.key()
        if key in seen:
            output.increment("duplicate_domains_skipped")
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def target_reached(output: OutputManager, target: int) -> bool:
    rows = output.state.get("rows", [])
    qualified_or_maybe = sum(1 for row in rows if row.get("qualified_status") in {"qualified", "maybe"})
    return qualified_or_maybe >= target


def runtime_expired(start_ts: float, max_minutes: Optional[int]) -> bool:
    if not max_minutes:
        return False
    return (time.time() - start_ts) >= max_minutes * 60


def niches_to_run(args: argparse.Namespace) -> List[str]:
    if args.all:
        return list(NICHES)
    if args.niche:
        return [args.niche]
    return ["agencies"]


def discover_for_niche(
    args: argparse.Namespace,
    niche: str,
    output: OutputManager,
    fetcher: Fetcher,
    log: Log,
) -> List[Candidate]:
    cities = load_cities(Path(args.city_file))
    candidates: List[Candidate] = []
    if args.mode in {"overpass", "hybrid"}:
        candidates.extend(discover_overpass(args, niche, cities, output, log))
    if args.mode in {"directories", "hybrid"}:
        candidates.extend(discover_directories(args, niche, output, fetcher, log))
    if args.mode in {"search", "hybrid"}:
        candidates.extend(discover_search(args, niche, output, log))
    if args.mode == "manual":
        candidates.extend(discover_search(args, niche, output, log))
    return dedupe_candidates(candidates, output)


def process_candidates(
    args: argparse.Namespace,
    candidates: Sequence[Candidate],
    output: OutputManager,
    crawler: Crawler,
    log: Log,
    start_ts: float,
) -> None:
    processed = output.processed_keys
    total = len(candidates)
    for index, candidate in enumerate(candidates, start=1):
        if target_reached(output, args.target):
            log.info(f"[TARGET] reached target={args.target}")
            break
        if runtime_expired(start_ts, args.max_runtime_minutes):
            log.info("[STOP] max runtime reached; resume later with --resume")
            break
        key = candidate.key()
        if key in processed:
            continue
        log.info(f"[CRAWL] [{index}/{total}] {candidate.domain or candidate.business_name or candidate.website}")
        if args.dry_run:
            output.mark_processed(key)
            continue
        try:
            pages, crawl_error = crawler.crawl(candidate)
            if crawl_error:
                output.add_crawl_error(f"{candidate.domain or candidate.website}: {crawl_error}")
            row = row_from_candidate(candidate, pages, crawl_error, args)
        except Exception as exc:
            message = f"{candidate.domain or candidate.website}: {exc}"
            log.error(f"[CRAWL_ERROR] {message}")
            output.add_crawl_error(message)
            row = row_from_candidate(candidate, [], "crawler exception", args)
        output.mark_processed(key)
        output.add_row(row)
        processed = output.processed_keys


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--mode", choices=MODES, default="hybrid")
    parser.add_argument("--niche", choices=NICHES)
    parser.add_argument("--all", action="store_true", help="Run all niches")
    parser.add_argument("--cities", default="", help='Comma-separated city names, e.g. "Miami,Houston"')
    parser.add_argument("--target", type=int, default=100)
    parser.add_argument("--max-runtime-minutes", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--max-pages-per-domain", type=int, default=8)
    parser.add_argument("--min-score", type=int, default=6)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--city-file", default="cities.json")
    parser.add_argument("--bbox", default="", help="Manual city bbox as south,west,north,east when a city is missing")
    parser.add_argument("--connector-file", default="connectors.json")
    parser.add_argument("--query-file", default="queries.json")
    parser.add_argument("--cache-dir", default=".cache")
    parser.add_argument("--output", default="leads.csv")
    parser.add_argument("--overpass-timeout", type=int, default=25)
    parser.add_argument("--max-queries-per-provider", type=int, default=25)
    parser.add_argument("--manual-url", action="append", help="Manual fallback URL; repeatable")
    parser.add_argument("--manual-file", default="", help="Manual fallback file with one URL per line")
    args = parser.parse_args(argv)
    if args.all:
        args.niche = args.niche or "all"
    elif not args.niche:
        parser.error("--niche is required unless --all is used")
    if args.target < 1:
        parser.error("--target must be positive")
    if args.delay < 0:
        parser.error("--delay cannot be negative")
    args.cache_dir = str(Path(args.cache_dir))
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    cache_dir = Path(args.cache_dir)
    output_path = Path(args.output)
    temp_log = Log(verbose=args.verbose)
    output = OutputManager(output_path=output_path, cache_dir=cache_dir, args=args, log=temp_log)
    log = Log(verbose=args.verbose, errors_path=output.errors_path)
    output.log = log
    output.load_or_reset(args.resume)
    start_ts = time.time()
    log.info(
        f"[START] mode={args.mode} niche={args.niche or 'all'} target={args.target}"
    )
    fetcher = Fetcher(delay=args.delay, log=log)
    crawler = Crawler(args=args, output=output, fetcher=fetcher, log=log)

    try:
        for niche in niches_to_run(args):
            if runtime_expired(start_ts, args.max_runtime_minutes):
                break
            log.info(f"[NICHE] {niche}")
            niche_args = args
            niche_args.niche = niche
            candidates = discover_for_niche(niche_args, niche, output, fetcher, log)
            log.info(f"[DISCOVERED] {len(candidates)} unique candidates for niche={niche}")
            process_candidates(niche_args, candidates, output, crawler, log, start_ts)
            if target_reached(output, args.target):
                break
    finally:
        output.write_report(finished=True)

    log.info(
        "[DONE] wrote leads_qualified.csv, leads_maybe.csv, leads_rejected.csv, "
        "run_report.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
