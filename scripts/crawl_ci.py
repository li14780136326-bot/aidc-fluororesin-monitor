#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIDC + Fluororesin Materials — CI-Compatible Multi-Source Crawler
=================================================================
Designed for GitHub Actions and other headless CI environments.
Uses pure Python HTTP (requests + feedparser) — no external CLIs needed.

Sources:
  - RSS feeds (feedparser) — always works
  - Jina Reader (requests → r.jina.ai) — always works
  - V2EX API (requests) — always works
  - Exa search (requests + EXA_API_KEY) — works if API key configured
  - Reddit RSS (feedparser) — always works
  - Zhihu (RSSHub) — always works
  - Weibo (RSSHub) — always works
  - Twitter/X (X API v2 + TWITTER_BEARER_TOKEN) — works if API key configured
  - WeChat Official Accounts (Sogou + RSSHub) — always works
  - Bilibili — skipped in CI (requires bili CLI)

Output: knowledge_base/archive/YYYY-MM-DD/raw_crawl.json
        (same format as crawl_sources.py for pipeline compatibility)

Usage:
  python scripts/crawl_ci.py --date 2026-07-05
  python scripts/crawl_ci.py --date 2026-07-05 --dry-run
  python scripts/crawl_ci.py --date 2026-07-05 --sources rss,jina
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urljoin, urlparse

# Fix Windows encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ── Project paths ──────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
KB_DIR = PROJECT_ROOT / "knowledge_base"
LOGS_DIR = PROJECT_ROOT / "logs"

# ── Optional imports ───────────────────────────────────────
try:
    import yaml
except ImportError:
    print("[WARN] pyyaml not installed. Install: pip install pyyaml")
    yaml = None

try:
    import feedparser as fp_module
except ImportError:
    print("[WARN] feedparser not installed. RSS disabled. Install: pip install feedparser")
    fp_module = None

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    print("[WARN] requests not installed. HTTP sources disabled. Install: pip install requests")
    requests = None  # type: ignore
    REQUESTS_AVAILABLE = False

# ── HTTP session ───────────────────────────────────────────
SESSION = None

def get_session() -> Any:
    global SESSION
    if SESSION is None and REQUESTS_AVAILABLE:
        SESSION = requests.Session()
        SESSION.headers.update({
            "User-Agent": "AIDC-Fluororesin-Monitor/2.0 (+https://github.com/aidc-fluororesin-monitor)",
            "Accept": "application/json, text/html, application/xhtml+xml, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7",
        })
    return SESSION


# ═══════════════════════════════════════════════════════════
# Utility functions
# ═══════════════════════════════════════════════════════════

