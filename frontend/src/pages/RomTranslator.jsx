import { useEffect, useState, useRef, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  Gamepad2,
  Upload,
  Languages,
  Download,
  FileArchive,
  Cpu,
  Zap,
  History,
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
import AiSettingsDialog, { loadSettings } from "@/components/rom/AiSettingsDialog";
import { ClearCacheButton } from "@/components/rom/ClearCacheButton";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const MODES = [
  { id: "export", label: "Export as Text", icon: FileText },
  { id: "patch", label: "Generate Patched ROM", icon: Download },
];

export default function RomTranslator() {
  const [languages, setLanguages] = useState([]);
  const [providers, setProviders] = useState({});
  const [encodings, setEncodings] = useState([]);
  const [encoding, setEncoding] = useState("auto");
  const [scanMode, setScanMode] = useState("bytewise");
  const [maxStrings, setMaxStrings] = useState(500);
  const [batchSize, setBatchSize] = useState(60);
  const [aiSettings, setAiSettings] = useState(loadSettings());
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [targetLang, setTargetLang] = useState("cs");
  const [mode, setMode] = useState("export");
  const [file, setFile] = useState(null);
  const [session, setSession] = useState(null);
  const [translations, setTranslations] = useState([]);
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [history, setHistory] = useState([]);
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
    loadHistory();
    pushLog("SYSTEM READY. Insert cartridge to begin.", "sys");
  }, [pushLog]);

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
  }, []);

  const loadHistory = async () => {
    try {
      const r = await axios.get(`${API}/history`);
      setHistory(r.data);
    } catch (_) { /* ignore */ }
  };

  const providerLabel = () => {
    const p = providers?.[aiSettings.provider];
    const modelId = aiSettings.model || p?.default || "";
    return `${(aiSettings.provider || "emergent").toUpperCase()} · ${modelId}`;
  };

  const handleFile = (f) => {
    if (!f) return;
    const name = f.name.toLowerCase();
    if (!name.endsWith(".gb") && !name.endsWith(".gbc") && !name.endsWith(".gba")) {
      toast.error("Nepodporovaný formát. Nahraj .gb, .gbc nebo .gba");
      return;
    }
    setFile(f);
    setSession(null);
    setTranslations([]);
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
      fd.append("max_strings", String(maxStrings));
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
      pushLog(`  LOAD  : ${r.data.strings.length} strings (limit ${maxStrings})`, "ok");
      if (r.data.found_total > r.data.strings.length) {
        pushLog(`  NOTE  : ${r.data.found_total - r.data.strings.length} more strings skipped — raise "Max Strings" to load more.`, "info");
      }
      pushLog(`> READY. Choose target language and press TRANSLATE.`, "cmd");
      loadHistory();
    } catch (e) {
      setStatus("error");
      const detail = e.response?.data?.detail || e.message || "Unknown error";
      pushLog(`! ERROR: ${detail}`, "err");
      pushLog(`  Try lowering "Max Strings" or switching encoding.`, "err");
      toast.error(`Extraction failed: ${detail}`);
    }
  };

  const translate = async () => {
    if (!session) return;
    if (aiSettings.provider !== "emergent" && !aiSettings.apiKey) {
      toast.error("Zadej API klíč nebo přepni na Emergent Universal Key");
      setSettingsOpen(true);
      return;
    }
    setStatus("translating");
    setProgress(2);
    setTranslations(session.strings.map((s) => ({ id: s.id, original: s.text, translated: "" })));
    pushLog(`> TRANSLATE :: target=${targetLang.toUpperCase()} via ${providerLabel()}`, "cmd");
    pushLog(`  Sending ${session.strings.length} strings in ${Math.ceil(session.strings.length / batchSize)} batch(es) of ${batchSize}...`, "info");

    try {
      const r = await axios.post(`${API}/rom/translate`, {
        session_id: session.session_id,
        target_language: targetLang,
        strings: session.strings,
        provider: aiSettings.provider,
        model: aiSettings.model || providers?.[aiSettings.provider]?.default,
        api_key: aiSettings.apiKey || "",
        batch_size: batchSize,
      });
      const jobId = r.data.job_id;
      pushLog(`  JOB ${jobId.slice(0, 8)}... running`, "info");
      pollRef.current = setInterval(async () => {
        try {
          const s = await axios.get(`${API}/rom/translate/status/${jobId}`);
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
              toast.warning(`${ok}/${data.total} přeloženo — ${fail} selhalo.`);
            } else {
              toast.success(cached > 0 ? `Překlad hotov! (${cached} z cache, ${ok - cached} nových)` : "Překlad dokončen!");
            }
          } else if (data.status === "error") {
            clearInterval(pollRef.current);
            pollRef.current = null;
            setStatus("error");
            const code = data.error_code || "";
            const friendly = data.error || "Translation failed";
            pushLog(`! ERROR: ${friendly}`, "err");
            if (code === "EMERGENT_BUDGET_EXCEEDED") {
              toast.error("Emergent kredit vyčerpán — přepni na vlastní AI klíč v Nastavení", {
                duration: 8000,
                action: {
                  label: "Otevřít nastavení",
                  onClick: () => setSettingsOpen(true),
                },
              });
            } else if (code === "QUOTA_EXCEEDED" || code === "INVALID_KEY") {
              toast.error(friendly, {
                duration: 8000,
                action: {
                  label: "Otevřít nastavení",
                  onClick: () => setSettingsOpen(true),
                },
              });
            } else {
              toast.error(friendly);
            }
          }
        } catch (err) {
          clearInterval(pollRef.current);
          pollRef.current = null;
          setStatus("error");
          pushLog(`! POLL FAILED: ${err.message}`, "err");
        }
      }, 1500);
    } catch (e) {
      setStatus("error");
      pushLog(`! TRANSLATION FAILED: ${e.response?.data?.detail || e.message}`, "err");
      toast.error(e.response?.data?.detail || "Translation failed");
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
      toast.success("Přeložená ROMka stažena!");
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
      toast.success("Textový soubor stažen!");
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
      toast.success(`Patchnuto ${patched} řetězců, ROMka stažena!`);
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
            <ClearCacheButton />
            <button
              onClick={() => setSettingsOpen(true)}
              className="h-9 px-3 border border-neutral-700 hover:border-[#8BAC0F] rounded-sm font-mono text-[11px] uppercase tracking-wider text-neutral-300 hover:text-[#9BBC0F] transition-colors flex items-center gap-2"
              data-testid="open-settings-btn"
            >
              <Settings2 className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">{providerLabel()}</span>
              <span className="sm:hidden">AI</span>
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-[1400px] mx-auto p-4 sm:p-6 grid grid-cols-1 lg:grid-cols-12 gap-4 sm:gap-6">
        {/* Dropzone */}
        <section
          className={`lg:col-span-5 bg-neutral-900 border rounded-sm p-6 transition-colors ${
            dragActive ? "border-[#8BAC0F]" : "border-neutral-800"
          }`}
          onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
          onDragLeave={() => setDragActive(false)}
          onDrop={onDrop}
          data-testid="dropzone-card"
        >
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-mono text-xs uppercase text-neutral-400 tracking-widest">01 · Cartridge Slot</h2>
            <FileArchive className="w-4 h-4 text-neutral-600" />
          </div>
          <div
            className={`border-2 border-dashed p-8 text-center cursor-pointer transition-colors ${
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
            <Upload className="w-8 h-8 mx-auto mb-3 text-[#8BAC0F]" strokeWidth={1.5} />
            {file ? (
              <>
                <p className="font-mono text-sm text-[#9BBC0F] break-all" data-testid="selected-file-name">{file.name}</p>
                <p className="font-mono text-xs text-neutral-500 mt-1">
                  {(file.size / 1024).toFixed(1)} KB
                </p>
              </>
            ) : (
              <>
                <p className="font-display text-base font-semibold">Insert ROM cartridge</p>
                <p className="font-mono text-xs text-neutral-500 mt-2">
                  Drop .gb / .gbc / .gba file or click to browse
                </p>
              </>
            )}
          </div>
          <button
            onClick={extract}
            disabled={!file || status === "extracting"}
            className="mt-5 w-full h-11 bg-[#8BAC0F] text-black font-display font-bold text-sm tracking-wide rounded-sm btn-brutal disabled:opacity-40 disabled:cursor-not-allowed disabled:shadow-none flex items-center justify-center gap-2"
            data-testid="extract-btn"
          >
            {status === "extracting" ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> SCANNING...</>
            ) : (
              <><Cpu className="w-4 h-4" /> SCAN & EXTRACT</>
            )}
          </button>
        </section>

        {/* Settings */}
        <section className="lg:col-span-4 bg-neutral-900 border border-neutral-800 rounded-sm p-6" data-testid="settings-card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-mono text-xs uppercase text-neutral-400 tracking-widest">02 · Config</h2>
            <Languages className="w-4 h-4 text-neutral-600" />
          </div>

          <label className="font-mono text-[10px] uppercase text-neutral-500 tracking-wider mb-2 block">Target Language</label>
          <Select value={targetLang} onValueChange={setTargetLang}>
            <SelectTrigger
              className="h-11 bg-neutral-950 border-neutral-700 rounded-sm font-mono text-sm"
              data-testid="language-select"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-neutral-900 border-neutral-800 rounded-sm">
              {languages.map((l) => (
                <SelectItem key={l.code} value={l.code} className="font-mono text-sm" data-testid={`lang-option-${l.code}`}>
                  <span className="text-[#8BAC0F] mr-2">{l.code.toUpperCase()}</span>{l.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <label className="font-mono text-[10px] uppercase text-neutral-500 tracking-wider mt-5 mb-2 block">Text Encoding</label>
          <Select value={encoding} onValueChange={setEncoding}>
            <SelectTrigger
              className="h-11 bg-neutral-950 border-neutral-700 rounded-sm font-mono text-sm"
              data-testid="encoding-select"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-neutral-900 border-neutral-800 rounded-sm">
              {encodings.map((e) => (
                <SelectItem key={e.id} value={e.id} className="font-mono text-sm" data-testid={`encoding-option-${e.id}`}>
                  {e.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <label className="font-mono text-[10px] uppercase text-neutral-500 tracking-wider mt-5 mb-2 block">
            Scan Mode <span className="text-neutral-600 normal-case tracking-normal">— text detection strategy</span>
          </label>
          <Select value={scanMode} onValueChange={setScanMode}>
            <SelectTrigger
              className="h-11 bg-neutral-950 border-neutral-700 rounded-sm font-mono text-sm"
              data-testid="scan-mode-select"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-neutral-900 border-neutral-800 rounded-sm">
              <SelectItem value="bytewise" className="font-mono text-sm" data-testid="scan-mode-option-bytewise">
                Bytewise scan (all text-looking runs)
              </SelectItem>
              <SelectItem value="pointers" className="font-mono text-sm" data-testid="scan-mode-option-pointers">
                Pointer table (Pokemon Gen 3 · high precision)
                <span className="text-[#9BBC0F] ml-2">recommended</span>
              </SelectItem>
            </SelectContent>
          </Select>

          <label className="font-mono text-[10px] uppercase text-neutral-500 tracking-wider mt-5 mb-2 block">Max Strings</label>
          <Select value={String(maxStrings)} onValueChange={(v) => setMaxStrings(Number(v))}>
            <SelectTrigger
              className="h-11 bg-neutral-950 border-neutral-700 rounded-sm font-mono text-sm"
              data-testid="max-strings-select"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-neutral-900 border-neutral-800 rounded-sm">
              {[100, 250, 500, 1000, 2000, 5000, 0].map((n) => (
                <SelectItem key={n} value={String(n)} className="font-mono text-sm" data-testid={`max-strings-option-${n}`}>
                  {n === 0
                    ? "UNLIMITED (all strings)"
                    : n === 5000
                    ? "5000 strings"
                    : `${n} strings`}
                  {(n === 0 || n >= 2000) && (
                    <span className="text-[#C7305C] ml-2">
                      {n === 0 ? "(⚠ can be huge · high LLM cost)" : "(slow · high LLM cost)"}
                    </span>
                  )}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <label className="font-mono text-[10px] uppercase text-neutral-500 tracking-wider mt-5 mb-2 block">
            Batch Size <span className="text-neutral-600 normal-case tracking-normal">— strings per AI call</span>
          </label>
          <Select value={String(batchSize)} onValueChange={(v) => setBatchSize(Number(v))}>
            <SelectTrigger
              className="h-11 bg-neutral-950 border-neutral-700 rounded-sm font-mono text-sm"
              data-testid="batch-size-select"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-neutral-900 border-neutral-800 rounded-sm">
              {[20, 60, 120, 200, 300].map((n) => (
                <SelectItem key={n} value={String(n)} className="font-mono text-sm" data-testid={`batch-size-option-${n}`}>
                  {n} strings / call {n === 60 ? " · default" : ""}{n >= 200 ? <span className="text-[#C7305C] ml-2">(risk of output truncation)</span> : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <label className="font-mono text-[10px] uppercase text-neutral-500 tracking-wider mt-5 mb-2 block">Output Mode</label>
          <div className="grid grid-cols-2 gap-2">
            {MODES.map((m) => {
              const Icon = m.icon;
              const active = mode === m.id;
              return (
                <button
                  key={m.id}
                  onClick={() => setMode(m.id)}
                  className={`h-11 border rounded-sm text-xs font-display font-semibold flex items-center justify-center gap-1.5 transition-colors ${
                    active
                      ? "border-[#8BAC0F] bg-[#8BAC0F]/10 text-[#9BBC0F]"
                      : "border-neutral-700 text-neutral-400 hover:border-neutral-600"
                  }`}
                  data-testid={`mode-${m.id}`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  <span className="hidden sm:inline">{m.label}</span>
                  <span className="sm:hidden">{m.id === "export" ? "Export" : "Patch"}</span>
                </button>
              );
            })}
          </div>

          <button
            onClick={translate}
            disabled={!session || status === "translating"}
            className="mt-5 w-full h-11 bg-[#8BAC0F] text-black font-display font-bold text-sm tracking-wide rounded-sm btn-brutal disabled:opacity-40 disabled:cursor-not-allowed disabled:shadow-none flex items-center justify-center gap-2"
            data-testid="translate-btn"
          >
            {status === "translating" ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> TRANSLATING...</>
            ) : (
              <><Zap className="w-4 h-4" /> TRANSLATE</>
            )}
          </button>

          {session?.strings?.length > 0 && (() => {
            const est = estimateCost(session.strings, aiSettings.provider, aiSettings.model || providers?.[aiSettings.provider]?.default, providers);
            if (!est) return null;
            const fmt = (v) => v < 0.001 ? "<$0.001" : v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(3)}`;
            return (
              <div className="mt-3 border border-neutral-800 rounded-sm p-3 bg-neutral-950/70" data-testid="cost-estimate">
                <div className="flex items-center justify-between font-mono text-[10px] uppercase text-neutral-500 tracking-widest mb-2">
                  <span>Estimated cost</span>
                  <span className="text-[#9BBC0F]">{fmt(est.total)}</span>
                </div>
                <div className="font-mono text-[10px] text-neutral-500 flex justify-between">
                  <span>{est.count} strings · ~{Math.round((est.inTokens + est.outTokens) / 1000)}k tokens</span>
                  <span>in {fmt(est.input)} + out {fmt(est.output)}</span>
                </div>
                <p className="font-mono text-[9px] text-neutral-600 mt-1.5">
                  * Rough estimate based on provider list pricing. Emergent Universal Key deducts from your credit balance.
                </p>
              </div>
            );
          })()}

          {mode === "patch" && (
            <button
              onClick={downloadPatched}
              disabled={status !== "done"}
              className="mt-3 w-full h-11 bg-transparent border border-[#8BAC0F] text-[#9BBC0F] font-display font-bold text-sm tracking-wide rounded-sm disabled:opacity-30 disabled:cursor-not-allowed hover:bg-[#8BAC0F]/10 transition-colors flex items-center justify-center gap-2"
              data-testid="download-btn"
            >
              <Download className="w-4 h-4" /> DOWNLOAD PATCHED ROM
            </button>
          )}

          {mode === "export" && (
            <>
              <button
                onClick={exportTxt}
                disabled={!session}
                className="mt-3 w-full h-11 bg-transparent border border-[#8BAC0F] text-[#9BBC0F] font-display font-bold text-sm tracking-wide rounded-sm disabled:opacity-30 disabled:cursor-not-allowed hover:bg-[#8BAC0F]/10 transition-colors flex items-center justify-center gap-2"
                data-testid="export-txt-btn"
              >
                <FileText className="w-4 h-4" /> EXPORT AS TEXT FILE
              </button>
              <input
                ref={importInput}
                type="file"
                accept=".txt,text/plain"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) importAndPatch(f);
                  e.target.value = "";
                }}
                data-testid="import-txt-input"
              />
              <button
                onClick={() => importInput.current?.click()}
                disabled={!session}
                className="mt-2 w-full h-11 bg-transparent border border-neutral-700 hover:border-[#8BAC0F] text-neutral-300 hover:text-[#9BBC0F] font-display font-bold text-sm tracking-wide rounded-sm disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
                data-testid="insert-translation-btn"
              >
                <FileUp className="w-4 h-4" /> INSERT TRANSLATION
              </button>
              <p className="font-mono text-[10px] text-neutral-600 mt-2 leading-relaxed">
                Export → uprav .txt v jakémkoli editoru → Insert Translation nahraje soubor a přepíše ROMku.
              </p>
            </>
          )}
        </section>

        {/* History */}
        <section className="lg:col-span-3 bg-neutral-900 border border-neutral-800 rounded-sm p-6" data-testid="history-card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-mono text-xs uppercase text-neutral-400 tracking-widest">03 · Recent</h2>
            <History className="w-4 h-4 text-neutral-600" />
          </div>
          {history.length === 0 ? (
            <p className="font-mono text-xs text-neutral-600">No sessions yet.</p>
          ) : (
            <ul className="space-y-2" data-testid="history-list">
              {history.slice(0, 6).map((h) => (
                <li key={h.session_id} className="border border-neutral-800 rounded-sm p-2.5 hover:border-neutral-700 transition-colors">
                  <p className="font-mono text-[11px] text-neutral-200 truncate">{h.filename}</p>
                  <p className="font-mono text-[10px] text-neutral-500 mt-0.5 flex items-center gap-2">
                    <span className="text-[#8BAC0F]">{h.rom_type}</span>
                    <span>·</span>
                    <span>{h.string_count} str</span>
                    {h.target_language && (
                      <>
                        <span>·</span>
                        <span className="text-[#9BBC0F]">{h.target_language.toUpperCase()}</span>
                      </>
                    )}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Terminal */}
        <section className="lg:col-span-8 bg-black border border-neutral-800 rounded-sm overflow-hidden scanlines" data-testid="terminal-card">
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
        <section className="lg:col-span-4 bg-neutral-900 border border-neutral-800 rounded-sm p-6" data-testid="stats-card">
          <h2 className="font-mono text-xs uppercase text-neutral-400 tracking-widest mb-4">04 · Session Stats</h2>
          <dl className="space-y-3 font-mono text-xs">
            <StatRow label="ROM Type" value={session?.rom_type || "—"} />
            <StatRow label="Size" value={session ? `${(session.rom_size / 1024).toFixed(1)} KB` : "—"} />
            <StatRow label="Encoding" value={session?.encoding || encoding} highlight={session?.encoding === "pokemon_gen3"} />
            <StatRow label="Found in ROM" value={session?.found_total ?? "—"} />
            <StatRow label="Loaded" value={session?.strings?.length ?? "—"} highlight />
            <StatRow label="Target" value={targetLang.toUpperCase()} />
            <StatRow label="Mode" value={mode === "export" ? "EXPORT TXT" : "PATCH"} />
            <StatRow label="AI" value={<span className="inline-flex items-center gap-1"><Sparkles className="w-3 h-3" />{(aiSettings.provider || "emergent").toUpperCase()}</span>} />
            <StatRow
              label="Translated"
              value={translations.filter((t) => t.translated).length + " / " + translations.length}
              highlight={status === "done"}
            />
          </dl>
        </section>

        {/* Translation table */}
        <section className="lg:col-span-12 bg-neutral-900 border border-neutral-800 rounded-sm" data-testid="viewer-card">
          <div className="flex items-center justify-between px-6 py-4 border-b border-neutral-800">
            <h2 className="font-display text-lg font-bold tracking-tight">Translation Viewer</h2>
            <span className="font-mono text-[11px] text-neutral-500">
              {session?.strings?.length || 0} extracted strings
            </span>
          </div>
          <TranslationTable
            strings={session?.strings || []}
            translations={translations}
          />
        </section>
      </main>

      <footer className="border-t border-neutral-800 mt-8 py-6 px-6">
        <div className="max-w-[1400px] mx-auto flex flex-col sm:flex-row items-center justify-between gap-2 font-mono text-[10px] text-neutral-600 uppercase tracking-widest">
          <span>rom.translate · v0.2 · dmg-01 mode</span>
          <span>bring your own key · gemini · openai · claude</span>
        </div>
      </footer>

      <AiSettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        providers={providers}
        settings={aiSettings}
        onSave={setAiSettings}
      />
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
