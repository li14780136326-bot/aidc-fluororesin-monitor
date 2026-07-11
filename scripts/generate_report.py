#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIDC + Fluororesin Materials — AI-Powered Morning Briefing Generator
=====================================================================
Reads verified_articles.json, sends article summaries to DeepSeek API,
and produces a coherent 800-1500 word intelligence briefing in CN + JP.

Usage:
  python scripts/generate_report.py --date 2026-07-05 --lang all
  python scripts/generate_report.py --date 2026-07-05 --lang cn

Env vars:
  DEEPSEEK_API_KEY  — DeepSeek API key (sk-...)
  DEEPSEEK_BASE_URL — optional, defaults to https://api.deepseek.com
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KB_DIR = PROJECT_ROOT / "knowledge_base"
REPORTS_DIR = PROJECT_ROOT / "reports"
WEBSITE_DATA_DIR = PROJECT_ROOT / "website" / "data" / "reports"

# ── DeepSeek API config ────────────────────────────────────
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = "deepseek-chat"  # DeepSeek-V3

# Category display names (shared between template_briefing and extract_summary)
CATEGORY_NAMES_CN = {
    "copper_interconnect": "铜缆互联",
    "liquid_cooling": "液冷与热管理",
    "pcb_substrate": "高频PCB基板",
    "fluororesin_material": "氟树脂材料",
    "pfas_regulation": "PFAS法规",
    "connector": "高速连接器",
    "optical_communication": "光通讯",
    "company_news": "公司动态",
    "polymer_industry": "塑料行业",
    "datacenter_infrastructure": "数据中心基础设施",
    "community_discussion": "社区讨论",
    "semiconductor_equipment": "半导体设备",
    "other": "其他",
}

CATEGORY_NAMES_JP = {
    "copper_interconnect": "銅ケーブル相互接続",
    "liquid_cooling": "液冷・熱管理",
    "pcb_substrate": "高周波PCB基板",
    "fluororesin_material": "フッ素樹脂材料",
    "pfas_regulation": "PFAS規制",
    "connector": "高速コネクタ",
    "optical_communication": "光通信",
    "company_news": "企業動向",
    "polymer_industry": "プラスチック業界",
    "datacenter_infrastructure": "データセンター基盤",
    "community_discussion": "コミュニティ議論",
    "semiconductor_equipment": "半導体装置",
    "other": "その他",
}

# Fix Windows encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# Data loading
# ═══════════════════════════════════════════════════════════

