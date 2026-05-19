'use strict';

/*
  BirdWatch Visualization Module — viz.js
  ========================================
  Architecture:
    BirdWatchViz  — singleton registry + lifecycle manager
    TimelineChart — swimlane timeline of detections over time (D3 v7)

  Adding a new chart type:
    1. Create a class with constructor(container, options), update(data), resize(), destroy()
    2. Call BirdWatchViz.register('mytype', MyChartClass) at the bottom of this file
    3. Add a sub-nav button in index.html and a mount call in app.js

  Alpine.js integration:
    Alpine fetches data and calls BirdWatchViz.mount() / update() / destroy()
    D3 owns all SVG state; Alpine owns all data-fetching and filter state
*/

const BirdWatchViz = (() => {
  const _registry = {};
  let   _active   = null;

  return {
    register(name, ChartClass) {
      _registry[name] = ChartClass;
    },

    mount(name, container, options) {
      if (_active) { _active.destroy(); _active = null; }
      const Cls = _registry[name];
      if (!Cls) { console.error('BirdWatchViz: unknown chart type:', name); return null; }
      _active = new Cls(container, options);
      return _active;
    },

    update(data)  { if (_active) _active.update(data); },
    resize()      { if (_active) _active.resize();     },
    destroy()     { if (_active) { _active.destroy(); _active = null; } },
    hasActive()   { return _active !== null; },
    getActive()   { return _active; },
  };
})();


/* ═══════════════════════════════════════════════════════════════════════════
   Timeline Chart — swimlane scatter plot of detections over time
   ═══════════════════════════════════════════════════════════════════════════ */

class TimelineChart {

  constructor(container, options = {}) {
    this.el          = container;
    this.onPlayClip  = options.onPlayClip  || (() => {});
    this.onOpenPanel = options.onOpenPanel || (() => {});

    this._raw    = [];
    this._view   = [];
    this._filters = { minConf: 0.5, cameraId: '', hours: 24 };

    // 20-color scale wrapping for >20 species
    this._color = d3.scaleOrdinal(
      [...d3.schemeTableau10, ...d3.schemePastel1, ...d3.schemeSet2]
    );

    this._margin = { top: 16, right: 24, bottom: 50, left: 182 };
    this._currentXScale = null;

    this._init();
  }

  /* ── Initialise SVG skeleton ──────────────────────────────────────── */
  _init() {
    const el = d3.select(this.el);
    el.selectAll('*').remove();

    const W = this._chartW();
    const H = this._chartH();

    this._svg = el.append('svg')
      .attr('width',  W + this._margin.left + this._margin.right)
      .attr('height', H + this._margin.top  + this._margin.bottom);

    // Clip so dots don't overflow axes
    this._svg.append('defs').append('clipPath').attr('id', 'bw-clip')
      .append('rect').attr('width', W).attr('height', H + 8);

    this._g = this._svg.append('g')
      .attr('transform', `translate(${this._margin.left},${this._margin.top})`);

    this._gGrid = this._g.append('g').attr('class', 'bw-grid').lower();
    this._gX    = this._g.append('g').attr('class', 'bw-axis-x')
                         .attr('transform', `translate(0,${H})`);
    this._gY    = this._g.append('g').attr('class', 'bw-axis-y');
    this._gDots = this._g.append('g').attr('class', 'bw-dots')
                         .attr('clip-path', 'url(#bw-clip)');

    // Transparent overlay for zoom interactions
    this._zoomRect = this._g.append('rect')
      .attr('class', 'bw-zoom-rect')
      .attr('width', W).attr('height', H)
      .attr('fill', 'none').attr('cursor', 'grab');

    // Zoom: scroll-wheel or shift+drag pans; ctrl+scroll zooms
    this._zoom = d3.zoom()
      .scaleExtent([0.1, 200])
      .on('zoom', ev => this._onZoom(ev));
    this._zoomRect.call(this._zoom);

    // Tooltip
    this._tip = d3.select(this.el).append('div')
      .attr('class', 'viz-tip').style('display', 'none');

    // Scales
    this._xScale = d3.scaleTime().range([0, W]);
    this._yScale = d3.scaleBand().range([0, H]).paddingInner(0.35).paddingOuter(0.15);

    // Resize observer
    this._ro = new ResizeObserver(() => this.resize());
    this._ro.observe(this.el);
  }

