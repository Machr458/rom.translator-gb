import { useEffect, useState, useRef, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  Gamepad2,
  Upload,
  Download,
  Zap,
  Loader2,
  CheckCircle2,
  XCircle,
  Settings2,
  FileText,
  FileUp,
} from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import Terminal from "@/components/rom/Terminal";
import TranslationTable from "@/components/rom/TranslationTable";
import AiSettingsDialog, { loadSettings, saveSettings } from "@/components/rom/AiSettingsDialog";
import { ClearCacheButton } from "@/components/rom/ClearCacheButton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";
const API = `${BACKEND_URL}/api`;
const APP_VERSION = process.env.REACT_APP_VERSION || "dev";
const UI_LANGUAGE_KEY = "romtrans.ui_language";
const COPY = {
  en: {
    settings: "Settings", settingsTitle: "Application settings", appLanguage: "App language",
    tagline: "Game Boy ROM translation",
    english: "English", czech: "Čeština", advanced: "Advanced ROM options", encoding: "Text encoding",
    scanMode: "Scan mode", bytewise: "Full scan", pointers: "Pointer table · GBA only",
    romStep: "01 / ROM", chooseRom: "Choose a ROM", chooseFile: "Select ROM file",
    dropHint: "or drop a .gb, .gbc, or .gba file here", noFile: "No ROM selected",
    loadRom: "Load ROM", loadingRom: "Loading ROM…", loaded: "ROM loaded",
    loadedStrings: "strings found", targetLanguage: "Translate into", translate: "Translate ROM",
    translating: "Translating…", downloadRom: "Download patched ROM", exportTxt: "Export TXT",
    importPatch: "Import TXT & patch ROM", translation: "Translation", original: "Original ROM text",
    translated: "Translated text", technical: "Technical log", appFooter: "Game Boy ROM localization",
    cost: "Estimated AI cost", session: "Loaded ROM", encodingInfo: "Encoding",
    changeRom: "Choose another ROM", settingsHint: "Language, cache, and ROM scan options",
    checkingCache: "Checking translation cache…", cachedTranslations: "already translated in cache",
    rejectedCached: "cached entries need a fresh translation for this ROM",
    apiKeyNeeded: "Save an API key in AI settings before translating.",
  },
  cs: {
    settings: "Nastavení", settingsTitle: "Nastavení aplikace", appLanguage: "Jazyk aplikace",
    tagline: "Překlad ROM pro Game Boy",
    english: "English", czech: "Čeština", advanced: "Pokročilé volby ROM", encoding: "Kódování textu",
    scanMode: "Režim skenování", bytewise: "Úplný sken", pointers: "Tabulka ukazatelů · pouze GBA",
    romStep: "01 / ROM", chooseRom: "Vyber ROM", chooseFile: "Vybrat soubor ROM",
    dropHint: "nebo sem přetáhni soubor .gb, .gbc či .gba", noFile: "Není vybraná ROM",
    loadRom: "Načíst ROM", loadingRom: "Načítám ROM…", loaded: "ROM načtena",
    loadedStrings: "nalezených textů", targetLanguage: "Přeložit do", translate: "Přeložit ROM",
    translating: "Překládám…", downloadRom: "Stáhnout patchnutou ROM", exportTxt: "Exportovat TXT",
    importPatch: "Importovat TXT a patchnout ROM", translation: "Překlad", original: "Původní text ROM",
    translated: "Přeložený text", technical: "Technický log", appFooter: "Lokalizace Game Boy ROM",
    cost: "Odhad ceny AI", session: "Načtená ROM", encodingInfo: "Kódování",
    changeRom: "Vybrat jinou ROM", settingsHint: "Jazyk, cache a volby skenování ROM",
    checkingCache: "Kontroluji překladovou cache…", cachedTranslations: "již přeloženo v cache",
    rejectedCached: "starších překladů se pro tuto ROM nepoužije",
    apiKeyNeeded: "Před překladem ulož API klíč v nastavení AI.",
  },
};