def load_verified(date_str: str) -> dict:
    path = KB_DIR / "archive" / date_str / "verified_articles.json"
    if not path.exists():
        sys.exit(f"Error: {path} not found. Run verify_articles.py first.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def deduplicate_across_days(articles: list[dict], date_str: str) -> list[dict]:
    """Remove articles whose IDs already appeared in previous days' archives.
    This prevents static product pages from appearing as 'new' every day."""
    seen_ids = set()
    archive_root = KB_DIR / "archive"
    if not archive_root.exists():
        return articles

    for d in sorted(d.name for d in archive_root.iterdir() if d.is_dir()):
        if d >= date_str:
            break
        prev_path = archive_root / d / "verified_articles.json"
        if prev_path.exists():
            try:
                with open(prev_path, "r", encoding="utf-8") as f:
                    prev_data = json.load(f)
                prev_articles = prev_data if isinstance(prev_data, list) else prev_data.get("articles", [])
                for a in prev_articles:
                    if isinstance(a, dict) and a.get("id"):
                        seen_ids.add(a["id"])
            except Exception:
                pass

    if not seen_ids:
        return articles

    deduped = [a for a in articles if a.get("id", "") not in seen_ids]
    removed = len(articles) - len(deduped)
    if removed > 0:
        print(f"  [DEDUP] Removed {removed} duplicate articles already seen in prior days")
    return deduped


# ═══════════════════════════════════════════════════════════
# AI intelligence report via DeepSeek API
# ═══════════════════════════════════════════════════════════

CN_SYSTEM_PROMPT = """你是一位资深的行业情报分析师，专注于 AIDC（AI 数据中心）和氟树脂材料领域。
你的任务是根据当日采集的文章列表，撰写一份专业的每日情报晨报。

**时效性红线（务必遵守）**：
- 只撰写当日（TODAY）发布的新信息。文末会标注今日日期。
- 如果某篇文章的发布日期不是今天，一律跳过，不得引用。
- 不要回顾历史、不要写"近期""此前""一直以来自"等跨时间叙述。
- 如果某领域今日确实没有任何新动态，直接写"今日该领域无重大更新"即可，不要用旧闻填充。
- 读者昨天已经读过昨天的日报，今天不需要重复任何昨天的内容。

**客观性红线（务必遵守）**：
- 不得进行主观臆测和推测。禁止使用任何猜测性措辞。
- 只报告事实：发生了什么事、谁说了什么、数据是多少。不要猜测原因或推导未经验证的结论。

**禁用词和禁用句式（绝对禁止出现在报告中）**：
以下词汇和句式在任何情况下都不得出现，违反即为不合格报告：
- 推测类：暗示、可能意味着、也许、不排除、疑似、或可解读为、或暗示、可能反映、可能影响、或可视为
- 采集故障类：404、页面异常、链接失效、Cookie、仅显示、内容缺失、信息不可见、无法访问、返回错误
- 模糊推测句式："值得警惕的是，这些变化可能……""不排除……的可能性""这一变化可能……"

**反面示例（以下是绝对错误的写法，不要模仿）**：
```
Rogers Corporation 的高频层压板产品页面当前仅显示标题与Logo，核心产品目录与技术参数完全缺失。作为AIDC核心供应商，Rogers的页面异常可能反映产品线更新或合规调整。
3M 的氟聚合物产品页面返回404错误，可能是产品线终止的后续动作。
```
↑ 上面这种写法是错误的！页面访问失败就是采集问题，不能当作情报来分析。报告404等于把采集故障伪装成新闻。

**强制跳过规则**：
- 如果某公司官网返回404或无法访问 → 直接跳过该公司，不要在任何段落中提及。
- 如果采集到的"信息"实际是 Cookie 弹窗、导航菜单、空壳页面 → 不是情报，跳过。
- 如果某条信息的核心内容就是"某个网站打不开" → 不是情报，跳过。

写作要求：
1. **导语**：用 2-3 句话概括今日最重要的新动态，让读者立刻知道今天发生了什么。
2. **分领域详述**：按主题领域分节（如铜缆互联、液冷、PCB、氟树脂材料、公司动态、法规等），每节将今日的新信息整合成连贯叙述，包含具体事实、数据、公司名称。不要逐条罗列！
3. **来源标注**：每条关键信息后面用 [来源](URL) 格式附上链接。
4. **前瞻提示**：最后给出一段"值得关注"，基于今日信号提醒接下来需要跟踪的事项。
5. **字数**：正文 800-1500 字。如果今日新闻确实很少，如实简短即可，不要注水。
6. **风格**：简洁专业，像 Bloomberg 早报而非新闻稿。不要写"据悉""值得一提的是"等套话。
7. **优先级**：只写真正重要或有趣的信息。某领域当日无动态可简略带过或跳过。
8. **图片插入**：如果文章资料中带有 🖼 标记的图片链接，选择有信息含量的（产品图、架构图、数据图表）用 `![描述](URL)` 格式插入到对应段落中。装饰性缩略图和图标略过。
9. 输出纯 Markdown，以## 今日摘要开头。
10. **【重要】摘要**：在报告末尾，单独一行写 `<!-- SUMMARY: 一句话摘要（≤80字） -->`。若今日无重大更新，写'今日AIDC铜缆互联、氟树脂材料、液冷系统等领域无重大更新。'"""

JP_SYSTEM_PROMPT = """あなたはAIDC（AIデータセンター）とフッ素樹脂材料分野を専門とする業界インテリジェンスアナリストです。
本日収集した記事リストに基づき、プロフェッショナルなデイリーインテリジェンスブリーフィングを作成してください。

**鮮度ルール（厳守）**：
- 本日（TODAY）発表された新しい情報のみを書くこと。本日の日付は文末に明記する。
- 記事の公開日が本日でないものは、一切引用してはならない。
- 「近頃」「これまで」「従来から」といった時間を跨ぐ記述は禁止。過去の振り返りは不要。
- ある分野で本日新しい動きがなければ「本日この分野に特筆すべき動きはない」と簡潔に書くだけでよい。古い情報で埋めないこと。
- 読者は昨日のレポートを既読である。昨日までの内容を繰り返さないこと。

**客観性ルール（厳守）**：
- 主観的な憶測や推測を一切行わないこと。事実のみを報告すること。
- 何が起きたか、誰が何を言ったか、データは何か。原因の推測や未検証の結論の導出は行わない。

**禁止用語・禁止表現（レポート内での使用を絶対禁止）**：
以下の用語や表現はいかなる場合も使用禁止。違反は不合格レポートとなる：
- 推測類：示唆している、〜かもしれない、〜と見られる、〜と推測される、可能性がある、不確実性、懸念される、〜を意味する可能性
- 収集障害類：404、ページ異常、リンク切れ、Cookie、情報が見えない、アクセス不能、エラーが返された
- 曖昧な推測文：「これらの変化は〜に影響を与える可能性がある」「〜の可能性を排除できない」

**強制スキップルール**：
- 企業サイトが404やアクセス不能だった場合 → その企業については一切言及せず、完全にスキップ。
- 収集された「情報」が実際はCookieバナー、ナビゲーションメニュー、空のページだった場合 → 情報ではないのでスキップ。
- 「サイトが開けない」こと自体が情報の中核である場合 → それは情報ではないのでスキップ。

執筆要件：
1. **リード**：本日の最も重要な新しい動きを2〜3文で要約し、読者が今日何が起きたかを即座に把握できるようにする。
2. **分野別詳細**：トピック分野ごとにセクションを分け（銅ケーブル相互接続、液冷、PCB、フッ素樹脂材料、企業動向、規制など）、本日の新情報を一貫した叙述にまとめる。箇条書きは避けること！
3. **出典明記**：各重要情報の後に [出典](URL) 形式でリンクを付ける。
4. **展望**：最後に「注目ポイント」として、本日のシグナルに基づき今後フォローすべき事項を提示する。
5. **文字数**：本文800〜1500字。本日のニュースが少なければ、正直に短くまとめてよい。
6. **スタイル**：簡潔で専門的。ブルームバーグのモーニングブリーフィングのようなトーン。「〜と思われる」「注目に値する」といった曖昧な表現は避ける。
7. **優先順位**：本当に重要または興味深い情報のみを書く。動きのない分野は簡略化またはスキップ。
8. **画像挿入**：記事資料に 🖼 マーク付きの画像リンクがある場合、情報価値のあるもの（製品図、アーキテクチャ図、データ図表）を選び `![説明](URL)` 形式で該当段落に挿入すること。装飾的なサムネイルやアイコンは省略。
9. 純粋なMarkdownで出力し、## 本日のサマリー から始めること。
10. **【重要】サマリー**：レポート末尾に `<!-- SUMMARY: 一文サマリー（80字以内） -->` を一行で記述。本日大きな動きがなければ「本日、AIDC銅ケーブル相互接続・フッ素樹脂材料・液冷システム分野に大きな動きはなかった。」と記述。"""


def build_articles_context(articles: list[dict]) -> str:
    """Build a compact context string from articles for the AI prompt."""
    lines = []
    # Filter out excluded articles, sort by credibility
    ranked = sorted(
        [a for a in articles if a.get("verification_status") != "excluded"],
        key=lambda a: (a.get("credibility_score", 0), len(a.get("snippet", ""))),
        reverse=True,
    )
    for i, a in enumerate(ranked[:30], 1):  # Max 30 articles to stay within context
        status = a.get("verification_status", "?")
        status_label = "✓" if status == "verified" else "△" if status == "single_source" else "?"
        cred = a.get("credibility_score", 0)
        domain = a.get("domain", "?")
        title = a.get("title", "")[:120]
        snippet = a.get("snippet", "")[:400]
        url = a.get("url", "")
        pub_date = a.get("publish_date", "") or "不明"

        lines.append(f"[{i}] {status_label}(信頼度{cred}/5) 公開日:{pub_date[:10]} {title}")
        lines.append(f"    URL: {url}")
        lines.append(f"    出典: {domain}")
        if snippet:
            lines.append(f"    抜粋: {snippet}")
        # Include images if available (product photos, charts, architecture diagrams)
        images = a.get("images", []) or []
        for img in images[:2]:  # Max 2 images per article
            img_type = img.get("type", "image")
            type_label = {"product": "製品図", "chart": "データ図表", "architecture": "アーキテクチャ図", "image": "画像"}.get(img_type, "画像")
            lines.append(f"    🖼[{type_label}]: {img['url']}")
        lines.append("")

    return "\n".join(lines)


def call_deepseek(system_prompt: str, user_content: str, lang: str) -> Optional[str]:
    """Call DeepSeek API (OpenAI-compatible) and return the response text."""
    if not DEEPSEEK_API_KEY:
        print(f"  [WARN] DEEPSEEK_API_KEY not set, falling back to template mode")
        return None

    try:
        import requests
    except ImportError:
        print(f"  [WARN] requests not available, falling back to template mode")
        return None

    url = f"{DEEPSEEK_BASE_URL}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.4,
        "max_tokens": 4096,
    }

    print(f"  [{lang.upper()}] Calling DeepSeek API ({DEEPSEEK_MODEL})...")
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        if resp.status_code != 200:
            print(f"  [ERROR] DeepSeek API returned {resp.status_code}: {resp.text[:200]}")
            return None
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        print(f"  [{lang.upper()}] Generated {len(content)} chars "
              f"(in: {usage.get('prompt_tokens', '?')} tokens, "
              f"out: {usage.get('completion_tokens', '?')} tokens)")
        return content
    except Exception as e:
        print(f"  [ERROR] DeepSeek API call failed: {e}")
        return None


