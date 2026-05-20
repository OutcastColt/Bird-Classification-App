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

/* ═══════════════════════════════════════════════════════════════════════════
   Spectrogram Chart — real-time scrolling FFT waterfall via WebSocket PCM
   ═══════════════════════════════════════════════════════════════════════════ */

class SpectrogramChart {
  static FFT_SIZE    = 1024;       // FFT window (samples)
  static HOP_SIZE    = 512;        // hop between windows (samples)
  static SAMPLE_RATE = 48000;      // Hz (matches FFmpeg output)
  static MAX_FREQ    = 8000;       // Hz — display ceiling (all bird calls)
  static CANVAS_H    = 300;        // px height of spectrogram

  constructor(container, options = {}) {
    this.el          = container;
    this.cameraId    = options.cameraId    || '';
    this.onOpenPanel = options.onOpenPanel || (() => {});

    this._sampleBuf  = [];          // accumulated float32 samples
    this._detections = [];          // [{timestamp, species_common, confidence}]
    this._colTimes   = [];          // ms timestamp per rendered column
    this._ws         = null;
    this._normMax    = 1;           // rolling normalisation ceiling

    this._init();
  }

  /* ── Setup ──────────────────────────────────────────────────────────── */
  _init() {
    const el = d3.select(this.el);
    el.selectAll('*').remove();

    // Status bar
    const hdr = el.append('div').attr('class', 'bw-spec-hdr');
    this._dot   = hdr.append('span').attr('class', 'bw-spec-dot');
    this._lbl   = hdr.append('span').attr('class', 'bw-spec-lbl')
                     .text(this.cameraId ? `${this.cameraId}` : 'Select a camera above');

    // Wrapper: freq axis + canvas side by side
    const wrap = el.append('div').style('display', 'flex').style('align-items', 'stretch');

    // Frequency axis (40px wide canvas on the left)
    this._freqAxisCanvas = wrap.append('canvas')
      .attr('width', 40).attr('height', SpectrogramChart.CANVAS_H)
      .style('flex-shrink', '0').node();
    this._drawFreqAxis();

    // Main spectrogram canvas
    this._canvas = wrap.append('canvas')
      .attr('height', SpectrogramChart.CANVAS_H)
      .style('flex', '1').style('cursor', 'crosshair')
      .node();
    this._ctx = this._canvas.getContext('2d');

    // Offscreen back buffer (avoids draw-to-self artefacts)
    this._back    = document.createElement('canvas');
    this._back.height = SpectrogramChart.CANVAS_H;
    this._backCtx = this._back.getContext('2d');

    // Tooltip
    this._tip = d3.select(this.el).append('div')
      .attr('class', 'viz-tip').style('display', 'none');

    // Mouse events
    this._canvas.addEventListener('mousemove',  e => this._onMouse(e));
    this._canvas.addEventListener('mouseleave', () => this._tip.style('display', 'none'));

    // Time axis below canvas
    const timeWrap = el.append('div').style('display', 'flex');
    timeWrap.append('div').style('width', '40px').style('flex-shrink', '0');
    this._timeCanvas = timeWrap.append('canvas')
      .attr('height', 20).style('flex', '1').node();

    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(this.el);
    this._resize();

    if (this.cameraId) this._connectWS();
  }

  _resize() {
    const W = Math.max(200, (this.el.getBoundingClientRect().width || 900) - 40);
    const H = SpectrogramChart.CANVAS_H;
    this._W = W;
    this._canvas.width      = W;
    this._back.width        = W;
    this._timeCanvas.width  = W;
    // Fill dark
    this._ctx.fillStyle = '#07090f';
    this._ctx.fillRect(0, 0, W, H);
    this._backCtx.fillStyle = '#07090f';
    this._backCtx.fillRect(0, 0, W, H);
    this._colTimes = new Array(W).fill(0);
    this._drawTimeAxis();
  }