  /* ── Public API ───────────────────────────────────────────────────── */

  update(data) {
    this._raw = Array.isArray(data) ? data : [];
    this._zoomReset();
    this._render();
  }

  setFilters(f) {
    this._filters = { ...this._filters, ...f };
    this._zoomReset();
    this._render();
  }

  // Called by WS live-update path — appends without full reload
  appendDetection(d) {
    this._raw.push(d);
    const cutoff = Date.now() - this._filters.hours * 3600000;
    if (new Date(d.timestamp).getTime() >= cutoff) this._render();
  }

  resize() {
    const W = this._chartW();
    this._svg.attr('width', W + this._margin.left + this._margin.right);
    this._svg.select('#bw-clip rect').attr('width', W);
    this._xScale.range([0, W]);
    this._zoomRect.attr('width', W);
    this._zoom.translateExtent([[0, 0], [W, 9999]]).extent([[0, 0], [W, 9999]]);
    this._render();
  }

  destroy() {
    if (this._ro) this._ro.disconnect();
    d3.select(this.el).selectAll('*').remove();
  }

  /* ── Internal helpers ─────────────────────────────────────────────── */

  _chartW() {
    const w = this.el.getBoundingClientRect().width || 800;
    return Math.max(200, w - this._margin.left - this._margin.right);
  }
  _chartH() { return 400; }  // base height — expanded dynamically by species count

  _zoomReset() {
    this._currentXScale = null;
    this._zoomRect.call(this._zoom.transform, d3.zoomIdentity);
  }