def ai_generate_briefing(articles: list[dict], lang: str) -> Optional[str]:
    """Generate a briefing using DeepSeek API for the given language."""
    context = build_articles_context(articles)
    article_count = len([a for a in articles if a.get("verification_status") != "excluded"])
    v_count = sum(1 for a in articles if a.get("verification_status") == "verified")
    date_str = datetime.now().strftime("%Y年%m月%d日")

    if lang == "jp":
        system = JP_SYSTEM_PROMPT
        user = (
            f"本日の日付: {date_str}\n"
            f"本日の収集記事（{article_count}件、うち検証済み{v_count}件）を以下に示します。\n"
            f"各記事の公開日を必ず確認し、本日({date_str})以外の日付の記事は無視してください。\n"
            f"これらを読んで、日本語でインテリジェンスブリーフィングを作成してください。\n\n"
            f"{context}"
        )
    else:
        system = CN_SYSTEM_PROMPT
        user = (
            f"今日日期: {date_str}\n"
            f"以下是今日采集的文章（共{article_count}篇，其中{v_count}篇经交叉验证确认）。\n"
            f"请逐一确认每篇文章的发布日期，只引用发布于今天({date_str})的文章，旧文章一律跳过。\n"
            f"请仔细阅读后撰写中文情报晨报。\n\n"
            f"{context}"
        )

    return call_deepseek(system, user, lang)