  /* ── WebSocket ──────────────────────────────────────────────────────── */
  _connectWS() {
    if (this._ws) { try { this._ws.close(); } catch(e){} this._ws = null; }
    if (!this.cameraId) return;

    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    this._ws = new WebSocket(`${proto}://${location.host}/ws/audio/${this.cameraId}`);
    this._ws.binaryType = 'arraybuffer';

    this._ws.onopen  = () => {
      this._dot.classed('bw-spec-dot-on', true);
      this._lbl.text(this.cameraId);
    };
    this._ws.onclose = () => {
      this._dot.classed('bw-spec-dot-on', false);
      setTimeout(() => this._connectWS(), 3000);
    };
    this._ws.onmessage = e => this._onChunk(e.data);
  }

  /* ── Audio processing ───────────────────────────────────────────────── */
  _onChunk(ab) {
    // Parse: [4-byte LE uint32 tsLen][tsBytes UTF-8][Int16 PCM...]
    const view  = new DataView(ab);
    const tsLen = view.getUint32(0, true);
    const ts    = new TextDecoder().decode(new Uint8Array(ab, 4, tsLen));
    const ts_ms = new Date(ts).getTime();
    const pcm16 = new Int16Array(ab, 4 + tsLen);

    // Int16 → float32, append to buffer
    const chunkStartMs = ts_ms - (pcm16.length / SpectrogramChart.SAMPLE_RATE) * 1000;
    for (let i = 0; i < pcm16.length; i++) this._sampleBuf.push(pcm16[i] / 32768);

    // Process complete FFT windows
    const FFT = SpectrogramChart.FFT_SIZE;
    const HOP = SpectrogramChart.HOP_SIZE;
    let win = 0;
    while (this._sampleBuf.length >= FFT) {
      const mag   = this._fft(this._sampleBuf, FFT);
      const colTs = chunkStartMs + (win * HOP / SpectrogramChart.SAMPLE_RATE) * 1000;
      this._renderColumn(mag, colTs);
      this._sampleBuf.splice(0, HOP);
      win++;
    }
    this._drawTimeAxis();
    this._renderDetectionOverlay();
  }

  _fft(samples, n) {
    const re = new Float32Array(n);
    const im = new Float32Array(n);
    // Hanning window
    for (let i = 0; i < n; i++) {
      re[i] = (samples[i] || 0) * 0.5 * (1 - Math.cos(6.2832 * i / (n - 1)));
    }
    // Bit-reversal
    let j = 0;
    for (let i = 1; i < n; i++) {
      let b = n >> 1;
      for (; j & b; b >>= 1) j ^= b;
      j ^= b;
      if (i < j) { [re[i], re[j]] = [re[j], re[i]]; }
    }
    // Butterfly
    for (let len = 2; len <= n; len <<= 1) {
      const ang = -6.2832 / len;
      const wr = Math.cos(ang), wi = Math.sin(ang);
      for (let i = 0; i < n; i += len) {
        let cr = 1, ci = 0;
        const half = len >> 1;
        for (let k = 0; k < half; k++) {
          const ur = re[i+k],     ui = im[i+k];
          const vr = re[i+k+half]*cr - im[i+k+half]*ci;
          const vi = re[i+k+half]*ci + im[i+k+half]*cr;
          re[i+k]      = ur+vr; im[i+k]      = ui+vi;
          re[i+k+half] = ur-vr; im[i+k+half] = ui-vi;
          const nr = cr*wr - ci*wi; ci = cr*wi + ci*wr; cr = nr;
        }
      }
    }
    // Log magnitude (first half, 0 → Nyquist)
    const half = n >> 1;
    const mag  = new Float32Array(half);
    for (let i = 0; i < half; i++) {
      mag[i] = Math.log1p(Math.sqrt(re[i]*re[i] + im[i]*im[i]));
    }
    return mag;
  }

