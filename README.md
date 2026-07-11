# AIDC + 氟树脂材料 情报监测系统

> AI 数据中心高速互联技术 × 氟树脂绝缘材料 — 每日自动采集 · 多源交叉验证 · 中日双语呈现

## 项目概览

本系统聚焦 **AIDC (AI 数据中心) 高速铜缆互联技术发展**及其对**氟树脂绝缘材料行业**的影响，实现：

1. **每日多源自动采集** — Exa 搜索 / RSS 订阅 / Jina Reader / B站 / V2EX / 微信公众号
2. **交叉验证** — 多源事实声明比对，2+ 独立信源确认才采纳
3. **中日双语日报** — 自动生成结构化日报 (JSON + Markdown)
4. **静态双语网站** — 零服务端依赖，可直接双击打开或部署到任意静态托管

## 项目结构

```
aidc-fluororesin-monitor/
├── config/
│   ├── sources.yaml              # 信源配置 (RSS/搜索/关键词/可信度)
│   └── credentials.example.json  # 凭证模板
├── knowledge_base/
│   ├── knowledge_base.json       # 累积知识库
│   └── archive/YYYY-MM-DD/       # 每日数据快照
├── reports/YYYY-MM-DD/           # 日报文件 (md + json)
├── website/                      # 静态双语网站
│   ├── index.html                # 语言选择入口
│   ├── cn/                       # 中文版
│   │   ├── index.html            # 首页仪表盘
│   │   ├── daily.html            # 日报档案
│   │   └── knowledge.html        # 知识图谱
│   ├── jp/                       # 日文版 (镜像结构)
│   ├── assets/                   # CSS/JS/i18n
│   └── data/                     # JSON 数据文件
├── scripts/
│   ├── daily_crawl.sh            # 总调度脚本 (Cron 触发)
│   ├── crawl_sources.py          # 多源采集器
│   ├── verify_articles.py        # 交叉验证引擎
│   ├── generate_report.py        # 日报生成器
│   ├── update_website.py         # 网站数据更新
│   └── build_site.py             # 网站构建验证
├── templates/
└── logs/
```

## 快速开始

### 1. 环境准备

```bash
# Python 依赖
pip install feedparser pyyaml requests

# agent-reach (P0 信源)
# 已安装则跳过: pipx install agent-reach 或使用 venv
```

### 2. 首次手动运行 (验证流程)

```bash
cd aidc-fluororesin-monitor

# Step 1: 多源采集
python scripts/crawl_sources.py --date $(date +%Y-%m-%d)

# Step 2: 交叉验证
python scripts/verify_articles.py --date $(date +%Y-%m-%d)

# Step 3: 生成日报
python scripts/generate_report.py --date $(date +%Y-%m-%d) --lang all

# Step 4: 更新网站
python scripts/update_website.py --date $(date +%Y-%m-%d)
python scripts/build_site.py
```

### 3. 预览网站

```bash
# 直接双击打开
start website/index.html

# 或部署到任意静态托管 (GitHub Pages / Netlify / Vercel / Nginx)
```

## 自动化

### 定时任务 (CronCreate)

| 任务 | 频率 | 说明 |
|------|------|------|
| 每日采集流水线 | 每天 08:00 | crawl → verify → report → website update |
| 每周深度审计 | 每周日 10:00 | deep-research 对抗性验证本周重大发现 |

> ⚠️ **注意**: 定时任务每 7 天自动过期。到期后需要重新创建：
> ```
> 帮我重新创建 AIDC 监测系统的每日定时任务
> ```

### 手动触发

```bash
bash scripts/daily_crawl.sh           # 当天
bash scripts/daily_crawl.sh 2026-07-05 # 指定日期
```

## 信源说明

### P0 零配置 (保证最小可运行)

| 信源 | 工具 | 覆盖范围 |
|------|------|----------|
| Exa AI 搜索 | `agent-reach` (mcporter) | 中/日/英全网搜索，15组关键词 |
| RSS 聚合 | `feedparser` | EETimes, 日经xTech, LightCounting 等 |
| Jina Reader | `curl r.jina.ai/URL` | 公司官网、产品页面全文提取 |
| B站搜索 | `bili search` | 行业会议、分析师中文内容 |
| V2EX | API | 中文技术社区讨论 |

### P1 可选增强 (需凭证)

- **微信公众号**: 配置 `config/credentials.json` 中的 WeChat token+cookie
- **Twitter/X**: 配置 Twitter cookie
- **Reddit**: 需要 Chrome 登录态 + OpenCLI

## 交叉验证策略

```
原始采集 → 来源可信度评分 (1-5) → 事实声明提取 → 跨源比对
                                                    │
                            ┌───────────────────────┼───────────────────────┐
                            ▼                       ▼                       ▼
                      ≥2 独立信源确认          1个高可信源(≥4分)         1个低可信源
                         ✅ 采纳                 ✅ 采纳(标注)            ❌ 排除
                     置信度: 高                置信度: 中               (严格模式)
```

### 可信度评分标准

- **5分**: 公司官网、学术期刊 (IEEE)、行业标准组织
- **4分**: 知名行业媒体 (日经、EETimes、LightCounting)
- **3分**: 财经媒体 (Bloomberg、Reuters、东方财富)
- **2分**: 论坛/社区 (V2EX、Reddit、B站)
- **1分**: 匿名/未验证来源

## 网站特性

- 🌐 **中日双语**: 自动检测浏览器语言，一键切换
- 📊 **数据仪表盘**: 今日快照 + 话题活跃度 + 关键发现卡片
- 📋 **日报档案**: 按日期/分类过滤，历史归档可搜索
- 🧬 **知识图谱**: 主题集群 + 标签云 + 追踪公司
- 📱 **响应式**: 适配桌面和移动端
- 🔒 **零依赖**: 纯静态 HTML/CSS/JS，无服务端，无数据库

## 追踪覆盖

### 技术领域
- AIDC 高速铜缆 (DAC/AEC/ACC)、CPO 共封装光学
- 224G SerDes、NVLink、InfiniBand 互联架构
- FEP/PTFE/PFA/ETFE 发泡氟树脂绝缘材料
- 成核剂、功能母粒、化学/物理发泡工艺
- PFAS/PFOA 全球法规动态

### 追踪公司
NVIDIA · Broadcom · Amphenol · TE Connectivity · Molex · 立讯精密 · 沃尔核材 · 永和股份 · 东岳集团 · 巨化股份 · Chemours · Daikin · AGC

## 扩展指南

### 添加新信源

编辑 `config/sources.yaml`，添加 RSS 源、搜索关键词或监控 URL。

### 自定义日报模板

编辑 `templates/daily_report_template.md`，格式遵循 Jinja2/Markdown。

### 部署到服务器

```bash
# 将 website/ 目录部署到 Nginx
cp -r website/* /var/www/aidc-monitor/

# 或使用 GitHub Pages
cd website && git init && git add -A && git commit -m "deploy"
git remote add origin git@github.com:user/aidc-monitor.git
git push -u origin main
```

## 运维

- **日志**: `logs/crawl_YYYY-MM-DD.log`
- **数据备份**: `knowledge_base/archive/` 保留每日原始数据
- **知识库**: `knowledge_base/knowledge_base.json` 为累积知识库
- **恢复**: 如采集失败，可手动指定日期重跑: `bash scripts/daily_crawl.sh 2026-07-05`

## License

MIT
