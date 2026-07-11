/* ============================================================
   AIDC + Fluororesin Intelligence Monitor — Data Loader
   Fetches JSON from website/data/ and renders UI components
   ============================================================ */

(function(global) {
  'use strict';

  var DATA_BASE = '../data/';  // relative from cn/ or jp/ pages

  /**
   * Fetch JSON data with error handling.
   * In file:// mode, fetch may fail — uses sample data fallback.
   */
  async function fetchJSON(path) {
    try {
      var resp = await fetch(path);
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      return await resp.json();
    } catch (e) {
      console.warn('DataLoader: Cannot load ' + path + ' — ' + e.message);
      return null;
    }
  }

  /**
   * Load daily report index
   */
  async function loadDailyIndex() {
    return await fetchJSON(DATA_BASE + 'daily_index.json');
  }

  /**
   * Load knowledge index
   */
  async function loadKnowledgeIndex() {
    return await fetchJSON(DATA_BASE + 'knowledge_index.json');
  }

  /**
   * Load a specific daily report
   */
  async function loadReport(dateStr) {
    return await fetchJSON(DATA_BASE + 'reports/' + dateStr + '.json');
  }

  /**
   * Get sample / demo data for when no real data exists yet
   */
  function getSampleDailyIndex() {
    return [
      {
        date: "2026-07-05",
        total_articles: 32,
        verified_count: 18,
        summary_cn: "今日共收集32篇相关文章，其中18篇经多源交叉验证确认。重点关注：NVIDIA Rubin平台互联架构更新、永和股份FEP产能扩建进展、PFAS法规日本市场影响评估。",
        summary_jp: "本日は32件の関連記事を収集し、18件がクロス検証済み。注目トピック：NVIDIA Rubinプラットフォーム相互接続更新、永和股份のFEP生産能力拡張、PFAS規制の日本市場への影響評価。",
        active_sources: ["exa", "rss", "jina", "bilibili"],
        categories: {"AIDC_development": 12, "fluororesin_material": 8, "company_news": 7, "regulation": 3, "market_data": 2}
      }
    ];
  }

  function getSampleKnowledgeIndex() {
    return {
      topics: [
        { id: "topic-copper-interconnect", name: "高速铜缆互联", name_jp: "高速銅ケーブル相互接続", keywords: ["DAC", "AEC", "224G", "SerDes", "铜连接"], article_count: 12, last_updated: "2026-07-06", recent_titles: ["NVIDIA Rubin平台采用224G SerDes铜缆互联", "立讯精密发布新一代DAC产品线"] },
        { id: "topic-thermal-management", name: "散热与热管理", name_jp: "熱管理・放熱", keywords: ["液冷", "冷却液", "氟化液"], article_count: 12, last_updated: "2026-07-06", recent_titles: ["Vertiv热管理产品更新"] },
        { id: "topic-pcb-substrate", name: "高频PCB基板", name_jp: "高周波PCB基板", keywords: ["PTFE基板", "Rogers", "低介电常数"], article_count: 3, last_updated: "2026-07-06", recent_titles: ["RO4000 Series Laminates"] },
        { id: "topic-fluorochem-supply", name: "氟化工供应链", name_jp: "フッ素化学サプライチェーン", keywords: ["永和", "东岳", "Chemours", "Daikin"], article_count: 4, last_updated: "2026-07-06", recent_titles: ["氟化工产业链产能跟踪"] }
      ],
      tag_cloud: [
        { tag: "FEP", count: 28 }, { tag: "DAC", count: 24 }, { tag: "NVIDIA", count: 22 },
        { tag: "PTFE", count: 19 }, { tag: "CPO", count: 18 }, { tag: "Foaming", count: 16 },
        { tag: "永和股份", count: 15 }, { tag: "Chemours", count: 14 }, { tag: "224G SerDes", count: 13 },
        { tag: "PFAS", count: 12 }, { tag: "Nucleating Agent", count: 11 }, { tag: "AGC", count: 10 }
      ],
      companies: [
        { name: "NVIDIA", ticker: "NVDA", name_jp: "NVIDIA", mention_count: 22, recent_articles: [{date:"2026-07-05",title:"NVIDIA Rubin平台互联架构更新",url:"#"},{date:"2026-07-01",title:"NVIDIA Blackwell Ultra量产进展",url:"#"}] },
        { name: "永和股份", ticker: "605020", name_jp: "永和股份", mention_count: 15, recent_articles: [{date:"2026-07-03",title:"永和股份FEP产能扩建",url:"#"}] },
        { name: "Chemours", ticker: "CC", name_jp: "Chemours", mention_count: 14, recent_articles: [{date:"2026-07-05",title:"Chemours PTFE价格调整",url:"#"}] }
      ],
      timeline: [
        { date: "2026-07-05", title: "NVIDIA Rubin平台互联架构更新", url: "#", topicIds: ["topic-aidc-copper"], credibility: 4 },
        { date: "2026-07-05", title: "Chemours上调PTFE报价", url: "#", topicIds: ["topic-fluorochem-supply"], credibility: 4 },
        { date: "2026-07-04", title: "Broadcom展示下一代CPO交换机方案", url: "#", topicIds: ["topic-cpo-optics"], credibility: 3 },
        { date: "2026-07-03", title: "永和股份FEP产能扩建项目环评公示", url: "#", topicIds: ["topic-fluororesin-foam"], credibility: 4 },
        { date: "2026-07-02", title: "NVIDIA Rubin Ultra互联架构细节曝光", url: "#", topicIds: ["topic-interconnect-roadmap"], credibility: 3 }
      ],
      total_articles: 156,
      last_updated: new Date().toISOString()
    };
  }

  /**
   * Render stats row on the home page
   */
  function renderStatsRow(containerId, data, lang) {
    var el = document.getElementById(containerId);
    if (!el) return;

    var t = global.t || function(k) { return k; };
    var total = data.total_articles || 0;
    var verified = data.verified_count || 0;
    var single = (data.total_articles || 0) - (data.verified_count || 0);

    el.innerHTML =
      '<div class="stat-card total">' +
        '<div class="stat-value">' + total + '</div>' +
        '<div class="stat-label">' + t('articles_collected', lang) + '</div>' +
      '</div>' +
      '<div class="stat-card verified">' +
        '<div class="stat-value">' + verified + '</div>' +
        '<div class="stat-label">' + t('articles_verified', lang) + '</div>' +
      '</div>' +
      '<div class="stat-card single">' +
        '<div class="stat-value">' + Math.max(0, single) + '</div>' +
        '<div class="stat-label">' + t('articles_single', lang) + '</div>' +
      '</div>' +
      '<div class="stat-card sources">' +
        '<div class="stat-value">' + ((data.active_sources && data.active_sources.length) || 4) + '</div>' +
        '<div class="stat-label">' + t('sources_active', lang) + '</div>' +
      '</div>';
  }

  /**
   * Render a list of daily reports
   */
  function renderReportList(containerId, reports, lang) {
    var el = document.getElementById(containerId);
    if (!el || !reports) return;

    var t = global.t || function(k) { return k; };
    var html = '';

    reports.slice(0, 7).forEach(function(r) {
      var date = r.date || '';
      var count = r.total_articles || 0;
      var verified = r.verified_count || 0;
      html += '<div class="report-list-item">' +
        '<a href="' + (lang === 'jp' ? '../jp/' : '../cn/') + 'daily.html?date=' + date + '">' +
          '<span>' + date + '</span>' +
          '<span class="date">' + verified + '/' + count + ' ' + t('verified_label', lang) + '</span>' +
        '</a></div>';
    });

    if (!html) {
      html = '<div class="empty-state"><span class="icon">📋</span>' + t('no_data', lang) + '</div>';
    }
    el.innerHTML = html;
  }

  /**
   * Render category pulse indicators
   */
  function renderCategoryPulse(containerId, categories, lang) {
    var el = document.getElementById(containerId);
    if (!el) return;

    var getCatName = global.getCategoryName || function(c) { return c; };
    var cats = categories || {};
    var entries = Object.entries(cats);
    if (!entries.length) {
      el.innerHTML = '';
      return;
    }

    var total = entries.reduce(function(s, e) { return s + e[1]; }, 0);
    var html = '';
    entries.forEach(function(e) {
      var name = e[0], count = e[1];
      var ratio = count / Math.max(total, 1);
      var dotClass = ratio > 0.35 ? 'hot' : ratio > 0.2 ? 'warm' : ratio > 0.08 ? 'normal' : 'cold';
      html += '<div class="pulse-item">' +
        '<span class="pulse-dot ' + dotClass + '"></span>' +
        '<span class="pulse-count">' + count + '</span>' +
        '<span class="pulse-label">' + getCatName(name, lang) + '</span>' +
      '</div>';
    });
    el.innerHTML = html;
  }

  // Public API
  global.DataLoader = {
    fetchJSON: fetchJSON,
    loadDailyIndex: loadDailyIndex,
    loadKnowledgeIndex: loadKnowledgeIndex,
    loadReport: loadReport,
    getSampleDailyIndex: getSampleDailyIndex,
    getSampleKnowledgeIndex: getSampleKnowledgeIndex,
    renderStatsRow: renderStatsRow,
    renderReportList: renderReportList,
    renderCategoryPulse: renderCategoryPulse
  };

})(window);
