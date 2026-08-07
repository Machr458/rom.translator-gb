import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { KeyRound, Sparkles, ShieldCheck, PlugZap, Loader2, CheckCircle2, XCircle } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const STORAGE_KEY = "romtrans.ai_settings";

export function loadSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { provider: "emergent", model: "", apiKey: "" };
    return JSON.parse(raw);
  } catch {
    return { provider: "emergent", model: "", apiKey: "" };
  }
}

export function saveSettings(s) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
}

export default function AiSettingsDialog({ open, onOpenChange, providers, settings, onSave }) {
  const [provider, setProvider] = useState(settings.provider || "emergent");
  const [model, setModel] = useState(settings.model || "");
  const [apiKey, setApiKey] = useState(settings.apiKey || "");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  useEffect(() => {
    if (open) {
      setProvider(settings.provider || "emergent");
      setModel(settings.model || "");
      setApiKey(settings.apiKey || "");
      setTestResult(null);
    }
  }, [open, settings]);

  const pInfo = providers?.[provider];
  const modelList = pInfo?.models || [];

  useEffect(() => {
    // If model isn't valid for current provider, reset to default
    if (pInfo && !modelList.find((m) => m.id === model)) {
      setModel(pInfo.default);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider]);

  const handleSave = () => {
    const finalModel = model || pInfo?.default || "";
    // For emergent we now allow an optional user key. For non-emergent providers, key is required.
    const next = { provider, model: finalModel, apiKey: apiKey.trim() };
    saveSettings(next);
    onSave(next);
    onOpenChange(false);
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await axios.post(`${API}/ai/test`, {
        provider,
        model: model || pInfo?.default,
        api_key: apiKey.trim(),
      }, { timeout: 45000 });
      setTestResult(r.data);
      if (r.data.ok) {
        toast.success(`Klíč funguje! Odpověď: "${r.data.reply}"`);
      } else {
        toast.error(r.data.friendly || r.data.error || "Test selhal");
      }
    } catch (e) {
      const msg = e.response?.data?.detail || e.message;
      setTestResult({ ok: false, error: msg, friendly: msg });
      toast.error("Test selhal: " + msg);
    } finally {
      setTesting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-neutral-900 border-neutral-800 rounded-sm max-w-lg" data-testid="ai-settings-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl flex items-center gap-2 tracking-tight">
            <KeyRound className="w-5 h-5 text-[#8BAC0F]" />
            AI Provider Settings
          </DialogTitle>
          <DialogDescription className="font-mono text-xs text-neutral-500">
            Vyber si AI a zadej svůj vlastní API klíč — klíč se ukládá pouze lokálně v prohlížeči, neposílá se nikam kromě konkrétního AI providera při překladu.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div>
            <label className="font-mono text-[10px] uppercase text-neutral-500 tracking-wider mb-2 block">
              Provider
            </label>
            <Select value={provider} onValueChange={setProvider}>
              <SelectTrigger className="h-11 bg-neutral-950 border-neutral-700 rounded-sm font-mono text-sm" data-testid="provider-select">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-neutral-900 border-neutral-800 rounded-sm">
                {Object.entries(providers || {}).map(([id, p]) => (
                  <SelectItem key={id} value={id} className="font-mono text-sm" data-testid={`provider-option-${id}`}>
                    <span className="text-[#8BAC0F] mr-2">{id.toUpperCase()}</span>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <label className="font-mono text-[10px] uppercase text-neutral-500 tracking-wider mb-2 block">
              Model
            </label>
            <Select value={model || pInfo?.default} onValueChange={setModel}>
              <SelectTrigger className="h-11 bg-neutral-950 border-neutral-700 rounded-sm font-mono text-sm" data-testid="model-select">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-neutral-900 border-neutral-800 rounded-sm">
                {modelList.map((m) => (
                  <SelectItem key={m.id} value={m.id} className="font-mono text-sm" data-testid={`model-option-${m.id}`}>
                    {m.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <label className="font-mono text-[10px] uppercase text-neutral-500 tracking-wider mb-2 block flex items-center gap-2">
              API Key
              {provider === "emergent" && (
                <span className="inline-flex items-center gap-1 text-neutral-400 normal-case tracking-normal">
                  <Sparkles className="w-3 h-3" /> optional (leave empty = server default)
                </span>
              )}
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={pInfo?.keyHint || "Enter API key"}
              className="w-full h-11 bg-neutral-950 border border-neutral-700 rounded-sm px-3 font-mono text-sm placeholder:text-neutral-600 focus:outline-none focus:border-[#8BAC0F]"
              data-testid="api-key-input"
            />
            <p className="font-mono text-[10px] text-neutral-600 mt-1.5 flex items-center gap-1">
              <ShieldCheck className="w-3 h-3" />
              Uloženo pouze v tvém prohlížeči (localStorage).
            </p>
          </div>
        </div>

        <DialogFooter className="gap-2 flex-col sm:flex-row items-stretch">
          <button
            onClick={handleTest}
            disabled={testing}
            className="h-10 px-4 border border-neutral-700 hover:border-[#8BAC0F] rounded-sm font-mono text-xs uppercase tracking-wider text-neutral-300 hover:text-[#9BBC0F] flex items-center justify-center gap-2 disabled:opacity-40"
            data-testid="settings-test"
          >
            {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : <PlugZap className="w-4 h-4" />}
            {testing ? "Testing..." : "Test Key"}
          </button>
          <div className="flex-1" />
          <button
            onClick={() => onOpenChange(false)}
            className="h-10 px-4 border border-neutral-700 rounded-sm font-mono text-xs uppercase tracking-wider text-neutral-400 hover:border-neutral-600"
            data-testid="settings-cancel"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="h-10 px-5 bg-[#8BAC0F] text-black font-display font-bold text-xs uppercase tracking-wider rounded-sm btn-brutal"
            data-testid="settings-save"
          >
            Save
          </button>
        </DialogFooter>

        {testResult && (
          <div
            className={`mt-3 border rounded-sm p-3 font-mono text-[11px] ${testResult.ok ? "border-[#8BAC0F] bg-[#8BAC0F]/5" : "border-[#C7305C] bg-[#C7305C]/5"}`}
            data-testid="test-result"
          >
            <div className="flex items-center gap-2 mb-1.5">
              {testResult.ok ? (
                <><CheckCircle2 className="w-4 h-4 text-[#8BAC0F]" /><span className="text-[#9BBC0F] font-bold">OK</span></>
              ) : (
                <><XCircle className="w-4 h-4 text-[#C7305C]" /><span className="text-[#C7305C] font-bold">FAILED</span></>
              )}
              {testResult.key_masked && (
                <span className="text-neutral-500">key: {testResult.key_masked} ({testResult.key_source})</span>
              )}
            </div>
            {testResult.ok ? (
              <p className="text-neutral-400">Reply: <span className="text-[#9BBC0F]">"{testResult.reply}"</span></p>
            ) : (
              <p className="text-neutral-300">{testResult.friendly || testResult.error}</p>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