export default function RomTranslator() {
  const [languages, setLanguages] = useState([]);
  const [providers, setProviders] = useState({});
  const [encodings, setEncodings] = useState([]);
  const [encoding, setEncoding] = useState("auto");
  const [scanMode, setScanMode] = useState("bytewise");
  const [aiSettings, setAiSettings] = useState(loadSettings());
  const [appLanguage, setAppLanguage] = useState(() => {
    try { return localStorage.getItem(UI_LANGUAGE_KEY) || "en"; } catch { return "en"; }
  });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [targetLang, setTargetLang] = useState("cs");
  const [file, setFile] = useState(null);
  const [session, setSession] = useState(null);
  const [translations, setTranslations] = useState([]);
  const [cachedCount, setCachedCount] = useState(0);
  const [rejectedCachedCount, setRejectedCachedCount] = useState(0);
  const [cachePreviewLoading, setCachePreviewLoading] = useState(false);
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [dragActive, setDragActive] = useState(false);
  const fileInput = useRef(null);
  const importInput = useRef(null);
  const pollRef = useRef(null);
  const t = COPY[appLanguage] || COPY.en;
  const estimate = session
    ? estimateCost(session.strings, aiSettings.provider, aiSettings.model || providers?.[aiSettings.provider]?.default, providers)
    : null;
  const formatCost = (value) => value < 0.001 ? "<$0.001" : value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(3)}`;
  const requiresApiKey = aiSettings.provider !== "emergent"
    && !aiSettings.apiKey?.trim()
    && !providers?.[aiSettings.provider]?.serverKeyAvailable;

  useEffect(() => {
    localStorage.setItem(UI_LANGUAGE_KEY, appLanguage);
    document.documentElement.lang = appLanguage;
  }, [appLanguage]);

  const pushLog = useCallback((line, kind = "info") => {
    setLogs((l) => [...l, { line, kind, ts: Date.now() }]);
  }, []);

  useEffect(() => {
    axios.get(`${API}/languages`).then((r) => setLanguages(r.data)).catch(() => { /* ignore */ });
    axios.get(`${API}/providers`).then((r) => setProviders(r.data)).catch(() => { /* ignore */ });
    axios.get(`${API}/encodings`).then((r) => setEncodings(r.data)).catch(() => { /* ignore */ });
    pushLog("SYSTEM READY. Select a ROM to begin.", "sys");
  }, [pushLog]);

  useEffect(() => {
    const providerIds = Object.keys(providers);
    if (!providerIds.length || providers[aiSettings.provider]) return;
    const fallbackProvider = providers.gemini ? "gemini" : providerIds[0];
    const nextSettings = {
      provider: fallbackProvider,
      model: providers[fallbackProvider]?.default || "",
      apiKey: "",
    };
    saveSettings(nextSettings);
    setAiSettings(nextSettings);
  }, [providers, aiSettings.provider]);

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
  }, []);

  useEffect(() => {
    if (!session) {
      setCachedCount(0);
      setRejectedCachedCount(0);
      setCachePreviewLoading(false);
      return undefined;
    }

    let active = true;
    setCachePreviewLoading(true);
    axios.post(`${API}/rom/cache-preview`, {
      session_id: session.session_id,
      target_language: targetLang,
      strings: session.strings,
    }, { timeout: 180000 }).then(({ data }) => {
      if (!active) return;
      const cachedById = new Map((data.translations || []).map((item) => [item.id, item.translated]));
      setTranslations(session.strings.map((item) => ({
        id: item.id,
        original: item.text,
        translated: cachedById.get(item.id) || "",
      })));
      setCachedCount(data.cached_count || 0);
      setRejectedCachedCount(data.rejected_count || 0);
    }).catch((error) => {
      if (!active) return;
      setTranslations(session.strings.map((item) => ({ id: item.id, original: item.text, translated: "" })));
      setCachedCount(0);
      setRejectedCachedCount(0);
      pushLog(`! CACHE PREVIEW FAILED: ${error.response?.data?.detail || error.message}`, "err");
    }).finally(() => {
      if (active) setCachePreviewLoading(false);
    });

    return () => { active = false; };
  }, [session, targetLang, pushLog]);

  const providerLabel = () => {
    const p = providers?.[aiSettings.provider];
    const modelId = aiSettings.model || p?.default || "";
    return `${(aiSettings.provider || "emergent").toUpperCase()} · ${modelId}`;
  };

  const handleFile = (f) => {
    if (!f) return;
    const name = f.name.toLowerCase();
    if (!name.endsWith(".gb") && !name.endsWith(".gbc") && !name.endsWith(".gba")) {
      toast.error("Unsupported file type. Choose a .gb, .gbc, or .gba ROM.");
      return;
    }
    setFile(f);
    setSession(null);
    setTranslations([]);
    setCachedCount(0);
    setRejectedCachedCount(0);
    setStatus("idle");
    setProgress(0);
    pushLog(`> LOAD ${f.name} [${(f.size / 1024).toFixed(1)} KB]`, "cmd");
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragActive(false);
    const f = e.dataTransfer.files?.[0];
    handleFile(f);
  };

  const extract = async () => {
    if (!file) return;
    setStatus("extracting");
    setProgress(10);
    pushLog("> SCAN ROM :: extracting printable strings...", "cmd");
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("encoding", encoding);
      fd.append("max_strings", "0");
      fd.append("scan_mode", scanMode);
      const r = await axios.post(`${API}/rom/extract`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 180000, // 3 min upper bound for very large ROMs
        maxContentLength: Infinity,
        maxBodyLength: Infinity,
        onUploadProgress: (e) => {
          if (e.total) setProgress(Math.round((e.loaded / e.total) * 60));
        },
      });
      setSession(r.data);
      setProgress(100);
      setStatus("ready");
      pushLog(`  TYPE  : ${r.data.rom_type}`, "info");
      pushLog(`  SIZE  : ${(r.data.rom_size / 1024).toFixed(1)} KB`, "info");
      pushLog(`  ENC   : ${r.data.encoding}`, "info");
      pushLog(`  FOUND : ${r.data.found_total} strings in ROM`, "info");
      pushLog(`  LOAD  : ${r.data.strings.length} story / dialog strings`, "ok");
      pushLog(`  SKIP  : ${r.data.excluded_names || 0} names (Pokemon, moves, items, places) kept original`, "info");
      pushLog("> READY. Choose a target language and select TRANSLATE.", "cmd");
    } catch (e) {
      setStatus("error");
      const detail = e.response?.data?.detail || e.message || "Unknown error";
      pushLog(`! ERROR: ${detail}`, "err");
      pushLog(`  Try changing the encoding or scan mode.`, "err");
      toast.error(`Extraction failed: ${detail}`);
    }
  };

  const translate = async () => {
    if (!session) return;
    if (aiSettings.provider !== "emergent" && !aiSettings.apiKey
      && !providers?.[aiSettings.provider]?.serverKeyAvailable) {
      toast.error("Enter an API key in Settings before translating.");
      return;
    }
    setStatus("translating");
    setProgress(2);
    pushLog(`> TRANSLATE :: target=${targetLang.toUpperCase()} via ${providerLabel()}`, "cmd");
    pushLog(`  Sending ${session.strings.length} strings; cached and duplicate texts are skipped, batches are automatic...`, "info");

    try {
      const r = await axios.post(`${API}/rom/translate`, {
        session_id: session.session_id,
        target_language: targetLang,
        strings: session.strings,
        provider: aiSettings.provider,
        model: aiSettings.model || providers?.[aiSettings.provider]?.default,
        api_key: aiSettings.apiKey || "",
      });
      const jobId = r.data.job_id;
      pushLog(`  JOB ${jobId.slice(0, 8)}... running`, "info");
      let consecutivePollFailures = 0;
      let pollInFlight = false;
      pollRef.current = setInterval(async () => {
        if (pollInFlight) return;
        pollInFlight = true;
        try {
          const s = await axios.get(`${API}/rom/translate/status/${jobId}`);
          consecutivePollFailures = 0;
          const data = s.data;
          const pct = data.total ? Math.round((data.done / data.total) * 95) + 5 : 10;
          setProgress(pct);
          if (data.translations?.length) setTranslations(data.translations);
          if (data.status === "done") {
            clearInterval(pollRef.current);
            pollRef.current = null;
            setStatus("done");
            setProgress(100);
            const ok = data.translated_count || 0;
            const fail = data.failed_count || 0;
            const cached = data.cached_count || 0;
            const fromCache = cached > 0 ? ` (${cached} from cache · free)` : "";
            pushLog(`  DONE. ${ok} translated${fromCache}, ${fail} failed (kept as original).`, fail ? "info" : "ok");
            if (fail) {
              data.errors?.forEach((er) => pushLog(`  ! ${er}`, "err"));
              toast.warning(`${ok}/${data.total} translated; ${fail} failed.`);
            } else {
              toast.success(cached > 0 ? `Translation complete: ${cached} from cache, ${ok - cached} new.` : "Translation complete.");
            }
          } else if (data.status === "error") {
            clearInterval(pollRef.current);
            pollRef.current = null;
            setStatus("error");
            const code = data.error_code || "";
            const friendly = data.error || "Translation failed";
            pushLog(`! ERROR: ${friendly}`, "err");
            if (code === "EMERGENT_BUDGET_EXCEEDED") {
              toast.error("Emergent credits are exhausted. Switch to your own AI provider key in Settings.", {
                duration: 8000,
              });
            } else if (code === "QUOTA_EXCEEDED" || code === "INVALID_KEY") {
              toast.error(friendly, {
                duration: 8000,
              });
            } else {
              toast.error(friendly);
            }
          }
        } catch (err) {
          const status = err.response?.status;
          if ([502, 503, 504].includes(status) && consecutivePollFailures < 5) {
            consecutivePollFailures += 1;
            pushLog(`  Poll temporarily unavailable (${status}); retrying ${consecutivePollFailures}/5...`, "info");
            return;
          }
          clearInterval(pollRef.current);
          pollRef.current = null;
          setStatus("error");
          pushLog(`! POLL FAILED: ${err.message}`, "err");
        } finally {
          pollInFlight = false;
        }
      }, 1500);
    } catch (e) {
      setStatus("error");
      pushLog(`! TRANSLATION FAILED: ${e.response?.data?.detail || e.message}`, "err");
      toast.error(e.response?.data?.detail || "Translation failed");
    }
  };

  const handleEditTranslation = async (s, text) => {
    setTranslations((prev) => {
      const base = prev.length ? prev : session.strings.map((x) => ({ id: x.id, original: x.text, translated: "" }));
      return base.map((t) => (t.id === s.id ? { ...t, translated: text } : t));
    });
    if (!text.trim()) return;
    try {
      await axios.post(`${API}/cache/entry`, { source: s.text, translated: text, target_language: targetLang });
      toast.success("Translation saved to cache.");
    } catch (e) {
      toast.error("Saved locally, but could not update cache: " + (e.response?.data?.detail || e.message));
    }
  };


  const downloadPatched = async () => {
    if (!session || !translations.length) return;
    pushLog(`> PATCH ROM :: writing ${translations.length} strings...`, "cmd");
    try {
      const r = await axios.post(
        `${API}/rom/patch`,
        { session_id: session.session_id, translations },
        { responseType: "blob" }
      );
      const blob = new Blob([r.data], { type: "application/octet-stream" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const base = session.filename.replace(/\.(gb|gbc|gba)$/i, "");
      const ext = session.filename.match(/\.(gb|gbc|gba)$/i)?.[0] || ".gb";
      a.href = url;
      a.download = `${base}_${targetLang}${ext}`;
      a.click();
      URL.revokeObjectURL(url);
      pushLog(`  DONE. Patched ROM downloaded.`, "ok");
      toast.success("Patched ROM downloaded.");
    } catch (e) {
      pushLog(`! PATCH FAILED: ${e.message}`, "err");
      toast.error("Download failed");
    }
  };

  const exportTxt = async () => {
    if (!session) return;
    // If AI translation hasn't run (or partially failed), export a template with originals
    // as placeholders — user can then translate manually in a text editor.
    const items = (translations && translations.length > 0)
      ? translations
      : session.strings.map((s) => ({ id: s.id, original: s.text, translated: "" }));
    pushLog(`> EXPORT TXT :: ${items.length} strings${translations.length ? "" : " (template, no AI translation yet)"}...`, "cmd");
    try {
      const r = await axios.post(
        `${API}/rom/export`,
        { session_id: session.session_id, translations: items },
        { responseType: "blob" }
      );
      const blob = new Blob([r.data], { type: "text/plain; charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const base = session.filename.replace(/\.(gb|gbc|gba)$/i, "");
      a.href = url;
      a.download = `${base}_translations.txt`;
      a.click();
      URL.revokeObjectURL(url);
      pushLog(`  DONE. TXT downloaded — edit and re-upload via 'Insert Translation'.`, "ok");
      toast.success("Translation file downloaded.");
    } catch (e) {
      const msg = e.response?.data?.detail || e.message;
      pushLog(`! EXPORT FAILED: ${msg}`, "err");
      toast.error(`Export failed: ${msg}`);
    }
  };

  const importAndPatch = async (uploadedFile) => {
    if (!uploadedFile || !session) return;
    pushLog(`> INSERT TRANSLATION :: reading ${uploadedFile.name}...`, "cmd");
    try {
      const fd = new FormData();
      fd.append("session_id", session.session_id);
      fd.append("file", uploadedFile);
      const r = await axios.post(`${API}/rom/import`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
        responseType: "blob",
      });
      const patched = r.headers["x-patched-count"] || "?";
      const missed = r.headers["x-missed-count"] || "0";
      const blob = new Blob([r.data], { type: "application/octet-stream" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const base = session.filename.replace(/\.(gb|gbc|gba)$/i, "");
      const ext = session.filename.match(/\.(gb|gbc|gba)$/i)?.[0] || ".gb";
      a.href = url;
      a.download = `${base}_translated${ext}`;
      a.click();
      URL.revokeObjectURL(url);
      pushLog(`  DONE. Patched ${patched} strings (${missed} missed). ROM downloaded.`, "ok");
      toast.success(`Patched ${patched} strings. ROM downloaded.`);
    } catch (e) {
      const msg = e.response?.data?.detail || e.message;
      pushLog(`! INSERT FAILED: ${msg}`, "err");
      toast.error(`Insert failed: ${msg}`);
    }
  };

  return (
    <div className="min-h-screen retro-grid text-neutral-50 font-display" data-testid="app-root">
      {/* Header */}
      <header className="border-b border-neutral-800 px-6 py-5" data-testid="app-header">
        <div className="max-w-[1400px] mx-auto flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-[#8BAC0F] flex items-center justify-center rounded-sm">
              <Gamepad2 className="w-6 h-6 text-black" strokeWidth={2.5} />
            </div>
            <div>
              <h1 className="font-display text-xl sm:text-2xl font-bold tracking-tight" data-testid="app-title">
                ROM<span className="text-[#8BAC0F]">.</span>translate
              </h1>
              <p className="text-[10px] sm:text-xs font-mono text-neutral-500 uppercase tracking-wider">
                {t.tagline}
              </p>
            </div>
          </div>
          <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
            <button
              onClick={() => setSettingsOpen(true)}
              className="h-10 px-3 border border-neutral-700 hover:border-[#8BAC0F] text-neutral-200 hover:text-[#9BBC0F] font-mono text-xs uppercase flex items-center gap-2"
              data-testid="settings-open"
            >
              <Settings2 className="w-4 h-4" /> {t.settings}
            </button>
            <DialogContent className="max-h-[88vh] overflow-y-auto bg-neutral-950 border-neutral-800 text-neutral-100 sm:rounded-sm">
              <DialogHeader>
                <DialogTitle className="font-display text-xl">{t.settingsTitle}</DialogTitle>
                <DialogDescription className="text-neutral-500 font-mono text-xs">{t.settingsHint}</DialogDescription>
              </DialogHeader>
              <div className="space-y-5">
                <label className="block">
                  <span className="font-mono text-[10px] uppercase text-neutral-500 mb-1.5 block">{t.appLanguage}</span>
                  <Select value={appLanguage} onValueChange={setAppLanguage}>
                    <SelectTrigger className="h-10 bg-neutral-900 border-neutral-700 rounded-sm font-mono text-xs" data-testid="app-language-select"><SelectValue /></SelectTrigger>
                    <SelectContent className="bg-neutral-900 border-neutral-800 rounded-sm">
                      <SelectItem value="en">English</SelectItem>
                      <SelectItem value="cs">Čeština</SelectItem>
                    </SelectContent>
                  </Select>
                </label>
                <ClearCacheButton language={appLanguage} />
                <details className="border-t border-neutral-800 pt-4" data-testid="advanced-rom-settings">
                  <summary className="cursor-pointer font-mono text-xs uppercase text-neutral-300">{t.advanced}</summary>
                  <div className="space-y-4 pt-4">
                    <label className="block">
                      <span className="font-mono text-[10px] uppercase text-neutral-500 mb-1.5 block">{t.encoding}</span>
                      <Select value={encoding} onValueChange={setEncoding}>
                        <SelectTrigger className="h-10 bg-neutral-900 border-neutral-700 rounded-sm font-mono text-xs" data-testid="encoding-select"><SelectValue /></SelectTrigger>
                        <SelectContent className="bg-neutral-900 border-neutral-800 rounded-sm">
                          {encodings.map((entry) => <SelectItem key={entry.id} value={entry.id}>{entry.label}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </label>
                    <label className="block">
                      <span className="font-mono text-[10px] uppercase text-neutral-500 mb-1.5 block">{t.scanMode}</span>
                      <Select value={scanMode} onValueChange={setScanMode}>
                        <SelectTrigger className="h-10 bg-neutral-900 border-neutral-700 rounded-sm font-mono text-xs" data-testid="scan-mode-select"><SelectValue /></SelectTrigger>
                        <SelectContent className="bg-neutral-900 border-neutral-800 rounded-sm">
                          <SelectItem value="bytewise">{t.bytewise}</SelectItem>
                          <SelectItem value="pointers">{t.pointers}</SelectItem>
                        </SelectContent>
                      </Select>
                    </label>
                  </div>
                </details>
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </header>

      <main className="max-w-5xl mx-auto p-4 sm:p-6 flex flex-col gap-5">
        <section
          className={`w-full max-w-3xl mx-auto bg-neutral-900 border rounded-sm p-5 sm:p-6 transition-colors ${
            dragActive ? "border-[#8BAC0F]" : "border-neutral-800"
          }`}
          onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
          onDragLeave={() => setDragActive(false)}
          onDrop={onDrop}
          data-testid="dropzone-card"
        >
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-mono text-xs uppercase text-neutral-400 tracking-widest">{t.romStep}</h2>
            {session && <CheckCircle2 className="w-4 h-4 text-[#9BBC0F]" />}
          </div>

          <div
            className={`border-2 border-dashed p-6 text-center cursor-pointer transition-colors ${
              dragActive ? "border-[#8BAC0F] bg-[#8BAC0F]/5" : "border-neutral-700 hover:border-[#8BAC0F]"
            }`}
            onClick={() => fileInput.current?.click()}
            data-testid="upload-rom-zone"
          >
            <input
              ref={fileInput}
              type="file"
              accept=".gb,.gbc,.gba"
              className="hidden"
              onChange={(e) => handleFile(e.target.files?.[0])}
              data-testid="rom-file-input"
            />
            <Upload className="w-7 h-7 mx-auto mb-2 text-[#8BAC0F]" strokeWidth={1.5} />
            {file ? (
              <>
                <p className="font-mono text-sm text-[#9BBC0F] break-all" data-testid="selected-file-name">{file.name}</p>
                <p className="font-mono text-xs text-neutral-500 mt-1">{(file.size / 1024).toFixed(1)} KB</p>
              </>
            ) : (
              <>
                <p className="font-display text-base font-semibold">{t.chooseRom}</p>
                <p className="font-mono text-xs text-neutral-500 mt-1.5">{t.dropHint}</p>
              </>
            )}
          </div>

          {file && !session && (
            <button
              onClick={extract}
              disabled={status === "extracting"}
              className="mt-4 w-full h-11 bg-[#8BAC0F] text-black font-display font-bold text-sm uppercase rounded-sm btn-brutal disabled:opacity-40 flex items-center justify-center gap-2"
              data-testid="extract-btn"
            >
              {status === "extracting" ? <><Loader2 className="w-4 h-4 animate-spin" />{t.loadingRom}</> : <>{t.loadRom}</>}
            </button>
          )}

          {session && (
            <section className="mt-6 border-t border-neutral-800 pt-5" data-testid="post-load-controls">
              <div className="mb-4">
                <p className="font-mono text-[10px] uppercase tracking-widest text-[#9BBC0F]">02 / {t.translation}</p>
                <p className="mt-1 font-mono text-xs text-neutral-500">{session.strings.length.toLocaleString()} {t.loadedStrings}</p>
                <p className="mt-2 font-mono text-[10px] text-neutral-500" data-testid="cache-preview-status">
                  {cachePreviewLoading
                    ? t.checkingCache
                    : `${cachedCount} ${t.cachedTranslations}${rejectedCachedCount ? ` · ${rejectedCachedCount} ${t.rejectedCached}` : ""}`}
                </p>
              </div>
              <label className="block">
                <span className="font-mono text-[10px] uppercase text-neutral-500 mb-1.5 block">{t.targetLanguage}</span>
                <Select value={targetLang} onValueChange={setTargetLang}>
                  <SelectTrigger className="h-11 bg-neutral-950 border-neutral-700 rounded-sm font-mono text-xs" data-testid="language-select"><SelectValue /></SelectTrigger>
                  <SelectContent className="bg-neutral-900 border-neutral-800 rounded-sm">
                    {languages.map((language) => (
                      <SelectItem key={language.code} value={language.code} data-testid={`lang-option-${language.code}`}>
                        <span className="text-[#8BAC0F] mr-2">{language.code.toUpperCase()}</span>{language.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
              <div className="mt-5 border-t border-neutral-800 pt-4">
                <AiSettingsDialog
                  providers={providers}
                  settings={aiSettings}
                  onSave={(next) => { saveSettings(next); setAiSettings(next); }}
                  language={appLanguage}
                />
              </div>
              {estimate && (
                <p className="mt-4 font-mono text-[10px] text-neutral-500" data-testid="cost-estimate">
                  {t.cost}: <span className="text-[#9BBC0F]">{formatCost(estimate.total)}</span>
                </p>
              )}
              {requiresApiKey && (
                <p className="mt-4 font-mono text-xs text-amber-400" role="status" data-testid="api-key-required">
                  {t.apiKeyNeeded}
                </p>
              )}
              <button
                onClick={translate}
                disabled={status === "translating" || cachePreviewLoading || requiresApiKey}
                className="mt-5 w-full h-12 bg-[#8BAC0F] text-black font-display font-bold text-sm uppercase rounded-sm btn-brutal disabled:opacity-50 flex items-center justify-center gap-2"
                data-testid="translate-btn"
              >
                {status === "translating" ? <><Loader2 className="w-4 h-4 animate-spin" />{t.translating}</> : <><Zap className="w-4 h-4" />{t.translate}</>}
              </button>
            </section>
          )}

          {session && (
            <section className="mt-5 border-t border-neutral-800 pt-4" data-testid="text-file-options">
              <div className="flex flex-col sm:flex-row gap-2">
                <button
                  onClick={exportTxt}
                  className="h-10 flex-1 border border-neutral-700 hover:border-[#8BAC0F] text-neutral-300 hover:text-[#9BBC0F] font-mono text-xs uppercase flex items-center justify-center gap-2"
                  data-testid="export-txt-btn"
                >
                  <FileText className="w-4 h-4" /> {t.exportTxt}
                </button>
                <input
                  ref={importInput}
                  type="file"
                  accept=".txt,text/plain"
                  className="hidden"
                  onChange={(event) => { const selectedFile = event.target.files?.[0]; if (selectedFile) importAndPatch(selectedFile); event.target.value = ""; }}
                  data-testid="import-txt-input"
                />
                <button
                  onClick={() => importInput.current?.click()}
                  className="h-10 flex-1 border border-neutral-700 hover:border-[#8BAC0F] text-neutral-300 hover:text-[#9BBC0F] font-mono text-xs uppercase flex items-center justify-center gap-2"
                  data-testid="insert-translation-btn"
                >
                  <FileUp className="w-4 h-4" /> {t.importPatch}
                </button>
              </div>
              <button
                onClick={downloadPatched}
                disabled={!translations.some((item) => item.translated && item.translated !== item.original)}
                className="mt-2 w-full h-10 bg-[#8BAC0F] text-black font-display font-bold text-xs uppercase rounded-sm btn-brutal disabled:opacity-50 flex items-center justify-center gap-2"
                data-testid="download-btn"
              >
                <Download className="w-3.5 h-3.5" /> {t.downloadRom}
              </button>
            </section>
          )}
        </section>

        {/* Terminal */}
        <section className="lg:col-span-7 bg-black border border-neutral-800 rounded-sm overflow-hidden scanlines" data-testid="terminal-card">
          <div className="flex items-center justify-between px-4 py-2.5 bg-neutral-900 border-b border-neutral-800">
            <div className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full bg-[#C7305C]"></div>
              <div className="w-2.5 h-2.5 rounded-full bg-yellow-500"></div>
              <div className="w-2.5 h-2.5 rounded-full bg-[#8BAC0F]"></div>
              <span className="font-mono text-[10px] text-neutral-500 uppercase ml-3">extraction.log</span>
            </div>
            <div className="flex items-center gap-2">
              {status === "done" && <CheckCircle2 className="w-3.5 h-3.5 text-[#8BAC0F]" />}
              {status === "error" && <XCircle className="w-3.5 h-3.5 text-[#C7305C]" />}
              {(status === "extracting" || status === "translating") && <Loader2 className="w-3.5 h-3.5 animate-spin text-[#8BAC0F]" />}
              <span className="font-mono text-[10px] uppercase text-neutral-500">{status}</span>
            </div>
          </div>
          <Terminal logs={logs} />
          {progress > 0 && progress < 100 && (
            <div className="px-4 pb-3">
              <div className="h-2 bg-neutral-900 border border-neutral-800 flex gap-[2px] p-[2px]">
                {Array.from({ length: 20 }).map((_, i) => (
                  <div
                    key={i}
                    className={`flex-1 ${i < Math.floor(progress / 5) ? "bg-[#8BAC0F]" : "bg-neutral-800"}`}
                  />
                ))}
              </div>
              <p className="font-mono text-[10px] text-neutral-500 mt-1">{progress}%</p>
            </div>
          )}
        </section>

        {session && (
          <section className="w-full max-w-3xl mx-auto border border-neutral-800 bg-neutral-900/80" data-testid="viewer-card">
            <div className="flex items-center justify-between px-4 sm:px-6 py-4 border-b border-neutral-800">
              <h2 className="font-display text-lg font-semibold">{t.translation}</h2>
              <span className="font-mono text-[10px] text-neutral-500">{session.strings.length.toLocaleString()}</span>
            </div>
            <TranslationTable
              strings={session.strings}
              translations={translations}
              encoding={session.encoding}
              onEdit={handleEditTranslation}
              language={appLanguage}
            />
          </section>
        )}

      </main>

      <footer className="border-t border-neutral-800 mt-8 py-6 px-6">
        <div className="max-w-5xl mx-auto flex items-center justify-between gap-2 font-mono text-[10px] text-neutral-600 uppercase tracking-widest">
          <span>ROM.translate · {t.appFooter}</span>
          <span>v{APP_VERSION}</span>
        </div>
      </footer>
    </div>
  );
}

function StatRow({ label, value, highlight = false }) {
  return (
    <div className="flex items-center justify-between border-b border-neutral-800 pb-2">
      <dt className="text-neutral-500 uppercase tracking-wider text-[10px]">{label}</dt>
      <dd className={`${highlight ? "text-[#9BBC0F]" : "text-neutral-200"} font-semibold`}>{value}</dd>
    </div>
  );
}

/** Rough cost estimate for a translation run.
 * Heuristic tokens: input ~ (avg_len * 1.2 + 25) per string (prompt + JSON overhead),
 * output ~ avg_len * 1.4 (translation with some expansion). Both divided by 4 chars/token.
 */
export function estimateCost(strings, provider, modelId, providers) {
  const p = providers?.[provider];
  if (!p) return null;
  const m = p.models.find((x) => x.id === modelId) || p.models.find((x) => x.id === p.default);
  if (!m?.pricing) return null;
  const count = strings.length;
  if (!count) return { input: 0, output: 0, total: 0, count: 0 };
  const avgLen = strings.reduce((s, x) => s + (x.text?.length || 20), 0) / count;
  const inTokens = count * ((avgLen * 1.2) + 25) / 4;
  const outTokens = count * (avgLen * 1.4) / 4;
  const inCost = (inTokens / 1_000_000) * m.pricing.input;
  const outCost = (outTokens / 1_000_000) * m.pricing.output;
  return {
    input: inCost,
    output: outCost,
    total: inCost + outCost,
    count,
    inTokens: Math.round(inTokens),
    outTokens: Math.round(outTokens),
  };
}
