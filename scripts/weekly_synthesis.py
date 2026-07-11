#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Weekly Synthesis — AI-powered weekly intelligence summary
=========================================================
Gathers the past week's verified articles, groups by topic,
and calls DeepSeek API to produce structured multi-dimensional analysis.

Output: written to knowledge_base.json's weekly_synthesis field
        and website/data/weekly_synthesis.json

Usage:
  python scripts/weekly_synthesis.py              # This week (Mon-Sun)
  python scripts/weekly_synthesis.py --date 2026-07-06  # Week ending date
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KB_DIR = PROJECT_ROOT / "knowledge_base"
ARCHIVE_DIR = KB_DIR / "archive"
KB_PATH = KB_DIR / "knowledge_base.json"

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = "deepseek-chat"

# Fix Windows encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SYNTHESIS_PROMPT_CN = """你是一位资深行业情报分析师。请根据本周收集的文章列表，撰写一份周度情报综合梳理。

要求：
1. **Overview**: 用3-5段话综述本周AIDC+氟树脂材料领域的整体态势。不要逐条罗列，要整合叙述。
2. **Key Developments**: 挑出本周最重要的3-5个进展，每个用一句话概括其重要性。
3. **Trending Topics**: 哪些主题热度明显上升？
4. **Companies to Watch**: 哪些公司本周有值得关注的动作？

输出严格的JSON格式（不要Markdown代码块）：
{
  "overview_cn": "综述段落（多段用\\n\\n分隔）",
  "overview_jp": "日本語の概要（同じく\\n\\n区切り）",
  "key_developments": [{"title_cn": "...", "title_jp": "...", "importance": "high|medium"}],
  "trending_topics": [{"name_cn": "...", "name_jp": "...", "trend": "rising|stable"}],
  "companies_to_watch": [{"name": "...", "reason_cn": "...", "reason_jp": "..."}],
  "risk_alerts": [{"title_cn": "...", "title_jp": "...", "severity": "high|medium|low"}]
}
"""


def gather_week_articles(end_date: str) -> list[dict]:
    """Collect all articles from the 7 days ending on end_date."""
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=6)

    articles = []
    if not ARCHIVE_DIR.exists():
        return articles

    for date_dir in sorted(ARCHIVE_DIR.iterdir()):
        if not date_dir.is_dir():
            continue
        d = date_dir.name
        if d < start_dt.strftime("%Y-%m-%d") or d > end_date:
            continue

        verified_path = date_dir / "verified_articles.json"
        if not verified_path.exists():
            continue

        with open(verified_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for a in data.get("articles", []):
            if a.get("verification_status") == "excluded":
                continue
            a["_date"] = d
            articles.append(a)

    return articles


def build_context(articles: list[dict]) -> str:
    """Build a compact context string for the AI prompt."""
    lines = []
    # Group by topic area (approximate by category)
    by_cat = defaultdict(list)
    for a in articles:
        cat = a.get("category", "other")
        by_cat[cat].append(a)

    for cat, cat_articles in sorted(by_cat.items()):
        lines.append(f"\n## {cat} ({len(cat_articles)} articles)")
        for a in cat_articles[:5]:  # Top 5 per category
            title = a.get("title", "")[:100]
            date = a.get("_date", "")
            snippet = (a.get("snippet", "") or "")[:200]
            lines.append(f"- [{date}] {title}")
            if snippet:
                lines.append(f"  {snippet}")

    return "\n".join(lines)


def call_deepseek(system: str, user: str) -> dict | None:
    """Call DeepSeek API and return parsed JSON response."""
    if not DEEPSEEK_API_KEY:
        print("  [SKIP] DEEPSEEK_API_KEY not set")
        return None

    try:
        import requests
    except ImportError:
        print("  [SKIP] requests library not available")
        return None

    url = f"{DEEPSEEK_BASE_URL}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "max_tokens": 3000,
        "response_format": {"type": "json_object"},
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        result = resp.json()
        content = result["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as e:
        print(f"  [ERROR] DeepSeek API call failed: {e}")
        return None


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Weekly AI synthesis")
    parser.add_argument("--date", default=None, help="Week ending date (YYYY-MM-DD)")
    args = parser.parse_args()

    end_date = args.date or datetime.now().strftime("%Y-%m-%d")
    print(f"Weekly Synthesis — Week ending {end_date}")
    print(f"AI: {'DeepSeek' if DEEPSEEK_API_KEY else 'disabled'}")

    articles = gather_week_articles(end_date)
    print(f"Collected {len(articles)} articles from past 7 days")

    if len(articles) < 3:
        print("  [SKIP] Not enough articles (< 3) for meaningful synthesis")
        return

    context = build_context(articles)
    synthesis = call_deepseek(SYNTHESIS_PROMPT_CN, context)

    if synthesis is None:
        print("  [SKIP] No AI synthesis generated")
        return

    # Add metadata
    synthesis["week_ending"] = end_date
    synthesis["article_count"] = len(articles)
    synthesis["generated_at"] = datetime.now().isoformat()

    # Write to KB
    kb = {}
    if KB_PATH.exists():
        with open(KB_PATH, "r", encoding="utf-8") as f:
            kb = json.load(f)

    kb["weekly_synthesis"] = synthesis

    with open(KB_PATH, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)

    print(f"  [OK] Weekly synthesis written — {len(synthesis.get('key_developments', []))} key developments")


if __name__ == "__main__":
    main()
