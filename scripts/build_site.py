#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Static site builder for AIDC + Fluororesin Intelligence Monitor.
Verifies website file structure and generates initial data files.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# Fix Windows encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEBSITE_DIR = PROJECT_ROOT / "website"
DATA_DIR = WEBSITE_DIR / "data"
KB_DIR = PROJECT_ROOT / "knowledge_base"


def check_files_exist() -> dict:
    """Check all required files exist"""
    required = {
        "index.html": WEBSITE_DIR / "index.html",
        "cn/index.html": WEBSITE_DIR / "cn" / "index.html",
        "jp/index.html": WEBSITE_DIR / "jp" / "index.html",
        "cn/daily.html": WEBSITE_DIR / "cn" / "daily.html",
        "jp/daily.html": WEBSITE_DIR / "jp" / "daily.html",
        "cn/knowledge.html": WEBSITE_DIR / "cn" / "knowledge.html",
        "jp/knowledge.html": WEBSITE_DIR / "jp" / "knowledge.html",
        "assets/css/style.css": WEBSITE_DIR / "assets" / "css" / "style.css",
        "assets/js/i18n.js": WEBSITE_DIR / "assets" / "js" / "i18n.js",
        "assets/js/data-loader.js": WEBSITE_DIR / "assets" / "js" / "data-loader.js",
    }

    status = {"ok": [], "missing": []}
    for label, path in required.items():
        if path.exists():
            status["ok"].append(label)
        else:
            status["missing"].append(label)
    return status


def generate_missing_data():
    """Generate initial data files if missing"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "reports").mkdir(parents=True, exist_ok=True)

    daily_index_path = DATA_DIR / "daily_index.json"
    if not daily_index_path.exists():
        with open(daily_index_path, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)
        print("  Created empty daily_index.json")

    ki_path = DATA_DIR / "knowledge_index.json"
    if not ki_path.exists():
        kb_path = KB_DIR / "knowledge_base.json"
        if kb_path.exists():
            with open(kb_path, "r", encoding="utf-8") as f:
                kb = json.load(f)
            ki = {
                "topics": [{
                    "id": t.get("id", ""),
                    "name": t.get("name", ""),
                    "name_jp": t.get("name_jp", ""),
                    "keywords": t.get("keywords", []),
                    "article_count": 0
                } for t in kb.get("topics", [])],
                "tag_cloud": [],
                "total_articles": len(kb.get("articles", [])),
                "last_updated": datetime.now().isoformat()
            }
            with open(ki_path, "w", encoding="utf-8") as f:
                json.dump(ki, f, ensure_ascii=False, indent=2)
            print(f"  Created knowledge_index.json with {len(ki['topics'])} topics")
        else:
            with open(ki_path, "w", encoding="utf-8") as f:
                json.dump({"topics": [], "tag_cloud": [], "total_articles": 0, "last_updated": datetime.now().isoformat()}, f, ensure_ascii=False)
            print("  Created empty knowledge_index.json")


def build() -> bool:
    """Run build verification and data generation"""
    print("=" * 60)
    print("AIDC+Fluororesin Static Site Builder")
    print(f"Project: {PROJECT_ROOT}")
    print("=" * 60)
    print()

    print("1. Checking file structure...")
    status = check_files_exist()

    if status["missing"]:
        print(f"\n  [FAIL] Missing required files ({len(status['missing'])}):")
        for m in status["missing"]:
            print(f"     - {m}")
        return False

    print(f"  [OK] All {len(status['ok'])} required files present")

    print("\n2. Generating data files...")
    generate_missing_data()

    print("\n3. Site stats:")
    html_count = sum(1 for p in WEBSITE_DIR.rglob("*.html") if p.is_file())
    js_count = sum(1 for p in (WEBSITE_DIR / "assets").rglob("*.js") if p.is_file())
    css_count = sum(1 for p in (WEBSITE_DIR / "assets").rglob("*.css") if p.is_file())
    data_count = sum(1 for p in DATA_DIR.rglob("*.json") if p.is_file())

    print(f"     HTML pages: {html_count}")
    print(f"     JS files:   {js_count}")
    print(f"     CSS files:  {css_count}")
    print(f"     Data files: {data_count}")

    print()
    print("=" * 60)
    print("[OK] Build successful!")
    print("   Open website/index.html in a browser to preview")
    print("   Deploy the entire website/ folder to any static host")
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build static website")
    parser.add_argument("--check", action="store_true", help="Check only")
    args = parser.parse_args()

    if args.check:
        status = check_files_exist()
        print(f"OK: {len(status['ok'])}, Missing: {len(status['missing'])}")
        for m in status["missing"]:
            print(f"  MISSING: {m}")
        return

    success = build()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