def load_config() -> dict:
    """Load sources.yaml configuration"""
    sources_path = CONFIG_DIR / "sources.yaml"
    if yaml:
        with open(sources_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    else:
        with open(sources_path, "r", encoding="utf-8") as f:
            return json.load(f)


def ensure_date_dir(date_str: str) -> Path:
    d = KB_DIR / "archive" / date_str
    d.mkdir(parents=True, exist_ok=True)
    return d


def article_hash(url: str, title: str) -> str:
    raw = f"{url}|{title}".strip().lower()
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


# ── Image extraction from feed entries / Jina markdown ──

def _extract_images_from_entry(entry) -> list[dict]:
    """Extract image URLs from a feedparser entry.
    Returns list of {url, alt, type} dicts."""
    images = []
    seen_urls = set()

    # media_content (RSS 2.0 standard)
    for mc in entry.get("media_content", []):
        url = mc.get("url", "")
        mtype = mc.get("type", "")
        if url and url not in seen_urls and ("image" in mtype or "photo" in mtype or not mtype):
            images.append({"url": url, "alt": mc.get("alt", "") or "", "type": "image"})
            seen_urls.add(url)

    # media_thumbnail
    for mt in entry.get("media_thumbnail", []):
        url = mt.get("url", "")
        if url and url not in seen_urls:
            images.append({"url": url, "alt": mt.get("alt", "") or "", "type": "thumbnail"})
            seen_urls.add(url)

    # enclosure (RSS podcast/media standard, also used for images)
    enc = entry.get("enclosure", {}) if isinstance(entry.get("enclosure"), dict) else entry.get("enclosures", [{}])[0] if entry.get("enclosures") else {}
    if isinstance(enc, dict):
        url = enc.get("url") or enc.get("href", "")
        mtype = enc.get("type", "")
        if url and url not in seen_urls and ("image" in mtype or "photo" in mtype):
            images.append({"url": url, "alt": "", "type": "image"})
            seen_urls.add(url)

    # links with image types
    for link in entry.get("links", []):
        if link.get("rel") == "enclosure" and "image" in link.get("type", ""):
            url = link.get("href", "")
            if url and url not in seen_urls:
                images.append({"url": url, "alt": "", "type": "image"})
                seen_urls.add(url)

    return images


def _extract_images_from_markdown(md_text: str) -> list[dict]:
    """Extract image URLs from markdown text (Jina output).
    Only keeps images that look like product photos, charts, or architecture diagrams.
    Filters out icons, logos, tracking pixels, avatars."""
    images = []
    seen_urls = set()

    # Match ![alt](url) patterns
    pattern = re.compile(r'!\[([^\]]*)\]\s*\(([^)]+)\)', re.IGNORECASE)
    for m in pattern.finditer(md_text):
        alt = m.group(1).strip()
        url = m.group(2).strip()

        # Skip tiny/icon/avatar images
        skip_signals = ["icon", "avatar", "logo", "pixel", "tracking", "badge",
                        "1x1", "spacer", "button", "arrow", "social", "share",
                        "favicon", "flag", "svg", "emoji"]
        if any(s in alt.lower() or s in url.lower() for s in skip_signals):
            continue

        if url and url not in seen_urls:
            # Classify image type based on alt text
            img_type = "other"
            if any(k in alt.lower() for k in ["chart", "graph", "数据", "グラフ", "表", "trend"]):
                img_type = "chart"
            elif any(k in alt.lower() for k in ["product", "产品", "製品", "photo", "设备"]):
                img_type = "product"
            elif any(k in alt.lower() for k in ["architecture", "架构", "diagram", "结构", "design", "block"]):
                img_type = "architecture"

            images.append({"url": url, "alt": alt[:120], "type": img_type})
            seen_urls.add(url)

    return images


def estimate_credibility(url: str, config: dict) -> int:
    domain = extract_domain(url)
    scores = config.get("credibility_scores", {})
    if domain in scores:
        return scores[domain]
    for key, score in scores.items():
        if domain.endswith(f".{key}"):
            return score
    return 2


def http_get(url: str, timeout: int = 30, headers: Optional[dict] = None) -> Optional[Any]:
    """HTTP GET with error handling. Returns requests.Response or None."""
    sess = get_session()
    if sess is None:
        return None
    try:
        hdrs = dict(sess.headers)
        if headers:
            hdrs.update(headers)
        return sess.get(url, timeout=timeout, headers=hdrs)
    except Exception as e:
        print(f"      [HTTP] {url[:60]}... → {e}")
        return None


def http_get_json(url: str, timeout: int = 30) -> Optional[dict]:
    resp = http_get(url, timeout=timeout)
    if resp is None:
        return None
    try:
        return resp.json()
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# Source: RSS Feeds
# ═══════════════════════════════════════════════════════════

def crawl_rss(config: dict) -> list[dict]:
    if fp_module is None:
        print("  [RSS] feedparser not available, skipping")
        return []

    articles = []
    feeds = config.get("rss_feeds", [])
    print(f"  [RSS] Polling {len(feeds)} feeds...")

    for feed in feeds:
        url = feed["url"]
        category = feed.get("category", "unknown")
        cred = feed.get("credibility", 3)
        lang = feed.get("language", "en")
        print(f"    Polling: {url[:80]}...")

        try:
            parsed = fp_module.parse(url)
            entries = parsed.entries[:10]
            for entry in entries:
                title = entry.get("title", "")
                link = entry.get("link", "")
                published = entry.get("published", "") or entry.get("updated", "")
                summary = entry.get("summary", "") or entry.get("description", "")

                if not link:
                    continue

                images = _extract_images_from_entry(entry)
                articles.append({
                    "id": article_hash(link, title),
                    "title": title,
                    "url": link,
                    "snippet": strip_html(summary)[:300],
                    "source": "rss",
                    "source_feed": url,
                    "category": category,
                    "language": lang,
                    "publish_date": published,
                    "credibility_score": cred,
                    "raw_source": "rss",
                    "domain": extract_domain(link),
                    "images": images,
                })
        except Exception as e:
            print(f"      [WARN] RSS failed {url[:60]}: {e}")

    print(f"  [RSS] Collected {len(articles)} articles")
    return articles


# ═══════════════════════════════════════════════════════════
# Content quality validation (prevents dead pages from becoming "intel")
# ═══════════════════════════════════════════════════════════

# Patterns that indicate a page is dead, a cookie wall, or otherwise useless
_DEAD_PAGE_SIGNALS = [
    # HTTP errors
    "404 not found", "page not found", "the page you were looking for doesn't exist",
    "page not found", "sorry, we can't find", "sorry, the page",
    # Access/cookie walls that block content
    "please enable cookies", "please enable javascript",
    "before you continue to the website", "verify you are a human",
    # Empty shells
    "your choices regarding cookies", "we value your privacy",
    # Redirect loops or access denied
    "access denied", "403 forbidden", "request blocked",
    # Purely navigational pages
    "you are being redirected",
    # Additional dead-page signals
    "page unavailable", "temporarily down", "under maintenance",
    "service unavailable", "bad gateway", "502",
    "javascript is required", "enable javascript in your browser",
    "this site requires javascript",
]

# Jina Reader response status markers (Jina sometimes prefixes with Status)
_JINA_STATUS_ERRORS = ["status: 404", "status: 403", "status: 500",
                        "status: 502", "status: 503", "status: 301",
                        "status: 302"]

# Content that consists mostly of these is not real page content
_BOILERPLATE_PATTERNS = [
    "cookie", "privacy", "terms of use", "accessibility statement",
    "all rights reserved", "copyright ©", "sign in", "log in",
    "subscribe", "newsletter", "cookie policy", "privacy policy",
    "manage cookie", "cookie settings", "cookie preferences",
    "please accept cookies", "this website uses cookies",
]

def _is_valid_jina_content(content: str, url: str, label: str) -> tuple[bool, str]:
    """Check if Jina-scraped content is real page content or a dead/blocked page.
    Returns (is_valid, reason)."""
    if not content or len(content.strip()) < 80:
        return False, "empty or too short (<80 chars)"

    content_lower = content.lower()

    # ── Check 1: Jina HTTP status markers (e.g. "Status: 404") ──
    content_head = content_lower[:200]
    for status_err in _JINA_STATUS_ERRORS:
        if status_err in content_head:
            return False, f"Jina returned HTTP error: \"{status_err}\""
    # Also check if entire body starts with an HTTP status
    stripped = content_lower.strip()
    for status_err in _JINA_STATUS_ERRORS:
        if stripped.startswith(status_err):
            return False, f"Jina returned HTTP error: \"{status_err}\""

    # ── Check 2: Dead-page signal words ──
    for signal in _DEAD_PAGE_SIGNALS:
        if signal in content_lower:
            # If the signal is in the first 500 chars, it's likely the main content
            head = content_lower[:500]
            if signal in head:
                return False, f"dead page signal in header: \"{signal}\""
            # If the whole document is short and contains the signal, it's dead
            if len(content) < 800:
                return False, f"dead page signal + short body: \"{signal}\""

    # ── Check 3: Count boilerplate vs real content ──
    lines = [l.strip() for l in content.split("\n") if l.strip()]
    meaningful_lines = [
        l for l in lines
        if len(l) > 30 and not any(bp in l.lower() for bp in _BOILERPLATE_PATTERNS)
    ]
    # If fewer than 3 meaningful lines, the page has no real content
    if len(meaningful_lines) < 3:
        return False, f"only {len(meaningful_lines)} meaningful line(s) — cookie wall or navigation shell"

    return True, ""


# ═══════════════════════════════════════════════════════════
# Source: Jina Reader (webpage → markdown extraction)
# ═══════════════════════════════════════════════════════════

def crawl_jina(config: dict) -> list[dict]:
    if not REQUESTS_AVAILABLE:
        print("  [Jina] requests not available, skipping")
        return []

    articles = []
    skipped = 0
    urls = config.get("daily_scrape_urls", [])
    print(f"  [Jina] Scraping {len(urls)} target URLs...")

    for item in urls:
        url = item["url"]
        label = item.get("label", url)
        cred = item.get("credibility", 4)
        category = item.get("category", "unknown")
        print(f"    Scraping: {label}")

        jina_url = f"https://r.jina.ai/{url}"
        resp = http_get(jina_url, timeout=35, headers={"Accept": "text/markdown"})
        if resp is None or not resp.text or len(resp.text) < 50:
            print(f"      [SKIP] Jina returned empty/minimal response")
            skipped += 1
            continue

        content = resp.text

        # ── Content quality gate ──
        is_valid, reason = _is_valid_jina_content(content, url, label)
        if not is_valid:
            print(f"      [SKIP] Quality check failed: {reason}")
            skipped += 1
            continue

        title = ""
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("Title:") or (line.startswith("# ") and len(line) > 3):
                title = line.replace("Title:", "").replace("#", "").strip()
                break
        if not title:
            title = label

        articles.append({
            "id": article_hash(url, title),
            "title": title,
            "url": url,
            "snippet": content[:500],
            "full_text": content,
            "source": "jina_scrape",
            "source_label": label,
            "category": category,
            "language": "auto",
            "publish_date": "",  # Jina snaps current page state — no specific publish date
            "credibility_score": cred,
            "raw_source": "jina",
            "domain": extract_domain(url),
            "images": _extract_images_from_markdown(content),
        })

    print(f"  [Jina] Collected {len(articles)} pages, skipped {skipped} (quality gate)")
    return articles


# ═══════════════════════════════════════════════════════════
# Source: V2EX Community
# ═══════════════════════════════════════════════════════════

def crawl_v2ex(config: dict) -> list[dict]:
    if not REQUESTS_AVAILABLE:
        print("  [V2EX] requests not available, skipping")
        return []

    articles = []
    nodes = ["ai", "programming", "hardware", "business"]
    keywords = [
        "AIDC", "数据中心", "GPU", "铜缆", "铜连接", "氟", "半导体",
        "芯片", "英伟达", "NVIDIA", "PCB", "液冷", "光模块", "CPO",
        "サーバ", "ケーブル", "データセンター"
    ]
    print(f"  [V2EX] Checking {len(nodes)} nodes...")

    for node in nodes:
        data = http_get_json(
            f"https://www.v2ex.com/api/topics/show.json?node_name={node}",
            timeout=15
        )
        if data is None:
            continue

        for topic in data:
            if not isinstance(topic, dict):
                continue
            title = topic.get("title", "")
            content = topic.get("content", "")
            combined = f"{title} {content}".lower()
            if not any(kw.lower() in combined for kw in keywords):
                continue

            tid = topic.get("id", "")
            url = f"https://www.v2ex.com/t/{tid}"
            articles.append({
                "id": article_hash(url, title),
                "title": title,
                "url": url,
                "snippet": content[:300],
                "source": "v2ex",
                "source_node": node,
                "category": "community_discussion",
                "language": "zh",
                "publish_date": datetime.fromtimestamp(
                    topic.get("created", 0)
                ).strftime("%Y-%m-%d") if topic.get("created") else "",
                "credibility_score": 2,
                "raw_source": "v2ex",
                "domain": "v2ex.com",
            })

    print(f"  [V2EX] Collected {len(articles)} relevant threads")
    return articles


# ═══════════════════════════════════════════════════════════
# Source: Exa AI Search (requires EXA_API_KEY)
# ═══════════════════════════════════════════════════════════

def crawl_exa(config: dict) -> list[dict]:
    api_key = os.environ.get("EXA_API_KEY", "")
    if not api_key:
        print("  [Exa] EXA_API_KEY not set, skipping Exa search")
        print("  [Exa] Set repository secret EXA_API_KEY to enable")
        return []

    articles = []
    queries = config.get("search_queries", [])
    print(f"  [Exa] Running {len(queries)} queries via Exa API...")

    for q in queries:
        query = q["query"]
        n = q.get("num_results", 5)
        category = q.get("category", "unknown")
        lang = q.get("language", "en")
        print(f"    [{lang}][{category}]: {query[:60]}...")

        resp = http_get_json(
            "https://api.exa.ai/search",
            timeout=30,
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
            },
        ) if REQUESTS_AVAILABLE else None

        if resp is None:
            # Exa API uses POST
            sess = get_session()
            if sess is None:
                continue
            try:
                r = sess.post(
                    "https://api.exa.ai/search",
                    json={"query": query, "numResults": n, "useAutoprompt": True},
                    headers={"x-api-key": api_key},
                    timeout=30,
                )
                data = r.json()
                results = data.get("results", [])
            except Exception as e:
                print(f"      [WARN] Exa API error: {e}")
                continue
        else:
            results = resp.get("results", [])

        for item in results:
            url = item.get("url", "")
            title = item.get("title", "")
            articles.append({
                "id": article_hash(url, title),
                "title": title,
                "url": url,
                "snippet": item.get("snippet", "") or item.get("text", ""),
                "source": "exa_search",
                "category": category,
                "language": lang,
                "publish_date": item.get("publishedDate", ""),
                "credibility_score": estimate_credibility(url, config),
                "raw_source": "exa",
                "domain": extract_domain(url),
            })

        time.sleep(0.3)

    print(f"  [Exa] Collected {len(articles)} articles")
    return articles