# ═══════════════════════════════════════════════════════════
# Template-based fallback (when API is unavailable)
# ═══════════════════════════════════════════════════════════

def template_briefing(articles: list[dict], lang: str) -> str:
    """Fallback template-based briefing with proper display names."""
    active = [a for a in articles if a.get("verification_status") != "excluded"]
    v_count = sum(1 for a in articles if a.get("verification_status") == "verified")
    categories = Counter(
        a.get("category", "other") for a in active
    )
    cat_names = CATEGORY_NAMES_JP if lang == "jp" else CATEGORY_NAMES_CN

    if lang == "jp":
        # Determine if there's anything noteworthy
        has_substance = any(
            a.get("credibility_score", 0) >= 3 and a.get("category") not in ("community_discussion", "other")
            for a in active
        )
        if not has_substance and v_count == 0:
            summary_line = "本日、AIDCおよびフッ素樹脂材料分野において特筆すべき新情報は確認されなかった。"
        elif not has_substance:
            summary_line = f"本日は{v_count}件の記事を収集したが、いずれもAIDC・フッ素樹脂材料分野の重大な新情報ではなかった。"
        else:
            top_cats = [cat_names.get(c, c) for c, _ in categories.most_common(3)]
            summary_line = f"本日は{'・'.join(top_cats)}分野を中心に{len(active)}件の情報を収集、{v_count}件が検証済み。"

        lines = [
            "## 本日のサマリー\n",
            summary_line,
            "" if DEEPSEEK_API_KEY else "（※AI要約は現在利用できません。DeepSeek APIキーを設定すると詳細な分析が自動生成されます。）\n",
            "## カテゴリ別記事数\n",
        ]
        for cat, count in categories.most_common(10):
            label = cat_names.get(cat, cat)
            lines.append(f"- {label}: {count}件")
    else:
        has_substance = any(
            a.get("credibility_score", 0) >= 3 and a.get("category") not in ("community_discussion", "other")
            for a in active
        )
        if not has_substance and v_count == 0:
            summary_line = "今日AIDC与氟树脂材料领域无重大新动态。"
        elif not has_substance:
            summary_line = f"今日采集{len(active)}篇相关文章，均非今日发布的重大行业动态。"
        else:
            top_cats = [cat_names.get(c, c) for c, _ in categories.most_common(3)]
            summary_line = f"今日{'、'.join(top_cats)}等领域共采集{len(active)}篇相关文章，{v_count}篇经交叉验证。"

        lines = [
            "## 今日摘要\n",
            summary_line,
            "" if DEEPSEEK_API_KEY else "（※AI摘要暂不可用。配置 DeepSeek API Key 后将自动生成详细分析。）\n",
            "## 分类统计\n",
        ]
        for cat, count in categories.most_common(10):
            label = cat_names.get(cat, cat)
            lines.append(f"- {label}: {count}篇")

    lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# Report assembly
