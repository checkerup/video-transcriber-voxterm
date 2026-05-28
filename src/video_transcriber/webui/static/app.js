/* Video Transcriber GUI — Alpine.js controller. */

if (typeof window.bootLog === "function") window.bootLog("app.js loaded");

// ---------- helpers ----------

function api() {
  // Available after pywebview boot.
  return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
}

async function call(name, ...args) {
  const a = api();
  if (!a || typeof a[name] !== "function") {
    throw new Error(`API method '${name}' not available (yet?)`);
  }
  return await a[name](...args);
}

function fmtSec(s) {
  if (s == null || !isFinite(s)) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return [h, m, sec].map((n) => String(n).padStart(2, "0")).join(":");
}

// ---------- Alpine root ----------

window.app = function () {
  if (typeof window.bootLog === "function") window.bootLog("app() factory called");
  return {
    // ----- state -----
    version: "1.1",
    tab: "process",
    tabs: [
      { id: "process",  icon: "📥", label: "Process",   sub: "Drop a video, set options, transcribe." },
      { id: "live",     icon: "🎙", label: "Live",      sub: "Record voice / screen / system audio." },
      { id: "history",  icon: "📋", label: "History",   sub: "Past runs + re-tag speakers." },
      { id: "settings", icon: "⚙",  label: "Settings",  sub: "Edit config.yaml." },
      { id: "system",   icon: "🔧", label: "System",    sub: "Hardware + logs." },
    ],

    config: null,
    hardware: {},
    history: [],
    logTail: [],

    process: {
      file: "",
      model_size: "",
      language: "",
      translate_to: "",
      summarize: false,
      diarize: true,
      diar_backend: "",
      diar_model: "",
      num_speakers: null,
      cluster_threshold: 0.7,
    },
    dragHot: false,
    activeJob: null,
    _jobsTimer: null,

    live: {
      mode: "voice",
      active: false,
      startedAt: 0,
      lastOutput: "",
    },
    liveModes: [
      { id: "voice",  label: "Voice", hint: "Microphone only." },
      { id: "screen", label: "Screen", hint: "Screen + microphone." },
      { id: "full",   label: "Full",  hint: "Screen + mic + system audio loopback." },
    ],

    settings: {
      yaml: "",
      savedAt: null,
      tg: {
        bot_token: "",
        chat_id: "",
        send_transcript: "file",
        send_summary_file: false,
        attach_audio: false,
        attach_video: false,
        savedAt: null,
        testResult: null,
      },
      llm: {
        provider: "gemini",
        api_key: "",
        api_base: "",
        model: "gemini-1.5-flash",
        prompt: "",
        system_prompt: "",
        temperature: 0.3,
        max_output_tokens: 8192,
        language: "auto",
        savedAt: null,
        testResult: null,
      },
    },

    drawer: {
      open: false,
      mode: "view", // view | retag
      name: "",
      transcripts: [],
      transcript: "",
      num_speakers: null,
      cluster_threshold: 0.7,
      _retag_target: "",
    },

    toasts: [],
    _toastId: 0,

    // ----- helpers -----
    activeTab() { return this.tabs.find((t) => t.id === this.tab) || this.tabs[0]; },
    basename(p) { return (p || "").replace(/\\/g, "/").split("/").pop(); },
    formatSec(s) { return fmtSec(s); },

    toast(text, kind = "ok", ttl = 3500) {
      const id = ++this._toastId;
      this.toasts.push({ id, text, kind });
      setTimeout(() => {
        this.toasts = this.toasts.filter((t) => t.id !== id);
      }, ttl);
    },

    // ----- bootstrap -----
    async init() {
      if (typeof window.bootLog === "function") window.bootLog("init() entered");
      try {
        if (typeof window.bootLog === "function") window.bootLog("waiting for pywebview.api");
        await this.waitForApi();
        if (typeof window.bootLog === "function") window.bootLog("pywebview.api ready", "ok");
      } catch (e) {
        if (typeof window.bootLog === "function") window.bootLog("waitForApi: " + e.message, "err");
        return;
      }
      try {
        const ping = await call("ping");
        if (typeof window.bootLog === "function")
          window.bootLog("ping ok: " + JSON.stringify(ping), "ok");
      } catch (e) {
        if (typeof window.bootLog === "function")
          window.bootLog("ping failed: " + e.message, "err");
      }
      try {
        await this.refreshAll();
        if (typeof window.bootLog === "function") window.bootLog("init() complete", "ok");
      } catch (e) {
        if (typeof window.bootLog === "function") window.bootLog("refreshAll: " + e.message, "err");
      }
      this.startJobPolling();
    },

    async waitForApi(timeoutMs = 8000) {
      const t0 = Date.now();
      while (!api()) {
        if (Date.now() - t0 > timeoutMs) throw new Error("pywebview api never appeared");
        await new Promise((r) => setTimeout(r, 80));
      }
    },

    async refreshAll() {
      try {
        this.config = await call("get_config");
      } catch (e) { console.error(e); }
      try { this.hardware = await call("hardware"); } catch (e) { console.error(e); }
      try { this.history = await call("list_history"); } catch (e) { console.error(e); }
      try { this.settings.yaml = await call("get_config_yaml"); } catch (e) { console.error(e); }
      // seed Process tab form fields from config (user's saved defaults)
      this._syncProcessFromConfig();
      // seed Telegram form from config
      this._syncTgFromConfig();
      this._syncLLMFromConfig();
    },

    // ----- file picking -----

    async pickFile() {
      try {
        const p = await call("pick_file", "video");
        if (p) this.process.file = p;
      } catch (e) {
        this.toast(String(e), "err");
      }
    },

    async onDrop(ev) {
      this.dragHot = false;
      // pywebview's HTML5 drop never gives a real OS file path. Fall
      // back to the native file picker.
      this.toast("Opening file picker (drag-drop can't pass paths in pywebview).", "ok", 2500);
      await this.pickFile();
    },

    // ----- process job -----

    async startProcess() {
      if (!this.process.file) return;
      const overrides = this._processOverrides();
      try {
        const res = await call("start_process", this.process.file, overrides);
        if (res.ok) {
          this.toast(`Queued: ${this.basename(this.process.file)}`);
        } else {
          this.toast(res.error || "failed to start", "err");
        }
      } catch (e) {
        this.toast(String(e), "err");
      }
    },

    _processOverrides() {
      const p = this.process;
      const o = { diarize: p.diarize };
      if (p.model_size) o.model_size = p.model_size;
      if (p.language) o.language = p.language;
      if (p.translate_to) o.translate_to = p.translate_to;
      if (p.summarize) o.summarize = true;
      if (p.diar_backend) o.diar_backend = p.diar_backend;
      if (p.diar_model) o.diar_model = p.diar_model;
      if (p.num_speakers) o.num_speakers = +p.num_speakers;
      if (p.cluster_threshold) o.cluster_threshold = +p.cluster_threshold;
      return o;
    },

    async cancelActive() {
      if (!this.activeJob) return;
      try {
        await call("cancel_job", this.activeJob.job_id);
        this.toast("Cancel requested.");
      } catch (e) { this.toast(String(e), "err"); }
    },

    startJobPolling() {
      if (this._jobsTimer) return;
      const tick = async () => {
        try {
          const jobs = await call("list_jobs");
          const running = jobs.find((j) => j.status === "running");
          const queued = jobs.find((j) => j.status === "queued");
          const finished = jobs.filter((j) => j.status === "done" || j.status === "failed" || j.status === "cancelled");
          const newActive = running || queued || null;
          // detect transition: previous active became finished -> notify + refresh history
          if (this.activeJob && !newActive) {
            const f = finished.find((j) => j.job_id === this.activeJob.job_id);
            if (f) {
              if (f.status === "done") this.toast(`Done: ${this.basename(f.file_path)}`, "ok");
              else if (f.status === "failed") this.toast(`Failed: ${f.error || ""}`, "err", 8000);
              else this.toast(`Cancelled.`, "ok");
              await this.refreshHistory();
            }
          }
          this.activeJob = newActive;
          if (newActive) this.logTail = newActive.log_tail || [];
          else this.logTail = await call("get_log_tail").catch(() => []);
        } catch (e) {
          // ignore transient errors
        } finally {
          const delay = this.activeJob ? 1000 : 3000;
          this._jobsTimer = setTimeout(tick, delay);
        }
      };
      tick();
    },

    async refreshHistory() {
      try { this.history = await call("list_history"); } catch (_) {}
    },

    // ----- live recording -----

    async startLive() {
      try {
        const res = await call("start_live_recording", this.live.mode);
        if (res.ok) {
          this.live.active = true;
          this.live.startedAt = Math.floor(Date.now() / 1000);
          this.toast(`Recording (${this.live.mode}) started.`);
        } else {
          this.toast(res.error || "failed", "err");
        }
      } catch (e) { this.toast(String(e), "err"); }
    },

    async stopLive() {
      try {
        const res = await call("stop_live_recording");
        this.live.active = false;
        if (res.ok) {
          this.live.lastOutput = res.media;
          this.toast(`Saved & queued for transcription.`);
        } else {
          this.toast(res.error || "stop failed", "err");
        }
      } catch (e) { this.toast(String(e), "err"); }
    },

    // ----- settings -----

    async saveYaml() {
      try {
        const res = await call("save_config_yaml", this.settings.yaml);
        if (res.ok) {
          this.config = res.config;
          this.settings.savedAt = Date.now();
          this.toast("Config saved.");
        } else {
          this.toast(res.error || "save failed", "err", 8000);
        }
      } catch (e) { this.toast(String(e), "err"); }
    },

    async reloadYaml() {
      try {
        this.settings.yaml = await call("get_config_yaml");
        this.toast("Reloaded.");
      } catch (e) { this.toast(String(e), "err"); }
    },

    _syncProcessFromConfig() {
      const c = this.config || {};
      const t = c.transcription || {};
      const d = c.diarization || {};
      const s = c.summarization || {};
      if (t.model_size) this.process.model_size = t.model_size;
      if (typeof t.language === "string") this.process.language = t.language;
      if (typeof t.translate_to === "string") this.process.translate_to = t.translate_to;
      this.process.summarize = !!s.enabled;
      this.process.diarize = !!d.enabled;
      if (d.cluster_threshold) this.process.cluster_threshold = +d.cluster_threshold;
      if (d.num_speakers) this.process.num_speakers = +d.num_speakers;
    },


    _syncLLMFromConfig() {
      const s = (this.config && this.config.summarization) || {};
      this.settings.llm.provider = s.provider || "gemini";
      this.settings.llm.api_key = s.api_key || "";
      this.settings.llm.api_base = s.api_base || "";
      this.settings.llm.model = s.model || "gemini-1.5-flash";
      this.settings.llm.prompt = s.prompt || "";
      this.settings.llm.system_prompt = s.system_prompt || "";
      this.settings.llm.temperature = typeof s.temperature === "number" ? s.temperature : 0.3;
      this.settings.llm.max_output_tokens = +s.max_output_tokens || 8192;
      this.settings.llm.language = s.language || "auto";
    },

    async saveLLM() {
      try {
        const patch = {
          "summarization.provider": this.settings.llm.provider,
          "summarization.api_key": this.settings.llm.api_key,
          "summarization.api_base": this.settings.llm.api_base,
          "summarization.model": this.settings.llm.model,
          "summarization.prompt": this.settings.llm.prompt,
          "summarization.system_prompt": this.settings.llm.system_prompt,
          "summarization.temperature": +this.settings.llm.temperature || 0.3,
          "summarization.max_output_tokens": +this.settings.llm.max_output_tokens || 8192,
          "summarization.language": this.settings.llm.language,
        };
        const res = await call("update_config", patch);
        if (res.ok) {
          this.settings.llm.savedAt = Date.now();
          this.toast("AI / LLM settings saved.", "ok");
          this.config = await call("get_config");
        } else {
          this.toast(res.error || "Save failed", "err", 8000);
        }
      } catch (e) { this.toast(String(e), "err"); }
    },

    async testLLM() {
      this.settings.llm.testResult = null;
      try {
        const res = await call("test_llm");
        this.settings.llm.testResult = res;
        this.toast(res.ok ? ("LLM OK: " + res.msg) : ("LLM error: " + (res.msg || res.error)),
                   res.ok ? "ok" : "err", 6000);
      } catch (e) {
        this.settings.llm.testResult = { ok: false, msg: String(e) };
        this.toast(String(e), "err");
      }
    },

    _syncTgFromConfig() {
      const tg = (this.config && this.config.telegram) || {};
      this.settings.tg.bot_token = tg.bot_token || "";
      this.settings.tg.chat_id = tg.chat_id || "";
      this.settings.tg.send_transcript = tg.send_transcript || "file";
      this.settings.tg.send_summary_file = !!tg.send_summary_file;
      this.settings.tg.attach_audio = !!tg.attach_audio;
      this.settings.tg.attach_video = !!tg.attach_video;
    },

    async saveTelegram() {
      try {
        const patch = {
          "telegram.bot_token": this.settings.tg.bot_token,
          "telegram.chat_id": this.settings.tg.chat_id,
          "telegram.send_transcript": this.settings.tg.send_transcript,
          "telegram.send_summary_file": !!this.settings.tg.send_summary_file,
          "telegram.attach_audio": !!this.settings.tg.attach_audio,
          "telegram.attach_video": !!this.settings.tg.attach_video,
        };
        const res = await call("update_config", patch);
        if (res.ok) {
          this.config = res.config;
          this.settings.tg.savedAt = Date.now();
          this.toast("Telegram settings saved.");
        } else {
          this.toast(res.error || "save failed", "err", 8000);
        }
      } catch (e) { this.toast(String(e), "err"); }
    },

    async testTelegram() {
      this.settings.tg.testResult = null;
      try {
        const res = await call("send_telegram_test");
        this.settings.tg.testResult = res.ok ? "ok" : (res.error || "failed");
        if (!res.ok) this.toast(res.error || "test failed", "err", 8000);
      } catch (e) {
        this.settings.tg.testResult = String(e);
        this.toast(String(e), "err");
      }
    },

    // ----- drawer / history actions -----

    async openTranscript(h) {
      this.drawer.open = true;
      this.drawer.mode = "view";
      this.drawer.name = h.name;
      this.drawer.transcripts = h.transcripts || [];
      this.drawer.transcript = "";
      if (h.transcripts && h.transcripts.length) {
        await this.loadTranscript(h.transcripts[0]);
      }
    },

    async loadTranscript(p) {
      try {
        const res = await call("read_transcript", p);
        if (res.ok) {
          this.drawer.transcript = res.text + (res.truncated ? "\n\n[…truncated…]" : "");
        } else {
          this.drawer.transcript = `Error: ${res.error}`;
        }
      } catch (e) { this.drawer.transcript = String(e); }
    },

    openRetag(h) {
      this.drawer.open = true;
      this.drawer.mode = "retag";
      this.drawer.name = h.name;
      this.drawer.transcripts = h.transcripts || [];
      this.drawer.num_speakers = null;
      this.drawer.cluster_threshold = 0.7;
      // pick the .txt transcript as the retag target if available
      this.drawer._retag_target = (h.transcripts || []).find((p) => p.endsWith(".txt")) || (h.transcripts || [])[0] || "";
    },

    async runRetag() {
      if (!this.drawer._retag_target) {
        this.toast("No transcript to retag.", "err");
        return;
      }
      const overrides = {};
      if (this.drawer.num_speakers) overrides.num_speakers = +this.drawer.num_speakers;
      if (this.drawer.cluster_threshold) overrides.cluster_threshold = +this.drawer.cluster_threshold;
      try {
        const res = await call("start_retag", this.drawer._retag_target, overrides);
        if (res.ok) {
          this.toast("Retag queued. Watch progress on Process tab.");
          this.drawer.open = false;
          this.tab = "process";
        } else {
          this.toast(res.error || "failed", "err");
        }
      } catch (e) { this.toast(String(e), "err"); }
    },
  };
};