  /* ── Rendering ──────────────────────────────────────────────────────── */
  _renderColumn(mag, ts_ms) {
    const W = this._W;
    const H = SpectrogramChart.CANVAS_H;
    const binsToShow = Math.floor(
      SpectrogramChart.MAX_FREQ / (SpectrogramChart.SAMPLE_RATE / 2) * (SpectrogramChart.FFT_SIZE >> 1)
    );

    // Rolling normalisation (avoids fixed-max issues with varying environments)
    let colMax = 0;
    for (let b = 0; b < binsToShow; b++) if (mag[b] > colMax) colMax = mag[b];
    this._normMax = this._normMax * 0.9995 + colMax * 0.0005 + 0.001;

    // Build 1-pixel-wide column as ImageData
    const col = this._ctx.createImageData(1, H);
    for (let py = 0; py < H; py++) {
      const bin   = Math.floor((1 - py / H) * binsToShow);
      const level = Math.min(1, (mag[Math.min(bin, mag.length - 1)] || 0) / this._normMax);
      const [r, g, b] = this._colormap(level);
      const idx = py * 4;
      col.data[idx]   = r;
      col.data[idx+1] = g;
      col.data[idx+2] = b;
      col.data[idx+3] = 255;
    }

    // Scroll: copy main → back (shifted 1px left), write new column on right, copy back
    this._backCtx.drawImage(this._canvas, -1, 0);
    this._backCtx.putImageData(col, W - 1, 0);
    this._ctx.drawImage(this._back, 0, 0);

    // Track column timestamps (circular shift)
    this._colTimes.push(ts_ms);
    if (this._colTimes.length > W) this._colTimes.shift();
  }

  _colormap(t) {
    // Spectrogram palette: black → deep blue → cyan → green → yellow → white
    if (t <= 0)    return [0, 0, 0];
    if (t < 0.15)  { const s = t / 0.15;        return [0, 0, Math.round(s * 180)]; }
    if (t < 0.35)  { const s = (t-0.15)/0.20;   return [0, Math.round(s*180), Math.round(180+s*75)]; }
    if (t < 0.55)  { const s = (t-0.35)/0.20;   return [0, Math.round(180+s*75), Math.round(255-s*100)]; }
    if (t < 0.75)  { const s = (t-0.55)/0.20;   return [Math.round(s*255), 255, 0]; }
    /* t < 1 */    { const s = (t-0.75)/0.25;   return [255, 255, Math.round(s*255)]; }
  }

  _renderDetectionOverlay() {
    if (!this._detections.length || !this._colTimes.length) return;
    const W = this._W;
    const H = SpectrogramChart.CANVAS_H;
    const ctx = this._ctx;

    ctx.save();
    for (const det of this._detections) {
      const det_ms = new Date(det.timestamp).getTime();
      // Find the canvas column closest to this timestamp
      let x = -1;
      for (let i = 0; i < this._colTimes.length; i++) {
        if (this._colTimes[i] >= det_ms) { x = i; break; }
      }
      if (x < 0 || x >= W) continue;

      // Deterministic color from species name
      const hue = Math.abs(
        det.species_common.split('').reduce((h, c) => ((h << 5) - h) + c.charCodeAt(0), 0)
      ) % 360;

      ctx.globalAlpha = 0.8;
      ctx.strokeStyle = `hsl(${hue},100%,65%)`;
      ctx.lineWidth   = 1.5;
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
      ctx.setLineDash([]);

      // Species label at top
      ctx.globalAlpha = 0.95;
      ctx.fillStyle   = `hsl(${hue},100%,75%)`;
      ctx.font        = 'bold 10px sans-serif';
      const label = det.species_common.split(' ').slice(0, 2).join(' ');
      // Avoid label going off right edge
      const lx = x + 3 > W - 60 ? x - 62 : x + 3;
      ctx.fillText(label, lx, 14);
    }
    ctx.restore();
  }

