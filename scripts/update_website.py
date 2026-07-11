#!/usr/bin/env python3
"""
网站数据更新器
===============
从 knowledge_base 和每日报告更新 website/data/ 下的 JSON 索引文件。

用法:
  python scripts/update_website.py --date 2026-07-05
  python scripts/update_website.py  # 全量重建所有索引
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Fix Windows encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KB_DIR = PROJECT_ROOT / "knowledge_base"
WEBSITE_DIR = PROJECT_ROOT / "website"
DATA_DIR = WEBSITE_DIR / "data"


def load_kb() -> dict:
    path = KB_DIR / "knowledge_base.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"articles": [], "topics": [], "tags_index": {}, "collections": []}


def scan_reports() -> list[str]:
    """扫描 archive 目录获取所有已完成的日期"""
    archive = KB_DIR / "archive"
    if not archive.exists():
        return []
    dates = sorted(
        [d.name for d in archive.iterdir() if d.is_dir() and (d / "verified_articles.json").exists()],
        reverse=True
    )
    return dates


def build_daily_index() -> list[dict]:
    """生成每日报告索引"""
    dates = scan_reports()
    index = []
    for d in dates:
        report_json = KB_DIR / "archive" / d / "report.json"
        if not report_json.exists():
            # 尝试从 website/data/reports/ 加载
            report_json = DATA_DIR / "reports" / f"{d}.json"

        if report_json.exists():
            with open(report_json, "r", encoding="utf-8") as f:
                report = json.load(f)
            index.append({
                "date": d,
                "total_articles": report.get("meta", {}).get("total_crawled", 0),
                "verified_count": report.get("meta", {}).get("verified_count", 0),
                "summary_cn": report.get("summary_cn", ""),
                "summary_jp": report.get("summary_jp", ""),
                "active_sources": report.get("meta", {}).get("active_sources", []),
                "categories": report.get("category_breakdown", {})
            })
        else:
            # 没有 report.json，从 verified_articles 生成简要索引
            verified_path = KB_DIR / "archive" / d / "verified_articles.json"
            if verified_path.exists():
                with open(verified_path, "r", encoding="utf-8") as f:
                    verified = json.load(f)
                index.append({
                    "date": d,
                    "total_articles": verified.get("verification_metadata", {}).get("total_input", 0),
                    "verified_count": verified.get("verification_metadata", {}).get("total_verified", 0),
                    "summary_cn": f"{d} 日报 (待生成)",
                    "summary_jp": f"{d} 日報 (生成待ち)",
                    "active_sources": [],
                    "categories": {}
                })

    return index


def build_knowledge_index() -> dict:
    """生成知识图谱索引（增强版：主题 + 公司 + 时间线）"""
    kb = load_kb()
    topics = kb.get("topics", [])
    articles = kb.get("articles", [])

    # 每个主题的关联文章数 + 最近文章
    topic_data = []
    for t in topics:
        tid = t.get("id", "")
        matched_articles = [a for a in articles if tid in a.get("topicIds", [])]
        # Sort by date (most recent first)
        matched_articles.sort(key=lambda a: a.get("publish_date", ""), reverse=True)
        # Deduplicate recent_titles (same article can appear on multiple dates)
        seen_titles = set()
        unique_titles = []
        for a in matched_articles:
            title = a.get("title", "")[:80]
            if title not in seen_titles:
                seen_titles.add(title)
                unique_titles.append(title)
        topic_data.append({
            "id": tid,
            "name": t.get("name", ""),
            "name_jp": t.get("name_jp", ""),
            "keywords": t.get("keywords", []),
            "article_count": len(matched_articles),
            "last_updated": matched_articles[0]["publish_date"] if matched_articles else "",
            "recent_titles": unique_titles[:3],
        })

    # 标签云 — prefer KB tag_cloud over tags_index
    tag_cloud = kb.get("tag_cloud", [])
    if not tag_cloud:
        tags = kb.get("tags_index", {})
        tag_cloud = sorted(
            [{"tag": k, "count": len(v)} for k, v in tags.items()],
            key=lambda x: x["count"], reverse=True,
        )[:50]

    # 公司数据
    companies = kb.get("company_data", [])

    # 时间线
    timeline = kb.get("all_timeline", [])[:30]
    weekly_synthesis = kb.get("weekly_synthesis")

    result = {
        "topics": topic_data,
        "tag_cloud": tag_cloud,
        "companies": companies,
        "timeline": timeline,
        "total_articles": len(articles),
        "last_updated": datetime.now().isoformat(),
    }
    if weekly_synthesis:
        result["weekly_synthesis"] = weekly_synthesis
    return result


def update_all(date_str: str | None = None):
    """更新所有网站数据文件"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "reports").mkdir(parents=True, exist_ok=True)

    print("Updating website data...")

    # 每日索引
    daily_index = build_daily_index()
    with open(DATA_DIR / "daily_index.json", "w", encoding="utf-8") as f:
        json.dump(daily_index, f, ensure_ascii=False, indent=2)
    print(f"  daily_index.json: {len(daily_index)} days")

    # 知识索引
    knowledge_index = build_knowledge_index()
    with open(DATA_DIR / "knowledge_index.json", "w", encoding="utf-8") as f:
        json.dump(knowledge_index, f, ensure_ascii=False, indent=2)
    print(f"  knowledge_index.json: {len(knowledge_index['topics'])} topics, {knowledge_index['total_articles']} articles")

    # 复制最新报告 (如果指定了日期)
    if date_str:
        report_src = KB_DIR / "archive" / date_str / "report.json"
        if report_src.exists():
            import shutil
            dest = DATA_DIR / "reports" / f"{date_str}.json"
            shutil.copy(report_src, dest)
            print(f"  Copied report: {date_str}.json")

    print("[OK] Website data updated")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Update website data files")
    parser.add_argument("--date", help="Copy specific date's report to website data")
    args = parser.parse_args()
    update_all(args.date)


if __name__ == "__main__":
    main()