# ═══════════════════════════════════════════════════════════
# Source: Reddit RSS (7 subreddits, keyword-filtered)
# ═══════════════════════════════════════════════════════════

def crawl_reddit(config: dict) -> list[dict]:
    """Collect Reddit posts via native RSS feeds (no auth needed)."""
    if fp_module is None:
        print("  [Reddit] feedparser not available, skipping")
        return []

    subs = config.get("reddit_subreddits", [])
    keywords = [kw.lower() for kw in config.get("reddit_keywords", [])]
    # Titles to skip (stickies, rules, meta posts)
    skip_titles = ["reminder", "please do not", "rules", "weekly discussion",
                   "megathread", "simple questions", "meta:", "announcement"]
    now_ts = datetime.now(timezone.utc)
    articles = []
    print(f"  [Reddit] Polling {len(subs)} subreddits...")

    for sub in subs:
        url = f"https://www.reddit.com/r/{sub['subreddit']}/.rss"
        category = sub.get("category", "unknown")
        cred = sub.get("credibility", 2)
        lang = sub.get("language", "en")
        print(f"    r/{sub['subreddit']} ...")

        try:
            # Use feedparser with browser UA to avoid Reddit 403
            parsed = fp_module.parse(
                url,
                agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/125.0.0.0 Safari/537.36",
            )
            status = getattr(parsed, "status", 0)
            if status not in (200, 301, 302) and not parsed.entries:
                print(f"      [WARN] HTTP {status}, {len(getattr(parsed, 'entries', []))} entries")
                continue
            entries = parsed.entries[:15]
            kept = 0
            for entry in entries:
                title = entry.get("title", "")
                link = entry.get("link", "")

                # Skip stickies and meta posts
                if any(sk in title.lower() for sk in skip_titles):
                    continue

                # Check publish date: skip posts older than 7 days
                published_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
                if published_parsed:
                    try:
                        from time import mktime
                        post_dt = datetime.fromtimestamp(mktime(published_parsed), tz=timezone.utc)
                        if (now_ts - post_dt).days > 7:
                            continue
                    except Exception:
                        pass  # Can't parse date, include anyway

                summary = entry.get("summary", "") or entry.get("description", "")
                combined = f"{title} {summary}".lower()

                if not any(kw in combined for kw in keywords):
                    continue

                articles.append({
                    "id": article_hash(link, title),
                    "title": title,
                    "url": link,
                    "snippet": strip_html(summary)[:300],
                    "source": "reddit",
                    "source_feed": f"r/{sub['subreddit']}",
                    "category": category,
                    "language": lang,
                    "publish_date": entry.get("published", "") or entry.get("updated", ""),
                    "credibility_score": cred,
                    "raw_source": "reddit",
                    "domain": extract_domain(link),
                    "images": _extract_images_from_entry(entry),
                })
                kept += 1
            print(f"      {len(entries)} posts, {kept} matched keywords")
        except Exception as e:
            print(f"      [WARN] Reddit RSS failed r/{sub['subreddit']}: {e}")
        time.sleep(2.0)  # Avoid Reddit rate limiting (429)

    print(f"  [Reddit] Collected {len(articles)} relevant posts")
    return articles