# ═══════════════════════════════════════════════════════════

def build_key_findings(articles: list[dict]) -> list[dict]:
    """Build key findings list from articles, filtering dead pages."""
    # Signals that an article is a dead page, not real content
    _DEAD_TITLE_SIGNALS = [
        "404", "403", "500", "502", "503",
        "not found", "file not found", "page not found",
        "access denied", "forbidden", "cookie policy",
    ]
    _DEAD_SNIPPET_SIGNALS = [
        "Warning: Target URL returned error",
        "Status: 404", "Status: 403", "Status: 500",
        "## Do Not Sell My Personal Information",
    ]

    def _is_dead_article(a: dict) -> bool:
        title = (a.get("title", "") or "").lower().strip()
        snippet = (a.get("snippet", "") or "")[:300]
        for sig in _DEAD_TITLE_SIGNALS:
            if sig in title:
                return True
        for sig in _DEAD_SNIPPET_SIGNALS:
            if sig.lower() in snippet.lower():
                return True
        if snippet.strip().startswith("## Do Not Sell"):
            return True
        return False

    findings = []
    for a in articles:
        if a.get("verification_status") == "excluded":
            continue
        if _is_dead_article(a):
            continue
        status = a.get("verification_status", "")
        cred = a.get("credibility_score", 0)
        importance = "high" if status == "verified" and cred >= 4 else "medium" if status == "verified" else "low"
        findings.append({
            "id": a.get("id", ""),
            "category": a.get("category", ""),
            "title": a.get("title", ""),
            "url": a.get("url", ""),
            "source_domain": a.get("domain", ""),
            "importance": importance,
            "confidence": status,
            "credibility_score": cred,
            "snippet": (a.get("snippet", "") or "")[:300],
        })

    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order.get(f["importance"], 1), -f["credibility_score"]))
    return findings[:20]