  _drawFreqAxis() {
    const ctx = this._freqAxisCanvas.getContext('2d');
    const H   = SpectrogramChart.CANVAS_H;
    ctx.fillStyle = '#0f1117';
    ctx.fillRect(0, 0, 40, H);
    ctx.fillStyle   = '#718096';
    ctx.font        = '9px sans-serif';
    ctx.textAlign   = 'right';
    for (const f of [8000, 6000, 4000, 2000, 1000, 500]) {
      const y = Math.round((1 - f / SpectrogramChart.MAX_FREQ) * H);
      ctx.fillText(f >= 1000 ? (f/1000) + 'k' : f, 36, y + 3);
      ctx.fillStyle = '#2d3748';
      ctx.fillRect(37, y, 3, 1);
      ctx.fillStyle = '#718096';
    }
    // kHz label
    ctx.save();
    ctx.translate(8, H / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = 'center';
    ctx.fillStyle = '#4a5568';
    ctx.fillText('kHz', 0, 0);
    ctx.restore();
  }

  _drawTimeAxis() {
    if (!this._timeCanvas) return;
    const ctx = this._timeCanvas.getContext('2d');
    const W   = this._W;
    ctx.fillStyle = '#0f1117';
    ctx.fillRect(0, 0, W, 20);
    ctx.fillStyle = '#718096';
    ctx.font      = '9px sans-serif';
    ctx.textAlign = 'center';
    // Draw a tick every ~100px
    for (let x = 0; x < W; x += 100) {
      const ts_ms = this._colTimes[x];
      if (!ts_ms) continue;
      const label = new Date(ts_ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      ctx.fillText(label, x, 12);
    }
  }

  _onMouse(e) {
    const rect = this._canvas.getBoundingClientRect();
    const x    = Math.floor(e.clientX - rect.left);
    const y    = Math.floor(e.clientY - rect.top);
    const freq = Math.round((1 - y / SpectrogramChart.CANVAS_H) * SpectrogramChart.MAX_FREQ);
    const ts_ms = this._colTimes[x];
    const t = ts_ms ? new Date(ts_ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';

    const tipX = e.offsetX > (this._W - 160) ? e.offsetX - 155 : e.offsetX + 14;
    this._tip
      .style('display', 'block')
      .style('left', (tipX + 40) + 'px')
      .style('top',  (e.offsetY - 8) + 'px')
      .html(`<div class="viz-tt-row"><b>Freq</b> ${freq.toLocaleString()} Hz</div>
             <div class="viz-tt-row"><b>Time</b> ${t}</div>`);
  }

  /* ── Public API ───────────────────────────────────────────────────── */
  update(data) {
    // Receive detection events to overlay on the spectrogram
    this._detections = Array.isArray(data)
      ? data.filter(d => !this.cameraId || d.camera_id === this.cameraId).slice(0, 50)
      : [];
  }

  setFilters(f) {
    if (f.cameraId !== undefined && f.cameraId !== this.cameraId) {
      this.cameraId = f.cameraId;
      this._lbl.text(f.cameraId || 'Select a camera above');
      this._resize();
      this._connectWS();
    }
  }

  appendDetection(d) {
    // Live WS detection — add to overlay list
    if (!this.cameraId || d.camera_id === this.cameraId) {
      this._detections.unshift(d);
      if (this._detections.length > 50) this._detections.pop();
      this._renderDetectionOverlay();
    }
  }

  resize()  { this._resize(); }
  destroy() {
    if (this._ro) this._ro.disconnect();
    if (this._ws) { try { this._ws.close(); } catch(e){} }
    d3.select(this.el).selectAll('*').remove();
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
   Rare Alerts Chart — watchlist management + recent rare detection panel
   ═══════════════════════════════════════════════════════════════════════════ */

class RareAlertsChart {

  constructor(container, options = {}) {
    this.el          = container;
    this.onPlayClip  = options.onPlayClip  || (() => {});
    this.onOpenPanel = options.onOpenPanel || (() => {});
    this.onViewChart = options.onViewChart || (() => {});  // cross-chart navigation

    this._detections = [];   // all detections (filtered client-side)
    this._watchlist  = [];   // [{species_common, min_confidence}]
    this._filters    = { hours: 24, minConf: 0.5 };
    this._addName    = '';
    this._addConf    = 0.75;

    this._init();
  }

  /* ── Setup ──────────────────────────────────────────────────────────── */
  _init() {
    d3.select(this.el).selectAll('*').remove();

    const wrap = d3.select(this.el).append('div').attr('class', 'ra-wrap');

    // ── Summary stats ────────────────────────────────────────────────
    this._statsEl = wrap.append('div').attr('class', 'ra-stats');

    // ── Watchlist management ─────────────────────────────────────────
    const wl = wrap.append('div').attr('class', 'card ra-section');
    wl.append('h2').text('Species Watchlist');

    this._watchlistEl = wl.append('div').attr('class', 'ra-wl-list');

    // Add-species form
    const form = wl.append('div').attr('class', 'ra-add-form');
    this._nameInput = form.append('input')
      .attr('type', 'text')
      .attr('placeholder', 'Species name (e.g. Bald Eagle)')
      .style('flex', '1');
    this._confInput = form.append('input')
      .attr('type', 'number')
      .attr('min', '0').attr('max', '1').attr('step', '0.05')
      .attr('value', '0.75')
      .attr('title', 'Min confidence (0–1)')
      .style('width', '70px');
    form.append('button').attr('class', 'btn').style('font-size', '.8rem')
      .text('Add to Watchlist')
      .on('click', () => this._addSpecies());

    // ── Recent rare detections ────────────────────────────────────────
    const rl = wrap.append('div').attr('class', 'card ra-section');
    rl.append('h2').attr('class', 'ra-alert-heading').text('Recent Rare Detections');
    this._listEl = rl.append('div').attr('class', 'ra-list');

    this._loadWatchlist();
  }

  /* ── Watchlist CRUD ─────────────────────────────────────────────────── */
  async _loadWatchlist() {
    try {
      const r = await fetch('/api/rare-species');
      this._watchlist = r.ok ? await r.json() : [];
    } catch(e) { this._watchlist = []; }
    this._renderWatchlist();
  }

  async _addSpecies() {
    const name = this._nameInput.property('value').trim();
    const conf = parseFloat(this._confInput.property('value')) || 0.75;
    if (!name) return;
    await fetch('/api/rare-species', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ species_common: name, min_confidence: conf }),
    });
    this._nameInput.property('value', '');
    this._loadWatchlist();
  }

  async _removeSpecies(species) {
    await fetch(`/api/rare-species/${encodeURIComponent(species)}`, { method: 'DELETE' });
    this._loadWatchlist();
  }

  _renderWatchlist() {
    const rows = this._watchlistEl.selectAll('.ra-wl-row').data(this._watchlist, d => d.species_common);

    const enter = rows.enter().append('div').attr('class', 'ra-wl-row');
    enter.append('span').attr('class', 'ra-wl-name');
    enter.append('span').attr('class', 'ra-wl-conf');
    enter.append('button').attr('class', 'btn danger').style('font-size','.75rem')
      .style('padding','.15rem .5rem').text('Remove')
      .on('click', (ev, d) => this._removeSpecies(d.species_common));

    const merged = enter.merge(rows);
    merged.select('.ra-wl-name').text(d => d.species_common);
    merged.select('.ra-wl-conf').text(d => `conf ≥ ${Math.round(d.min_confidence * 100)}%`);

    rows.exit().remove();

    if (!this._watchlist.length) {
      if (this._watchlistEl.select('.ra-wl-empty').empty()) {
        this._watchlistEl.append('p').attr('class', 'ra-wl-empty')
          .text('Watchlist empty — add species above to start receiving rare alerts.');
      }
    } else {
      this._watchlistEl.select('.ra-wl-empty').remove();
    }
  }

  /* ── Detection list ─────────────────────────────────────────────────── */
  _computeRare() {
    const cutoff = Date.now() - this._filters.hours * 3600000;
    const watchMap = Object.fromEntries(this._watchlist.map(w => [w.species_common, w.min_confidence]));

    return this._detections.filter(d => {
      const thresh = watchMap[d.species_common];
      return thresh !== undefined
        && d.confidence >= thresh
        && d.confidence >= this._filters.minConf
        && new Date(d.timestamp).getTime() >= cutoff;
    }).sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
  }

  _render() {
    const rare = this._computeRare();

    // Stats
    const today = rare.filter(d =>
      new Date(d.timestamp).toDateString() === new Date().toDateString()
    ).length;
    this._statsEl.html(`
      <div class="ra-stat"><span class="ra-stat-num">${today}</span><span class="ra-stat-lbl">today</span></div>
      <div class="ra-stat"><span class="ra-stat-num">${rare.length}</span><span class="ra-stat-lbl">in selected window</span></div>
    `);

    // Detection rows
    const self    = this;
    const rows    = this._listEl.selectAll('.ra-row').data(rare, d => d.id || (d.timestamp + d.species_common));

    const enter = rows.enter().append('div').attr('class', 'ra-row');

    // Thumbnail
    enter.append('img').attr('class', 'bird-thumb ra-thumb').attr('alt', '');
    // Info block
    const info = enter.append('div').attr('class', 'ra-info');
    info.append('div').attr('class', 'ra-species');
    info.append('div').attr('class', 'ra-meta');
    // Buttons
    const btns = enter.append('div').attr('class', 'ra-btns');
    btns.append('button').attr('class', 'play-btn ra-play').text('▶ Play')
      .on('click', (ev, d) => self.onPlayClip(d.clip_path));
    btns.append('button').attr('class', 'btn ra-view-tl').style('font-size','.75rem').text('Timeline')
      .on('click', (ev, d) => self.onViewChart('timeline', d.species_common));
    btns.append('button').attr('class', 'btn ra-view-info').style('font-size','.75rem').style('background','#2b6cb0').text('Info')
      .on('click', (ev, d) => self.onOpenPanel(d.species_common, d.species_sci));

    const merged = enter.merge(rows);

    merged.select('.ra-thumb')
      .attr('src', d => {
        const key = d.species_sci || d.species_common;
        const img = window._bwImages && window._bwImages[key];
        return img || '';
      })
      .style('display', d => {
        const key = d.species_sci || d.species_common;
        return (window._bwImages && window._bwImages[key]) ? '' : 'none';
      });

    merged.select('.ra-species')
      .html(d => `${d.species_common} <span class="conf-badge" style="background:#742a2a;color:#feb2b2">${Math.round(d.confidence*100)}%</span>`);

    merged.select('.ra-meta')
      .text(d => `${d.camera_id}  ·  ${new Date(d.timestamp).toLocaleString([], { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' })}`);

    rows.exit().remove();

    if (!rare.length) {
      if (this._listEl.select('.ra-empty').empty()) {
        this._listEl.append('p').attr('class', 'ra-empty')
          .text('No rare detections in the selected time window. Add species to the watchlist above.');
      }
    } else {
      this._listEl.select('.ra-empty').remove();
    }
  }

  /* ── Public API ───────────────────────────────────────────────────── */
  update(data) {
    this._detections = Array.isArray(data) ? data : [];
    this._render();
  }

  setFilters(f) {
    this._filters = { ...this._filters, ...f };
    this._render();
  }

  appendDetection(d) {
    this._detections.unshift(d);
    this._render();
  }

  resize()  { /* no SVG to resize */ }
  destroy() { d3.select(this.el).selectAll('*').remove(); }
}

/* ── Register built-in chart types ─────────────────────────────────────── */
BirdWatchViz.register('timeline',    TimelineChart);
BirdWatchViz.register('speciesconf', SpeciesConfidenceChart);
BirdWatchViz.register('spectrogram', SpectrogramChart);
BirdWatchViz.register('rare',        RareAlertsChart);