# ═══════════════════════════════════════════════════════════
# RSSHub helper: fetch route with instance fallback
# ═══════════════════════════════════════════════════════════

def _fetch_rsshub_route(config: dict, route: str) -> list[dict]:
    """Try to fetch an RSSHub route from configured instances.
    Returns list of parsed feed entries (raw, not article dicts)."""
    if fp_module is None:
        return []

    rsshub_cfg = config.get("rsshub", {})
    instances = rsshub_cfg.get("instances", ["https://rsshub.app"])
    delay = rsshub_cfg.get("request_delay", 2.0)

    for instance in instances:
        url = f"{instance}{route}"
        try:
            parsed = fp_module.parse(url)
            if parsed.entries and not parsed.get("bozo", 0):
                return list(parsed.entries)
            elif parsed.entries:
                # bozo_exception but we have entries — use them
                return list(parsed.entries)
        except Exception:
            continue
        time.sleep(0.5)

    return []


def _rsshub_entries_to_articles(entries: list[dict], route_cfg: dict) -> list[dict]:
    """Convert RSSHub feed entries to standard article dicts."""
    articles = []
    for entry in entries[:8]:
        title = entry.get("title", "")
        link = entry.get("link", "")
        summary = entry.get("summary", "") or entry.get("description", "")
        published = entry.get("published", "") or entry.get("updated", "")

        if not link:
            continue

        articles.append({
            "id": article_hash(link, title),
            "title": title,
            "url": link,
            "snippet": strip_html(summary)[:300],
            "source": "rsshub",
            "source_label": route_cfg.get("label", ""),
            "category": route_cfg.get("category", "unknown"),
            "language": route_cfg.get("language", "zh"),
            "publish_date": published,
            "credibility_score": route_cfg.get("credibility", 2),
            "raw_source": "rsshub",
            "domain": extract_domain(link),
        })
    return articles


# ═══════════════════════════════════════════════════════════
# Source: Zhihu via RSSHub
# ═══════════════════════════════════════════════════════════

