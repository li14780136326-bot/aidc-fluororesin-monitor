#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Knowledge Base Updater
======================
Scans archive articles, matches them against topic keywords,
updates knowledge_base.json with cumulative data.

Usage:
  python scripts/update_knowledge_base.py          # Full update
  python scripts/update_knowledge_base.py --dry-run  # Preview only
"""

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Fix Windows encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KB_DIR = PROJECT_ROOT / "knowledge_base"
ARCHIVE_DIR = KB_DIR / "archive"
KB_PATH = KB_DIR / "knowledge_base.json"

# ── Company alias table (for mention detection) ──
COMPANY_ALIASES = {
    "NVIDIA": {"aliases": ["NVIDIA", "nvidia", "Nvidia"], "ticker": "NVDA", "name_jp": "NVIDIA"},
    "Broadcom": {"aliases": ["Broadcom", "broadcom"], "ticker": "AVGO", "name_jp": "Broadcom"},
    "Amphenol": {"aliases": ["Amphenol", "amphenol"], "ticker": "APH", "name_jp": "Amphenol"},
    "TE Connectivity": {"aliases": ["TE Connectivity", "TE connectivity", "te.com"], "ticker": "TEL", "name_jp": "TE Connectivity"},
    "Molex": {"aliases": ["Molex", "molex"], "ticker": "—", "name_jp": "Molex"},
    "Vertiv": {"aliases": ["Vertiv", "vertiv"], "ticker": "VRT", "name_jp": "Vertiv"},
    "Corning": {"aliases": ["Corning", "corning"], "ticker": "GLW", "name_jp": "Corning"},
    "Rogers Corp": {"aliases": ["Rogers", "rogers", "Rogers Corporation", "Rogers Corp"], "ticker": "ROG", "name_jp": "Rogers Corp"},
    "AGC": {"aliases": ["AGC", "agc", "AGC Inc", "AGC株式会社"], "ticker": "5201.T", "name_jp": "AGC"},
    "3M": {"aliases": ["3M", "3m"], "ticker": "MMM", "name_jp": "3M"},
    "Chemours": {"aliases": ["Chemours", "chemours"], "ticker": "CC", "name_jp": "Chemours"},
    "Daikin": {"aliases": ["Daikin", "daikin", "大金"], "ticker": "6367.T", "name_jp": "ダイキン"},
    "永和股份": {"aliases": ["永和股份", "永和"], "ticker": "605020", "name_jp": "永和股份"},
    "东岳集团": {"aliases": ["东岳集团", "东岳"], "ticker": "00189.HK", "name_jp": "東岳集団"},
    "巨化股份": {"aliases": ["巨化股份", "巨化"], "ticker": "600160", "name_jp": "巨化股份"},
    "沃尔核材": {"aliases": ["沃尔核材", "沃尔"], "ticker": "002130", "name_jp": "沃爾核材"},
    "万马股份": {"aliases": ["万马股份", "万马"], "ticker": "002276", "name_jp": "万馬股份"},
    "立讯精密": {"aliases": ["立讯精密", "立讯"], "ticker": "002475", "name_jp": "立訊精密"},
    "Covestro": {"aliases": ["Covestro", "covestro"], "ticker": "1COV.DE", "name_jp": "Covestro"},
    "Kebo": {"aliases": ["Kebo AG", "Kebo"], "ticker": "—", "name_jp": "Kebo AG"},
    "Plastisud": {"aliases": ["Plastisud", "plastisud"], "ticker": "—", "name_jp": "Plastisud Group"},
}


def load_kb() -> dict:
    if KB_PATH.exists():
        with open(KB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"_meta": {"project": "AIDC + 氟树脂材料 信息监测"}, "articles": [],
            "topics": [], "tags_index": {}, "cross_refs": [], "collections": []}


# ── Dead article detection (mirrors crawl_ci.py _is_valid_jina_content) ──
_DEAD_TITLE_SIGNALS = [
    "404", "403", "500", "502", "503",
    "not found", "file not found", "page not found",
    "access denied", "forbidden", "cookie policy",
]
_DEAD_SNIPPET_SIGNALS = [
    "warning: target url returned error",
    "status: 404", "status: 403", "status: 500",
    "## do not sell my personal information",
    "cookie policy",
]


def _is_dead_article(a: dict) -> bool:
    """Filter out 404 pages, cookie walls, ad trackers from knowledge graph."""
    title = (a.get("title", "") or "").lower().strip()
    snippet = (a.get("snippet", "") or "")[:300].lower()
    url = (a.get("url", "") or "").lower()

    # Ad tracking URLs as titles
    if title.startswith("https://") and any(d in title for d in ("adsrvr", "doubleclick", "track/cmf")):
        return True

    # Dead page title signals
    for sig in _DEAD_TITLE_SIGNALS:
        if sig in title:
            return True

    # Dead page snippet signals
    for sig in _DEAD_SNIPPET_SIGNALS:
        if sig in snippet:
            return True

    # Ad tracking domains in URL
    if any(d in url for d in ("adsrvr.org", "doubleclick.net")):
        return True

    return False


def scan_archive_articles() -> list[dict]:
    """Scan all archive directories and collect verified articles."""
    all_articles = []
    if not ARCHIVE_DIR.exists():
        print("  No archive directory found")
        return all_articles

    for date_dir in sorted(ARCHIVE_DIR.iterdir()):
        if not date_dir.is_dir():
            continue
        verified_path = date_dir / "verified_articles.json"
        if not verified_path.exists():
            continue

        with open(verified_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        articles = data.get("articles", [])
        date_str = date_dir.name

        for a in articles:
            if a.get("verification_status") == "excluded":
                continue
            # Skip dead articles (404, cookie walls, ad trackers)
            if _is_dead_article(a):
                continue
            # Skip low-credibility social media posts (< credibility 3)
            if a.get("credibility_score", 0) <= 2 and a.get("source", "") in ("reddit", "bilibili", "v2ex"):
                continue
            a["_date"] = date_str  # Attach date from archive
            all_articles.append(a)

    return all_articles


def match_topics(article: dict, topics: list[dict]) -> list[str]:
    """Match an article against topic keywords using word-boundary matching.
    Short keywords (<=3 chars) use word-boundary regex to avoid false matches.
    Longer keywords use substring match for flexibility."""
    text = (article.get("title", "") + " " + article.get("snippet", "")).lower()
    matched = []
    for topic in topics:
        keywords = topic.get("keywords", [])
        for kw in keywords:
            kw_lower = kw.lower()
            if len(kw_lower) <= 3:
                # Word boundary for short keywords to avoid false matches
                # e.g., "DAC" should NOT match "dashboard"
                if re.search(r'\b' + re.escape(kw_lower) + r'\b', text):
                    matched.append(topic["id"])
                    break
            else:
                if kw_lower in text:
                    matched.append(topic["id"])
                    break
    return matched


def match_companies(article: dict) -> list[str]:
    """Detect company mentions in article title + snippet."""
    text = (article.get("title", "") + " " + article.get("snippet", "")).lower()
    mentioned = []
    for company, info in COMPANY_ALIASES.items():
        for alias in info["aliases"]:
            if alias.lower() in text:
                mentioned.append(company)
                break
    return mentioned


def update_knowledge_base(dry_run: bool = False):
    """Main update function."""
    print("=" * 60)
    print("Knowledge Base Updater")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    print()

    # Load existing
    kb = load_kb()
    # Filter dead articles from existing KB (clean old contamination)
    kb["articles"] = [a for a in kb.get("articles", []) if not _is_dead_article(a)]
    topics = kb.get("topics", [])
    existing_articles = kb.get("articles", [])
    existing_urls = {a.get("url", "") for a in existing_articles}
    tags_index = defaultdict(list, kb.get("tags_index", {}))

    # Scan archive
    print("1. Scanning archive articles...")
    archive_articles = scan_archive_articles()
    print(f"   Found {len(archive_articles)} articles across archive")

    # Filter new articles
    new_articles = [a for a in archive_articles if a.get("url", "") not in existing_urls]
    print(f"   New (not yet in KB): {len(new_articles)}")

    if dry_run:
        print("\n  [DRY RUN] Would add {len(new_articles)} articles to knowledge base")
        # Show topic match preview
        topic_matches = Counter()
        for a in new_articles[:20]:
            for tid in match_topics(a, topics):
                topic_matches[tid] += 1
        if topic_matches:
            print("\n  Topic match preview (first 20 articles):")
            for tid, count in topic_matches.most_common():
                topic_name = next((t["name"] for t in topics if t["id"] == tid), tid)
                print(f"    {topic_name}: {count} hits")
        return

    # Process new articles
    print("\n2. Matching articles to topics...")
    topic_article_counts = Counter()
    company_mentions = defaultdict(list)
    timeline_events = defaultdict(list)
    tag_counter = Counter()

    # Rebuild topic counts and company mentions from ALL articles
    # (not just new ones) to reflect filtered/cleaned state
    all_kb_articles = existing_articles + []
    for a in all_kb_articles:
        article_topics = a.get("topicIds", [])
        article_companies = a.get("companies", [])
        for tid in article_topics:
            topic_article_counts[tid] += 1
        for company in article_companies:
            company_mentions[company].append({
                "date": a.get("publish_date", a.get("_date", "")),
                "title": a.get("title", ""),
                "url": a.get("url", ""),
                "credibility": a.get("credibility_score", 0),
            })

    for a in new_articles:
        article_topics = match_topics(a, topics)
        article_companies = match_companies(a)
        date_str = a.get("_date", "")

        # Build KB article entry
        kb_article = {
            "id": a.get("id", ""),
            "title": a.get("title", ""),
            "url": a.get("url", ""),
            "domain": a.get("domain", ""),
            "publish_date": a.get("publish_date", date_str),
            "snippet": (a.get("snippet", "") or "")[:300],
            "topicIds": article_topics,
            "companies": article_companies,
            "credibility_score": a.get("credibility_score", 0),
            "added_at": datetime.now().isoformat(),
        }

        # Count topics
        for tid in article_topics:
            topic_article_counts[tid] += 1
            # Timeline event
            timeline_events[tid].append({
                "date": date_str,
                "title": a.get("title", ""),
                "url": a.get("url", ""),
                "credibility": a.get("credibility_score", 0),
            })

        # Count companies
        for company in article_companies:
            company_mentions[company].append({
                "date": date_str,
                "title": a.get("title", ""),
                "url": a.get("url", ""),
                "credibility": a.get("credibility_score", 0),
            })

        # Build tag cloud from matched keywords
        for tid in article_topics:
            topic = next((t for t in topics if t["id"] == tid), None)
            if topic:
                for kw in topic.get("keywords", [])[:5]:  # Top 5 keywords per topic
                    if kw.lower() in (a.get("title", "") + " " + a.get("snippet", "")).lower():
                        tag_counter[kw] += 1
                        break

        existing_articles.append(kb_article)

    # Update tags_index
    for tag, count in tag_counter.items():
        if tag not in tags_index:
            tags_index[tag] = []
        # Extend with article IDs that contain this tag
        for a in new_articles:
            if tag.lower() in (a.get("title", "") + " " + a.get("snippet", "")).lower():
                if a.get("id") not in tags_index[tag]:
                    tags_index[tag].append(a.get("id"))

    # Update topic article counts (from ALL articles, not just new)
    print(f"   Topic matches: {dict(topic_article_counts.most_common(10))}")
    for topic in topics:
        tid = topic["id"]
        count = topic_article_counts.get(tid, 0)
        topic["article_count"] = count
        if count > 0:
            print(f"     {topic['name']}: {count} articles")

    # Sort company recent articles (last 5 per company)
    company_data = []
    for company, info in COMPANY_ALIASES.items():
        articles_list = company_mentions.get(company, [])
        if articles_list:
            articles_list.sort(key=lambda x: x["date"], reverse=True)
            company_data.append({
                "name": company,
                "ticker": info["ticker"],
                "name_jp": info["name_jp"],
                "mention_count": len(articles_list),
                "recent_articles": articles_list[:5],
            })

    # Sort timeline per topic (last 10 events)
    topic_timelines = {}
    for tid, events in timeline_events.items():
        events.sort(key=lambda x: x["date"], reverse=True)
        topic_timelines[tid] = events[:10]

    # Global timeline (all articles sorted by date)
    all_timeline = []
    for a in archive_articles:
        all_timeline.append({
            "date": a.get("_date", ""),
            "title": a.get("title", ""),
            "url": a.get("url", ""),
            "topicIds": match_topics(a, topics),
            "credibility": a.get("credibility_score", 0),
        })
    all_timeline.sort(key=lambda x: x["date"], reverse=True)

    # Build tag cloud
    tag_cloud = sorted(
        [{"tag": k, "count": len(v)} for k, v in tags_index.items()],
        key=lambda x: x["count"], reverse=True,
    )[:50]

    # Update KB
    kb["articles"] = existing_articles
    kb["tags_index"] = dict(tags_index)
    kb["company_data"] = sorted(company_data, key=lambda x: x["mention_count"], reverse=True)
    kb["topic_timelines"] = topic_timelines
    kb["all_timeline"] = all_timeline[:50]
    kb["tag_cloud"] = tag_cloud
    kb["_meta"]["updated_at"] = datetime.now().isoformat()
    kb["_meta"]["total_articles"] = len(existing_articles)

    print(f"\n3. Saving knowledge_base.json...")
    print(f"   Total articles: {len(existing_articles)}")
    print(f"   Companies tracked: {len(company_data)}")
    print(f"   Tag cloud: {len(tag_cloud)} tags")
    print(f"   Timeline events: {len(all_timeline)}")

    with open(KB_PATH, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)
    print(f"\n  [OK] Knowledge base updated → {KB_PATH}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Update knowledge base from archive articles")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no file changes")
    args = parser.parse_args()
    update_knowledge_base(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
