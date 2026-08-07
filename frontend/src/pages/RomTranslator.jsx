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

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const MODES = [
  { id: "view", label: "View Translations", icon: Languages },
  { id: "patch", label: "Generate Patched ROM", icon: Download },
];

export default function RomTranslator() {
  const [languages, setLanguages] = useState([]);
  const [targetLang, setTargetLang] = useState("cs");
  const [mode, setMode] = useState("view");
  const [file, setFile] = useState(null);
  const [session, setSession] = useState(null); // {session_id, filename, rom_size, rom_type, strings}
  const [translations, setTranslations] = useState([]); // [{id, original, translated}]
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState("idle"); // idle|extracting|ready|translating|done|error
  const [progress, setProgress] = useState(0);
  const [history, setHistory] = useState([]);
  const [dragActive, setDragActive] = useState(false);
  const fileInput = useRef(null);

  const pushLog = useCallback((line, kind = "info") => {
    setLogs((l) => [...l, { line, kind, ts: Date.now() }]);
  }, []);

  useEffect(() => {
    axios.get(`${API}/languages`).then((r) => setLanguages(r.data)).catch(() => { /* ignore */ });
    loadHistory();
    pushLog("SYSTEM READY. Insert cartridge to begin.", "sys");
  }, [pushLog]);

  const loadHistory = async () => {
    try {
      const r = await axios.get(`${API}/history`);
      setHistory(r.data);
    } catch (_) {}
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
      const r = await axios.post(`${API}/rom/extract`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
        onUploadProgress: (e) => {
          if (e.total) setProgress(Math.round((e.loaded / e.total) * 60));
        },
      });
      setSession(r.data);
      setProgress(100);
      setStatus("ready");
      pushLog(`  TYPE  : ${r.data.rom_type}`, "info");
      pushLog(`  SIZE  : ${(r.data.rom_size / 1024).toFixed(1)} KB`, "info");
      pushLog(`  FOUND : ${r.data.strings.length} strings`, "ok");
      pushLog(`> READY. Choose target language and press TRANSLATE.`, "cmd");
      loadHistory();
    } catch (e) {
      setStatus("error");
      pushLog(`! ERROR: ${e.response?.data?.detail || e.message}`, "err");
      toast.error(e.response?.data?.detail || "Extraction failed");
    }
  };

  const translate = async () => {
    if (!session) return;
    setStatus("translating");
    setProgress(5);
    setTranslations(session.strings.map((s) => ({ id: s.id, original: s.text, translated: "" })));
    pushLog(`> TRANSLATE :: target=${targetLang.toUpperCase()} model=gemini-3-flash`, "cmd");
    pushLog(`  Sending ${session.strings.length} strings to AI...`, "info");

    // Simulated progress while waiting
    const tick = setInterval(() => setProgress((p) => Math.min(90, p + 3)), 800);

    try {
      const r = await axios.post(`${API}/rom/translate`, {
        session_id: session.session_id,
        target_language: targetLang,
        strings: session.strings,
      });
      clearInterval(tick);
      setTranslations(r.data.translations);
      setProgress(100);
      setStatus("done");
      pushLog(`  DONE. ${r.data.translations.length} strings translated.`, "ok");
      toast.success("Překlad dokončen!");
    } catch (e) {
      clearInterval(tick);
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
          <div className="hidden sm:flex items-center gap-2 text-xs font-mono text-neutral-500">
            <div className="w-2 h-2 bg-[#8BAC0F] rounded-full animate-pulse" />
            <span>ONLINE · gemini-3-flash</span>
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
                  <span className="sm:hidden">{m.id === "view" ? "View" : "Patch"}</span>
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

        {/* Config summary compact card */}
        <section className="lg:col-span-4 bg-neutral-900 border border-neutral-800 rounded-sm p-6" data-testid="stats-card">
          <h2 className="font-mono text-xs uppercase text-neutral-400 tracking-widest mb-4">04 · Session Stats</h2>
          <dl className="space-y-3 font-mono text-xs">
            <StatRow label="ROM Type" value={session?.rom_type || "—"} />
            <StatRow label="Size" value={session ? `${(session.rom_size / 1024).toFixed(1)} KB` : "—"} />
            <StatRow label="Strings" value={session?.strings?.length ?? "—"} highlight />
            <StatRow label="Target" value={targetLang.toUpperCase()} />
            <StatRow label="Mode" value={mode === "view" ? "VIEW" : "PATCH"} />
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
          <span>rom.translate · v0.1 · dmg-01 mode</span>
          <span>powered by gemini 3 flash · your api key</span>
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