def crawl_zhihu(config: dict) -> list[dict]:
    """Collect Zhihu articles via direct API + RSSHub fallback."""
    zhihu_cfg = config.get("zhihu", {})
    if not zhihu_cfg.get("enabled", True):
        print("  [Zhihu] Disabled in config, skipping")
        return []
    if not REQUESTS_AVAILABLE:
        print("  [Zhihu] requests not available, skipping")
        return []

    routes = zhihu_cfg.get("routes", [])
    articles = []
    print(f"  [Zhihu] Fetching {len(routes)} routes...")

    # Phase 1: Try direct Zhihu search API
    for route_cfg in routes:
        route = route_cfg["route"]
        label = route_cfg.get("label", route)
        category = route_cfg.get("category", "unknown")
        cred = route_cfg.get("credibility", 2)
        lang = route_cfg.get("language", "zh")

        # Extract keyword from route: /zhihu/search/{keyword}
        keyword = route.replace("/zhihu/search/", "").replace("/zhihu/topic/", "")
        print(f"    {label} (keyword: {keyword})")

        # Try direct Zhihu search API
        sess = get_session()
        try:
            search_url = (
                f"https://www.zhihu.com/api/v4/search_v3"
                f"?q={quote(keyword)}&type=content&correction=1&limit=10"
            )
            resp = sess.get(search_url, timeout=20, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/125.0.0.0 Safari/537.36",
                "Referer": "https://www.zhihu.com/search?type=content&q=" + quote(keyword),
            })
            if resp.status_code == 200:
                data = resp.json()
                results = []
                # Extract from different response formats
                if isinstance(data, dict):
                    results = data.get("data", data.get("list", []))
                for item in results[:8]:
                    obj = item.get("object", item) if isinstance(item, dict) else {}
                    title = obj.get("title", obj.get("excerpt", ""))
                    url = obj.get("url", obj.get("id", ""))
                    if url and not url.startswith("http"):
                        url = f"https://www.zhihu.com/question/{url}" if url.isdigit() else f"https://zhuanlan.zhihu.com/p/{url}"
                    snippet = obj.get("excerpt", "") or obj.get("content", "")
                    if title and url:
                        articles.append({
                            "id": article_hash(url, str(title)[:50]),
                            "title": str(title)[:120],
                            "url": url,
                            "snippet": str(snippet)[:300],
                            "source": "zhihu",
                            "source_label": label,
                            "category": category,
                            "language": lang,
                            "publish_date": obj.get("created_time", obj.get("updated_time", "")),
                            "credibility_score": cred,
                            "raw_source": "zhihu",
                            "domain": extract_domain(url),
                        })
                if results:
                    print(f"      {len(results)} results via API")
                    time.sleep(1)
                    continue
        except Exception as e:
            print(f"      [WARN] Zhihu API: {e}")

        # Phase 2: Fallback to RSSHub
        entries = _fetch_rsshub_route(config, route)
        if entries:
            arts = _rsshub_entries_to_articles(entries, route_cfg)
            articles.extend(arts)
            print(f"      {len(arts)} articles via RSSHub fallback")
        else:
            print(f"      [WARN] No entries (both API and RSSHub failed)")

    print(f"  [Zhihu] Collected {len(articles)} articles")
    return articles


# ═══════════════════════════════════════════════════════════
# Source: Weibo via RSSHub
# ═══════════════════════════════════════════════════════════

def crawl_weibo(config: dict) -> list[dict]:
    """Collect Weibo posts via RSSHub routes."""
    weibo_cfg = config.get("weibo", {})
    if not weibo_cfg.get("enabled", True):
        print("  [Weibo] Disabled in config, skipping")
        return []

    routes = weibo_cfg.get("routes", [])
    articles = []
    print(f"  [Weibo] Fetching {len(routes)} routes via RSSHub...")

    for route_cfg in routes:
        route = route_cfg["route"]
        label = route_cfg.get("label", route)
        print(f"    {label}")
        entries = _fetch_rsshub_route(config, route)
        if entries:
            arts = _rsshub_entries_to_articles(entries, route_cfg)
            articles.extend(arts)
            print(f"      {len(arts)} posts")
        else:
            print(f"      [WARN] No entries")

    print(f"  [Weibo] Collected {len(articles)} posts")
    return articles


# ═══════════════════════════════════════════════════════════
# Source: Twitter/X via X API v2 (free tier)
# ═══════════════════════════════════════════════════════════