# ═══════════════════════════════════════════════════════════
# Post-processing: sanitize AI-generated briefing
# ═══════════════════════════════════════════════════════════

# Chinese forbidden words/patterns — sentences containing these will be removed
_CN_FORBIDDEN = [
    # Speculation words
    r"暗示", r"可能意味着", r"也许", r"不排除", r"疑似",
    r"或可解读为", r"可能反映", r"可能影响", r"或暗示",
    r"可能暗示", r"值得警惕的是.*可能", r"不排除.*可能",
    r"或可视为", r"可视为.*信号",
    # Collection failure descriptions (these are NOT intelligence)
    r"404", r"403", r"页面异常", r"链接失效", r"Cookie",
    r"仅显示.*标题", r"仅显示.*Logo", r"内容缺失",
    r"信息不可见", r"返回.*错误", r"无法访问",
    r"页面.*缺失", r"产品目录.*缺失", r"技术参数.*缺失",
    r"页面.*空", r"仅.*Cookie", r"仅.*导航",
]
_JP_FORBIDDEN = [
    r"示唆", r"可能性がある", r"かもしれない", r"と見られる",
    r"と推測される", r"不確実", r"懸念される",
    r"404", r"ページ異常", r"リンク切れ", r"Cookie",
    r"アクセス不能", r"エラーが返", r"情報が見えない",
    r"意味する可能性", r"排除できない",
]


def sanitize_briefing(text: str, lang: str) -> tuple[str, int]:
    """Remove sentences containing forbidden words/patterns.
    Returns (sanitized_text, removed_count)."""
    import re

    forbidden = _CN_FORBIDDEN if lang == "cn" else _JP_FORBIDDEN
    fallback_line = (
        "今日该领域无重大更新。" if lang == "cn"
        else "本日この分野に特筆すべき動きはない。"
    )

    lines = text.split("\n")
    cleaned = []
    removed_total = 0
    # Track consecutive empty lines to avoid excessive gaps
    prev_empty = False

    for line in lines:
        stripped = line.strip()

        # Always pass through: headings, summary markers, source citations, horizontal rules
        if (stripped.startswith("#") or stripped.startswith("<!--") or
            stripped.startswith("[来源]") or stripped.startswith("[出典]") or
            stripped.startswith("---") or stripped.startswith(">") or
            stripped.startswith("*") or stripped == ""):
            if stripped == "":
                if not prev_empty:
                    cleaned.append(line)
                prev_empty = True
            else:
                cleaned.append(line)
                prev_empty = False
            continue

        # Check if this line contains forbidden patterns
        should_remove = False
        matched_pattern = ""
        for pattern in forbidden:
            if re.search(pattern, stripped):
                should_remove = True
                matched_pattern = pattern
                break

        if should_remove:
            removed_total += 1
            prev_empty = False
            continue

        cleaned.append(line)
        prev_empty = False

    result = "\n".join(cleaned)

    # If a section became empty after sanitization (heading followed by nothing),
    # fill with fallback text
    # Pattern: ## heading\n\n(next heading or end) with nothing in between
    result = re.sub(
        r"(##\s+[^\n]+)\n(?=\n*(?:##|$|\n*$))",
        rf"\1\n\n{fallback_line}\n",
        result,
    )

    # Warn if significant content was removed
    if removed_total > 0:
        total_lines = len([l for l in text.split("\n") if l.strip() and not l.strip().startswith("#")])
        if total_lines > 0 and removed_total / max(total_lines, 1) > 0.3:
            print(f"  [WARN] sanitize_briefing({lang}): removed {removed_total} lines "
                  f"({removed_total * 100 // max(total_lines, 1)}% of content) — AI可能未遵守prompt规则")

    return result, removed_total


