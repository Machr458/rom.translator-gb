import { useEffect, useState, useRef, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  Gamepad2,
  Upload,
  Download,
  FileArchive,
  Cpu,
  Zap,
  ChevronDown,
  Loader2,
  CheckCircle2,
  XCircle,
  Settings2,
  Sparkles,
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

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";
const API = `${BACKEND_URL}/api`;

export default function RomTranslator() {
  const [languages, setLanguages] = useState([]);
  const [providers, setProviders] = useState({});
  const [encodings, setEncodings] = useState([]);
  const [encoding, setEncoding] = useState("auto");
  const [scanMode, setScanMode] = useState("bytewise");
  const [aiSettings, setAiSettings] = useState(loadSettings());
  const [targetLang, setTargetLang] = useState("cs");
  const [file, setFile] = useState(null);
  const [session, setSession] = useState(null);
  const [translations, setTranslations] = useState([]);
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [dragActive, setDragActive] = useState(false);
  const fileInput = useRef(null);
  const importInput = useRef(null);
  const pollRef = useRef(null);

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
    if (aiSettings.provider !== "emergent" && !aiSettings.apiKey) {
      toast.error("Enter an API key in Settings before translating.");
      return;
    }
    setStatus("translating");
    setProgress(2);
    setTranslations(session.strings.map((s) => ({ id: s.id, original: s.text, translated: "" })));
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
                ROM<span className="text-[#8BAC0F]">.</span>TRANSLATE
              </h1>
              <p className="text-[10px] sm:text-xs font-mono text-neutral-500 uppercase tracking-wider">
                Gameboy · AI localization terminal
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden sm:inline-flex items-center gap-2 border border-neutral-800 px-3 py-2 font-mono text-[10px] uppercase text-neutral-400">
              <Sparkles className="w-3 h-3 text-[#9BBC0F]" /> {providerLabel()}
            </span>
          </div>
        </div>
      </header>

      <main className="max-w-[1400px] mx-auto p-4 sm:p-6 grid grid-cols-1 lg:grid-cols-12 gap-4 sm:gap-6">
        <section
          className={`lg:col-span-5 bg-neutral-900 border rounded-sm p-5 sm:p-6 transition-colors ${
            dragActive ? "border-[#8BAC0F]" : "border-neutral-800"
          }`}
          onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
          onDragLeave={() => setDragActive(false)}
          onDrop={onDrop}
          data-testid="dropzone-card"
        >
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-mono text-xs uppercase text-neutral-400 tracking-widest">01 · Cartridge</h2>
            <FileArchive className="w-4 h-4 text-neutral-600" />
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
                <p className="font-display text-base font-semibold">Select a ROM</p>
                <p className="font-mono text-xs text-neutral-500 mt-1.5">Drop a .gb, .gbc, or .gba file here</p>
              </>
            )}
          </div>

          <details className="group mt-4 border border-neutral-800 bg-neutral-950/50" data-testid="settings-dropdown">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-3 font-mono text-[11px] uppercase tracking-wider text-neutral-300 hover:text-[#9BBC0F]">
              <span className="flex items-center gap-2"><Settings2 className="w-3.5 h-3.5" /> Settings</span>
              <span className="text-[10px] text-neutral-600 normal-case">{targetLang.toUpperCase()} · {providerLabel()}</span>
              <ChevronDown className="w-4 h-4 shrink-0 transition-transform group-open:rotate-180" />
            </summary>
            <div className="space-y-4 border-t border-neutral-800 p-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <label className="block">
                  <span className="font-mono text-[10px] uppercase text-neutral-500 mb-1.5 block">Target language</span>
                  <Select value={targetLang} onValueChange={setTargetLang}>
                    <SelectTrigger className="h-10 bg-neutral-950 border-neutral-700 rounded-sm font-mono text-xs" data-testid="language-select">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-neutral-900 border-neutral-800 rounded-sm">
                      {languages.map((language) => (
                        <SelectItem key={language.code} value={language.code} className="font-mono text-xs" data-testid={`lang-option-${language.code}`}>
                          <span className="text-[#8BAC0F] mr-2">{language.code.toUpperCase()}</span>{language.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </label>
                <label className="block">
                  <span className="font-mono text-[10px] uppercase text-neutral-500 mb-1.5 block">Text encoding</span>
                  <Select value={encoding} onValueChange={setEncoding}>
                    <SelectTrigger className="h-10 bg-neutral-950 border-neutral-700 rounded-sm font-mono text-xs" data-testid="encoding-select">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-neutral-900 border-neutral-800 rounded-sm">
                      {encodings.map((entry) => (
                        <SelectItem key={entry.id} value={entry.id} className="font-mono text-xs" data-testid={`encoding-option-${entry.id}`}>
                          {entry.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </label>
              </div>

              <label className="block">
                <span className="font-mono text-[10px] uppercase text-neutral-500 mb-1.5 block">Scan mode</span>
                <Select value={scanMode} onValueChange={setScanMode}>
                  <SelectTrigger className="h-10 bg-neutral-950 border-neutral-700 rounded-sm font-mono text-xs" data-testid="scan-mode-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-neutral-900 border-neutral-800 rounded-sm">
                    <SelectItem value="bytewise" className="font-mono text-xs" data-testid="scan-mode-option-bytewise">
                      Full scan · story and descriptions
                    </SelectItem>
                    <SelectItem value="pointers" className="font-mono text-xs" data-testid="scan-mode-option-pointers">
                      Pointer table · GBA only
                    </SelectItem>
                  </SelectContent>
                </Select>
              </label>

              <AiSettingsDialog
                providers={providers}
                settings={aiSettings}
                onSave={setAiSettings}
              />
            </div>
          </details>

          <button
            onClick={extract}
            disabled={!file || status === "extracting"}
            className="mt-4 w-full h-11 bg-[#8BAC0F] text-black font-display font-bold text-sm tracking-wide rounded-sm btn-brutal disabled:opacity-40 disabled:cursor-not-allowed disabled:shadow-none flex items-center justify-center gap-2"
            data-testid="extract-btn"
          >
            {status === "extracting" ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> SCANNING...</>
            ) : (
              <><Cpu className="w-4 h-4" /> SCAN & EXTRACT</>
            )}
          </button>

          <button
            onClick={translate}
            disabled={!session || status === "translating"}
            className="mt-2 w-full h-11 bg-transparent border border-[#8BAC0F] text-[#9BBC0F] font-display font-bold text-sm tracking-wide rounded-sm disabled:opacity-30 disabled:cursor-not-allowed hover:bg-[#8BAC0F]/10 transition-colors flex items-center justify-center gap-2"
            data-testid="translate-btn"
          >
            {status === "translating" ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> TRANSLATING...</>
            ) : (
              <><Zap className="w-4 h-4" /> TRANSLATE</>
            )}
          </button>

          <button
            onClick={downloadPatched}
            disabled={status !== "done"}
            className="mt-2 w-full h-11 bg-transparent border border-neutral-700 text-neutral-300 font-display font-bold text-sm tracking-wide rounded-sm disabled:opacity-30 disabled:cursor-not-allowed hover:border-[#8BAC0F] hover:text-[#9BBC0F] transition-colors flex items-center justify-center gap-2"
            data-testid="download-btn"
          >
            <Download className="w-4 h-4" /> DOWNLOAD PATCHED ROM
          </button>

          {session?.strings?.length > 0 && (() => {
            const estimate = estimateCost(session.strings, aiSettings.provider, aiSettings.model || providers?.[aiSettings.provider]?.default, providers);
            if (!estimate) return null;
            const formatCost = (value) => value < 0.001 ? "<$0.001" : value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(3)}`;
            return (
              <div className="mt-3 border border-neutral-800 rounded-sm p-3 bg-neutral-950/70" data-testid="cost-estimate">
                <div className="flex items-center justify-between font-mono text-[10px] uppercase text-neutral-500 mb-2">
                  <span>Estimated cost</span>
                  <span className="text-[#9BBC0F]">{formatCost(estimate.total)}</span>
                </div>
                <div className="font-mono text-[10px] text-neutral-500 flex justify-between gap-2">
                  <span>{estimate.count} strings · ~{Math.round((estimate.inTokens + estimate.outTokens) / 1000)}k tokens</span>
                  <span>In {formatCost(estimate.input)} · Out {formatCost(estimate.output)}</span>
                </div>
              </div>
            );
          })()}

          <details className="group mt-4 border-t border-neutral-800 pt-3" data-testid="text-file-options">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 font-mono text-[10px] uppercase tracking-wider text-neutral-500 hover:text-neutral-300">
              <span className="flex items-center gap-2"><FileText className="w-3.5 h-3.5" /> Other options · export / import</span>
              <ChevronDown className="w-4 h-4 transition-transform group-open:rotate-180" />
            </summary>
            <div className="pt-3">
              <button
                onClick={exportTxt}
                disabled={!session}
                className="w-full h-10 bg-transparent border border-neutral-700 hover:border-[#8BAC0F] text-neutral-300 hover:text-[#9BBC0F] font-display font-bold text-xs tracking-wide rounded-sm disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
                data-testid="export-txt-btn"
              >
                <FileText className="w-4 h-4" /> EXPORT TRANSLATION FILE
              </button>
              <input
                ref={importInput}
                type="file"
                accept=".txt,text/plain"
                className="hidden"
                onChange={(event) => {
                  const selectedFile = event.target.files?.[0];
                  if (selectedFile) importAndPatch(selectedFile);
                  event.target.value = "";
                }}
                data-testid="import-txt-input"
              />
              <button
                onClick={() => importInput.current?.click()}
                disabled={!session}
                className="mt-2 w-full h-10 bg-transparent border border-neutral-700 hover:border-[#8BAC0F] text-neutral-300 hover:text-[#9BBC0F] font-display font-bold text-xs tracking-wide rounded-sm disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
                data-testid="insert-translation-btn"
              >
                <FileUp className="w-4 h-4" /> IMPORT & BUILD ROM
              </button>
            </div>
          </details>
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

        {/* Session stats */}
        <section className="lg:col-span-5 bg-neutral-900 border border-neutral-800 rounded-sm p-6" data-testid="stats-card">
          <h2 className="font-mono text-xs uppercase text-neutral-400 tracking-widest mb-4">02 · Session</h2>
          <dl className="space-y-3 font-mono text-xs">
            <StatRow label="ROM Type" value={session?.rom_type || "—"} />
            <StatRow label="Size" value={session ? `${(session.rom_size / 1024).toFixed(1)} KB` : "—"} />
            <StatRow label="Encoding" value={session?.encoding || encoding} highlight={session?.encoding === "pokemon_gen3"} />
            <StatRow label="Found in ROM" value={session?.found_total ?? "—"} />
            <StatRow label="Loaded" value={session?.strings?.length ?? "—"} highlight />
            <StatRow label="Target" value={targetLang.toUpperCase()} />
            <StatRow label="AI" value={<span className="inline-flex items-center gap-1"><Sparkles className="w-3 h-3" />{(aiSettings.provider || "emergent").toUpperCase()}</span>} />
            <StatRow
              label="Translated"
              value={translations.filter((t) => t.translated).length + " / " + translations.length}
              highlight={status === "done"}
            />
          </dl>
        </section>

        {/* Translation table */}
        <section className="lg:col-span-7 bg-neutral-900 border border-neutral-800 rounded-sm" data-testid="viewer-card">
          <div className="flex items-center justify-between px-6 py-4 border-b border-neutral-800">
            <h2 className="font-display text-lg font-bold tracking-tight">Translation Viewer</h2>
            <span className="font-mono text-[11px] text-neutral-500">{session?.strings?.length || 0} strings</span>
          </div>
          <TranslationTable
            strings={session?.strings || []}
            translations={translations}
            encoding={session?.encoding}
            onEdit={handleEditTranslation}
          />
        </section>
      </main>

      <footer className="border-t border-neutral-800 mt-8 py-6 px-6">
        <div className="max-w-[1400px] mx-auto flex flex-col sm:flex-row items-center justify-between gap-2 font-mono text-[10px] text-neutral-600 uppercase tracking-widest">
          <span>ROM Translate</span>
          <span>Gemini · OpenAI · Anthropic · FreeTheAI</span>
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