def crawl_twitter(config: dict) -> list[dict]:
    """Collect tweets via X API v2 (requires TWITTER_BEARER_TOKEN)."""
    token = os.environ.get("TWITTER_BEARER_TOKEN", "")
    if not token:
        print("  [Twitter] TWITTER_BEARER_TOKEN not set, skipping")
        print("  [Twitter] Set repository secret TWITTER_BEARER_TOKEN to enable")
        return []
    if not REQUESTS_AVAILABLE:
        print("  [Twitter] requests not available, skipping")
        return []

    tw_cfg = config.get("twitter", {})
    if not tw_cfg.get("enabled", True):
        print("  [Twitter] Disabled in config, skipping")
        return []

    articles = []
    auth_headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "AIDC-Fluororesin-Monitor/2.0",
    }
    sess = get_session()

    # ── Phase 1: Account timelines ──
    accounts = tw_cfg.get("accounts_to_monitor", [])
    max_accts = tw_cfg.get("max_accounts_per_run", 8)
    max_tweets = tw_cfg.get("max_tweets_per_account", 5)

    # Rotate accounts: use hash of date to pick which 8 accounts to check today
    import hashlib as _hl
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    seed = int(_hl.md5(today.encode()).hexdigest()[:8], 16)
    selected = accounts if len(accounts) <= max_accts else [
        accounts[i % len(accounts)] for i in range(seed, seed + max_accts)
    ]

    print(f"  [Twitter] Checking {len(selected)}/{len(accounts)} accounts...")
    for account in selected:
        username = account["username"]
        category = account.get("category", "company_news")
        cred = account.get("credibility", 4)
        print(f"    @{username} ...")

        try:
            # Get user ID
            uid_resp = sess.get(
                f"https://api.twitter.com/2/users/by/username/{username}",
                headers=auth_headers, timeout=15,
            )
            if uid_resp.status_code != 200:
                print(f"      [WARN] User lookup failed (HTTP {uid_resp.status_code})")
                continue
            user_data = uid_resp.json().get("data", {})
            user_id = user_data.get("id", "")
            if not user_id:
                continue

            # Get recent tweets
            tweets_resp = sess.get(
                f"https://api.twitter.com/2/users/{user_id}/tweets"
                f"?max_results={max_tweets}"
                "&tweet.fields=created_at,public_metrics"
                "&exclude=retweets,replies",
                headers=auth_headers, timeout=15,
            )
            if tweets_resp.status_code == 429:
                print(f"      [WARN] Rate limited, stopping account polling")
                break
            if tweets_resp.status_code != 200:
                continue

            for tweet in tweets_resp.json().get("data", []) or []:
                text = tweet.get("text", "")
                tid = tweet.get("id", "")
                url = f"https://x.com/{username}/status/{tid}"
                articles.append({
                    "id": article_hash(url, text[:50]),
                    "title": text[:120],
                    "url": url,
                    "snippet": text[:300],
                    "source": "twitter",
                    "source_label": f"@{username}",
                    "category": category,
                    "language": "en",
                    "publish_date": tweet.get("created_at", ""),
                    "credibility_score": cred,
                    "raw_source": "twitter",
                    "domain": "x.com",
                })
            time.sleep(1)

        except Exception as e:
            print(f"      [WARN] @{username}: {e}")

    # ── Phase 2: Search queries ──
    max_search = tw_cfg.get("max_tweets_per_search", 10)
    for sq in tw_cfg.get("search_queries", [])[:3]:  # Max 3 searches/day
        query = sq["query"]
        category = sq.get("category", "unknown")
        print(f"    Search: {query[:60]}...")

        try:
            search_resp = sess.get(
                "https://api.twitter.com/2/tweets/search/recent",
                params={
                    "query": query,
                    "max_results": max_search,
                    "tweet.fields": "created_at",
                },
                headers=auth_headers, timeout=15,
            )
            if search_resp.status_code == 429:
                print(f"      [WARN] Search rate limited")
                break
            if search_resp.status_code != 200:
                continue

            for tweet in search_resp.json().get("data", []) or []:
                text = tweet.get("text", "")
                tid = tweet.get("id", "")
                url = f"https://x.com/i/status/{tid}"
                articles.append({
                    "id": article_hash(url, text[:50]),
                    "title": text[:120],
                    "url": url,
                    "snippet": text[:300],
                    "source": "twitter",
                    "source_label": f"search: {query[:40]}",
                    "category": category,
                    "language": "en",
                    "publish_date": tweet.get("created_at", ""),
                    "credibility_score": 2,
                    "raw_source": "twitter",
                    "domain": "x.com",
                })
            time.sleep(2)
        except Exception as e:
            print(f"      [WARN] Search '{query[:40]}': {e}")

    print(f"  [Twitter] Collected {len(articles)} tweets")
    return articles


# ═══════════════════════════════════════════════════════════
# Source: WeChat Official Accounts (Sogou + RSSHub fallback)
# ═══════════════════════════════════════════════════════════

def _parse_sogou_html(html: str) -> list[dict]:
    """Parse Sogou WeChat search results HTML. Returns list of {title, url, snippet, date}."""
    results = []

    # Try BeautifulSoup first
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for item in soup.select("ul.news-list li"):
            title_el = item.select_one(".txt-box h3 a")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            sogou_url = title_el.get("href", "")

            snippet_el = item.select_one(".txt-box .txt-info")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            source_el = item.select_one(".txt-box .s-p")
            source = source_el.get_text(strip=True) if source_el else ""

            # Date: extract from script tag (timeConvert(1664345307))
            date_str = ""
            for scr in item.select("script"):
                txt = scr.get_text()
                import re as _re
                ts_match = _re.search(r"timeConvert\('(\d+)'\)", txt)
                if ts_match:
                    from datetime import datetime as _dt
                    ts = int(ts_match.group(1))
                    date_str = _dt.fromtimestamp(ts).strftime("%Y-%m-%d")
                    break

            if title and sogou_url:
                results.append({
                    "title": title,
                    "url": sogou_url,  # Sogou redirect link
                    "snippet": snippet,
                    "date": date_str,
                    "source_account": source,
                })
        if results:
            return results
    except ImportError:
        pass

    # Fallback: regex parsing for bare requests
    import re as _re
    # Parse news-list items
    item_pattern = _re.compile(
        r'<li[^>]*id="sogou_vr_[^"]*"[^>]*>(.*?)</li>',
        _re.DOTALL,
    )
    for match in item_pattern.finditer(html):
        block = match.group(1)
        # Title and link from h3 > a
        title_m = _re.search(r'<h3[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, _re.DOTALL)
        if not title_m:
            continue
        sogou_url = title_m.group(1)
        title = _re.sub(r"<[^>]+>", "", title_m.group(2)).strip()
        # Snippet
        snippet_m = _re.search(r'<p[^>]*class="[^"]*txt-info[^"]*"[^>]*>(.*?)</p>', block, _re.DOTALL)
        snippet = _re.sub(r"<[^>]+>", "", snippet_m.group(1)).strip() if snippet_m else ""
        # Date from timeConvert
        ts_m = _re.search(r"timeConvert\('(\d+)'\)", block)
        date_str = ""
        if ts_m:
            from datetime import datetime as _dt
            date_str = _dt.fromtimestamp(int(ts_m.group(1))).strftime("%Y-%m-%d")

        if title and sogou_url:
            results.append({
                "title": title, "url": sogou_url, "snippet": snippet, "date": date_str,
                "source_account": "",
            })

    return results


def _crawl_wechat_sogou(wechat_config: dict) -> list[dict]:
    """Search WeChat articles via Sogou (weixin.sogou.com)."""
    if not REQUESTS_AVAILABLE:
        return []

    articles = []
    search_terms = wechat_config.get("search_terms", [])
    delay = wechat_config.get("sogou_request_delay", 2.5)
    max_results = wechat_config.get("max_results_per_search", 5)
    sess = get_session()

    sogou_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://weixin.sogou.com/",
    }

    # 30-day cutoff for article freshness
    now_ts = datetime.now(timezone.utc)
    cutoff_date = now_ts - timedelta(days=90)  # 90 days for niche topics

    for st in search_terms:
        keyword = st["keyword"]
        category = st.get("category", "unknown")
        cred = st.get("credibility", 4)
        lang = st.get("language", "zh")
        print(f"    Sogou search: {keyword[:50]}...")

        # tsn=1 for time-sorted (newest first), type=2 for WeChat
        url = f"https://weixin.sogou.com/weixin?type=2&query={quote(keyword)}&ie=utf8"
        try:
            resp = sess.get(url, headers=sogou_headers, timeout=20)
            if resp.status_code == 200 and len(resp.text) > 500:
                results = _parse_sogou_html(resp.text)
                count = 0
                for r in results[:max_results]:
                    # Filter by date (skip very old articles)
                    article_date = r.get("date", "")
                    if article_date:
                        try:
                            from datetime import datetime as _dt
                            ad = _dt.strptime(article_date, "%Y-%m-%d")
                            ad_aware = ad.replace(tzinfo=timezone.utc)
                            if ad_aware < cutoff_date:
                                continue  # Too old
                        except ValueError:
                            pass  # Can't parse date, include anyway

                    # Construct full Sogou redirect URL
                    sogou_url = r["url"]
                    if sogou_url.startswith("/link?"):
                        sogou_url = f"https://weixin.sogou.com{sogou_url}"

                    articles.append({
                        "id": article_hash(sogou_url, r["title"]),
                        "title": r["title"],
                        "url": sogou_url,
                        "snippet": r["snippet"][:300],
                        "source": "wechat_sogou",
                        "source_label": f"Sogou: {keyword[:30]}",
                        "source_account": r.get("source_account", ""),
                        "category": category,
                        "language": lang,
                        "publish_date": article_date,
                        "credibility_score": cred,
                        "raw_source": "wechat",
                        "domain": "mp.weixin.qq.com",
                    })
                    count += 1
                if count > 0:
                    print(f"      {count} recent articles")
            elif resp.status_code == 302 or resp.status_code == 403:
                print(f"      [WARN] Sogou blocked (HTTP {resp.status_code})")
                break  # If blocked once, likely blocked for all
            else:
                print(f"      [WARN] Sogou returned HTTP {resp.status_code}, {len(resp.text)} bytes")
        except Exception as e:
            print(f"      [WARN] Sogou request failed: {e}")

        time.sleep(delay)

    return articles


