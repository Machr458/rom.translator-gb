import { useState } from "react";
import { Pencil, Check, X } from "lucide-react";

const G3_TWO_BYTE = new Set(["PLAYER", "STR1", "STR2", "STR3", "KUN", "RIVAL", "VERSION", "AQUA", "MAGMA", "ARCHIE", "MAXIE", "KYOGRE", "GROUDON"]);

const byteLength = (text, encoding) =>
  text.replace(/\{([^{}]{1,16})\}/g, (_, t) => {
    const n = t.includes(":") ? t.split(":").length : encoding === "pokemon_gen3" && G3_TWO_BYTE.has(t) ? 2 : 1;
    return "#".repeat(n);
  }).length;

export const EditableCell = ({ value, maxLen, onSave, index, encoding, language = "en" }) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const cs = language === "cs";

  const start = () => { setDraft(value || ""); setEditing(true); };
  const save = () => { onSave(draft); setEditing(false); };

  if (!editing) {
    return (
      <div className="flex items-start gap-2 group">
        <span className="flex-1" data-testid={`translated-text-${index}`}>
          {value ? <span className="text-[#9BBC0F]">{value}</span> : <span className="text-neutral-700">—</span>}
        </span>
        <button
          onClick={start}
          className="shrink-0 p-1 rounded-sm text-neutral-600 hover:text-[#9BBC0F] hover:bg-neutral-800 transition-colors"
          title={cs ? "Upravit překlad" : "Edit translation"}
          data-testid={`edit-btn-${index}`}
        >
          <Pencil className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  }

  const used = byteLength(draft, encoding);
  const over = maxLen && used > maxLen;
  return (
    <div className="flex flex-col gap-1">
      <textarea
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); save(); }
          if (e.key === "Escape") setEditing(false);
        }}
        rows={2}
        className="w-full bg-neutral-900 border border-[#8BAC0F] rounded-sm px-2 py-1 font-mono text-xs text-neutral-50 focus:outline-none resize-y"
        data-testid={`edit-input-${index}`}
      />
      <div className="flex items-center justify-between gap-2">
        <span className={`font-mono text-[10px] ${over ? "text-amber-400" : "text-neutral-500"}`} data-testid={`edit-len-${index}`}>
          {used} / {maxLen} B{over ? (cs ? " · zkrácení v ROM jen při selhání přesunu" : " · ROM truncates only if relocation fails") : ""}
        </span>
        <div className="flex gap-1">
          <button onClick={save} className="p-1 rounded-sm text-[#9BBC0F] hover:bg-neutral-800" title={cs ? "Uložit (Enter)" : "Save (Enter)"} data-testid={`edit-save-${index}`}>
            <Check className="w-3.5 h-3.5" />
          </button>
          <button onClick={() => setEditing(false)} className="p-1 rounded-sm text-neutral-400 hover:bg-neutral-800" title={cs ? "Zrušit (Esc)" : "Cancel (Esc)"} data-testid={`edit-cancel-${index}`}>
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
};
