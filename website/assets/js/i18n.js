/* ============================================================
   AIDC + Fluororesin Intelligence Monitor — i18n String Tables
   ============================================================ */
window.I18N = {
  cn: {
    site_title: "AIDC + 氟树脂材料 情报监测",
    nav_home: "首页",
    nav_daily: "日报",
    nav_knowledge: "知识图谱",
    nav_archive: "归档",
    today_snapshot: "今日数据快照",
    articles_collected: "采集文章",
    articles_verified: "已验证 (2+信源)",
    articles_single: "单一信源",
    sources_active: "活跃信源",
    key_findings: "关键发现",
    category_pulse: "话题活跃度",
    recent_reports: "最近日报",
    source_health: "信源状态",
    verified_label: "已验证",
    single_source_label: "单一信源",
    unverified_label: "未验证",
    importance_high: "高",
    importance_medium: "中",
    importance_low: "低",
    filter_all: "全部",
    no_data: "暂无数据",
    loading: "加载中...",
    last_updated: "最后更新",
    credibility: "可信度",
    source: "来源",
    view_report: "查看日报",
    language: "语言",
    topic_overview: "主题概览",
    companies_tracked: "追踪公司",
    article_count: "篇文章",
    back_to_top: "回到顶部",
    about_text: "本平台聚焦 AIDC (AI数据中心) 中氟树脂材料的全场景应用——从铜缆互联、液冷系统、高频PCB、光通讯到电源系统——每日自动采集多源信息并进行交叉验证。"
  },
  jp: {
    site_title: "AIDC + フッ素樹脂材料 インテリジェンス",
    nav_home: "ホーム",
    nav_daily: "日報",
    nav_knowledge: "ナレッジマップ",
    nav_archive: "アーカイブ",
    today_snapshot: "本日のスナップショット",
    articles_collected: "収集記事",
    articles_verified: "検証済み (2+ソース)",
    articles_single: "単一ソース",
    sources_active: "アクティブソース",
    key_findings: "主要な発見",
    category_pulse: "トピック活発度",
    recent_reports: "最近の日報",
    source_health: "ソース状態",
    verified_label: "検証済み",
    single_source_label: "単一ソース",
    unverified_label: "未検証",
    importance_high: "高",
    importance_medium: "中",
    importance_low: "低",
    filter_all: "すべて",
    no_data: "データなし",
    loading: "読み込み中...",
    last_updated: "最終更新",
    credibility: "信頼度",
    source: "ソース",
    view_report: "日報を見る",
    language: "言語",
    topic_overview: "トピック概要",
    companies_tracked: "追跡企業",
    article_count: "記事",
    back_to_top: "トップへ",
    about_text: "本プラットフォームはAIDC（AIデータセンター）におけるフッ素樹脂材料の全応用——銅ケーブル相互接続、液冷システム、高周波PCB、光通信から電源システムまで——を対象に、毎日マルチソース情報を自動収集しクロス検証を行います。"
  }
};

window.getCurrentLang = function() {
  if (window.location.pathname.includes('/jp/')) return 'jp';
  return 'cn';
};

window.t = function(key, lang) {
  lang = lang || window.getCurrentLang();
  var table = window.I18N[lang] || window.I18N.cn;
  return table[key] || key;
};

// Extended category name translations for v2.0 topics
window.CATEGORY_NAMES = {
  cn: {
    copper_interconnect: "铜缆互联",
    liquid_cooling: "液冷系统",
    pcb_substrate: "高频PCB",
    optical_communication: "光通讯",
    power_system: "电源系统",
    connector: "高速连接器",
    thermal_management: "散热管理",
    capacitor: "电容器",
    rf_microwave: "RF/微波",
    semiconductor_equipment: "半导体设备",
    sensor_coating: "传感器/涂层",
    fluororesin_material: "氟树脂材料",
    company_news: "公司动态",
    regulation: "法规政策",
    market_data: "市场数据",
    market_research: "行业研究",
    community_discussion: "社区讨论",
    AIDC_development: "AIDC/互联",
    other: "其他"
  },
  jp: {
    copper_interconnect: "銅ケーブル相互接続",
    liquid_cooling: "液冷システム",
    pcb_substrate: "高周波PCB",
    optical_communication: "光通信",
    power_system: "電源システム",
    connector: "高速コネクタ",
    thermal_management: "熱管理",
    capacitor: "コンデンサ",
    rf_microwave: "RF・マイクロ波",
    semiconductor_equipment: "半導体製造装置",
    sensor_coating: "センサ・コーティング",
    fluororesin_material: "フッ素樹脂材料",
    company_news: "企業動向",
    regulation: "規制政策",
    market_data: "市場データ",
    market_research: "業界研究",
    community_discussion: "コミュニティ",
    AIDC_development: "AIDC相互接続",
    other: "その他"
  }
};

window.getCategoryName = function(cat, lang) {
  lang = lang || window.getCurrentLang();
  var map = window.CATEGORY_NAMES[lang] || window.CATEGORY_NAMES.cn;
  return map[cat] || cat;
};
