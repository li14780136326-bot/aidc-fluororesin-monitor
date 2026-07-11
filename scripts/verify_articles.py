#!/usr/bin/env python3
"""
AIDC + 氟树脂材料 交叉验证引擎
================================
从 raw_crawl.json 读取采集结果，对每篇文章：
1. 评估来源可信度
2. 提取事实声明 (Claude)
3. 跨源交叉比对
4. 分配验证状态: verified / single_source / disputed / unverified

用法:
  python scripts/verify_articles.py --date 2026-07-05
  python scripts/verify_articles.py --date 2026-07-05 --strict  # 严格模式 (单源低可信全排除)
"""

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
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


def load_raw_crawl(date_str: str) -> dict:
    """加载采集结果"""
    path = KB_DIR / "archive" / date_str / "raw_crawl.json"
    if not path.exists():
        sys.exit(f"Error: {path} not found. Run crawl_sources.py first.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_credibility_scores() -> dict:
    """加载来源可信度配置"""
    config_path = PROJECT_ROOT / "config" / "sources.yaml"
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return config.get("credibility_scores", {})
    except Exception:
        return {}


def extract_domain(url: str) -> str:
    """从 URL 提取域名"""
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def score_credibility(url: str, source_type: str, scores: dict) -> int:
    """综合评估单篇文章可信度 (1-5)"""
    domain = extract_domain(url)
    # 精确匹配
    if domain in scores:
        return scores[domain]
    # 子域名匹配
    for key, s in scores.items():
        if domain.endswith(f".{key}"):
            return s
    # 按信源类型默认
    defaults = {
        "exa_search": 3, "rss": 3, "jina_scrape": 4, "bilibili": 2, "v2ex": 2,
        "reddit": 2, "twitter": 2, "rsshub": 3, "wechat_sogou": 4,
        "wechat_rsshub": 3, "wechat": 3,
    }
    return defaults.get(source_type, 2)


def extract_claims_from_article(article: dict) -> list[str]:
    """
    从文章 snippet/full_text 提取事实声明。
    这里用启发式方法提取包含数字、时间、专有名词的句子作为候选声明。
    Claude 可以通过修改此函数来提供更智能的提取。

    在实际 Workflow 中，这里会调用 Claude:
      Skill("claude", "Extract factual claims from: <text>")
    """
    text = article.get("full_text", "") or article.get("snippet", "")
    if not text:
        return []

    # 简单句分割
    sentences = re.split(r"[。！？.!?\n]", text)
    claims = []
    for s in sentences:
        s = s.strip()
        if len(s) < 15:  # 太短
            continue
        # 包含数字 (指标数据) 或专有名词倾向
        has_number = bool(re.search(r"\d+[万亿千百%倍吨亿]", s))
        has_proper = bool(re.search(r"[A-Z]{2,}|[一-鿿]{2,}(公司|集团|股份|技术|平台|发布|宣布)", s))
        if has_number or has_proper:
            claims.append(s[:300])  # 截断
    return claims[:8]  # 每篇最多8条


def normalize_claim(text: str) -> str:
    """标准化声明文本用于比对"""
    # 去空格、统一标点、小写
    t = text.strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[，。．、；：！？「」『』【】（）]", ",", t)
    return t


def claim_similarity(c1: str, c2: str) -> float:
    """简单的 Jaccard 相似度 (词级别)"""
    words1 = set(normalize_claim(c1).split())
    words2 = set(normalize_claim(c2).split())
    if not words1 or not words2:
        return 0.0
    return len(words1 & words2) / len(words1 | words2)


def verify_articles(raw_data: dict, strict: bool = False) -> dict:
    """执行交叉验证

    Args:
        raw_data: crawl_sources.py 的输出
        strict: True=单源且非高可信则拒绝

    Returns:
        验证结果 dict
    """
    articles = raw_data.get("articles", [])
    credibility_scores = load_credibility_scores()
    print(f"Verifying {len(articles)} articles...")

    # Step 1: 评估每篇文章可信度 + 提取声明
    enriched = []
    for a in articles:
        url = a.get("url", "")
        src = a.get("source", "")
        domain = extract_domain(url)
        cred = score_credibility(url, src, credibility_scores)
        # 如果文章本身的 credibility_score 为0，使用计算的
        if a.get("credibility_score", 0) == 0:
            a["credibility_score"] = cred
        a["domain"] = domain
        claims = extract_claims_from_article(a)
        a["extracted_claims"] = claims
        enriched.append(a)
        if claims:
            print(f"  [{domain}] {len(claims)} claims from: {a.get('title', '')[:50]}")

    # Step 2: 建立声明注册表 (归一化声明 → 来源列表)
    claim_registry: dict[str, list[dict]] = defaultdict(list)
    for a in enriched:
        for idx, claim in enumerate(a.get("extracted_claims", [])):
            norm = normalize_claim(claim)
            # 用哈希做近似key
            h = hashlib.sha256(norm.encode()).hexdigest()[:12]
            claim_registry[h].append({
                "article_id": a.get("id", ""),
                "article_title": a.get("title", ""),
                "url": a.get("url", ""),
                "domain": a.get("domain", ""),
                "credibility": a.get("credibility_score", 0),
                "claim_text": claim,
                "claim_idx": idx
            })

    # 合并相似声明 (词级相似度 > 0.5 视为同一声明)
    merged_registry = merge_similar_claims(claim_registry)

    # Step 3: 验证每篇文章
    verified_articles = []
    stats = {"verified": 0, "single_source_high": 0, "disputed": 0, "excluded": 0}

    for a in enriched:
        claims = a.get("extracted_claims", [])
        if not claims:
            # 无声明可验证，按来源可信度决定
            if a.get("credibility_score", 0) >= 4:
                a["verification_status"] = "single_source"
                a["verification_confidence"] = "medium"
                a["verification_note"] = "无明确事实声明，基于来源可信度采纳"
                stats["single_source_high"] += 1
                verified_articles.append(a)
            else:
                a["verification_status"] = "unverified"
                a["verification_confidence"] = "low"
                a["verification_note"] = "无明确事实声明且来源可信度低"
                stats["excluded"] += 1
                if not strict:
                    a["verification_status"] = "single_source"  # 宽松模式仍保留
                    verified_articles.append(a)
            continue

        # 为每条声明查找跨源确认
        corroboration_counts: list[int] = []
        corroboration_sources: list[list[str]] = []
        for idx, claim in enumerate(claims):
            norm = normalize_claim(claim)
            h = hashlib.sha256(norm.encode()).hexdigest()[:12]
            sources_for_claim = merged_registry.get(h, [])
            # 去重域名计数 (不同域名视为独立信源)
            unique_domains = set(s["domain"] for s in sources_for_claim)
            corroboration_counts.append(len(unique_domains))
            corroboration_sources.append(list(unique_domains))

        cred_score = a.get("credibility_score", 0)
        max_corroboration = max(corroboration_counts) if corroboration_counts else 0
        avg_corroboration = sum(corroboration_counts) / len(corroboration_counts) if corroboration_counts else 0

        # 验证规则
        if max_corroboration >= 2:
            a["verification_status"] = "verified"
            a["verification_confidence"] = "high" if avg_corroboration >= 2.5 else "medium"
            a["verification_note"] = f"核心声明有 {max_corroboration} 个独立信源交叉确认"
            stats["verified"] += 1

        elif cred_score >= 4:
            a["verification_status"] = "single_source"
            a["verification_confidence"] = "medium"
            a["verification_note"] = f"单一高可信源 (分数={cred_score})，等待更多确认"
            stats["single_source_high"] += 1

        elif cred_score >= 3 and avg_corroboration >= 1.5:
            a["verification_status"] = "single_source"
            a["verification_confidence"] = "low"
            a["verification_note"] = "中等可信源，部分声明有微弱交叉确认"
            stats["single_source_high"] += 1

        else:
            if strict:
                a["verification_status"] = "excluded"
                a["verification_confidence"] = "low"
                a["verification_note"] = "严格模式：低可信源且无充分交叉确认"
                stats["excluded"] += 1
                continue  # 不加入最终结果
            else:
                a["verification_status"] = "unverified"
                a["verification_confidence"] = "low"
                a["verification_note"] = "低可信源，建议读者自行判断"
                stats["excluded"] += 1

        # 附加交叉确认详情
        a["corroboration"] = {
            "max_unique_sources": max_corroboration,
            "avg_corroboration": round(avg_corroboration, 2),
            "corroborating_domains": list(set(d for subs in corroboration_sources for d in subs))
        }
        verified_articles.append(a)

    # 检测冲突声明
    disputes = detect_disputes(merged_registry, enriched)
    if disputes:
        print(f"\n  ⚠️  Detected {len(disputes)} disputed claims")

    print(f"\n  Verification Summary:")
    print(f"    ✅ Verified (2+ sources):    {stats['verified']}")
    print(f"    🔵 Single source (credible): {stats['single_source_high']}")
    print(f"    ⚠️  Disputed:                 {len(disputes)}")
    print(f"    ❌ Excluded/Unverified:      {stats['excluded']}")

    crawl_meta = raw_data.get("crawl_metadata", {})

    return {
        "verification_metadata": {
            "date": crawl_meta.get("date", ""),
            "verified_at": datetime.now().isoformat(),
            "strict_mode": strict,
            "total_input": len(articles),
            "total_verified": len(verified_articles),
            "stats": stats,
            "disputes": disputes,
            "sources_used": crawl_meta.get("sources_used", []),
            "sources_failed": crawl_meta.get("sources_failed", []),
        },
        "articles": verified_articles
    }


def merge_similar_claims(registry: dict) -> dict:
    """合并相似的声明条目"""
    keys = list(registry.keys())
    merged = dict(registry)
    # 简化处理：检查相似键并合并
    for i, k1 in enumerate(keys):
        for k2 in keys[i+1:]:
            if k1 not in merged or k2 not in merged:
                continue
            # 比较第一对声明的相似度
            c1 = merged[k1][0]["claim_text"] if merged[k1] else ""
            c2 = merged[k2][0]["claim_text"] if merged[k2] else ""
            if claim_similarity(c1, c2) > 0.5:
                merged[k1].extend(merged[k2])
                del merged[k2]
    return merged


def detect_disputes(registry: dict, articles: list[dict]) -> list[dict]:
    """检测冲突声明"""
    disputes = []
    for h, sources in registry.items():
        if len(sources) < 2:
            continue
        # 检查是否有否定/冲突表述
        texts = [s["claim_text"] for s in sources]
        has_negative = any(re.search(r"(不是|不对|错误|虚假|否认|辟谣|debunk|false|incorrect|no\b)", t.lower()) for t in texts)
        if has_negative and len(set(s["domain"] for s in sources)) >= 2:
            disputes.append({
                "claim_hash": h,
                "claim_text": sources[0]["claim_text"][:200],
                "sources": [{"domain": s["domain"], "title": s["article_title"][:80]} for s in sources]
            })
    return disputes


def main():
    parser = argparse.ArgumentParser(description="AIDC+Fluororesin Cross-Verification Engine")
    parser.add_argument("--date", required=True, help="Target date (YYYY-MM-DD)")
    parser.add_argument("--strict", action="store_true", help="Strict mode: exclude all single-source low-credibility")
    parser.add_argument("--input", help="Custom input path (default: archive/<date>/raw_crawl.json)")
    parser.add_argument("--output", help="Custom output path (default: archive/<date>/verified_articles.json)")
    args = parser.parse_args()

    input_path = args.input or str(KB_DIR / "archive" / args.date / "raw_crawl.json")
    output_path = args.output or str(KB_DIR / "archive" / args.date / "verified_articles.json")

    print(f"{'='*60}")
    print(f"AIDC+Fluororesin Cross-Verification Engine")
    print(f"Date: {args.date} | Mode: {'STRICT' if args.strict else 'STANDARD'}")
    print(f"Input: {input_path}")
    print(f"{'='*60}\n")

    raw_data = load_raw_crawl(args.date)
    verified = verify_articles(raw_data, strict=args.strict)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(verified, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Verification complete!")
    print(f"   Input:  {verified['verification_metadata']['total_input']} articles")
    print(f"   Output: {verified['verification_metadata']['total_verified']} articles")
    print(f"   Saved:  {output_path}")


if __name__ == "__main__":
    main()
