import { useEffect, useState } from "react";
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
import { KeyRound, Sparkles, ShieldCheck } from "lucide-react";

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

  useEffect(() => {
    if (open) {
      setProvider(settings.provider || "emergent");
      setModel(settings.model || "");
      setApiKey(settings.apiKey || "");
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
    const next = { provider, model: finalModel, apiKey: provider === "emergent" ? "" : apiKey.trim() };
    saveSettings(next);
    onSave(next);
    onOpenChange(false);
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
                <span className="inline-flex items-center gap-1 text-[#8BAC0F] normal-case tracking-normal">
                  <Sparkles className="w-3 h-3" /> not required
                </span>
              )}
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={pInfo?.keyHint || "Enter API key"}
              disabled={provider === "emergent"}
              className="w-full h-11 bg-neutral-950 border border-neutral-700 rounded-sm px-3 font-mono text-sm placeholder:text-neutral-600 focus:outline-none focus:border-[#8BAC0F] disabled:opacity-40"
              data-testid="api-key-input"
            />
            <p className="font-mono text-[10px] text-neutral-600 mt-1.5 flex items-center gap-1">
              <ShieldCheck className="w-3 h-3" />
              Uloženo pouze v tvém prohlížeči (localStorage).
            </p>
          </div>
        </div>

        <DialogFooter className="gap-2">
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
      </DialogContent>
    </Dialog>
  );
}
