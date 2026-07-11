#!/bin/bash
# ============================================================
# AIDC + 氟树脂材料 每日采集总调度脚本
# ============================================================
# 由 CronCreate 每日 08:00 CST 触发执行
#
# 流程:
#   Stage 1: 多源并行采集 (crawl_sources.py)
#   Stage 2: 交叉验证 (verify_articles.py)
#   Stage 3: 日报生成 + 双语翻译 (generate_report.py)
#   Stage 4: 网站更新 (update_website.py + build_site.py)
#
# 用法:
#   bash scripts/daily_crawl.sh              # 当天
#   bash scripts/daily_crawl.sh 2026-07-05   # 指定日期
# ============================================================

set -euo pipefail

DATE="${1:-$(date +%Y-%m-%d)}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/crawl_${DATE}.log"

# ── Logging ────────────────────────────────────────────────
log() {
    echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"
}

exec > >(tee -a "$LOG") 2>&1

echo ""
echo "============================================================"
echo " AIDC + Fluororesin Daily Crawl Pipeline"
echo " Date: $DATE"
echo " Project: $PROJECT_DIR"
echo " Start: $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
echo ""

# ── Detect Python ──────────────────────────────────────────
# Cross-platform: try known real paths first, then fall back to PATH
PYTHON=""
for candidate in \
    "/c/Users/15337/AppData/Local/Programs/Python/Python311/python.exe" \
    "/c/Program Files/Python311/python.exe" \
    "/c/Program Files/Python312/python.exe" \
    python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1; then
        # Verify it actually works (Windows Store placeholder fails here)
        if $candidate --version >/dev/null 2>&1; then
            PYTHON="$candidate"
            break
        fi
    fi
done
if [ -z "$PYTHON" ]; then
    log "[FATAL] No working Python interpreter found"
    exit 1
fi
log "Using Python: $($PYTHON --version 2>&1)"

# ── Detect environment ─────────────────────────────────────
# CI (GitHub Actions) → use crawl_ci.py (pure HTTP)
# Local with agent-reach → use crawl_sources.py (full CLI)
if [ -n "${CI:-}" ] || [ -n "${GITHUB_ACTIONS:-}" ]; then
    CRAWL_SCRIPT="scripts/crawl_ci.py"
    log "CI environment detected → using crawl_ci.py"
else
    # Try agent-reach venv activation (cross-platform)
    AGENT_VENV=""
    for path in \
        "$HOME/.agent-reach-venv/bin/activate" \
        "$HOME/.agent-reach-venv/Scripts/activate"; do
        if [ -f "$path" ]; then
            AGENT_VENV="$path"
            break
        fi
    done
    if [ -n "$AGENT_VENV" ]; then
        source "$AGENT_VENV" 2>/dev/null || true
        log "Activated agent-reach venv"
    fi
    CRAWL_SCRIPT="scripts/crawl_sources.py"
    log "Local environment → using crawl_sources.py (full)"
fi

# ═══════════════════════════════════════════════════════════
# Stage 1: Multi-Source Crawl
# ═══════════════════════════════════════════════════════════
log "=== STAGE 1: Multi-Source Crawl ==="

$PYTHON "$CRAWL_SCRIPT" --date "$DATE" || {
    log "[WARN] Crawl had errors but continuing with partial data"
}

# ═══════════════════════════════════════════════════════════
# Stage 2: Cross-Verification
# ═══════════════════════════════════════════════════════════
log ""
log "=== STAGE 2: Cross-Verification ==="

$PYTHON scripts/verify_articles.py --date "$DATE" || {
    log "[WARN] Verification had errors, check logs"
}

# ═══════════════════════════════════════════════════════════
# Stage 3: Generate Daily Reports
# ═══════════════════════════════════════════════════════════
log ""
log "=== STAGE 3: Generate Daily Reports ==="

$PYTHON scripts/generate_report.py --date "$DATE" --lang all || {
    log "[WARN] Report generation had errors"
}

# ═══════════════════════════════════════════════════════════
# Stage 4: Update Website
# ═══════════════════════════════════════════════════════════
log ""
log "=== STAGE 4: Update Website ==="

$PYTHON scripts/update_website.py --date "$DATE" || {
    log "[WARN] Website data update had errors"
}

$PYTHON scripts/build_site.py || {
    log "[WARN] Website build had errors"
}

# ═══════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════
echo ""
echo "============================================================"
log " Pipeline Complete!"
log " Date: $DATE"
log " End: $(date '+%Y-%m-%d %H:%M:%S')"
log " Log: $LOG"
echo "============================================================"