def _crawl_wechat_rsshub(config: dict) -> list[dict]:
    """Fallback: fetch WeChat articles via RSSHub routes."""
    wechat_cfg = config.get("wechat", {})
    search_terms = wechat_cfg.get("search_terms", [])
    articles = []

    for st in search_terms[:3]:  # Limit RSSHub attempts
        keyword = st["keyword"]
        category = st.get("category", "unknown")
        cred = st.get("credibility", 4)
        lang = st.get("language", "zh")
        # RSSHub WeChat route: /wechat/mp/search/{keyword}
        route = f"/wechat/mp/search/{quote(keyword)}"
        entries = _fetch_rsshub_route(config, route)
        if entries:
            for entry in entries[:5]:
                title = entry.get("title", "")
                link = entry.get("link", "")
                summary = entry.get("summary", "") or entry.get("description", "")
                if not link:
                    continue
                articles.append({
                    "id": article_hash(link, title),
                    "title": title,
                    "url": link,
                    "snippet": strip_html(summary)[:300],
                    "source": "wechat_rsshub",
                    "source_label": f"RSSHub: {keyword[:30]}",
                    "category": category,
                    "language": lang,
                    "publish_date": entry.get("published", ""),
                    "credibility_score": cred,
                    "raw_source": "wechat",
                    "domain": extract_domain(link),
                })
        time.sleep(1)

    return articles


def crawl_wechat(config: dict) -> list[dict]:
    """Collect WeChat Official Account articles via Sogou + RSSHub fallback."""
    wechat_cfg = config.get("wechat", {})
    if not wechat_cfg.get("enabled", True):
        print("  [WeChat] Disabled in config, skipping")
        return []

    articles: list[dict] = []

    # Phase 1: Sogou search
    if wechat_cfg.get("sogou_search_enabled", True):
        print("  [WeChat] Phase 1: Sogou WeChat Search...")
        sogou_arts = _crawl_wechat_sogou(wechat_cfg)
        articles.extend(sogou_arts)
        print(f"  [WeChat] Sogou: {len(sogou_arts)} articles")
    else:
        print("  [WeChat] Sogou search disabled in config")

    # Phase 2: RSSHub fallback (if Sogou got nothing)
    if len(articles) == 0 and wechat_cfg.get("rsshub_fallback_enabled", True):
        print("  [WeChat] Phase 2: RSSHub fallback...")
        rsshub_arts = _crawl_wechat_rsshub(config)
        articles.extend(rsshub_arts)
        print(f"  [WeChat] RSSHub: {len(rsshub_arts)} articles")

    if len(articles) == 0:
        print("  [WeChat] WARNING: Both Sogou and RSSHub failed — "
              "WeChat source produced 0 articles")

    print(f"  [WeChat] Collected {len(articles)} articles")
    return articles


# ═══════════════════════════════════════════════════════════
# Date filtering — only keep today's articles
# ═══════════════════════════════════════════════════════════

def parse_article_date(date_val: str) -> Optional[datetime]:
    """Try to parse an article's publish_date into a UTC datetime.
    Returns None if unparseable (article is kept rather than discarded)."""
    if not date_val:
        return None

    if isinstance(date_val, (int, float)):
        try:
            return datetime.fromtimestamp(date_val, tz=timezone.utc)
        except Exception:
            return None

    date_str = str(date_val).strip()

    # ISO format: 2026-07-06T14:00:00+00:00
    try:
        # fromisoformat handles most ISO variants
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        pass

    # Simple date: 2026-07-06
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        pass

    # RFC 2822: Mon, 06 Jul 2026 12:00:00 +0000
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str)
    except Exception:
        pass

    return None  # Can't parse — keep the article


