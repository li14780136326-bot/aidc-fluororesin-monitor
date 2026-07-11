/**
 * AIDC Architecture Visualization Engine
 * D3.js scroll-driven scrollytelling — 8-layer full-stack penetration
 *
 * Dependencies: D3.js v7 (CDN), architecture.json, knowledge_index.json
 * Exposes: window.ArchViz
 */
(function () {
  'use strict';

  const ArchViz = {};
  window.ArchViz = ArchViz;

  // ── State ──
  let archData = null;
  let knowledgeData = null;
  let mergedLayers = [];
  let currentLayer = -1;
  let currentBranchPath = 'hybrid'; // default
  let svgRoot = null;
  let observer = null;
  let layerObservers = [];

  // ── Config ──
  const COLORS = {
    bg: '#F5F5F7',
    text: '#1D1D1F',
    secondary: '#86868B',
    accent: '#3A6FA0',
    accentLight: '#8AA9C6',
    accentSubtle: 'rgba(58,111,160,0.08)',
    accentGlow: 'rgba(58,111,160,0.25)',
    hairline: 'rgba(0,0,0,0.08)',
    white: '#FFFFFF',
    copper: '#C47A4A',
    copperLight: '#E8C9A0',
    fiber: '#4A90C4',
    fiberLight: '#A0C8E8',
    pvdf: '#5F8FB5',
    ptfe: '#3A6FA0',
    fep: '#6BA0C8',
    pfa: '#4A80B0',
    etfe: '#7AB0D0',
    fluorinated: '#34668A',
    warm: '#D4956A'
  };

  // ── Public API ──
  ArchViz.init = async function (options) {
    const opts = options || {};
    const lang = opts.lang || 'cn';
    const rootId = opts.rootId || 'archRoot';
    const svgContainerId = opts.svgContainerId || 'archSvgCanvas';

    try {
      archData = await loadArchitectureData();
      knowledgeData = await loadDynamicData();
      mergeData();

      renderPage(rootId, svgContainerId, lang);
      setupScrollObserver(lang);
      setupBranchTabs(lang);
      window.addEventListener('resize', () => redrawCurrentLayer(lang));
    } catch (err) {
      console.error('ArchViz init failed:', err);
      const root = document.getElementById(rootId);
      if (root) root.innerHTML = '<p class="kg-empty" style="padding:120px 0;text-align:center">可视化加载失败，请刷新重试</p>';
    }
  };

  // ── Data Loading ──
  async function loadArchitectureData() {
    const resp = await fetch('../data/architecture.json');
    if (!resp.ok) throw new Error('Failed to load architecture.json');
    return resp.json();
  }

  async function loadDynamicData() {
    try {
      const resp = await fetch('../data/knowledge_index.json');
      if (!resp.ok) return null;
      return resp.json();
    } catch (e) {
      console.warn('Dynamic data unavailable, using static fallback');
      return null;
    }
  }

  function mergeData() {
    mergedLayers = (archData.layers || []).map(function (layer) {
      var merged = Object.assign({}, layer);
      merged.dynamicArticles = [];
      merged.dynamicCompanies = [];

      if (knowledgeData) {
        // Match topics by topic_ids
        if (layer.topic_ids && layer.topic_ids.length && knowledgeData.topics) {
          layer.topic_ids.forEach(function (tid) {
            var topic = knowledgeData.topics.find(function (t) { return t.id === tid; });
            if (topic && topic.recent_titles) {
              topic.recent_titles.forEach(function (title) {
                if (merged.dynamicArticles.length < 3) {
                  merged.dynamicArticles.push({ title: title, source: topic.name || tid, date: topic.last_updated || '' });
                }
              });
            }
          });
        }

        // Match companies
        if (layer.company_names && layer.company_names.length && knowledgeData.companies) {
          layer.company_names.forEach(function (cname) {
            var company = knowledgeData.companies.find(function (c) {
              return (c.name || '').toLowerCase() === cname.toLowerCase();
            });
            if (company && company.recent_articles && company.recent_articles.length) {
              company.recent_articles.slice(0, 2).forEach(function (art) {
                merged.dynamicCompanies.push({
                  company: company.name,
                  ticker: company.ticker || '',
                  title: art.title || '',
                  date: art.date || '',
                  url: art.url || '#'
                });
              });
            }
          });
        }
      }
      return merged;
    });
  }

  // ── Page Rendering ──
  function renderPage(rootId, svgContainerId, lang) {
    var root = document.getElementById(rootId);
    if (!root) return;
    var suf = lang === 'jp' ? '_jp' : '_cn';

    var html = '';

    // Hero
    html += '<header class="arch-hero">' +
      '<h1 class="arch-hero-title">' + (lang === 'jp' ? 'AIDCアーキテクチャにおけるフッ素樹脂' : 'AIDC 架构中的氟树脂') + '</h1>' +
      '<p class="arch-hero-sub">' + (lang === 'jp' ? 'データセンターからナノ相互接続までの全スタック材料透過' : '从数据中心到纳米互连的全栈材料穿透') + '</p>' +
      '<p class="arch-scroll-hint">↓ ' + (lang === 'jp' ? 'スクロールして探索' : '向下滚动探索') + '</p>' +
      '</header>';

    // SVG canvas (sticky, shared across all layers)
    html += '<div class="arch-svg-sticky" id="' + svgContainerId + '"></div>';

    // Layers
    mergedLayers.forEach(function (layer, i) {
      var label = 'Layer ' + layer.level;
      var name = layer['name' + suf] || layer.name_cn || '';
      var desc = layer['description' + suf] || layer.description_cn || '';

      html += '<section class="arch-layer" id="archLayer' + i + '" data-layer="' + i + '">' +
        '<div class="arch-layer-content">' +
          '<span class="arch-layer-label">' + label + '</span>' +
          '<h2 class="arch-layer-title">' + name + '</h2>' +
          '<p class="arch-layer-desc">' + desc + '</p>';

      // Materials
      if (layer.materials && layer.materials.length) {
        html += '<div class="arch-materials">';
        layer.materials.forEach(function (mat) {
          html += '<span class="arch-material-tag">' + mat.type + '</span>' +
            '<span class="arch-material-role">' + (mat['role' + suf] || mat.role_cn || '') + '</span>' +
            '<span class="arch-material-reason">' + (mat['reason' + suf] || mat.reason_cn || '') + '</span>';
        });
        html += '</div>';
      }

      // Branch point UI (Layer 6 only)
      if (layer.is_branch_point) {
        var paths = (archData.branch_point || {}).paths || [];
        html += '<div class="arch-branch-tabs" id="archBranchTabs">';
        paths.forEach(function (p, pi) {
          html += '<button class="arch-branch-tab' + (p.id === currentBranchPath ? ' active' : '') + '" data-path="' + p.id + '">' +
            (p['name' + suf] || p.name_cn || '') + '</button>';
        });
        html += '</div>';
        // Show active path description
        var activePath = paths.find(function(p){ return p.id === currentBranchPath; }) || paths[1];
        html += '<p class="arch-branch-desc" id="archBranchDesc">' + (activePath['description' + suf] || activePath.description_cn || '') + '</p>';
        html += '<p class="arch-branch-shift" id="archBranchShift">' + (activePath['material_shift' + suf] || activePath.material_shift_cn || '') + '</p>';
      }

      // Dynamic callout
      if (layer.dynamicArticles.length || layer.dynamicCompanies.length) {
        html += '<div class="arch-dynamic-callout">';
        html += '<span class="arch-dynamic-callout-label">' + (lang === 'jp' ? '最新動向' : '最新动态') + '</span>';
        layer.dynamicArticles.forEach(function (art) {
          html += '<span class="arch-dynamic-callout-link">' + art.title.substring(0, 80) +
            (art.date ? ' <span class="arch-dynamic-date">(' + art.date.substring(0, 10) + ')</span>' : '') + '</span>';
        });
        layer.dynamicCompanies.forEach(function (co) {
          html += '<a href="' + co.url + '" target="_blank" rel="noopener" class="arch-dynamic-callout-link">' +
            '<strong>' + co.company + '</strong> ' + (co.ticker && co.ticker !== '—' ? co.ticker + ' ' : '') +
            co.title.substring(0, 70) + ' <span class="arch-dynamic-date">(' + co.date + ')</span></a>';
        });
        html += '</div>';
      }

      html += '</div></section>';
    });

    // Summary section
    html += renderSummary(lang);

    root.innerHTML = html;

    // Initialize SVG after DOM is ready
    svgRoot = d3.select('#' + svgContainerId);
    drawLayerSvg(0, lang); // Draw first layer initially
  }

  function renderSummary(lang) {
    var suf = lang === 'jp' ? '_jp' : '_cn';
    var summary = archData.material_summary;
    var materials = ['PTFE', 'FEP', 'PFA', 'ETFE', 'PVDF'];
    var layerLabels = [];
    for (var i = 1; i <= 8; i++) { layerLabels.push('L' + i); }

    var html = '<section class="arch-summary"><h2 class="kg-section-label">' +
      (lang === 'jp' ? '材料分布マトリクス' : '材料分布矩阵') + '</h2>';

    // Matrix
    html += '<div class="arch-summary-matrix">';
    // Header row
    html += '<div class="arch-summary-cell arch-summary-hd" style="font-weight:600">' +
      (lang === 'jp' ? 'フッ素樹脂' : '氟树脂') + '</div>';
    materials.forEach(function (m) {
      html += '<div class="arch-summary-cell arch-summary-hd" style="font-weight:600;text-align:center">' + m + '</div>';
    });
    // Layer rows
    mergedLayers.forEach(function (layer) {
      html += '<div class="arch-summary-cell" style="font-size:0.78rem;color:var(--text-secondary)">' +
        'L' + layer.level + ' ' + (layer['name' + suf] || layer.name_cn || '') + '</div>';
      materials.forEach(function (m) {
        var hasMat = layer.materials && layer.materials.some(function (mat) { return mat.type.indexOf(m) === 0; });
        html += '<div class="arch-summary-cell' + (hasMat ? ' highlight' : '') + '" style="text-align:center">' +
          (hasMat ? '●' : '—') + '</div>';
      });
    });
    html += '</div>';

    // Material cards
    html += '<div class="arch-material-cards">';
    materials.forEach(function (m) {
      var info = summary[m];
      if (!info) return;
      var layerCount = (info.layers || []).length;
      html += '<div class="arch-material-card">' +
        '<span class="arch-material-card-type">' + m + '</span>' +
        '<span class="arch-material-card-name">' + (info['full_name' + suf] || info.full_name_cn || '') + '</span>' +
        '<span class="arch-material-card-prop">' + (info['key_property' + suf] || info.key_property_cn || '') + '</span>' +
        '<span class="arch-material-card-layers">' + (lang === 'jp' ? '該当層: ' : '涉及层: ') + (info.layers || []).join(', ') + '</span>' +
        '</div>';
    });
    html += '</div>';

    // Knowledge graph link
    html += '<div class="arch-back-link"><a href="knowledge.html" class="kg-back">← ' +
      (lang === 'jp' ? '知識グラフに戻る' : '返回知识图谱') + '</a></div>';

    html += '</section>';
    return html;
  }

  // ── SVG Drawing (D3.js) ──
  function drawLayerSvg(layerIdx, lang, branchPath) {
    if (!svgRoot) return;
    var layer = mergedLayers[layerIdx];
    if (!layer) return;

    var bp = branchPath || currentBranchPath;
    var container = svgRoot.node();
    var W = container.clientWidth || 800;
    var H = Math.min(container.clientHeight || 500, W * 0.65);
    var pad = 40;

    svgRoot.selectAll('*').remove();

    var svg = svgRoot.append('svg')
      .attr('viewBox', '0 0 ' + W + ' ' + H)
      .attr('preserveAspectRatio', 'xMidYMid meet');

    // Background
    svg.append('rect').attr('width', W).attr('height', H).attr('fill', COLORS.bg);

    var g = svg.append('g').attr('transform', 'translate(' + pad + ',' + pad + ')');
    var iW = W - pad * 2;
    var iH = H - pad * 2;

    switch (layer.svg_key) {
      case 'building':   drawBuilding(g, iW, iH, layer); break;
      case 'rack':       drawRack(g, iW, iH, layer); break;
      case 'cooling':    drawCooling(g, iW, iH, layer); break;
      case 'server':     drawServer(g, iW, iH, layer); break;
      case 'optics':     drawOptics(g, iW, iH, layer); break;
      case 'interconnect': drawInterconnect(g, iW, iH, layer, bp); break;
      case 'pcb':        drawPcb(g, iW, iH, layer, bp); break;
      case 'chip':       drawChip(g, iW, iH, layer); break;
      default: break;
    }
  }

  // ── Layer 1: Building ──
  function drawBuilding(g, W, H, layer) {
    var cx = W / 2;
    // Sky
    g.append('rect').attr('x', 0).attr('y', 0).attr('width', W).attr('height', H * 0.25)
      .attr('fill', '#E8EDF2').attr('rx', 4);
    // Ground
    g.append('rect').attr('x', 0).attr('y', H * 0.72).attr('width', W).attr('height', H * 0.28)
      .attr('fill', '#DDE3E8').attr('rx', 2);
    // Building body
    g.append('rect').attr('x', W * 0.15).attr('y', H * 0.2).attr('width', W * 0.7).attr('height', H * 0.52)
      .attr('fill', COLORS.white).attr('stroke', COLORS.hairline).attr('stroke-width', 1).attr('rx', 3);
    // Roof — PVDF coating (highlighted)
    g.append('rect').attr('x', W * 0.15 - 6).attr('y', H * 0.17).attr('width', W * 0.7 + 12).attr('height', H * 0.06)
      .attr('fill', COLORS.accentSubtle).attr('stroke', COLORS.accent).attr('stroke-width', 1.5).attr('rx', 4);
    g.append('text').attr('x', cx).attr('y', H * 0.2).attr('text-anchor', 'middle')
      .attr('fill', COLORS.accent).attr('font-size', 11).attr('font-weight', 600).text('PVDF 涂层');
    // Interior rack silhouettes
    for (var i = 0; i < 6; i++) {
      g.append('rect').attr('x', W * 0.22 + i * W * 0.1).attr('y', H * 0.35)
        .attr('width', W * 0.06).attr('height', H * 0.32)
        .attr('fill', '#E8EBF0').attr('rx', 1);
    }
    // ETFE wiring from building edge to racks
    g.append('line').attr('x1', W * 0.05).attr('y1', H * 0.28).attr('x2', W * 0.22).attr('y2', H * 0.4)
      .attr('stroke', COLORS.etfe).attr('stroke-width', 2).attr('stroke-dasharray', '6,3');
    g.append('text').attr('x', W * 0.06).attr('y', H * 0.26)
      .attr('fill', COLORS.secondary).attr('font-size', 10).text('ETFE 线缆护套');
    // Label
    g.append('text').attr('x', cx).attr('y', H * 0.88).attr('text-anchor', 'middle')
      .attr('fill', COLORS.secondary).attr('font-size', 11)
      .text('数据中心建筑剖面 — 视野: 100m →');
  }

  // ── Layer 2: Rack ──
  function drawRack(g, W, H, layer) {
    var rackW = W * 0.09, rackH = H * 0.7, gap = W * 0.03;
    var startX = W * 0.06, startY = H * 0.1;
    for (var i = 0; i < 7; i++) {
      var x = startX + i * (rackW + gap);
      // Rack body
      g.append('rect').attr('x', x).attr('y', startY).attr('width', rackW).attr('height', rackH)
        .attr('fill', COLORS.white).attr('stroke', COLORS.hairline).attr('stroke-width', 0.8).attr('rx', 2);
      // Server slots
      for (var j = 0; j < 8; j++) {
        g.append('rect').attr('x', x + 3).attr('y', startY + 8 + j * (rackH / 8))
          .attr('width', rackW - 6).attr('height', rackH / 9)
          .attr('fill', '#F0F1F5').attr('rx', 1);
      }
      // PTFE insulator between racks
      if (i < 6) {
        g.append('rect').attr('x', x + rackW).attr('y', startY + rackH * 0.2)
          .attr('width', gap).attr('height', rackH * 0.6)
          .attr('fill', COLORS.accentSubtle).attr('stroke', COLORS.accentLight).attr('stroke-width', 0.5);
        g.append('text').attr('x', x + rackW + gap / 2).attr('y', startY + rackH * 0.15)
          .attr('text-anchor', 'middle').attr('fill', COLORS.accent).attr('font-size', 7).text('PTFE');
      }
    }
    g.append('text').attr('x', W / 2).attr('y', H * 0.95).attr('text-anchor', 'middle')
      .attr('fill', COLORS.secondary).attr('font-size', 11)
      .text('机柜排列剖面 — 冷热通道结构 →');
  }

  // ── Layer 3: Cooling ──
  function drawCooling(g, W, H, layer) {
    // Rack silhouettes (faded)
    var rackW = W * 0.08, rackH = H * 0.55, gap = W * 0.04;
    for (var i = 0; i < 6; i++) {
      g.append('rect').attr('x', W * 0.08 + i * (rackW + gap)).attr('y', H * 0.12)
        .attr('width', rackW).attr('height', rackH)
        .attr('fill', '#EEF0F3').attr('rx', 1);
    }
    // PVDF cooling pipes (highlighted)
    var pipeY = H * 0.25;
    g.append('rect').attr('x', W * 0.02).attr('y', pipeY).attr('width', W * 0.96).attr('height', 10)
      .attr('fill', COLORS.accentSubtle).attr('stroke', COLORS.pvdf).attr('stroke-width', 1.5).attr('rx', 5);
    g.append('text').attr('x', W * 0.05).attr('y', pipeY - 6)
      .attr('fill', COLORS.pvdf).attr('font-size', 10).attr('font-weight', 600).text('PVDF 供液管路');

    var pipeY2 = H * 0.5;
    g.append('rect').attr('x', W * 0.02).attr('y', pipeY2).attr('width', W * 0.96).attr('height', 10)
      .attr('fill', COLORS.accentSubtle).attr('stroke', COLORS.pvdf).attr('stroke-width', 1.5).attr('rx', 5);
    g.append('text').attr('x', W * 0.05).attr('y', pipeY2 - 6)
      .attr('fill', COLORS.pvdf).attr('font-size', 10).attr('font-weight', 600).text('PVDF 回液管路');

    // Immersion tank
    g.append('rect').attr('x', W * 0.3).attr('y', H * 0.6).attr('width', W * 0.4).attr('height', H * 0.28)
      .attr('fill', 'rgba(52,102,138,0.06)').attr('stroke', COLORS.fluorinated).attr('stroke-width', 1).attr('rx', 6);
    g.append('text').attr('x', W / 2).attr('y', H * 0.72).attr('text-anchor', 'middle')
      .attr('fill', COLORS.fluorinated).attr('font-size', 11).attr('font-weight', 600).text('浸没式冷却槽');
    g.append('text').attr('x', W / 2).attr('y', H * 0.78).attr('text-anchor', 'middle')
      .attr('fill', COLORS.secondary).attr('font-size', 10).text('氟化液介质 | PFA 内衬');
  }

  // ── Layer 4: Server ──
  function drawServer(g, W, H, layer) {
    // Motherboard
    g.append('rect').attr('x', W * 0.05).attr('y', H * 0.2).attr('width', W * 0.9).attr('height', H * 0.55)
      .attr('fill', '#2D5A3D').attr('rx', 4);
    // PTFE backplane (highlighted)
    g.append('rect').attr('x', W * 0.08).attr('y', H * 0.24).attr('width', W * 0.84).attr('height', H * 0.08)
      .attr('fill', COLORS.accentSubtle).attr('stroke', COLORS.ptfe).attr('stroke-width', 1.5).attr('rx', 2);
    g.append('text').attr('x', W / 2).attr('y', H * 0.29).attr('text-anchor', 'middle')
      .attr('fill', COLORS.ptfe).attr('font-size', 10).attr('font-weight', 600).text('PTFE 高速背板基材');

    // Daughter cards
    for (var i = 0; i < 4; i++) {
      g.append('rect').attr('x', W * 0.12 + i * W * 0.2).attr('y', H * 0.4)
        .attr('width', W * 0.14).attr('height', H * 0.28)
        .attr('fill', '#3A6D4A').attr('stroke', '#5A9A6A').attr('stroke-width', 0.5).attr('rx', 2);
    }
    // FEP internal cables (highlighted)
    g.append('line').attr('x1', W * 0.2).attr('y1', H * 0.32).attr('x2', W * 0.2).attr('y2', H * 0.4)
      .attr('stroke', COLORS.fep).attr('stroke-width', 2.5);
    g.append('line').attr('x1', W * 0.5).attr('y1', H * 0.32).attr('x2', W * 0.5).attr('y2', H * 0.4)
      .attr('stroke', COLORS.fep).attr('stroke-width', 2.5);
    g.append('text').attr('x', W * 0.51).attr('y', H * 0.37)
      .attr('fill', COLORS.fep).attr('font-size', 9).attr('font-weight', 600).text('FEP 线缆绝缘');

    // Signal annotation
    g.append('text').attr('x', W / 2).attr('y', H * 0.92).attr('text-anchor', 'middle')
      .attr('fill', COLORS.secondary).attr('font-size', 11)
      .text('服务器主板剖面 — 224Gbps PAM4 信号路径 →');
  }

  // ── Layer 5: Optical Module ──
  function drawOptics(g, W, H, layer) {
    var cx = W / 2, cy = H / 2;
    // Module housing
    g.append('rect').attr('x', cx - W * 0.35).attr('y', cy - H * 0.25).attr('width', W * 0.7).attr('height', H * 0.5)
      .attr('fill', COLORS.white).attr('stroke', COLORS.hairline).attr('stroke-width', 1).attr('rx', 6);
    // Fiber entry (left)
    g.append('circle').attr('cx', cx - W * 0.3).attr('cy', cy).attr('r', 8).attr('fill', COLORS.fiberLight).attr('stroke', COLORS.fiber).attr('stroke-width', 1.5);
    g.append('line').attr('x1', 0).attr('y1', cy).attr('x2', cx - W * 0.3 - 8).attr('y2', cy)
      .attr('stroke', COLORS.fiber).attr('stroke-width', 2);
    // PFA buffer (highlighted ring around fiber)
    g.append('circle').attr('cx', cx - W * 0.3).attr('cy', cy).attr('r', 13)
      .attr('fill', 'none').attr('stroke', COLORS.pfa).attr('stroke-width', 2.5).attr('stroke-dasharray', '4,2');
    g.append('text').attr('x', cx - W * 0.3).attr('y', cy - 18)
      .attr('text-anchor', 'middle').attr('fill', COLORS.pfa).attr('font-size', 9).attr('font-weight', 600).text('PFA 缓冲层');
    // Laser diode
    g.append('rect').attr('x', cx - W * 0.1).attr('y', cy - H * 0.05).attr('width', W * 0.08).attr('height', H * 0.1)
      .attr('fill', '#E84A4A').attr('rx', 2);
    // Lens system
    g.append('ellipse').attr('cx', cx + W * 0.08).attr('cy', cy).attr('rx', W * 0.06).attr('ry', H * 0.12)
      .attr('fill', 'none').attr('stroke', COLORS.accent).attr('stroke-width', 1);
    // PTFE spacer
    g.append('rect').attr('x', cx + W * 0.15).attr('y', cy - H * 0.15).attr('width', W * 0.04).attr('height', H * 0.3)
      .attr('fill', COLORS.accentSubtle).attr('stroke', COLORS.ptfe).attr('stroke-width', 1);
    g.append('text').attr('x', cx + W * 0.17).attr('y', cy + H * 0.02)
      .attr('fill', COLORS.ptfe).attr('font-size', 9).attr('font-weight', 600).text('PTFE 绝缘垫');
    // Electrical connector (right)
    g.append('rect').attr('x', cx + W * 0.23).attr('y', cy - H * 0.15).attr('width', W * 0.08).attr('height', H * 0.3)
      .attr('fill', COLORS.copperLight).attr('stroke', COLORS.copper).attr('stroke-width', 1).attr('rx', 2);
    g.append('text').attr('x', cx + W * 0.27).attr('y', cy + H * 0.32)
      .attr('text-anchor', 'middle').attr('fill', COLORS.secondary).attr('font-size', 9).text('金手指');
  }

  // ── Layer 6: Interconnect (Branch Point) ──
  function drawInterconnect(g, W, H, layer, branchPath) {
    var cx = W / 2, cy = H / 2;
    var bp = branchPath || 'hybrid';
    var fiberW = bp === 'pure-optical' ? 1.0 : (bp === 'hybrid' ? 0.5 : 0.0);
    var copperW = bp === 'pure-copper' ? 1.0 : (bp === 'hybrid' ? 0.5 : 0.0);

    // Central switch/ASIC
    g.append('rect').attr('x', cx - W * 0.08).attr('y', cy - H * 0.12).attr('width', W * 0.16).attr('height', H * 0.24)
      .attr('fill', COLORS.white).attr('stroke', COLORS.text).attr('stroke-width', 1.5).attr('rx', 4);
    g.append('text').attr('x', cx).attr('y', cy + H * 0.04).attr('text-anchor', 'middle')
      .attr('fill', COLORS.text).attr('font-size', 10).attr('font-weight', 600).text('Switch/ASIC');

    // Fiber path (left)
    if (fiberW > 0) {
      var fAlpha = fiberW;
      g.append('line').attr('x1', cx - W * 0.08).attr('y1', cy - H * 0.04).attr('x2', 0).attr('y2', cy - H * 0.04)
        .attr('stroke', COLORS.fiber).attr('stroke-width', 2 + fiberW * 2).attr('opacity', 0.3 + fAlpha * 0.7);
      // CPO block
      g.append('rect').attr('x', W * 0.05).attr('y', cy - H * 0.2).attr('width', W * 0.12).attr('height', H * 0.16)
        .attr('fill', COLORS.accentSubtle).attr('stroke', COLORS.fiber).attr('stroke-width', 1).attr('rx', 3);
      g.append('text').attr('x', W * 0.11).attr('y', cy - H * 0.1).attr('text-anchor', 'middle')
        .attr('fill', COLORS.fiber).attr('font-size', 8).attr('font-weight', 600).text('CPO/硅光子');
      // PFA label
      g.append('text').attr('x', W * 0.11).attr('y', cy - H * 0.03).attr('text-anchor', 'middle')
        .attr('fill', COLORS.pfa).attr('font-size', 8).text('PFA/FEP 缓冲');
    }

    // Copper path (right)
    if (copperW > 0) {
      var cAlpha = copperW;
      g.append('line').attr('x1', cx + W * 0.08).attr('y1', cy + H * 0.04).attr('x2', W).attr('y2', cy + H * 0.04)
        .attr('stroke', COLORS.copper).attr('stroke-width', 2 + copperW * 2).attr('opacity', 0.3 + cAlpha * 0.7);
      // Connector block
      g.append('rect').attr('x', W * 0.68).attr('y', cy + H * 0.08).attr('width', W * 0.2).attr('height', H * 0.18)
        .attr('fill', COLORS.accentSubtle).attr('stroke', COLORS.copper).attr('stroke-width', 1).attr('rx', 3);
      g.append('text').attr('x', W * 0.78).attr('y', cy + H * 0.18).attr('text-anchor', 'middle')
        .attr('fill', COLORS.copper).attr('font-size', 8).attr('font-weight', 600).text('连接器/DAC');
      // PTFE label
      g.append('text').attr('x', W * 0.78).attr('y', cy + H * 0.28).attr('text-anchor', 'middle')
        .attr('fill', COLORS.ptfe).attr('font-size', 8).text('PTFE 绝缘体');
    }

    // PCB substrate (below)
    g.append('rect').attr('x', cx - W * 0.25).attr('y', cy + H * 0.3).attr('width', W * 0.5).attr('height', H * 0.08)
      .attr('fill', COLORS.accentSubtle).attr('stroke', COLORS.ptfe).attr('stroke-width', 1).attr('rx', 2);
    g.append('text').attr('x', cx).attr('y', cy + H * 0.35).attr('text-anchor', 'middle')
      .attr('fill', COLORS.ptfe).attr('font-size', 9).attr('font-weight', 600).text('PTFE 高频基板 (Dk≈2.1)');

    // Branch path indicator
    var pathLabel = bp === 'pure-optical' ? '纯光路径' : (bp === 'pure-copper' ? '纯铜路径' : '混合路径');
    g.append('text').attr('x', cx).attr('y', H * 0.96).attr('text-anchor', 'middle')
      .attr('fill', COLORS.accent).attr('font-size', 12).attr('font-weight', 600)
      .text('当前: ' + pathLabel);
  }

  // ── Layer 7: PCB Substrate ──
  function drawPcb(g, W, H, layer, branchPath) {
    var bp = branchPath || 'hybrid';
    var ptfeLayers = bp === 'pure-copper' ? 6 : (bp === 'hybrid' ? 4 : 2);

    // PCB stack
    var boardX = W * 0.1, boardW = W * 0.8, boardY = H * 0.1, boardH = H * 0.7;
    g.append('rect').attr('x', boardX).attr('y', boardY).attr('width', boardW).attr('height', boardH)
      .attr('fill', '#F5F0E8').attr('stroke', COLORS.hairline).attr('stroke-width', 1).attr('rx', 2);

    // Copper layers
    for (var i = 0; i < 8; i++) {
      g.append('rect').attr('x', boardX + 4).attr('y', boardY + 4 + i * (boardH / 8)).attr('width', boardW - 8).attr('height', 2)
        .attr('fill', COLORS.copper);
    }

    // PTFE dielectric layers (highlighted)
    var ptfeY = [];
    var step = boardH / (ptfeLayers + 1);
    for (var j = 0; j < ptfeLayers; j++) {
      var py = boardY + step * (j + 0.5);
      ptfeY.push(py);
      g.append('rect').attr('x', boardX + 10).attr('y', py - 4).attr('width', boardW - 20).attr('height', 8)
        .attr('fill', COLORS.accentSubtle).attr('stroke', COLORS.ptfe).attr('stroke-width', 1).attr('rx', 1);
    }

    // Annotations
    g.append('text').attr('x', boardX + boardW / 2).attr('y', boardY - 8).attr('text-anchor', 'middle')
      .attr('fill', COLORS.ptfe).attr('font-size', 10).attr('font-weight', 600).text('PTFE/陶瓷复合层压板');

    // Signal trace
    g.append('line').attr('x1', boardX).attr('y1', ptfeY[0]).attr('x2', boardX + boardW).attr('y2', ptfeY[ptfeLayers - 1])
      .attr('stroke', COLORS.accentLight).attr('stroke-width', 1).attr('stroke-dasharray', '4,4');

    // Branch-dependent note
    var note = bp === 'pure-copper' ? '纯铜架构: 6层PTFE, 高频损耗要求最高' : (bp === 'pure-optical' ? '纯光架构: 2层PTFE, 仅控制板需要' : '混合架构: 4层PTFE, 信号+电源分层');
    g.append('text').attr('x', W / 2).attr('y', H * 0.94).attr('text-anchor', 'middle')
      .attr('fill', COLORS.secondary).attr('font-size', 10).text(note);
  }

  // ── Layer 8: Chip Package ──
  function drawChip(g, W, H, layer) {
    var cx = W / 2, cy = H * 0.4;
    // Substrate
    g.append('rect').attr('x', cx - W * 0.3).attr('y', cy + H * 0.05).attr('width', W * 0.6).attr('height', H * 0.08)
      .attr('fill', '#F5F0E8').attr('stroke', COLORS.hairline).attr('stroke-width', 0.8).attr('rx', 2);
    // Die
    g.append('rect').attr('x', cx - W * 0.15).attr('y', cy - H * 0.15).attr('width', W * 0.3).attr('height', H * 0.2)
      .attr('fill', '#1D1D1F').attr('rx', 3);
    g.append('text').attr('x', cx).attr('y', cy - H * 0.02).attr('text-anchor', 'middle')
      .attr('fill', COLORS.white).attr('font-size', 10).attr('font-weight', 500).text('ASIC/GPU Die');

    // Bumps
    for (var i = 0; i < 8; i++) {
      g.append('circle').attr('cx', cx - W * 0.1 + i * W * 0.028).attr('cy', cy + H * 0.05)
        .attr('r', 3).attr('fill', COLORS.copper).attr('stroke', COLORS.copperLight).attr('stroke-width', 0.5);
    }

    // Underfill (highlighted)
    g.append('rect').attr('x', cx - W * 0.17).attr('y', cy + H * 0.03).attr('width', W * 0.34).attr('height', H * 0.04)
      .attr('fill', COLORS.accentSubtle).attr('stroke', COLORS.pfa).attr('stroke-width', 1).attr('rx', 1);
    g.append('text').attr('x', cx + W * 0.2).attr('y', cy + H * 0.06)
      .attr('fill', COLORS.pfa).attr('font-size', 8).attr('font-weight', 600).text('氟聚合物 underfill');

    // Low-K dielectric layer (highlighted)
    g.append('rect').attr('x', cx - W * 0.22).attr('y', cy - H * 0.22).attr('width', W * 0.44).attr('height', H * 0.05)
      .attr('fill', 'rgba(58,111,160,0.12)').attr('stroke', COLORS.ptfe).attr('stroke-width', 1).attr('rx', 1);
    g.append('text').attr('x', cx + W * 0.25).attr('y', cy - H * 0.19)
      .attr('fill', COLORS.ptfe).attr('font-size', 8).attr('font-weight', 600).text('PTFE Low-K 介质 (Dk→1.9)');

    // RDL layers
    for (var j = 0; j < 3; j++) {
      g.append('line').attr('x1', cx - W * 0.25).attr('y1', cy - H * 0.1 + j * H * 0.04)
        .attr('x2', cx + W * 0.25).attr('y2', cy - H * 0.1 + j * H * 0.04)
        .attr('stroke', COLORS.copperLight).attr('stroke-width', 1);
    }
    g.append('text').attr('x', cx + W * 0.28).attr('y', cy - H * 0.06)
      .attr('fill', COLORS.secondary).attr('font-size', 8).text('RDL 再分布层');

    // Scale indicator
    g.append('line').attr('x1', cx - W * 0.3).attr('y1', H * 0.88).attr('x2', cx - W * 0.1).attr('y2', H * 0.88)
      .attr('stroke', COLORS.secondary).attr('stroke-width', 1);
    g.append('text').attr('x', cx - W * 0.2).attr('y', H * 0.85)
      .attr('text-anchor', 'middle').attr('fill', COLORS.secondary).attr('font-size', 9).text('≈ 20μm');
  }

  // ── Scroll Observer ──
  function setupScrollObserver(lang) {
    // Clean up previous observers
    if (observer) observer.disconnect();
    layerObservers = [];

    var layers = document.querySelectorAll('.arch-layer');
    if (!layers.length) return;

    var svgContainer = document.getElementById('archSvgCanvas');
    var options = { threshold: [0, 0.3, 0.6, 0.9] };

    observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var idx = parseInt(entry.target.getAttribute('data-layer'), 10);
        if (isNaN(idx)) return;

        if (entry.isIntersecting && entry.intersectionRatio >= 0.3) {
          if (idx !== currentLayer) {
            currentLayer = idx;
            drawLayerSvg(idx, lang, currentBranchPath);
          }
          // Handle branch scroll for Layer 6
          if (idx === 6 && entry.intersectionRatio >= 0.7) {
            var paths = ['pure-optical', 'hybrid', 'pure-copper'];
            var ratioInLayer = Math.min(1, Math.max(0, (entry.intersectionRatio - 0.3) / 0.6));
            var pathIdx = Math.min(2, Math.floor(ratioInLayer * 3));
            if (paths[pathIdx] !== currentBranchPath) {
              currentBranchPath = paths[pathIdx];
              drawLayerSvg(6, lang, currentBranchPath);
              updateBranchUI(lang);
            }
          }
        }
      });
    }, options);

    layers.forEach(function (layer) { observer.observe(layer); });
  }

  // ── Branch Tab UI ──
  function setupBranchTabs(lang) {
    // Use event delegation since tabs are dynamically rendered
    document.addEventListener('click', function (e) {
      var tab = e.target.closest('.arch-branch-tab');
      if (!tab) return;
      var path = tab.getAttribute('data-path');
      if (path && path !== currentBranchPath) {
        currentBranchPath = path;
        drawLayerSvg(6, lang, currentBranchPath);
        updateBranchUI(lang);
      }
    });
  }

  function updateBranchUI(lang) {
    var bp = archData.branch_point;
    var paths = bp.paths || [];
    var activePath = paths.find(function (p) { return p.id === currentBranchPath; }) || paths[1];
    var suf = lang === 'jp' ? '_jp' : '_cn';

    // Update tabs
    var tabs = document.querySelectorAll('.arch-branch-tab');
    tabs.forEach(function (tab) {
      var p = tab.getAttribute('data-path');
      if (p === currentBranchPath) { tab.classList.add('active'); }
      else { tab.classList.remove('active'); }
    });

    // Update description
    var descEl = document.getElementById('archBranchDesc');
    if (descEl) descEl.textContent = activePath['description' + suf] || activePath.description_cn || '';

    var shiftEl = document.getElementById('archBranchShift');
    if (shiftEl) shiftEl.textContent = activePath['material_shift' + suf] || activePath.material_shift_cn || '';
  }

  function redrawCurrentLayer(lang) {
    if (currentLayer >= 0) {
      drawLayerSvg(currentLayer, lang, currentBranchPath);
    }
  }
})();
