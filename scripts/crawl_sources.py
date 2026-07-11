#!/usr/bin/env python3
"""
AIDC + 氟树脂材料 多源信息采集器
=====================================
协调 agent-reach / RSS / B站 / V2EX / Jina Reader 等多个信源的并行采集，
输出去重后的结构化数据到 knowledge_base/archive/YYYY-MM-DD/raw_crawl.json

用法:
  python scripts/crawl_sources.py --date 2026-07-05
  python scripts/crawl_sources.py --date 2026-07-05 --dry-run   # 只打印不执行
  python scripts/crawl_sources.py --date 2026-07-05 --sources exa,rss  # 只跑指定信源

依赖:
  - agent-reach (Exa, Jina, Bilibili, V2EX, RSS)
  - feedparser (pip install feedparser)
  - pyyaml (pip install pyyaml)
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# --- 项目路径 ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
KB_DIR = PROJECT_ROOT / "knowledge_base"
LOGS_DIR = PROJECT_ROOT / "logs"

# --- 可选依赖 ---
try:
    import yaml
except ImportError:
    print("[WARN] pyyaml not installed. Install: pip install pyyaml")
    yaml = None

try:
    import feedparser as fp_module
except ImportError:
    print("[WARN] feedparser not installed. RSS feeds disabled. Install: pip install feedparser")
    fp_module = None

try:
    import requests as req_module
except ImportError:
    req_module = None

# ── 社交媒体采集函数 (从 crawl_ci 共享) ──
try:
    from crawl_ci import (
        crawl_reddit, crawl_zhihu, crawl_weibo, crawl_twitter, crawl_wechat,
    )
except ImportError:
    # 导入失败时提供空实现，避免桌面版崩溃
    def _empty_source(config: dict) -> list:
        return []
    crawl_reddit = _empty_source
    crawl_zhihu = _empty_source
    crawl_weibo = _empty_source
    crawl_twitter = _empty_source
    crawl_wechat = _empty_source


def load_config() -> dict:
    """加载 sources.yaml 配置"""
    sources_path = CONFIG_DIR / "sources.yaml"
    if yaml:
        with open(sources_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    else:
        # 纯 JSON 回退 (如果是 json 格式)
        with open(sources_path, "r", encoding="utf-8") as f:
            import json as _json
            return _json.load(f)


def ensure_date_dir(date_str: str) -> Path:
    """创建并返回 archive/YYYY-MM-DD/ 目录"""
    d = KB_DIR / "archive" / date_str
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_cmd(cmd: str, timeout: int = 60) -> dict:
    """运行 shell 命令并返回 {ok, stdout, stderr, exit_code}"""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=str(PROJECT_ROOT)
        )
        return {"ok": r.returncode == 0, "stdout": r.stdout.strip(), "stderr": r.stderr.strip(), "exit_code": r.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"Timeout after {timeout}s", "exit_code": -1}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e), "exit_code": -1}


def article_hash(url: str, title: str) -> str:
    """生成文章去重用的哈希"""
    raw = f"{url}|{title}".strip().lower()
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ============================================================
# 采集函数 (每个信源一个函数)
# ============================================================

def crawl_exa(config: dict) -> list[dict]:
    """通过 Exa AI 搜索采集"""
    articles = []
    queries = config.get("search_queries", [])
    print(f"  [Exa] Running {len(queries)} search queries...")

    for q in queries:
        query = q["query"]
        n = q.get("num_results", 5)
        category = q.get("category", "unknown")
        lang = q.get("language", "en")
        print(f"    Searching [{lang}][{category}]: {query[:60]}...")

        # agent-reach 方式调用 Exa (通过 mcporter)
        cmd = f'mcporter call \'exa.web_search_exa(query: "{query}", numResults: {n})\''
        result = run_cmd(cmd, timeout=30)

        if result["ok"] and result["stdout"]:
            try:
                data = json.loads(result["stdout"])
                results = data.get("results", []) if isinstance(data, dict) else []
                for item in results:
                    articles.append({
                        "id": article_hash(item.get("url", ""), item.get("title", "")),
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("snippet", "") or item.get("text", ""),
                        "source": "exa_search",
                        "category": category,
                        "language": lang,
                        "publish_date": item.get("publishedDate", ""),
                        "credibility_score": estimate_credibility(item.get("url", ""), config),
                        "raw_source": "exa"
                    })
            except (json.JSONDecodeError, TypeError) as e:
                print(f"      [WARN] Failed to parse Exa result: {e}")
        else:
            print(f"      [WARN] Exa search failed: {result['stderr'][:100]}")

        time.sleep(0.5)  # Rate limiting

    print(f"  [Exa] Collected {len(articles)} articles")
    return articles


def crawl_rss(config: dict) -> list[dict]:
    """通过 RSS/Atom 聚合采集"""
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
        print(f"    Polling: {url[:80]}...")

        try:
            parsed = fp_module.parse(url)
            entries = parsed.entries[:10]  # 每个源最多取10篇
            for entry in entries:
                title = entry.get("title", "")
                link = entry.get("link", "")
                published = entry.get("published", "") or entry.get("updated", "")
                summary = entry.get("summary", "") or entry.get("description", "")

                articles.append({
                    "id": article_hash(link, title),
                    "title": title,
                    "url": link,
                    "snippet": strip_html(summary)[:300],
                    "source": "rss",
                    "source_feed": url,
                    "category": category,
                    "language": feed.get("language", "en"),
                    "publish_date": published,
                    "credibility_score": cred,
                    "raw_source": "rss"
                })
        except Exception as e:
            print(f"      [WARN] RSS poll failed for {url}: {e}")

    print(f"  [RSS] Collected {len(articles)} articles")
    return articles


def crawl_jina_scrape(config: dict) -> list[dict]:
    """通过 Jina Reader 抓取指定网页全文"""
    articles = []
    urls = config.get("daily_scrape_urls", [])
    print(f"  [Jina] Scraping {len(urls)} target URLs...")

    for item in urls:
        url = item["url"]
        label = item.get("label", url)
        cred = item.get("credibility", 4)
        category = item.get("category", "unknown")
        print(f"    Scraping: {label} ({url[:60]}...)")

        # Jina Reader: https://r.jina.ai/<URL>
        jina_url = f"https://r.jina.ai/{url}"
        cmd = f'curl -s -L --max-time 30 "{jina_url}" -H "Accept: text/markdown"'
        result = run_cmd(cmd, timeout=35)

        if result["ok"] and len(result["stdout"]) > 50:
            content = result["stdout"]
            title = extract_title_md(content) or label
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
                "publish_date": datetime.now().strftime("%Y-%m-%d"),
                "credibility_score": cred,
                "raw_source": "jina"
            })
        else:
            print(f"      [WARN] Jina scrape failed for {url}: {result['stderr'][:100]}")

    print(f"  [Jina] Collected {len(articles)} pages")
    return articles


def crawl_bilibili(config: dict) -> list[dict]:
    """通过 bili-cli 搜索 B站"""
    articles = []
    queries = config.get("bilibili_queries", [])
    print(f"  [Bilibili] Running {len(queries)} search queries...")

    for q_item in queries:
        query = q_item["query"]
        print(f"    Searching: {query[:60]}...")

        cmd = f'bili search "{query}" --type video -n 5'
        result = run_cmd(cmd, timeout=20)

        if result["ok"] and result["stdout"]:
            # bili-cli 输出为表格格式，简单解析
            lines = result["stdout"].strip().split("\n")
            for line in lines[1:]:  # 跳过标题行
                parts = line.split("\t")
                if len(parts) >= 2:
                    title = parts[0].strip()
                    url = parts[1].strip() if len(parts) > 1 else ""
                    articles.append({
                        "id": article_hash(url, title),
                        "title": title,
                        "url": url,
                        "snippet": "",
                        "source": "bilibili",
                        "category": "AIDC_development",
                        "language": "zh",
                        "publish_date": "",
                        "credibility_score": 2,  # 用户生成内容
                        "raw_source": "bilibili"
                    })
        else:
            print(f"      [WARN] Bilibili search failed: {result['stderr'][:100]}")

    print(f"  [Bilibili] Collected {len(articles)} articles")
    return articles


def crawl_v2ex(config: dict) -> list[dict]:
    """通过 V2EX API 检查相关节点"""
    articles = []
    # V2EX 节点: ai, programming, hardware, business
    nodes = ["ai", "programming", "hardware", "business"]
    keywords = ["AIDC", "数据中心", "GPU", "铜缆", "氟", "半导体", "芯片", "英伟达", "NVIDIA"]
    print(f"  [V2EX] Checking {len(nodes)} nodes for relevant topics...")

    for node in nodes:
        cmd = f'curl -s "https://www.v2ex.com/api/topics/show.json?node_name={node}" -H "User-Agent: agent-reach/1.0"'
        result = run_cmd(cmd, timeout=15)

        if result["ok"]:
            try:
                topics = json.loads(result["stdout"])
                for topic in topics:
                    title = topic.get("title", "")
                    content = topic.get("content", "")
                    combined = f"{title} {content}".lower()

                    # 关键词过滤
                    if any(kw.lower() in combined for kw in keywords):
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
                            "publish_date": datetime.fromtimestamp(topic.get("created", 0)).strftime("%Y-%m-%d") if topic.get("created") else "",
                            "credibility_score": 2,
                            "raw_source": "v2ex"
                        })
            except json.JSONDecodeError:
                pass

    print(f"  [V2EX] Collected {len(articles)} relevant threads")
    return articles


# ============================================================
# 辅助函数
# ============================================================

def estimate_credibility(url: str, config: dict) -> int:
    """基于域名+来源配置估算可信度"""
    domain = extract_domain(url)
    scores = config.get("credibility_scores", {})
    # 精确匹配
    if domain in scores:
        return scores[domain]
    # 子域名匹配
    for key, score in scores.items():
        if domain.endswith(f".{key}"):
            return score
    # 默认: 未知来源 = 2
    return 2


def extract_domain(url: str) -> str:
    """从 URL 提取域名"""
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return url


def extract_title_md(markdown_text: str) -> str | None:
    """从 Markdown 内容提取标题"""
    for line in markdown_text.split("\n"):
        line = line.strip()
        if line.startswith("# ") and len(line) > 3:
            return line[2:].strip()
        if line and not line.startswith("!") and not line.startswith("["):
            return line[:150]
    return None


def strip_html(text: str) -> str:
    """去除 HTML 标签"""
    import re
    return re.sub(r"<[^>]+>", "", text)


def deduplicate_articles(articles: list[dict]) -> list[dict]:
    """按 id/URL/标题相似度去重"""
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    unique: list[dict] = []

    for a in articles:
        aid = a.get("id", "")
        url = a.get("url", "").strip().lower()

        if aid in seen_ids or url in seen_urls:
            continue

        seen_ids.add(aid)
        if url:
            seen_urls.add(url)
        unique.append(a)

    print(f"  [Dedup] {len(articles)} → {len(unique)} ({len(articles) - len(unique)} duplicates removed)")
    return unique


# ============================================================
# 主入口
# ============================================================

def crawl_all(config: dict, date_str: str, sources: list[str] | None = None, dry_run: bool = False) -> dict:
    """执行全部采集流程

    Args:
        config: sources.yaml 配置
        date_str: 日期字符串 YYYY-MM-DD
        sources: 指定信源列表 (如 ["exa", "rss"])，None=全部
        dry_run: 只打印不执行

    Returns:
        crawl_result dict
    """
    all_sources = {
        "exa": (crawl_exa, True),       # (func, is_critical)
        "rss": (crawl_rss, True),
        "jina": (crawl_jina_scrape, False),
        "bilibili": (crawl_bilibili, False),
        "v2ex": (crawl_v2ex, False),
        # ── 社交媒体扩展 (从 crawl_ci 导入) ──
        "reddit": (crawl_reddit, False),
        "zhihu": (crawl_zhihu, False),
        "weibo": (crawl_weibo, False),
        "twitter": (crawl_twitter, False),
        "wechat": (crawl_wechat, False),
    }

    if sources:
        all_sources = {k: v for k, v in all_sources.items() if k in sources}

    stats = {}
    all_articles: list[dict] = []
    errors: list[str] = []

    for name, (func, critical) in all_sources.items():
        print(f"\n--- {name.upper()} ---")
        if dry_run:
            print(f"  [DRY-RUN] Would execute {func.__name__}()")
            stats[name] = {"status": "skipped", "count": 0}
            continue

        try:
            articles = func(config)
            all_articles.extend(articles)
            stats[name] = {"status": "ok", "count": len(articles)}
        except Exception as e:
            msg = f"{name}: {e}"
            print(f"  [FAIL] {msg}")
            traceback.print_exc()
            errors.append(msg)
            stats[name] = {"status": "failed", "error": str(e)}
            if critical:
                print(f"  [WARN] Critical source {name} failed, continuing with partial data")

    # 去重
    print("\n--- DEDUP ---")
    unique = deduplicate_articles(all_articles)

    # 按可信度排序 (高分在前)
    unique.sort(key=lambda a: a.get("credibility_score", 0), reverse=True)

    result = {
        "crawl_metadata": {
            "date": date_str,
            "crawled_at": datetime.now().isoformat(),
            "total_raw": len(all_articles),
            "total_unique": len(unique),
            "sources_used": [k for k, v in stats.items() if v["status"] == "ok"],
            "sources_failed": [k for k, v in stats.items() if v["status"] == "failed"],
            "source_stats": stats,
            "errors": errors
        },
        "articles": unique
    }

    return result


def main():
    parser = argparse.ArgumentParser(description="AIDC+Fluororesin Multi-Source Crawler")
    parser.add_argument("--date", required=True, help="Target date (YYYY-MM-DD)")
    parser.add_argument("--sources", help="Comma-separated source names (exa,rss,jina,bilibili,v2ex)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no actual crawl")
    parser.add_argument("--output", help="Custom output path (default: archive/<date>/raw_crawl.json)")
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"AIDC+Fluororesin Multi-Source Crawler")
    print(f"Date: {args.date} | {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print(f"{'='*60}")

    config = load_config()
    sources = args.sources.split(",") if args.sources else None

    result = crawl_all(config, args.date, sources=sources, dry_run=args.dry_run)

    if args.dry_run:
        print("\n[DRY-RUN] Complete. No data written.")
        return

    # 保存结果
    date_dir = ensure_date_dir(args.date)
    output_path = args.output or str(date_dir / "raw_crawl.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 写入日志
    log_path = LOGS_DIR / f"crawl_{args.date}.log"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"Crawl completed: {args.date}\n")
        f.write(f"Sources: {result['crawl_metadata']['sources_used']}\n")
        f.write(f"Raw: {result['crawl_metadata']['total_raw']}, Unique: {result['crawl_metadata']['total_unique']}\n")
        if result['crawl_metadata']['errors']:
            for e in result['crawl_metadata']['errors']:
                f.write(f"  ERROR: {e}\n")

    print(f"\n{'='*60}")
    print(f"✅ Crawl complete!")
    print(f"   Raw: {result['crawl_metadata']['total_raw']}, Unique: {result['crawl_metadata']['total_unique']}")
    print(f"   Sources OK: {result['crawl_metadata']['sources_used']}")
    print(f"   Sources FAIL: {result['crawl_metadata']['sources_failed']}")
    print(f"   Output: {output_path}")
    print(f"   Log: {log_path}")


if __name__ == "__main__":
    main()
