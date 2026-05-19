// BirdWatch Dashboard — Alpine.js + Fetch + WebSocket

document.addEventListener('alpine:init', () => {
  Alpine.data('dashboard', () => ({
    tab: 'live',

    // Live
    liveDetections: [],
    cameraStatuses: {},
    wsConnected: false,
    MAX_LIVE: 50,
    detectionSummary: { total: 0, today: 0, top_species: [] },
    birdImages: {},         // { sciName: imageUrl }
    speciesConservation: {}, // { sciName: { code: 'LC', label: 'Least Concern' } }

    // Bird info side panel
    birdPanel: {
      open: false, loading: false,
      common: '', sci: '', summary: '', image: '',
      sections: [], conservation: '', conservationCode: '',
      wikiUrl: '', recordings: [],
    },

    // History
    historyRows: [],
    histPage: 0,
    histLimit: 25,
    histFilter: { camera_id: '', species: '', conservation: '', date_from: '', date_to: '' },
    detectedSpecies: [],  // [{ species_common, species_sci, c }]

    // Cameras
    cameras: [],
    newCam: { id: '', name: '', stream_url: '', enabled: true },
    editingCam: false,
    camSaved: false,

    // Settings
    settings: {},
    settingsSaved: false,

    // Weather widget (Open-Meteo — no API key required)
    weather: { temp: null, desc: '', symbol: '', wind: null, loading: false },

    // Visualization tab (flat top-level properties — Alpine resolves these reliably)
    vizChartType: 'timeline',
    vizLoading:   false,
    vizMinConf:   0.5,
    vizCameraId:  '',
    vizHours:     24,

    // Alert rules
    alertRules: [],
    newRule: { species_filter: '', min_confidence: 0.70, method: 'webhook',
               config: '', cooldown_mins: 10, enabled: true },
    ruleSaved: false,

    async init() {
      await this.loadCameraStatuses();
      await this.loadCameras();
      await this.loadSettings();
      await this.loadAlertRules();
      await this.loadDetectionSummary();
      await this.loadWeather();
      this.connectWS();
      setInterval(() => this.loadCameraStatuses(), 10000);
      setInterval(() => this.loadDetectionSummary(), 30000);
      setInterval(() => this.loadWeather(), 30 * 60 * 1000); // refresh every 30 min
    },

    connectWS() {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${proto}://${location.host}/ws/detections`);
      ws.onopen = async () => {
        this.wsConnected = true;
        // Pre-populate live feed from DB so detections missed before WS connected show up
        await this.loadRecentDetections();
      };
      ws.onclose = () => {
        this.wsConnected = false;
        setTimeout(() => this.connectWS(), 3000);
      };
      ws.onmessage = (e) => {
        const det = JSON.parse(e.data);
        // Avoid duplicates: skip if same id already in list
        if (det.id && this.liveDetections.some(d => d.id === det.id)) return;
        this.liveDetections.unshift(det);
        if (this.liveDetections.length > this.MAX_LIVE)
          this.liveDetections.pop();
        this.fetchBirdImage(det.species_common, det.species_sci);
        this.loadDetectionSummary();
        // Forward live detection to active viz chart
        if (BirdWatchViz.hasActive()) BirdWatchViz.getActive().appendDetection?.(det);
      };
    },

    async loadDetectionSummary() {
      try {
        const r = await fetch('/api/detections/summary');
        this.detectionSummary = await r.json();
        // Pre-fetch images for top species
        for (const s of this.detectionSummary.top_species)
          this.fetchBirdImage(s.species_common, s.species_sci || s.species_common);
      } catch (e) { /* non-fatal */ }
    },

    fetchBirdImage(commonName, sciName) {
      const key = sciName || commonName;
      if (key in this.birdImages) return;
      this.birdImages = { ...this.birdImages, [key]: null };
      const query = encodeURIComponent((sciName || commonName).replace(/ /g, '_'));
      fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${query}`)
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          this.birdImages = { ...this.birdImages, [key]: data?.thumbnail?.source || '' };
        })
        .catch(() => { this.birdImages = { ...this.birdImages, [key]: '' }; });
      // Fetch conservation status in parallel
      this.fetchConservation(commonName, sciName);
    },

    fetchConservation(commonName, sciName) {
      const key = sciName || commonName;
      if (key in this.speciesConservation) return;
      this.speciesConservation = { ...this.speciesConservation, [key]: null };
      fetch(`https://api.inaturalist.org/v1/taxa?q=${encodeURIComponent(sciName || commonName)}&rank=species&per_page=1`)
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          const status = data?.results?.[0]?.conservation_status;
          const entry = status
            ? { code: (status.status || '').toUpperCase(), label: status.status_name || '' }
            : { code: '', label: '' };
          this.speciesConservation = { ...this.speciesConservation, [key]: entry };
        })
        .catch(() => { this.speciesConservation = { ...this.speciesConservation, [key]: { code: '', label: '' } }; });
    },

    // Returns conservation entry { code, label } or null if not loaded / no status
    consv(sciName, commonName) {
      const d = this.speciesConservation[sciName || commonName];
      return d && d.code ? d : null;
    },

    birdImg(det) {
      const key = det.species_sci || det.species_common;
      return key ? (this.birdImages[key] || '') : '';
    },

    birdImgKey(sciName, commonName) {
      const key = sciName || commonName;
      return key ? (this.birdImages[key] || '') : '';
    },

    async loadRecentDetections() {
      try {
        const r = await fetch(`/api/detections?limit=${this.MAX_LIVE}`);
        const rows = await r.json();
        // Merge with any detections already received via WS (keep WS ones at front)
        const existingIds = new Set(this.liveDetections.map(d => d.id).filter(Boolean));
        const newRows = rows.filter(d => !existingIds.has(d.id));
        this.liveDetections = [...this.liveDetections, ...newRows].slice(0, this.MAX_LIVE);
        for (const d of this.liveDetections)
          this.fetchBirdImage(d.species_common, d.species_sci);
      } catch (e) { /* non-fatal */ }
    },

    async loadCameraStatuses() {
      const r = await fetch('/api/cameras');
      const cams = await r.json();
      this.cameraStatuses = {};
      for (const c of cams) this.cameraStatuses[c.id] = c.status || 'unknown';
    },

    async loadHistory() {
      const conservationOnly = this.histFilter.conservation && !this.histFilter.species;

      const p = new URLSearchParams({
        // Fetch a larger batch when filtering by conservation only (client-side filter)
        limit:  conservationOnly ? 200 : this.histLimit,
        offset: conservationOnly ? 0   : this.histPage * this.histLimit,
      });
      if (this.histFilter.camera_id) p.set('camera_id', this.histFilter.camera_id);
      if (this.histFilter.species)   p.set('species', this.histFilter.species);
      // Append time so date-only strings compare correctly with stored ISO datetimes
      if (this.histFilter.date_from) p.set('date_from', this.histFilter.date_from + 'T00:00:00');
      if (this.histFilter.date_to)   p.set('date_to',   this.histFilter.date_to   + 'T23:59:59');

      const r = await fetch(`/api/detections?${p}`);
      let rows = await r.json();

      // Conservation-only filter: match against the iNaturalist cache
      if (conservationOnly) {
        const code = this.histFilter.conservation;
        rows = rows.filter(d => {
          const key = d.species_sci || d.species_common;
          const c = this.speciesConservation[key];
          return c && c.code === code;
        });
        rows = rows.slice(0, this.histLimit);
      }

      this.historyRows = rows;
      for (const d of this.historyRows)
        this.fetchBirdImage(d.species_common, d.species_sci);
    },

    async loadDetectedSpecies() {
      try {
        const r = await fetch('/api/detections/species');
        this.detectedSpecies = await r.json();
        // Pre-fetch conservation status for all detected species
        for (const s of this.detectedSpecies)
          this.fetchConservation(s.species_common, s.species_sci);
      } catch(e) { /* non-fatal */ }
    },

    // Species dropdown filtered by selected conservation code
    filteredSpecies() {
      if (!this.histFilter.conservation) return this.detectedSpecies;
      return this.detectedSpecies.filter(s => {
        const key = s.species_sci || s.species_common;
        const c = this.speciesConservation[key];
        return c && c.code === this.histFilter.conservation;
      });
    },

    histPrev() { if (this.histPage > 0) { this.histPage--; this.loadHistory(); } },
    histNext() { this.histPage++; this.loadHistory(); },

    playClip(clipPath) {
      const audio = new Audio(`/api/clips/${clipPath}`);
      audio.play();
    },

    formatConf(c) { return `${(c * 100).toFixed(0)}%`; },

    formatTime(ts) {
      try { return new Date(ts).toLocaleTimeString(); } catch { return ts; }
    },

    async loadCameras() {
      const r = await fetch('/api/cameras');
      this.cameras = await r.json();
    },

    async saveCamera() {
      if (!this.newCam.id.trim() || !this.newCam.name.trim() || !this.newCam.stream_url.trim()) {
        alert('ID, Name, and Stream URL are all required and cannot be empty.');
        return;
      }
      const url = this.editingCam ? `/api/cameras/${this.newCam.id}` : '/api/cameras';
      const method = this.editingCam ? 'PUT' : 'POST';
      const r = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.newCam),
      });
      if (r.ok) {
        this.newCam = { id: '', name: '', stream_url: '', enabled: true };
        this.editingCam = false;
        this.camSaved = true;
        await this.loadCameras();
        await this.loadCameraStatuses();
        setTimeout(() => { this.camSaved = false; }, 3000);
      }
    },

    editCamera(cam) {
      this.newCam = { id: cam.id, name: cam.name, stream_url: cam.stream_url, enabled: !!cam.enabled };
      this.editingCam = true;
      document.getElementById('camera-form').scrollIntoView({ behavior: 'smooth' });
    },

    cancelEdit() {
      this.newCam = { id: '', name: '', stream_url: '', enabled: true };
      this.editingCam = false;
    },

    async deleteCamera(id) {
      if (!confirm(`Delete camera ${id}?`)) return;
      await fetch(`/api/cameras/${id}`, { method: 'DELETE' });
      if (this.editingCam && this.newCam.id === id) this.cancelEdit();
      await this.loadCameras();
    },

    async loadSettings() {
      const r = await fetch('/api/settings');
      this.settings = await r.json();
    },

    async saveSettings() {
      const r = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.settings),
      });
      if (r.ok) {
        this.settingsSaved = true;
        this.loadWeather();   // refresh weather if lat/lon changed
        setTimeout(() => { this.settingsSaved = false; }, 3000);
      }
    },

    async loadAlertRules() {
      const r = await fetch('/api/alerts/rules');
      this.alertRules = await r.json();
    },

    async saveRule() {
      let configObj = {};
      try { configObj = JSON.parse(this.newRule.config || '{}'); } catch { alert('Config must be valid JSON'); return; }
      const body = { ...this.newRule, config: configObj };
      const r = await fetch('/api/alerts/rules', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (r.ok) {
        this.newRule = { species_filter: '', min_confidence: 0.70, method: 'webhook',
                         config: '', cooldown_mins: 10, enabled: true };
        this.ruleSaved = true;
        await this.loadAlertRules();
        setTimeout(() => { this.ruleSaved = false; }, 3000);
      }
    },

    async deleteRule(id) {
      await fetch(`/api/alerts/rules/${id}`, { method: 'DELETE' });
      await this.loadAlertRules();
    },

    async loadWeather() {
      const lat = this.settings?.lat;
      const lon = this.settings?.lon;
      if (!lat || !lon) return;
      this.weather.loading = true;
      try {
        const url = `https://api.open-meteo.com/v1/forecast`
          + `?latitude=${lat}&longitude=${lon}`
          + `&current=temperature_2m,weathercode,windspeed_10m`
          + `&temperature_unit=fahrenheit&windspeed_unit=mph&timezone=auto`;
        const r = await fetch(url);
        if (r.ok) {
          const d = await r.json();
          const c = d.current;
          this.weather = {
            temp:    Math.round(c.temperature_2m),
            wind:    Math.round(c.windspeed_10m),
            desc:    this._wmoDesc(c.weathercode),
            symbol:  this._wmoSymbol(c.weathercode),
            loading: false,
          };
        }
      } catch(e) { this.weather.loading = false; }
    },

    _wmoDesc(code) {
      if (code === 0)              return 'Clear';
      if (code <= 1)               return 'Mainly Clear';
      if (code <= 2)               return 'Partly Cloudy';
      if (code <= 3)               return 'Overcast';
      if (code <= 48)              return 'Fog';
      if (code <= 55)              return 'Drizzle';
      if (code <= 65)              return 'Rain';
      if (code <= 75)              return 'Snow';
      if (code <= 77)              return 'Snow Grains';
      if (code <= 82)              return 'Showers';
      if (code <= 86)              return 'Snow Showers';
      if (code <= 99)              return 'Thunderstorm';
      return 'Unknown';
    },

    _wmoSymbol(code) {
      if (code === 0)              return '☀';
      if (code <= 2)               return '⛅';
      if (code <= 3)               return '☁';
      if (code <= 48)              return '≡';   // fog bars
      if (code <= 55)              return '~';   // drizzle
      if (code <= 65)              return '☂';
      if (code <= 77)              return '❄';
      if (code <= 82)              return '☂';
      if (code <= 86)              return '❄';
      if (code <= 99)              return '⚡';
      return '?';
    },

    // ── Visualization tab ─────────────────────────────────────────────────

    async openVizTab() {
      this.tab = 'viz';
      await new Promise(r => setTimeout(r, 60));
      this.mountViz();
    },

    async mountViz() {
      const container = document.getElementById('viz-chart');
      if (!container) return;
      BirdWatchViz.mount(this.vizChartType, container, {
        onPlayClip:  clipPath => this.playClip(clipPath),
        onOpenPanel: (common, sci) => this.openBirdPanel(common, sci),
      });
      await this.loadVizData();
    },

    async loadVizData() {
      this.vizLoading = true;
      try {
        const dateFrom = new Date(Date.now() - this.vizHours * 3600000).toISOString();
        const p = new URLSearchParams({ limit: 2000, date_from: dateFrom });
        if (this.vizCameraId) p.set('camera_id', this.vizCameraId);
        const r = await fetch(`/api/detections?${p}`);
        BirdWatchViz.update(await r.json());
      } catch(e) { /* non-fatal */ }
      this.vizLoading = false;
    },

    applyVizFilters() {
      const f = { minConf: this.vizMinConf, cameraId: this.vizCameraId, hours: this.vizHours };
      if (BirdWatchViz.hasActive()) BirdWatchViz.getActive().setFilters(f);
      this.loadVizData();
    },

    resetVizZoom() {
      const f = { minConf: this.vizMinConf, cameraId: this.vizCameraId, hours: this.vizHours };
      if (BirdWatchViz.hasActive()) BirdWatchViz.getActive().setFilters(f);
    },

    cameraStatusClass(status) {
      const map = { connected: 'connected', reconnecting: 'reconnecting',
                    error: 'error', disabled: 'disabled', starting: 'starting' };
      return map[status] || 'starting';
    },

    // ── Bird info side panel ──────────────────────────────────────────────

    async openBirdPanel(commonName, sciName) {
      this.birdPanel = {
        open: true, loading: true,
        common: commonName, sci: sciName || '',
        summary: '', image: this.birdImages[sciName || commonName] || '',
        sections: [], conservation: '', conservationCode: '',
        wikiUrl: '', recordings: [],
      };

      const query = encodeURIComponent((sciName || commonName).replace(/ /g, '_'));

      // Wikipedia summary (description + thumbnail)
      try {
        const r = await fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${query}`);
        if (r.ok) {
          const d = await r.json();
          this.birdPanel.summary  = d.extract || '';
          if (d.thumbnail?.source) this.birdPanel.image = d.thumbnail.source;
          this.birdPanel.wikiUrl  = d.content_urls?.desktop?.page || '';
        }
      } catch(e) {}

      // Wikipedia article sections via Action API (supports CORS via origin=*)
      // Uses action=query&prop=extracts to get the full HTML, then parses h2 sections
      try {
        const actionUrl = 'https://en.wikipedia.org/w/api.php?action=query'
          + '&prop=extracts&format=json&origin=*&exlimit=1'
          + '&titles=' + query;
        const r = await fetch(actionUrl);
        if (r.ok) {
          const d = await r.json();
          const pages = d?.query?.pages || {};
          const page  = Object.values(pages)[0];
          if (page?.extract) {
            // Parse the HTML: split on <h2> tags to get named sections
            const parser   = new DOMParser();
            const doc      = parser.parseFromString(page.extract, 'text/html');
            const sections = [];
            let current    = null;

            for (const el of doc.body.childNodes) {
              if (el.nodeName === 'H2') {
                if (current && current.text.trim().length > 80)
                  sections.push({ ...current, expanded: false });
                current = {
                  title: el.textContent.replace(/\[edit\]/gi, '').trim(),
                  text: '',
                };
              } else if (current && (el.nodeName === 'P' || el.nodeName === 'UL')) {
                current.text += ' ' + (el.textContent || '').trim();
              }
            }
            if (current && current.text.trim().length > 80)
              sections.push({ ...current, expanded: false });

            this.birdPanel.sections = sections;
          }
        }
      } catch(e) {}

      // iNaturalist — conservation status + fallback image
      try {
        const r = await fetch(`https://api.inaturalist.org/v1/taxa?q=${encodeURIComponent(sciName || commonName)}&rank=species&per_page=1`);
        if (r.ok) {
          const d = await r.json();
          const t = d.results?.[0];
          if (t) {
            this.birdPanel.conservationCode = t.conservation_status?.status || '';
            this.birdPanel.conservation     = t.conservation_status?.status_name || '';
            if (!this.birdPanel.image && t.default_photo?.medium_url)
              this.birdPanel.image = t.default_photo.medium_url;
          }
        }
      } catch(e) {}

      // Local recordings of this species from our own cameras
      try {
        const r = await fetch(`/api/detections?species=${encodeURIComponent(commonName)}&limit=5`);
        if (r.ok) this.birdPanel.recordings = await r.json();
      } catch(e) {}

      this.birdPanel.loading = false;
    },

    closeBirdPanel() { this.birdPanel.open = false; },

    toggleSection(i) {
      this.birdPanel.sections[i] = {
        ...this.birdPanel.sections[i],
        expanded: !this.birdPanel.sections[i].expanded,
      };
    },

    conservationStyle(code) {
      const map = {
        LC: 'background:#276749;color:#c6f6d5',
        NT: 'background:#744210;color:#fefcbf',
        VU: 'background:#7b341e;color:#fbd38d',
        EN: 'background:#742a2a;color:#feb2b2',
        CR: 'background:#4a1942;color:#fbb6ce',
        EW: 'background:#4a1942;color:#fbb6ce',
        EX: 'background:#2d3748;color:#a0aec0',
      };
      return map[(code || '').toUpperCase()] || 'background:#2d3748;color:#a0aec0';
    },
  }));
});
