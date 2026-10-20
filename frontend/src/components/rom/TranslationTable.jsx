import { useMemo, useState, useEffect } from "react";
import { EditableCell } from "@/components/rom/EditableCell";

const PAGE_SIZE = 200;

export default function TranslationTable({ strings, translations, onEdit, encoding }) {
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [query, setQuery] = useState("");

  // Reset visible when the extracted set changes
  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
    setQuery("");
  }, [strings]);

  const map = useMemo(() => {
    const m = new Map();
    translations.forEach((t) => m.set(t.id, t.translated));
    return m;
  }, [translations]);

  const filtered = useMemo(() => {
    if (!query.trim()) return strings;
    const q = query.toLowerCase();
    return strings.filter((s) => {
      const tr = map.get(s.id) || "";
      return s.text.toLowerCase().includes(q) || tr.toLowerCase().includes(q);
    });
  }, [strings, map, query]);

  const rowsToRender = filtered.slice(0, visibleCount);
  const remaining = Math.max(0, filtered.length - visibleCount);

  if (!strings.length) {
    return (
      <div className="p-8 text-center font-mono text-xs text-neutral-500" data-testid="empty-viewer">
        Load a ROM and select SCAN & EXTRACT to see its strings here.
      </div>
    );
  }

  return (
    <div data-testid="translation-table">
      {/* Toolbar: search + counters */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 px-4 py-2 border-b border-neutral-800 bg-neutral-950/50">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter strings..."
          className="flex-1 h-8 bg-neutral-900 border border-neutral-800 rounded-sm px-3 font-mono text-xs placeholder:text-neutral-600 focus:outline-none focus:border-[#8BAC0F]"
          data-testid="table-search"
        />
        <div className="font-mono text-[10px] text-neutral-500 flex items-center gap-3">
          <span data-testid="table-count-rendered">
            <span className="text-[#9BBC0F]">{rowsToRender.length}</span> / {filtered.length}
            {query && filtered.length < strings.length && ` (of ${strings.length})`}
          </span>
        </div>
      </div>

      <div className="overflow-x-auto max-h-[520px] overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-neutral-900 border-b border-neutral-800">
            <tr>
              <th className="text-left px-4 py-2.5 font-mono text-[10px] uppercase text-neutral-500 tracking-widest w-16">Addr</th>
              <th className="text-left px-4 py-2.5 font-mono text-[10px] uppercase text-neutral-500 tracking-widest w-[45%]">Original</th>
              <th className="text-left px-4 py-2.5 font-mono text-[10px] uppercase text-neutral-500 tracking-widest border-l border-neutral-800">Translated</th>
            </tr>
          </thead>
          <tbody>
            {rowsToRender.map((s, i) => {
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
                    <EditableCell
                      value={tr}
                      maxLen={s.length}
                      index={i}
                      encoding={encoding}
                      onSave={(text) => onEdit?.(s, text)}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {remaining > 0 && (
        <div className="px-4 py-3 border-t border-neutral-800 flex items-center justify-between font-mono text-xs">
          <span className="text-neutral-500">
            {remaining.toLocaleString()} more strings hidden. Showing first {rowsToRender.length.toLocaleString()} for performance.
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setVisibleCount((v) => v + PAGE_SIZE)}
              className="h-8 px-3 border border-neutral-700 hover:border-[#8BAC0F] rounded-sm text-neutral-300 hover:text-[#9BBC0F] transition-colors text-[11px] uppercase tracking-wider"
              data-testid="load-more-btn"
            >
              +{PAGE_SIZE} more
            </button>
            {filtered.length <= 5000 && (
              <button
                onClick={() => setVisibleCount(filtered.length)}
                className="h-8 px-3 border border-neutral-700 hover:border-[#8BAC0F] rounded-sm text-neutral-300 hover:text-[#9BBC0F] transition-colors text-[11px] uppercase tracking-wider"
                data-testid="load-all-btn"
              >
                Show all
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