def filter_by_date(articles: list[dict], target_date: str) -> list[dict]:
    """Keep only articles whose publish_date matches the target date (±1 day).
    Articles with unparseable dates are kept (don't discard potentially valuable data)."""
    kept = []
    removed = 0
    target = target_date[:10]  # "2026-07-06"

    for a in articles:
        pd = a.get("publish_date", "")
        parsed = parse_article_date(pd)

        if parsed is None:
            # Unparseable date — for Jina articles with no date, demote to unverified
            # Static product pages should not be treated as "today's news"
            source = a.get("source", "")
            if source in ("jina", "jina_scrape") and not pd:
                a["verification_status"] = "unverified"
                a["credibility_score"] = min(a.get("credibility_score", 3), 2)
            kept.append(a)
            continue

        article_date = parsed.strftime("%Y-%m-%d")

        # Allow target date ±1 day for timezone tolerance
        from datetime import timedelta as _td
        target_dt = datetime.strptime(target, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        min_date = (target_dt - _td(days=1)).strftime("%Y-%m-%d")
        max_date = (target_dt + _td(days=1)).strftime("%Y-%m-%d")

        if min_date <= article_date <= max_date:
            kept.append(a)
        else:
            removed += 1

    if removed > 0:
        print(f"  [DateFilter] Removed {removed} articles outside {target} (±1d)")

    return kept


# ═══════════════════════════════════════════════════════════
# Deduplication
# ═══════════════════════════════════════════════════════════

def deduplicate_articles(articles: list[dict]) -> list[dict]:
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    unique: list[dict] = []

    for a in articles:
        aid = a.get("id", "")
        url = a.get("url", "").strip().lower()
        if aid in seen_ids or (url and url in seen_urls):
            continue
        seen_ids.add(aid)
        if url:
            seen_urls.add(url)
        unique.append(a)

    print(f"  [Dedup] {len(articles)} → {len(unique)} "
          f"({len(articles) - len(unique)} duplicates removed)")
    return unique


# ═══════════════════════════════════════════════════════════
# Main orchestrator
# ═══════════════════════════════════════════════════════════

SOURCES = {
    "rss": (crawl_rss, True),
    "jina": (crawl_jina, False),
    "v2ex": (crawl_v2ex, False),
    "exa": (crawl_exa, False),
    "reddit": (crawl_reddit, False),
    "zhihu": (crawl_zhihu, False),
    "weibo": (crawl_weibo, False),
    "twitter": (crawl_twitter, False),
    "wechat": (crawl_wechat, False),
}


def crawl_all(config: dict, date_str: str,
              sources: Optional[list[str]] = None,
              dry_run: bool = False) -> dict:
    active = dict(SOURCES)
    if sources:
        active = {k: v for k, v in SOURCES.items() if k in sources}

    stats = {}
    all_articles: list[dict] = []
    errors: list[str] = []

    for name, (func, critical) in active.items():
        print(f"\n{'─'*50}\n  [{name.upper()}]\n{'─'*50}")
        if dry_run:
            print(f"  [DRY-RUN] Would execute {func.__name__}()")
            stats[name] = {"status": "skipped", "count": 0}
            continue

        try:
            arts = func(config)
            all_articles.extend(arts)
            stats[name] = {"status": "ok", "count": len(arts)}
        except Exception as e:
            msg = f"{name}: {e}"
            print(f"  [FAIL] {msg}")
            traceback.print_exc()
            errors.append(msg)
            stats[name] = {"status": "failed", "error": str(e)}
            if critical:
                print(f"  [WARN] Critical source {name} failed")

    print(f"\n{'─'*50}\n  [DEDUP]\n{'─'*50}")
    unique = deduplicate_articles(all_articles)

    print(f"\n{'─'*50}\n  [DATE FILTER]\n{'─'*50}")
    unique = filter_by_date(unique, date_str)

    unique.sort(key=lambda a: a.get("credibility_score", 0), reverse=True)

    return {
        "crawl_metadata": {
            "date": date_str,
            "crawled_at": datetime.now(timezone.utc).isoformat(),
            "runner": "crawl_ci",
            "total_raw": len(all_articles),
            "total_unique": len(unique),
            "sources_used": [k for k, v in stats.items() if v["status"] == "ok"],
            "sources_failed": [k for k, v in stats.items() if v["status"] == "failed"],
            "source_stats": stats,
            "errors": errors,
        },
        "articles": unique,
    }


def main():
    parser = argparse.ArgumentParser(description="CI-compatible multi-source crawler")
    parser.add_argument("--date", required=True, help="Target date (YYYY-MM-DD)")
    parser.add_argument("--sources", help="Comma-separated: rss,jina,v2ex,exa,reddit,zhihu,weibo,twitter,wechat")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    print("=" * 60)
    print(" AIDC + Fluororesin — CI Multi-Source Crawler")
    print(f" Date: {args.date} | {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print("=" * 60)

    config = load_config()
    src_list = args.sources.split(",") if args.sources else None
    result = crawl_all(config, args.date, sources=src_list, dry_run=args.dry_run)

    if args.dry_run:
        print("\n[DRY-RUN] Complete. No data written.")
        return

    date_dir = ensure_date_dir(args.date)
    output_path = date_dir / "raw_crawl.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"crawl_ci_{args.date}.log"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"Crawl CI completed: {args.date}\n")
        meta = result["crawl_metadata"]
        f.write(f"Sources OK: {meta['sources_used']}\n")
        f.write(f"Sources FAIL: {meta['sources_failed']}\n")
        f.write(f"Raw: {meta['total_raw']}, Unique: {meta['total_unique']}\n")
        for e in meta["errors"]:
            f.write(f"  ERROR: {e}\n")

    print(f"\n{'='*60}")
    print(f" Crawl complete!")
    print(f"   Raw: {meta['total_raw']}, Unique: {meta['total_unique']}")
    print(f"   Sources OK: {meta['sources_used']}")
    print(f"   Sources FAIL: {meta['sources_failed']}")
    print(f"   Output: {output_path}")


if __name__ == "__main__":
    main()