  _render() {
    const now    = new Date();
    const cutoff = new Date(now - this._filters.hours * 3600000);

    // Apply filters
    this._view = this._raw.filter(d =>
      d.confidence >= this._filters.minConf &&
      new Date(d.timestamp) >= cutoff &&
      (!this._filters.cameraId || d.camera_id === this._filters.cameraId) &&
      (!this._filters.species  || d.species_common === this._filters.species)
    );

    // Species sorted by detection count descending
    const counts  = d3.rollup(this._view, v => v.length, d => d.species_common);
    const species = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a));

    // Dynamic height: 42px per species lane, min 120px
    const H = Math.max(120, species.length * 42);
    const W = this._chartW();

    this._svg.attr('height', H + this._margin.top + this._margin.bottom);
    this._svg.select('#bw-clip rect').attr('height', H + 8);
    this._yScale.range([0, H]);
    this._gX.attr('transform', `translate(0,${H})`);
    this._zoomRect.attr('height', H);
    this._zoom.translateExtent([[0, 0], [W, H]]).extent([[0, 0], [W, H]]);

    // Update domain scales
    this._xScale.domain([cutoff, now]);
    this._yScale.domain(species);

    const xs = this._currentXScale || this._xScale;

    // ── X axis ──────────────────────────────────────────────────────
    this._gX.call(
      d3.axisBottom(xs).ticks(6)
        .tickFormat(d => d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }))
    );
    this._styleXAxis();

    // ── Y axis ──────────────────────────────────────────────────────
    this._gY.call(
      d3.axisLeft(this._yScale).tickSize(0).tickPadding(8)
    );
    this._gY.select('.domain').remove();
    this._gY.selectAll('.tick text')
      .style('fill', '#e2e8f0')
      .style('font-size', '12px')
      .text(d => d.length > 22 ? d.slice(0, 20) + '…' : d);

    // ── Grid lines (horizontal, one per lane) ──────────────────────
    const gridSel = this._gGrid.selectAll('line.bw-gridline').data(species);
    gridSel.enter().append('line').attr('class', 'bw-gridline')
    .merge(gridSel)
      .attr('x1', 0).attr('x2', W)
      .attr('y1', d => this._yScale(d) + this._yScale.bandwidth() / 2)
      .attr('y2', d => this._yScale(d) + this._yScale.bandwidth() / 2)
      .attr('stroke', '#1e2535').attr('stroke-width', 1);
    gridSel.exit().remove();

    // ── Detection dots ─────────────────────────────────────────────
    const self = this;
    const key  = d => (d.id != null ? String(d.id) : '') + '|' + d.timestamp + '|' + d.species_common;

    const dots = this._gDots.selectAll('circle.bw-dot').data(this._view, key);

    dots.enter().append('circle').attr('class', 'bw-dot')
      .attr('r', 0)
      .attr('fill',    d => this._color(d.species_common))
      .attr('opacity', 0.82)
      .attr('cursor',  'pointer')
      .on('mouseover', function(event, d) { self._showTip(event, d); })
      .on('mouseout',  ()        => this._tip.style('display', 'none'))
      .on('click',     (ev, d)   => {
        this.onPlayClip(d.clip_path);
        this.onOpenPanel(d.species_common, d.species_sci);
      })
    .merge(dots)
      .transition().duration(200)
      .attr('cx', d => xs(new Date(d.timestamp)))
      .attr('cy', d => (this._yScale(d.species_common) ?? 0) + this._yScale.bandwidth() / 2)
      .attr('r',  d => 3 + d.confidence * 5);  // 3px (conf=0) → 8px (conf=1)

    dots.exit().transition().duration(150).attr('r', 0).remove();

    // ── Legend ──────────────────────────────────────────────────────
    this._renderLegend(species);
  }

  _renderLegend(species) {
    let legend = d3.select(this.el).select('.bw-legend');
    if (legend.empty()) {
      legend = d3.select(this.el).append('div').attr('class', 'bw-legend');
    }
    const items = legend.selectAll('.bw-leg-item').data(species, d => d);
    const enter = items.enter().append('div').attr('class', 'bw-leg-item');
    enter.append('span').attr('class', 'bw-leg-swatch');
    enter.append('span').attr('class', 'bw-leg-label');

    enter.merge(items)
      .select('.bw-leg-swatch').style('background', d => this._color(d));
    enter.merge(items)
      .select('.bw-leg-label').text(d => d);

    items.exit().remove();
  }

  _onZoom(event) {
    const xs = event.transform.rescaleX(this._xScale);
    this._currentXScale = xs;

    this._gX.call(
      d3.axisBottom(xs).ticks(6)
        .tickFormat(d => d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }))
    );
    this._styleXAxis();

    this._gDots.selectAll('circle.bw-dot')
      .attr('cx', d => xs(new Date(d.timestamp)));

    const W = this._chartW();
    this._gGrid.selectAll('line.bw-gridline').attr('x2', W);
  }

  _styleXAxis() {
    this._gX.select('.domain').style('stroke', '#2d3748');
    this._gX.selectAll('.tick line').style('stroke', '#2d3748');
    this._gX.selectAll('.tick text').style('fill', '#a0aec0').style('font-size', '11px');
  }

  _showTip(event, d) {
    const t = new Date(d.timestamp).toLocaleString([], {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
    const bx  = this.el.getBoundingClientRect();
    const ex  = event.clientX - bx.left;
    const ey  = event.clientY - bx.top;
    const tx  = ex > bx.width - 210 ? ex - 200 : ex + 14;

    this._tip
      .style('display', 'block')
      .style('left', tx + 'px')
      .style('top',  (ey - 8) + 'px')
      .html(`
        <div class="viz-tt-name">${d.species_common}</div>
        ${d.species_sci ? `<div class="viz-tt-sci">${d.species_sci}</div>` : ''}
        <div class="viz-tt-row"><b>Time</b> ${t}</div>
        <div class="viz-tt-row"><b>Camera</b> ${d.camera_id}</div>
        <div class="viz-tt-row"><b>Confidence</b> ${Math.round(d.confidence * 100)}%</div>
        <div class="viz-tt-hint">Click to play &amp; view species</div>
      `);
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
   Species Confidence Chart — horizontal bar chart, aggregated from raw detections
   ═══════════════════════════════════════════════════════════════════════════ */

class SpeciesConfidenceChart {

  constructor(container, options = {}) {
    this.el              = container;
    this.onSpeciesSelect = options.onSpeciesSelect || (() => {});

    this._raw      = [];
    this._topN     = 15;
    this._selected = null;
    this._filters  = { minConf: 0.5, hours: 24, cameraId: '' };

    // Red(low) → Yellow → Green(high) confidence color scale
    this._confColor = d3.scaleSequential(d3.interpolateRdYlGn).domain([0.5, 1.0]);

    this._margin = { top: 20, right: 110, bottom: 50, left: 185 };
    this._init();
  }

  /* ── Setup ──────────────────────────────────────────────────────────── */
  _init() {
    d3.select(this.el).selectAll('*').remove();

    const W = this._chartW();

    this._svg = d3.select(this.el).append('svg')
      .attr('width',  W + this._margin.left + this._margin.right)
      .attr('height', 100);

    const defs = this._svg.append('defs');
    const grad = defs.append('linearGradient').attr('id', 'bw-conf-grad')
      .attr('x1', '0%').attr('x2', '100%');
    grad.append('stop').attr('offset',   '0%').attr('stop-color', this._confColor(0.50));
    grad.append('stop').attr('offset',  '50%').attr('stop-color', this._confColor(0.75));
    grad.append('stop').attr('offset', '100%').attr('stop-color', this._confColor(1.00));

    this._g    = this._svg.append('g')
      .attr('transform', `translate(${this._margin.left},${this._margin.top})`);
    this._gBars = this._g.append('g');
    this._gX    = this._g.append('g');
    this._gY    = this._g.append('g');

    // X axis label
    this._g.append('text').attr('class', 'bw-xlabel')
      .attr('text-anchor', 'middle')
      .attr('fill', '#a0aec0').attr('font-size', '11px');

    // Confidence legend (top-right corner)
    const leg = this._g.append('g').attr('class', 'bw-sc-legend');
    leg.append('rect').attr('width', 80).attr('height', 8).attr('rx', 2)
      .attr('fill', 'url(#bw-conf-grad)');
    leg.append('text').attr('y', 18).attr('fill', '#718096').attr('font-size', '10px').text('50%');
    leg.append('text').attr('class', 'leg-hi').attr('y', 18)
      .attr('fill', '#718096').attr('font-size', '10px').text('100%');
    leg.append('text').attr('y', -4).attr('fill', '#a0aec0').attr('font-size', '10px')
      .text('Avg Confidence');

    // Tooltip
    this._tip = d3.select(this.el).append('div')
      .attr('class', 'viz-tip').style('display', 'none');

    this._xScale = d3.scaleLinear().range([0, W]);
    this._yScale = d3.scaleBand().paddingInner(0.25).paddingOuter(0.12);

    this._ro = new ResizeObserver(() => this.resize());
    this._ro.observe(this.el);
  }

  /* ── Public API ───────────────────────────────────────────────────── */

  update(data) {
    this._raw = Array.isArray(data) ? data : [];
    this._render();
  }

  setFilters(f) {
    this._filters = { ...this._filters, ...f };
    this._render();
  }

  setTopN(n) {
    this._topN = n;
    this._render();
  }

  resize() {
    const W = this._chartW();
    this._xScale.range([0, W]);
    this._svg.attr('width', W + this._margin.left + this._margin.right);
    this._render();
  }

  destroy() {
    if (this._ro) this._ro.disconnect();
    d3.select(this.el).selectAll('*').remove();
  }

  /* ── Internal ────────────────────────────────────────────────────── */

  _chartW() {
    const w = this.el.getBoundingClientRect().width || 800;
    return Math.max(200, w - this._margin.left - this._margin.right);
  }

  _aggregate() {
    const cutoff = new Date(Date.now() - this._filters.hours * 3600000);
    const src    = this._raw.filter(d =>
      d.confidence >= this._filters.minConf &&
      new Date(d.timestamp) >= cutoff &&
      (!this._filters.cameraId || d.camera_id === this._filters.cameraId)
    );

    const groups = d3.group(src, d => d.species_common);
    const result = [];
    for (const [species, dets] of groups) {
      const confs = dets.map(d => d.confidence);
      result.push({
        species,
        species_sci: dets[0].species_sci || '',
        count:   dets.length,
        avgConf: d3.mean(confs),
        minConf: d3.min(confs),
        maxConf: d3.max(confs),
      });
    }
    result.sort((a, b) => b.count - a.count);
    return this._topN > 0 ? result.slice(0, this._topN) : result;
  }

  _render() {
    const data = this._aggregate();
    const W    = this._chartW();
    const H    = Math.max(60, data.length * 40);

    this._svg
      .attr('width',  W + this._margin.left + this._margin.right)
      .attr('height', H + this._margin.top  + this._margin.bottom);

    this._xScale.domain([0, d3.max(data, d => d.count) || 1]).range([0, W]);
    this._yScale.domain(data.map(d => d.species)).range([0, H]);

    // X axis
    this._gX.attr('transform', `translate(0,${H})`)
      .call(d3.axisBottom(this._xScale).ticks(5).tickFormat(d3.format('d')));
    this._gX.select('.domain').style('stroke', '#2d3748');
    this._gX.selectAll('.tick line').style('stroke', '#2d3748');
    this._gX.selectAll('.tick text').style('fill', '#a0aec0').style('font-size', '11px');

    this._g.select('.bw-xlabel')
      .attr('x', W / 2)
      .attr('y', H + 40)
      .text('Detection Count');

    // Y axis
    this._gY.call(d3.axisLeft(this._yScale).tickSize(0).tickPadding(8));
    this._gY.select('.domain').remove();
    this._gY.selectAll('.tick text')
      .style('fill',        d => d === this._selected ? '#68d391' : '#e2e8f0')
      .style('font-weight', d => d === this._selected ? '700'     : '400')
      .style('font-size', '12px')
      .text(d => d.length > 22 ? d.slice(0, 20) + '…' : d);

    // Legend position
    this._g.select('.bw-sc-legend').attr('transform', `translate(${W - 78}, 0)`);
    this._g.select('.leg-hi').attr('x', 68);

    // ── Bars ────────────────────────────────────────────────────────
    const self = this;
    const bars = this._gBars.selectAll('rect.bw-sbar').data(data, d => d.species);

    bars.enter().append('rect').attr('class', 'bw-sbar')
      .attr('x', 0).attr('rx', 3).attr('cursor', 'pointer')
      .on('mouseover', function(event, d) { self._showTip(event, d); })
      .on('mouseout',  ()      => this._tip.style('display', 'none'))
      .on('click',     (ev, d) => {
        this._selected = this._selected === d.species ? null : d.species;
        this.onSpeciesSelect(this._selected);
        this._render();
      })
    .merge(bars)
      .transition().duration(300)
      .attr('y',       d => this._yScale(d.species))
      .attr('height',  this._yScale.bandwidth())
      .attr('width',   d => this._xScale(d.count))
      .attr('fill',    d => this._confColor(d.avgConf))
      .attr('opacity', d => this._selected && d.species !== this._selected ? 0.3 : 0.88);

    bars.exit().transition().duration(150).attr('width', 0).remove();

    // ── End labels (count + avg %) ──────────────────────────────────
    const labels = this._gBars.selectAll('text.bw-sbar-lbl').data(data, d => d.species);

    labels.enter().append('text').attr('class', 'bw-sbar-lbl')
      .attr('fill', '#a0aec0').attr('font-size', '11px')
    .merge(labels)
      .transition().duration(300)
      .attr('x', d => this._xScale(d.count) + 6)
      .attr('y', d => this._yScale(d.species) + this._yScale.bandwidth() / 2 + 4)
      .text(d => `${d.count}  ${Math.round(d.avgConf * 100)}%`)
      .attr('opacity', d => this._selected && d.species !== this._selected ? 0.35 : 1);

    labels.exit().remove();
  }

  _showTip(event, d) {
    const bx = this.el.getBoundingClientRect();
    const ex = event.clientX - bx.left;
    const ey = event.clientY - bx.top;
    const tx = ex > bx.width - 220 ? ex - 215 : ex + 14;

    this._tip
      .style('display', 'block')
      .style('left', tx + 'px')
      .style('top',  (ey - 8) + 'px')
      .html(`
        <div class="viz-tt-name">${d.species}</div>
        ${d.species_sci ? `<div class="viz-tt-sci">${d.species_sci}</div>` : ''}
        <div class="viz-tt-row"><b>Detections</b> ${d.count}</div>
        <div class="viz-tt-row"><b>Avg confidence</b> ${Math.round(d.avgConf * 100)}%</div>
        <div class="viz-tt-row"><b>Range</b> ${Math.round(d.minConf * 100)}% – ${Math.round(d.maxConf * 100)}%</div>
        <div class="viz-tt-hint">Click to select &bull; filters timeline</div>
      `);
  }
}

/* ── Register built-in chart types ─────────────────────────────────────── */
BirdWatchViz.register('timeline',    TimelineChart);
BirdWatchViz.register('speciesconf', SpeciesConfidenceChart);