# ═══════════════════════════════════════════════════════════
# Report assembly
# ═══════════════════════════════════════════════════════════

def generate_report(date_str: str) -> dict:
    """Generate the complete daily report JSON."""
    verified_data = load_verified(date_str)
    articles = verified_data.get("articles", [])
    metadata = verified_data.get("verification_metadata", {})

    # Cross-day deduplication: remove articles seen in prior days
    articles = deduplicate_across_days(articles, date_str)

    active_articles = [a for a in articles if a.get("verification_status") != "excluded"]

    # ── AI-powered briefings ──
    print("Generating AI intelligence reports...")
    briefing_cn = ai_generate_briefing(articles, "cn")
    if not briefing_cn:
        briefing_cn = template_briefing(articles, "cn")

    briefing_jp = ai_generate_briefing(articles, "jp")
    if not briefing_jp:
        briefing_jp = template_briefing(articles, "jp")

    # ── Apply post-processing sanitization ──
    print("Applying post-processing sanitization...")
    briefing_cn, cn_removed = sanitize_briefing(briefing_cn, "cn")
    briefing_jp, jp_removed = sanitize_briefing(briefing_jp, "jp")
    if cn_removed > 0:
        print(f"  [CN] Removed {cn_removed} problematic sentences")
    if jp_removed > 0:
        print(f"  [JP] Removed {jp_removed} problematic sentences")

    # ── Summaries (extract from AI-generated SUMMARY tag, or derive) ──
    def extract_summary(text: str, lang: str) -> str:
        """Extract short summary from briefing.
        Priority: 1) <!-- SUMMARY: ... --> tag  2) First paragraph  3) Fallback"""
        import re
        # Look for explicit summary tag from AI
        m = re.search(r'<!--\s*SUMMARY:\s*(.+?)\s*-->', text)
        if m:
            return m.group(1)[:120]

        # Fallback: generate from category breakdown
        cats = [c for c, n in by_cat.most_common(5) if n > 0]
        if not cats:
            if lang == "jp":
                return "本日、AIDC関連分野に特筆すべき新情報はなかった。"
            return "今日AIDC铜缆互联、氟树脂材料、液冷系统等领域无重大更新。"

        if lang == "jp":
            cat_names = CATEGORY_NAMES_JP
            names = [cat_names.get(c, c) for c in cats[:3]]
            return f"本日は{'・'.join(names)}分野で{len(active_articles)}件の情報を収集。"
        else:
            cat_names = CATEGORY_NAMES_CN
            names = [cat_names.get(c, c) for c in cats[:3]]
            return f"今日{'、'.join(names)}等领域共采集{len(active_articles)}篇相关文章。"

    # ── Category breakdown ──
    by_cat = Counter(
        a.get("category", "other") for a in articles
        if a.get("verification_status") != "excluded"
    )

    report = {
        "date": date_str,
        "generated_at": datetime.now().isoformat(),
        "generator": "deepseek" if DEEPSEEK_API_KEY else "template",
        "meta": {
            "total_crawled": metadata.get("total_input", len(articles)),
            "verified_count": metadata.get("stats", {}).get("verified", 0),
            "single_source_count": metadata.get("stats", {}).get("single_source_high", 0),
            "excluded_count": metadata.get("stats", {}).get("excluded", 0),
            "active_sources": metadata.get("sources_used", []),
            "failed_sources": metadata.get("sources_failed", []),
        },
        "briefing_cn": briefing_cn,
        "briefing_jp": briefing_jp,
        "summary_cn": extract_summary(briefing_cn, "cn"),
        "summary_jp": extract_summary(briefing_jp, "jp"),
        "category_breakdown": dict(by_cat.most_common()),
        "key_findings": build_key_findings(articles),
        "articles": [{
            "id": a.get("id", ""),
            "title": a.get("title", ""),
            "url": a.get("url", ""),
            "domain": a.get("domain", ""),
            "credibility_score": a.get("credibility_score", 0),
            "verification_status": a.get("verification_status", ""),
            "category": a.get("category", ""),
            "snippet": (a.get("snippet", "") or "")[:300],
        } for a in articles],
        "source_domains": [
            {"domain": d, "count": c}
            for d, c in Counter(
                a.get("domain", "?") for a in articles
            ).most_common(10)
        ],
    }

    return report


