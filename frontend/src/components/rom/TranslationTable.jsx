import { useMemo } from "react";

export default function TranslationTable({ strings, translations }) {
  const map = useMemo(() => {
    const m = new Map();
    translations.forEach((t) => m.set(t.id, t.translated));
    return m;
  }, [translations]);

  if (!strings.length) {
    return (
      <div className="p-8 text-center font-mono text-xs text-neutral-500" data-testid="empty-viewer">
        // Load a ROM and press SCAN & EXTRACT to see strings here
      </div>
    );
  }

  return (
    <div className="overflow-x-auto max-h-[520px] overflow-y-auto" data-testid="translation-table">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-neutral-900 border-b border-neutral-800">
          <tr>
            <th className="text-left px-4 py-2.5 font-mono text-[10px] uppercase text-neutral-500 tracking-widest w-16">Addr</th>
            <th className="text-left px-4 py-2.5 font-mono text-[10px] uppercase text-neutral-500 tracking-widest">Original</th>
            <th className="text-left px-4 py-2.5 font-mono text-[10px] uppercase text-neutral-500 tracking-widest border-l border-neutral-800">Translated</th>
          </tr>
        </thead>
        <tbody>
          {strings.map((s, i) => {
            const tr = map.get(s.id);
            return (
              <tr
                key={s.id}
                className={`border-b border-neutral-800 hover:bg-neutral-900/50 ${tr ? "flash-green" : ""}`}
                data-testid={`row-${i}`}
              >
                <td className="px-4 py-2 font-mono text-[10px] text-neutral-600 align-top">
                  0x{s.offset.toString(16).padStart(6, "0")}
                </td>
                <td className="px-4 py-2 font-mono text-xs text-neutral-400 align-top break-all">
                  {s.text}
                </td>
                <td className="px-4 py-2 font-mono text-xs text-neutral-50 align-top break-all border-l border-neutral-800">
                  {tr ? (
                    <span className="text-[#9BBC0F]">{tr}</span>
                  ) : (
                    <span className="text-neutral-700">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
