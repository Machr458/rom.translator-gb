import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  CheckCircle2,
  Loader2,
  PlugZap,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const API = `${process.env.REACT_APP_BACKEND_URL || ""}/api`;
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

export function saveSettings(settings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

export default function AiSettingsDialog({ providers, settings, onSave, language = "en" }) {
  const [provider, setProvider] = useState(settings.provider || "emergent");
  const [model, setModel] = useState(settings.model || "");
  const [apiKey, setApiKey] = useState(settings.apiKey || "");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  useEffect(() => {
    setProvider(settings.provider || "emergent");
    setModel(settings.model || "");
    setApiKey(settings.apiKey || "");
  }, [settings]);

  const providerInfo = providers?.[provider];
  const models = providerInfo?.models || [];
  const cs = language === "cs";

  useEffect(() => {
    const availableModels = providerInfo?.models || [];
    const defaultModel = providerInfo?.default;
    if (defaultModel && !availableModels.some((entry) => entry.id === model)) {
      setModel(defaultModel);
    }
  }, [model, providerInfo]);

  const handleSave = () => {
    const next = {
      provider,
      model: models.some((entry) => entry.id === model) ? model : providerInfo?.default || "",
      apiKey: apiKey.trim(),
    };
    saveSettings(next);
    onSave(next);
    toast.success(cs ? "Nastavení AI uloženo." : "AI settings saved.");
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const response = await axios.post(`${API}/ai/test`, {
        provider,
        model: model || providerInfo?.default,
        api_key: apiKey.trim(),
      }, { timeout: 45000 });
      setTestResult(response.data);
      if (response.data.ok) {
        toast.success(cs ? `Připojení funguje: "${response.data.reply}"` : `Connection successful: "${response.data.reply}"`);
      } else {
        toast.error(response.data.friendly || response.data.error || (cs ? "Test připojení selhal." : "Connection test failed."));
      }
    } catch (error) {
      const message = error.response?.data?.detail || error.message;
      setTestResult({ ok: false, error: message, friendly: message });
      toast.error(cs ? `Test API klíče selhal: ${message}` : `API key test failed: ${message}`);
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="space-y-4" data-testid="ai-settings-panel">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="block">
          <span className="font-mono text-[10px] uppercase text-neutral-500 mb-1.5 block">{cs ? "AI služba" : "AI provider"}</span>
          <Select value={provider} onValueChange={setProvider}>
            <SelectTrigger className="h-10 bg-neutral-950 border-neutral-700 rounded-sm font-mono text-xs" data-testid="provider-select">
              <SelectValue placeholder={cs ? "Vyber AI službu" : "Select provider"} />
            </SelectTrigger>
            <SelectContent className="bg-neutral-900 border-neutral-800 rounded-sm">
              {Object.entries(providers || {}).map(([id, info]) => (
                <SelectItem key={id} value={id} className="font-mono text-xs" data-testid={`provider-option-${id}`}>
                  {info.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>

        <label className="block">
          <span className="font-mono text-[10px] uppercase text-neutral-500 mb-1.5 block">Model</span>
          <Select value={model || providerInfo?.default} onValueChange={setModel}>
            <SelectTrigger className="h-10 bg-neutral-950 border-neutral-700 rounded-sm font-mono text-xs" data-testid="model-select">
              <SelectValue placeholder={cs ? "Vyber model" : "Select model"} />
            </SelectTrigger>
            <SelectContent className="bg-neutral-900 border-neutral-800 rounded-sm">
              {models.map((entry) => (
                <SelectItem key={entry.id} value={entry.id} className="font-mono text-xs" data-testid={`model-option-${entry.id}`}>
                  {entry.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
      </div>

      <label className="block">
          <span className="font-mono text-[10px] uppercase text-neutral-500 mb-1.5 block">{cs ? "API klíč" : "API key"}</span>
        <input
          type="password"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          placeholder={providerInfo?.keyHint || (cs ? "Vlož API klíč" : "Enter API key")}
          className="w-full h-10 bg-neutral-950 border border-neutral-700 rounded-sm px-3 font-mono text-xs placeholder:text-neutral-600 focus:outline-none focus:border-[#8BAC0F]"
          data-testid="api-key-input"
        />
        <span className="font-mono text-[10px] text-neutral-600 mt-1.5 flex items-center gap-1">
          <ShieldCheck className="w-3 h-3" /> {cs ? "Ukládá se pouze v tomto prohlížeči." : "Stored only in this browser."}
        </span>
      </label>

      <div className="flex flex-wrap gap-2">
        <button
          onClick={handleTest}
          disabled={testing || !provider}
          className="h-9 px-3 border border-neutral-700 hover:border-[#8BAC0F] rounded-sm font-mono text-[10px] uppercase tracking-wider text-neutral-300 hover:text-[#9BBC0F] flex items-center justify-center gap-2 disabled:opacity-40"
          data-testid="settings-test"
        >
          {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <PlugZap className="w-3.5 h-3.5" />}
          {testing ? (cs ? "Testuji…" : "Testing…") : (cs ? "Otestovat API klíč" : "Test API key")}
        </button>
        <button
          onClick={handleSave}
          className="h-9 px-4 bg-[#8BAC0F] text-black font-display font-bold text-[10px] uppercase tracking-wider rounded-sm btn-brutal"
          data-testid="settings-save"
        >
          {cs ? "Uložit AI nastavení" : "Save AI settings"}
        </button>
      </div>

      {testResult && (
        <div className={`border rounded-sm p-3 font-mono text-[11px] ${testResult.ok ? "border-[#8BAC0F] bg-[#8BAC0F]/5" : "border-[#C7305C] bg-[#C7305C]/5"}`} data-testid="test-result">
          <div className="flex items-center gap-2 mb-1.5">
            {testResult.ok ? (
              <><CheckCircle2 className="w-4 h-4 text-[#8BAC0F]" /><span className="text-[#9BBC0F] font-bold">{cs ? "Připojeno" : "Connected"}</span></>
            ) : (
              <><XCircle className="w-4 h-4 text-[#C7305C]" /><span className="text-[#C7305C] font-bold">{cs ? "Chyba" : "Failed"}</span></>
            )}
          </div>
          <p className="text-neutral-300">{testResult.ok ? `${cs ? "Odpověď" : "Reply"}: ${testResult.reply}` : testResult.friendly || testResult.error}</p>
        </div>
      )}
    </div>
  );
}