def report_to_markdown(report: dict, lang: str) -> str:
    """Convert report to standalone Markdown file."""
    is_jp = lang == "jp"
    meta = report["meta"]
    briefing = report["briefing_jp"] if is_jp else report["briefing_cn"]

    if is_jp:
        header = (
            f"# AIDC・フッ素樹脂材料 デイリーブリーフィング — {report['date']}\n\n"
            f"**発行**: {report['generated_at']}\n\n"
            f"---\n\n"
            f"> 収集 {meta['total_crawled']} 件 | 検証済み {meta['verified_count']} 件 | "
            f"アクティブソース {len(meta['active_sources'])} 個\n\n"
        )
    else:
        header = (
            f"# AIDC + 氟树脂材料 每日晨报 — {report['date']}\n\n"
            f"**生成时间**: {report['generated_at']}\n\n"
            f"---\n\n"
            f"> 采集 {meta['total_crawled']} 篇 | 验证通过 {meta['verified_count']} 篇 | "
            f"活跃信源 {len(meta['active_sources'])} 个\n\n"
        )

    return header + briefing + f"\n\n---\n*本报告由 AIDC + Fluororesin Intelligence Monitor 自动生成*\n"


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="AI-powered morning briefing generator")
    parser.add_argument("--date", required=True, help="Target date (YYYY-MM-DD)")
    parser.add_argument("--lang", default="all", choices=["cn", "jp", "all"])
    args = parser.parse_args()

    print("=" * 60)
    print("AIDC + Fluororesin — AI Morning Briefing Generator")
    print(f"Date: {args.date} | Lang: {args.lang}")
    if DEEPSEEK_API_KEY:
        print(f"AI: DeepSeek ({DEEPSEEK_MODEL}) — ✓ enabled")
    else:
        print("AI: disabled — set DEEPSEEK_API_KEY to enable")
    print("=" * 60)
    print()

    report = generate_report(args.date)

    report_dir = REPORTS_DIR / args.date
    report_dir.mkdir(parents=True, exist_ok=True)
    WEBSITE_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Save JSON
    json_path = report_dir / "report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  JSON: {json_path}")

    site_json = WEBSITE_DATA_DIR / f"{args.date}.json"
    with open(site_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Save Markdown
    if args.lang in ("cn", "all"):
        md = report_to_markdown(report, "cn")
        with open(report_dir / "report_cn.md", "w", encoding="utf-8") as f:
            f.write(md)
        print(f"  Markdown (CN): {len(md)} chars")

    if args.lang in ("jp", "all"):
        md = report_to_markdown(report, "jp")
        with open(report_dir / "report_jp.md", "w", encoding="utf-8") as f:
            f.write(md)
        print(f"  Markdown (JP): {len(md)} chars")

    print(f"\n  Report: {report['meta']['total_crawled']} articles, "
          f"{len(report['category_breakdown'])} categories")
    print(f"  Generator: {report['generator']}")


if __name__ == "__main__":
    main()
