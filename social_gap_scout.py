#!/usr/bin/env python3
"""
Social Gap Scout

Finds businesses with public social intent, especially Instagram, but no
functional primary website. Designed as a separate CLI from lead_scout.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse, urlunparse

import requests
from dotenv import load_dotenv

from lead_scout import (
    HistoryStore,
    Log,
    clean_text,
    extract_emails_from_text,
    extract_phone,
    hash_text,
    load_cities,
    markdown_cell,
    normalize_domain,
    normalize_url,
    parse_bbox,
    pick_best_email,
    read_json,
    short_text,
    split_cities,
    stable_slug,
    utc_now,
    write_json,
)


APP_NAME = "North Star Clips Social Gap Scout"
USER_AGENT = (
    "NorthStarClipsSocialGapScout/1.0 "
    "(local research tool; public data only; no login or captcha bypass)"
)

OUTPUT_COLUMNS = [
    "business_name",
    "business_type",
    "qualified_status",
    "rank_score",
    "website",
    "website_status",
    "instagram_url",
    "instagram_verified",
    "instagram_signal",
    "facebook_url",
    "best_contact",
    "phone",
    "email",
    "city_state",
    "address",
    "source_mode",
    "source_provider",
    "source_query",
    "reason",
    "osm_id",
    "osm_type",
    "lat",
    "lon",
    "raw_tags",
]

CLEAN_COLUMNS = [
    "status",
    "score",
    "business",
    "instagram",
    "contact",
    "city_state",
    "website_status",
    "reason",
    "source",
]

SOCIAL_DOMAINS = {
    "instagram.com",
    "facebook.com",
    "fb.com",
    "m.facebook.com",
}

DEFAULT_PROFILES = {
    "roofing": {
        "keywords": ["roof", "roofer", "roofing", "roof repair", "roof replacement", "gutter"],
        "selectors": [
            ('craft=roofer', 'nwr["craft"="roofer"]({bbox});'),
            ('craft=roofing', 'nwr["craft"="roofing"]({bbox});'),
            ('name~roof', 'nwr["name"~"roof|roofer|roofing|gutter",i]({bbox});'),
            ('description~roof', 'nwr["description"~"roof|roofer|roofing|gutter",i]({bbox});'),
        ],
    },
    "plumbing": {
        "keywords": ["plumb", "plumber", "plumbing", "drain", "pipe"],
        "selectors": [
            ('craft=plumber', 'nwr["craft"="plumber"]({bbox});'),
            ('name~plumb', 'nwr["name"~"plumb|plumber|plumbing|drain",i]({bbox});'),
        ],
    },
    "hvac": {
        "keywords": ["hvac", "air conditioning", "heating", "cooling"],
        "selectors": [
            ('craft=hvac', 'nwr["craft"="hvac"]({bbox});'),
            ('name~hvac', 'nwr["name"~"hvac|air conditioning|heating|cooling",i]({bbox});'),
        ],
    },
}


@dataclass
class GapCandidate:
    business_name: str = ""
    business_type: str = ""
    website: str = ""
    instagram_url: str = ""
    facebook_url: str = ""
    phone: str = ""
    email: str = ""
    city_state: str = ""
    address: str = ""
    source_mode: str = "overpass"
    source_provider: str = "overpass"
    source_query: str = ""
    source_tags: Dict[str, Any] = field(default_factory=dict)
    osm_id: str = ""
    osm_type: str = ""
    lat: str = ""
    lon: str = ""

    @property
    def domain(self) -> str:
        return normalize_domain(self.website)

    @property
    def source_email(self) -> str:
        return self.email

    @property
    def niche(self) -> str:
        return self.business_type

    def key(self) -> str:
        if self.instagram_url:
            return f"instagram:{normalize_social_url(self.instagram_url)}"
        if self.facebook_url:
            return f"facebook:{normalize_social_url(self.facebook_url)}"
        if self.business_name and self.city_state:
            return f"name:{stable_slug(self.business_name)}:{stable_slug(self.city_state)}"
        return stable_slug(json.dumps(asdict(self), sort_keys=True))


def run_name(args: argparse.Namespace) -> str:
    if args.run_name:
        return stable_slug(args.run_name)
    stem = Path(args.output).stem or "social_gap"
    if stem != "social_gap":
        return stable_slug(stem)
    cities = split_cities(args.cities or "")
    bits = [args.business_type, "social-gap"]
    if cities:
        bits.append("-".join(stable_slug(city, 24) for city in cities[:3]))
    return stable_slug("_".join(bits))


def city_label(entry: Dict[str, Any]) -> str:
    return f"{entry.get('name', '')}, {entry.get('state', '')}".strip(", ")


def unique_city_names(cities: Dict[str, Dict[str, Any]]) -> List[str]:
    seen: Set[str] = set()
    names: List[str] = []
    for entry in cities.values():
        label = city_label(entry)
        key = label.lower()
        if label and key not in seen:
            seen.add(key)
            names.append(label)
    return names


def keyword_list(args: argparse.Namespace) -> List[str]:
    if args.keywords:
        return [item.strip().lower() for item in args.keywords.split(",") if item.strip()]
    profile = DEFAULT_PROFILES.get(args.business_type.lower(), {})
    defaults = profile.get("keywords", [])
    if defaults:
        return list(defaults)
    raw = args.business_type.lower().replace("_", " ").replace("-", " ")
    return sorted({raw, raw.rstrip("s"), raw + "s"})


def keyword_regex(keywords: Sequence[str]) -> str:
    parts = [re.escape(word.strip()) for word in keywords if word.strip()]
    return "|".join(parts) or re.escape("business")


def text_matches_business(tags: Dict[str, Any], keywords: Sequence[str]) -> bool:
    blob = " ".join(str(value) for value in tags.values()).lower()
    return any(keyword.lower() in blob for keyword in keywords)


def normalize_social_url(value: str) -> str:
    value = clean_text(value)
    if not value:
        return ""
    value = value.strip("@")
    if value.startswith("instagram:"):
        value = value.split(":", 1)[1].strip("@")
    if value.startswith("facebook:"):
        value = value.split(":", 1)[1].strip("@")
    if re.match(r"^[A-Za-z0-9._]{2,64}$", value):
        value = f"https://www.instagram.com/{value}/"
    url = normalize_url(value)
    if not url:
        return ""
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host in {"instagram.com", "facebook.com", "fb.com", "m.facebook.com"}:
        parts = [part for part in parsed.path.split("/") if part]
        if not parts:
            return ""
        if parts[0].lower() in {"p", "reel", "stories", "explore", "accounts"}:
            return ""
        return urlunparse((parsed.scheme, parsed.netloc.lower(), f"/{parts[0]}/", "", "", ""))
    return ""


def social_domain(url: str) -> str:
    return normalize_domain(url)


def is_social_only_website(url: str) -> bool:
    domain = social_domain(url)
    return domain in SOCIAL_DOMAINS or any(domain.endswith("." + item) for item in SOCIAL_DOMAINS)


def extract_socials_from_tags(tags: Dict[str, Any]) -> Tuple[str, str]:
    instagram = ""
    facebook = ""
    for key, value in tags.items():
        key_l = key.lower()
        value_s = str(value)
        if "instagram" in key_l or "instagram.com" in value_s.lower():
            instagram = instagram or normalize_social_url(value_s)
        if "facebook" in key_l or "fb.com" in value_s.lower() or "facebook.com" in value_s.lower():
            facebook = facebook or normalize_social_url(value_s)
    for value in tags.values():
        value_s = str(value)
        if not instagram:
            match = re.search(r"https?://(?:www\.)?instagram\.com/[A-Za-z0-9._]+/?", value_s, flags=re.I)
            if match:
                instagram = normalize_social_url(match.group(0))
        if not facebook:
            match = re.search(r"https?://(?:www\.)?(?:facebook|fb)\.com/[A-Za-z0-9._-]+/?", value_s, flags=re.I)
            if match:
                facebook = normalize_social_url(match.group(0))
    return instagram, facebook


def website_from_tags(tags: Dict[str, Any]) -> str:
    raw = tags.get("website") or tags.get("contact:website") or tags.get("url") or tags.get("contact:url") or ""
    url = normalize_url(str(raw))
    return url


def address_from_tags(tags: Dict[str, Any]) -> str:
    parts = [
        tags.get("addr:housenumber", ""),
        tags.get("addr:street", ""),
        tags.get("addr:city", ""),
        tags.get("addr:state", ""),
        tags.get("addr:postcode", ""),
    ]
    return clean_text(" ".join(str(part) for part in parts if part))


def build_overpass_queries(args: argparse.Namespace, bbox: Tuple[float, float, float, float], keywords: Sequence[str]) -> List[Tuple[str, str]]:
    south, west, north, east = bbox
    bbox_str = f"{south},{west},{north},{east}"
    timeout = args.overpass_timeout
    profile = DEFAULT_PROFILES.get(args.business_type.lower(), {})
    selectors = list(profile.get("selectors", []))
    regex = keyword_regex(keywords)
    if not selectors:
        selectors = [
            ("name~keywords", f'nwr["name"~"{regex}",i]({{bbox}});'),
            ("description~keywords", f'nwr["description"~"{regex}",i]({{bbox}});'),
        ]
    selectors.extend(
        [
            ("instagram-tagged", 'nwr["contact:instagram"]({bbox});nwr["instagram"]({bbox});'),
            ("facebook-tagged", 'nwr["contact:facebook"]({bbox});nwr["facebook"]({bbox});'),
        ]
    )
    queries = []
    for label, selector in selectors:
        selector = selector.format(bbox=bbox_str)
        queries.append((label, f"[out:json][timeout:{timeout}];({selector});out center tags;"))
    return queries


def fetch_overpass(session: requests.Session, endpoint: str, query: str, delay: float, log: Log, retries: int = 3) -> Dict[str, Any]:
    for attempt in range(retries):
        try:
            response = session.post(endpoint, data={"data": query}, timeout=60)
            if response.status_code in {429, 503, 504}:
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


def candidate_from_overpass(element: Dict[str, Any], args: argparse.Namespace, city_entry: Dict[str, Any], label: str) -> GapCandidate:
    tags = element.get("tags", {}) or {}
    instagram, facebook = extract_socials_from_tags(tags)
    email = pick_best_email(extract_emails_from_text(str(tags.get("email") or tags.get("contact:email") or "")), "general")
    phone = clean_text(str(tags.get("phone") or tags.get("contact:phone") or tags.get("contact:mobile") or ""))
    if not phone:
        phone = extract_phone(" ".join(str(value) for value in tags.values()))
    lat = str(element.get("lat") or element.get("center", {}).get("lat") or "")
    lon = str(element.get("lon") or element.get("center", {}).get("lon") or "")
    return GapCandidate(
        business_name=str(tags.get("name", "")),
        business_type=args.business_type,
        website=website_from_tags(tags),
        instagram_url=instagram,
        facebook_url=facebook,
        phone=phone,
        email=email,
        city_state=city_label(city_entry),
        address=address_from_tags(tags),
        source_query=label,
        source_tags=tags,
        osm_id=str(element.get("id", "")),
        osm_type=str(element.get("type", "")),
        lat=lat,
        lon=lon,
    )


class WebsiteChecker:
    def __init__(self, args: argparse.Namespace, log: Log) -> None:
        self.args = args
        self.log = log
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.last_by_domain: Dict[str, float] = {}

    def wait(self, domain: str, delay: Optional[float] = None) -> None:
        if not domain:
            return
        delay = self.args.delay if delay is None else delay
        elapsed = time.time() - self.last_by_domain.get(domain, 0)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self.last_by_domain[domain] = time.time()

    def check_website(self, url: str) -> str:
        if not url:
            return "no_website"
        if is_social_only_website(url):
            return "social_only"
        domain = normalize_domain(url)
        if not domain:
            return "broken"
        self.wait(domain)
        for attempt in range(2):
            try:
                response = self.session.get(url, timeout=self.args.website_timeout, allow_redirects=True)
                final_url = response.url or url
                if is_social_only_website(final_url):
                    return "social_only"
                if response.status_code in {401, 403}:
                    return "exists_blocked"
                if response.status_code >= 500:
                    return "dead"
                if response.status_code >= 400:
                    return "dead"
                text = response.text[:1500].lower()
                if "domain is for sale" in text or "buy this domain" in text or "website coming soon" in text:
                    return "broken"
                return "functional"
            except requests.RequestException:
                if attempt == 0:
                    time.sleep(max(1.0, self.args.delay))
        return "dead"

    def check_social(self, url: str) -> Tuple[str, str]:
        if not url:
            return "", ""
        if not self.args.check_social_pages:
            return "source_url", "account url found from public source; activity not checked"
        domain = normalize_domain(url)
        self.wait(domain, self.args.social_delay)
        try:
            response = self.session.get(url, timeout=self.args.social_timeout, allow_redirects=True)
        except requests.RequestException as exc:
            return "unverified", f"social check failed: {exc}"
        if response.status_code == 404:
            return "not_found", "profile returned 404"
        if response.status_code in {200, 301, 302, 429, 403}:
            return "seen", "public profile endpoint responded; activity not safely parsed"
        return "unverified", f"profile status={response.status_code}"


def qualifies_no_website(status: str) -> bool:
    return status in {"no_website", "dead", "broken", "social_only"}


def score_candidate(candidate: GapCandidate, website_status: str, instagram_verified: str, keywords: Sequence[str]) -> Tuple[int, str, str]:
    has_instagram = bool(candidate.instagram_url)
    has_contact = bool(candidate.email or candidate.phone)
    keyword_match = text_matches_business(candidate.source_tags, keywords)
    if not has_instagram:
        return 0, "rejected", "no instagram account found"
    if not qualifies_no_website(website_status):
        return 0, "rejected", "functional website exists"
    score = 5
    if website_status in {"dead", "broken", "social_only"}:
        score += 1
    if has_contact:
        score += 1
    if candidate.facebook_url:
        score += 1
    if keyword_match:
        score += 1
    if instagram_verified in {"seen", "source_url"}:
        score += 1
    score = min(10, score)
    reason = "instagram present and no functional website"
    return score, "qualified", reason


class SocialGapOutput:
    def __init__(self, args: argparse.Namespace, log: Log) -> None:
        self.args = args
        self.log = log
        self.run_name = run_name(args)
        self.run_id = f"{self.run_name}-{hash_text(utc_now() + self.run_name)}"
        self.output_dir = Path(args.results_dir) / self.run_name
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.output_path = self.output_dir / Path(args.output).name
        self.qualified_path = self.output_dir / "social_gap_qualified.csv"
        self.rejected_path = self.output_dir / "social_gap_rejected.csv"
        self.clean_path = self.output_dir / "social_gap_clean.csv"
        self.brief_path = self.output_dir / "social_gap_brief.md"
        self.report_path = self.output_dir / "run_report.json"
        self.discovered_path = self.output_dir / "discovered_profiles.txt"
        self.errors_path = self.output_dir / "errors.log"
        self.state_path = Path(args.cache_dir) / "social_gap_runs" / f"{self.run_name}.json"
        self.history = HistoryStore(Path(args.history_file), enabled=not args.ignore_history, stale_minutes=args.lock_stale_minutes)
        self.state = self.initial_state()

    def initial_state(self) -> Dict[str, Any]:
        return {
            "started_at": utc_now(),
            "finished_at": "",
            "run_name": self.run_name,
            "run_id": self.run_id,
            "business_type": self.args.business_type,
            "cities": split_cities(self.args.cities or ""),
            "target": self.args.target,
            "results_dir": str(self.output_dir),
            "history_file": str(self.history.path) if self.history.enabled else "",
            "total_queries_run": 0,
            "total_overpass_results_collected": 0,
            "unique_profiles_found": 0,
            "processed_profiles": 0,
            "qualified_count": 0,
            "rejected_count": 0,
            "duplicate_profiles_skipped": 0,
            "history_duplicates_skipped": 0,
            "active_duplicates_skipped": 0,
            "no_instagram_skipped": 0,
            "provider_errors": [],
            "rows": [],
            "processed_keys": [],
            "discovered_keys": [],
        }

    def load_or_reset(self) -> None:
        if self.args.resume and self.state_path.exists():
            self.state = read_json(self.state_path, self.initial_state())
            self.log.info(f"[RESUME] processed={len(self.state.get('processed_keys', []))} rows={len(self.state.get('rows', []))}")
        else:
            self.state = self.initial_state()
            self.discovered_path.write_text("", encoding="utf-8")
            self.errors_path.write_text("", encoding="utf-8")
            self.write_all()

    @property
    def processed_keys(self) -> Set[str]:
        return set(self.state.setdefault("processed_keys", []))

    @property
    def discovered_keys(self) -> Set[str]:
        return set(self.state.setdefault("discovered_keys", []))

    def increment(self, key: str, amount: int = 1) -> None:
        self.state[key] = int(self.state.get(key, 0)) + amount

    def save_state(self) -> None:
        write_json(self.state_path, self.state)

    def history_key(self, candidate: GapCandidate) -> str:
        return candidate.key()

    def mark_discovered(self, candidate: GapCandidate) -> bool:
        key = candidate.key()
        if not key:
            return False
        if self.history.seen(key):
            self.increment("history_duplicates_skipped")
            self.save_state()
            return False
        discovered = self.discovered_keys
        if key in discovered:
            self.increment("duplicate_profiles_skipped")
            self.save_state()
            return False
        discovered.add(key)
        self.state["discovered_keys"] = sorted(discovered)
        self.state["unique_profiles_found"] = len(discovered)
        with self.discovered_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{key}\n")
        self.save_state()
        return True

    def mark_processed(self, key: str) -> None:
        processed = self.processed_keys
        processed.add(key)
        self.state["processed_keys"] = sorted(processed)
        self.state["processed_profiles"] = len(processed)

    def claim(self, candidate: GapCandidate) -> Tuple[str, str]:
        key = self.history_key(candidate)
        if self.history.seen(key):
            self.increment("history_duplicates_skipped")
            self.save_state()
            return key, ""
        token = self.history.claim(key, self.run_id)
        if not token and self.history.enabled:
            self.increment("active_duplicates_skipped")
            self.save_state()
        return key, token

    def release(self, key: str, token: str) -> None:
        self.history.release(key, token)

    def add_row(self, row: Dict[str, Any]) -> None:
        normalized = {column: row.get(column, "") for column in OUTPUT_COLUMNS}
        normalized["rank_score"] = str(normalized.get("rank_score", ""))
        self.state.setdefault("rows", []).append(normalized)
        self.write_all()
        self.log.info(
            f"[RESULT] {normalized['qualified_status']:<9} | score={normalized['rank_score']} | "
            f"Q={self.state.get('qualified_count', 0)} R={self.state.get('rejected_count', 0)} | "
            f"{normalized['reason']}"
        )

    def recount(self) -> None:
        rows = self.state.get("rows", [])
        self.state["qualified_count"] = sum(1 for row in rows if row.get("qualified_status") == "qualified")
        self.state["rejected_count"] = sum(1 for row in rows if row.get("qualified_status") == "rejected")

    def sorted_rows(self) -> List[Dict[str, Any]]:
        return sorted(
            self.state.get("rows", []),
            key=lambda row: (
                0 if row.get("qualified_status") == "qualified" else 1,
                -int(row.get("rank_score") or 0),
                row.get("business_name", ""),
            ),
        )

    def write_csv(self, path: Path, rows: Sequence[Dict[str, Any]]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row.get(column, "") for column in OUTPUT_COLUMNS})

    def clean_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        contact = row.get("email") or row.get("phone") or row.get("best_contact") or ""
        return {
            "status": row.get("qualified_status", ""),
            "score": row.get("rank_score", ""),
            "business": row.get("business_name", ""),
            "instagram": row.get("instagram_url", ""),
            "contact": contact,
            "city_state": row.get("city_state", ""),
            "website_status": row.get("website_status", ""),
            "reason": row.get("reason", ""),
            "source": f"{row.get('source_provider', '')} / {row.get('source_query', '')}".strip(" /"),
        }

    def write_clean_csv(self) -> None:
        with self.clean_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CLEAN_COLUMNS)
            writer.writeheader()
            for row in self.sorted_rows():
                clean = self.clean_row(row)
                writer.writerow({column: clean.get(column, "") for column in CLEAN_COLUMNS})

    def write_brief(self) -> None:
        rows = self.sorted_rows()
        lines = [
            f"# Social Gap Brief: {self.run_name}",
            "",
            f"- Business type: {self.args.business_type}",
            f"- Results folder: `{self.output_dir}`",
            f"- Qualified: {self.state.get('qualified_count', 0)}",
            f"- Rejected: {self.state.get('rejected_count', 0)}",
            f"- History skips: {self.state.get('history_duplicates_skipped', 0)}",
            f"- Active skips: {self.state.get('active_duplicates_skipped', 0)}",
            "",
        ]
        if not rows:
            lines.extend(["No rows yet.", ""])
        else:
            lines.extend(["| Score | Business | Instagram | Contact | City | Website |", "| ---: | --- | --- | --- | --- | --- |"])
            for row in rows[:75]:
                if row.get("qualified_status") != "qualified":
                    continue
                clean = self.clean_row(row)
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            markdown_cell(clean.get("score"), 4),
                            markdown_cell(clean.get("business"), 34),
                            markdown_cell(clean.get("instagram"), 44),
                            markdown_cell(clean.get("contact"), 34),
                            markdown_cell(clean.get("city_state"), 20),
                            markdown_cell(clean.get("website_status"), 18),
                        ]
                    )
                    + " |"
                )
        self.brief_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_report(self, finished: bool = False) -> None:
        if finished:
            self.state["finished_at"] = utc_now()
        self.recount()
        report = {key: value for key, value in self.state.items() if key not in {"rows", "processed_keys", "discovered_keys"}}
        write_json(self.report_path, report)
        self.save_state()

    def write_all(self) -> None:
        self.recount()
        rows = self.sorted_rows()
        self.write_csv(self.output_path, rows)
        self.write_csv(self.qualified_path, [row for row in rows if row.get("qualified_status") == "qualified"])
        self.write_csv(self.rejected_path, [row for row in rows if row.get("qualified_status") == "rejected"])
        self.write_clean_csv()
        self.write_brief()
        self.save_state()


def render_box(log: Log, title: str, items: Sequence[Tuple[str, Any]]) -> None:
    width = 72
    log.info("+" + "-" * width + "+")
    log.info("| " + short_text(title, width - 2).ljust(width - 1) + "|")
    log.info("+" + "-" * width + "+")
    for label, value in items:
        log.info("| " + short_text(f"{label}: {value}", width - 2).ljust(width - 1) + "|")
    log.info("+" + "-" * width + "+")


def discover_overpass(args: argparse.Namespace, output: SocialGapOutput, log: Log) -> List[GapCandidate]:
    cities = load_cities(Path(args.city_file))
    selected = unique_city_names(cities) if args.all_cities else split_cities(args.cities or "")
    if not selected:
        selected = ["Miami", "Dallas", "Houston", "Los Angeles", "Phoenix"]
    keywords = keyword_list(args)
    endpoint = os.getenv("OVERPASS_URL", "").strip() or "https://overpass-api.de/api/interpreter"
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    cache_dir = Path(args.cache_dir) / "social_gap_overpass"
    cache_dir.mkdir(parents=True, exist_ok=True)
    candidates: List[GapCandidate] = []

    for raw_city in selected:
        city_entry = cities.get(raw_city.lower())
        if not city_entry:
            manual_bbox = parse_bbox(args.bbox or "")
            if not manual_bbox:
                output.state.setdefault("provider_errors", []).append(f"Missing city bbox: {raw_city}")
                continue
            city_entry = {"name": raw_city, "state": "", "bbox": {"south": manual_bbox[0], "west": manual_bbox[1], "north": manual_bbox[2], "east": manual_bbox[3]}}
        bbox_obj = city_entry.get("bbox", {})
        bbox = (float(bbox_obj["south"]), float(bbox_obj["west"]), float(bbox_obj["north"]), float(bbox_obj["east"]))
        for label, query in build_overpass_queries(args, bbox, keywords):
            output.increment("total_queries_run")
            log.info(f"[OVERPASS] city={city_entry.get('name')} query={label}")
            if args.dry_run:
                continue
            cache_key = f"{stable_slug(args.business_type)}_{stable_slug(city_label(city_entry))}_{stable_slug(label)}_{hash_text(query)}.json"
            cache_path = cache_dir / cache_key
            if cache_path.exists():
                data = read_json(cache_path, {})
                log.debug(f"[CACHE] overpass {cache_path}")
            else:
                data = fetch_overpass(session, endpoint, query, args.delay, log)
                if data:
                    write_json(cache_path, data)
                time.sleep(args.delay)
            elements = data.get("elements", []) if isinstance(data, dict) else []
            output.increment("total_overpass_results_collected", len(elements))
            log.info(f"[FOUND] {len(elements)} raw POIs")
            for element in elements:
                tags = element.get("tags", {}) or {}
                if not text_matches_business(tags, keywords):
                    continue
                candidate = candidate_from_overpass(element, args, city_entry, label)
                if not candidate.instagram_url and not args.allow_facebook_only:
                    output.increment("no_instagram_skipped")
                    continue
                if not candidate.instagram_url and not candidate.facebook_url:
                    output.increment("no_instagram_skipped")
                    continue
                if output.mark_discovered(candidate):
                    candidates.append(candidate)
            log.info(f"[DISCOVERED] {len(candidates)} social-gap candidates")
    return candidates


def row_from_candidate(candidate: GapCandidate, checker: WebsiteChecker, keywords: Sequence[str]) -> Dict[str, Any]:
    website_status = checker.check_website(candidate.website)
    instagram_verified, instagram_signal = checker.check_social(candidate.instagram_url)
    score, status, reason = score_candidate(candidate, website_status, instagram_verified, keywords)
    best_contact = candidate.email or candidate.phone
    return {
        "business_name": candidate.business_name,
        "business_type": candidate.business_type,
        "qualified_status": status,
        "rank_score": score,
        "website": candidate.website,
        "website_status": website_status,
        "instagram_url": candidate.instagram_url,
        "instagram_verified": instagram_verified,
        "instagram_signal": instagram_signal,
        "facebook_url": candidate.facebook_url,
        "best_contact": best_contact,
        "phone": candidate.phone,
        "email": candidate.email,
        "city_state": candidate.city_state,
        "address": candidate.address,
        "source_mode": candidate.source_mode,
        "source_provider": candidate.source_provider,
        "source_query": candidate.source_query,
        "reason": reason,
        "osm_id": candidate.osm_id,
        "osm_type": candidate.osm_type,
        "lat": candidate.lat,
        "lon": candidate.lon,
        "raw_tags": json.dumps(candidate.source_tags, ensure_ascii=True, sort_keys=True),
    }


def target_reached(output: SocialGapOutput, target: int) -> bool:
    return int(output.state.get("qualified_count", 0)) >= target


def runtime_expired(start_ts: float, max_minutes: Optional[int]) -> bool:
    return bool(max_minutes and (time.time() - start_ts) >= max_minutes * 60)


def process_candidates(args: argparse.Namespace, output: SocialGapOutput, checker: WebsiteChecker, candidates: Sequence[GapCandidate], log: Log, start_ts: float) -> None:
    processed = output.processed_keys
    keywords = keyword_list(args)
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
        history_key, token = output.claim(candidate)
        if output.history.enabled and not token:
            log.info(f"[SKIP] duplicate/active | {history_key}")
            output.mark_processed(key)
            processed = output.processed_keys
            continue
        log.info(
            f"[CHECK] {index:>4}/{len(candidates):<4} | "
            f"Q={output.state.get('qualified_count', 0)} R={output.state.get('rejected_count', 0)} | "
            f"{candidate.business_name or candidate.instagram_url}"
        )
        try:
            if args.dry_run:
                output.mark_processed(key)
            else:
                row = row_from_candidate(candidate, checker, keywords)
                output.mark_processed(key)
                output.add_row(row)
                output.history.mark_processed(history_key, candidate, row, output.run_id)
        finally:
            output.release(history_key, token)
        processed = output.processed_keys


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--business-type", default="roofing", help="Business to find, e.g. roofing, plumbing, hvac")
    parser.add_argument("--keywords", default="", help="Comma-separated matching keywords; defaults are profile-based")
    parser.add_argument("--cities", default="", help='Comma-separated cities, e.g. "Miami,Dallas,Houston"')
    parser.add_argument("--all-cities", action="store_true", help="Run every city in --city-file")
    parser.add_argument("--target", type=int, default=500)
    parser.add_argument("--delay", type=float, default=2.5)
    parser.add_argument("--website-timeout", type=int, default=10)
    parser.add_argument("--max-runtime-minutes", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--allow-facebook-only", action="store_true", help="Allow Facebook-only leads when no Instagram is found")
    parser.add_argument("--check-social-pages", action="store_true", help="Opt-in unauthenticated social URL checks; default avoids Meta requests")
    parser.add_argument("--social-delay", type=float, default=15.0)
    parser.add_argument("--social-timeout", type=int, default=10)
    parser.add_argument("--city-file", default="cities.json")
    parser.add_argument("--bbox", default="")
    parser.add_argument("--cache-dir", default=".cache")
    parser.add_argument("--results-dir", default="runs")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--output", default="social_gap_leads.csv")
    parser.add_argument("--history-file", default=".cache/social_gap_history.jsonl")
    parser.add_argument("--ignore-history", action="store_true")
    parser.add_argument("--lock-stale-minutes", type=int, default=720)
    parser.add_argument("--overpass-timeout", type=int, default=25)
    args = parser.parse_args(argv)
    if args.target < 1:
        parser.error("--target must be positive")
    if args.delay < 0:
        parser.error("--delay cannot be negative")
    if args.social_delay < 0:
        parser.error("--social-delay cannot be negative")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    temp_log = Log(verbose=args.verbose)
    output = SocialGapOutput(args, temp_log)
    log = Log(verbose=args.verbose, errors_path=output.errors_path)
    output.log = log
    output.load_or_reset()
    render_box(
        log,
        APP_NAME,
        [
            ("business", args.business_type),
            ("target", args.target),
            ("results", output.output_dir),
            ("instagram checks", "opt-in" if args.check_social_pages else "source-url only"),
            ("history", output.history.path if output.history.enabled else "disabled"),
        ],
    )
    start_ts = time.time()
    checker = WebsiteChecker(args, log)
    try:
        candidates = discover_overpass(args, output, log)
        log.info(f"[DISCOVERED] {len(candidates)} unique candidates")
        process_candidates(args, output, checker, candidates, log, start_ts)
    finally:
        output.write_report(finished=True)
    render_box(
        log,
        "Social Gap Run Complete",
        [
            ("qualified", output.state.get("qualified_count", 0)),
            ("rejected", output.state.get("rejected_count", 0)),
            ("history skips", output.state.get("history_duplicates_skipped", 0)),
            ("results", output.output_dir),
        ],
    )
    log.info("[DONE] wrote social_gap_qualified.csv, social_gap_clean.csv, social_gap_brief.md, run_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
