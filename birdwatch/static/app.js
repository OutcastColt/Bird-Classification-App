// BirdWatch Dashboard — Alpine.js + Fetch + WebSocket

document.addEventListener('alpine:init', () => {
  Alpine.data('dashboard', () => ({
    tab: 'live',

    // Live
    liveDetections: [],
    cameraStatuses: {},
    wsConnected: false,
    MAX_LIVE: 50,

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
      this.connectWS();
      setInterval(() => this.loadCameraStatuses(), 10000);
    },

    connectWS() {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${proto}://${location.host}/ws/detections`);
      ws.onopen = () => { this.wsConnected = true; };
      ws.onclose = () => {
        this.wsConnected = false;
        setTimeout(() => this.connectWS(), 3000);
      };
      ws.onmessage = (e) => {
        const det = JSON.parse(e.data);
        this.liveDetections.unshift(det);
        if (this.liveDetections.length > this.MAX_LIVE)
          this.liveDetections.pop();
      };
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
      if (this.histFilter.date_from) p.set('date_from', this.histFilter.date_from);
      if (this.histFilter.date_to) p.set('date_to', this.histFilter.date_to);
      const r = await fetch(`/api/detections?${p}`);
      this.historyRows = await r.json();
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
