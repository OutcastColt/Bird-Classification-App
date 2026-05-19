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
    birdImages: {},  // cache: { 'Cardinalis cardinalis': 'https://...' }

    // History
    historyRows: [],
    histPage: 0,
    histLimit: 25,
    histFilter: { camera_id: '', species: '', date_from: '', date_to: '' },

    // Cameras
    cameras: [],
    newCam: { id: '', name: '', stream_url: '', enabled: true },
    editingCam: false,
    camSaved: false,

    // Settings
    settings: {},
    settingsSaved: false,

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
      this.connectWS();
      setInterval(() => this.loadCameraStatuses(), 10000);
      setInterval(() => this.loadDetectionSummary(), 30000);
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
      if (key in this.birdImages) return;    // already cached or in-flight
      this.birdImages = { ...this.birdImages, [key]: null };  // mark in-flight
      const query = encodeURIComponent((sciName || commonName).replace(/ /g, '_'));
      fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${query}`)
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          const url = data?.thumbnail?.source || '';
          this.birdImages = { ...this.birdImages, [key]: url };
        })
        .catch(() => {
          this.birdImages = { ...this.birdImages, [key]: '' };
        });
    },

    birdImg(det) {
      const key = det.species_sci || det.species_common;
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
      const p = new URLSearchParams({ limit: this.histLimit, offset: this.histPage * this.histLimit });
      if (this.histFilter.camera_id) p.set('camera_id', this.histFilter.camera_id);
      if (this.histFilter.species) p.set('species', this.histFilter.species);
      // Append time so date-only strings compare correctly with stored ISO datetimes
      if (this.histFilter.date_from) p.set('date_from', this.histFilter.date_from + 'T00:00:00');
      if (this.histFilter.date_to)   p.set('date_to',   this.histFilter.date_to   + 'T23:59:59');
      const r = await fetch(`/api/detections?${p}`);
      this.historyRows = await r.json();
      for (const d of this.historyRows)
        this.fetchBirdImage(d.species_common, d.species_sci);
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

    cameraStatusClass(status) {
      const map = { connected: 'connected', reconnecting: 'reconnecting',
                    error: 'error', disabled: 'disabled', starting: 'starting' };
      return map[status] || 'starting';
    },
  }));
});
