import { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Trash2, Loader2 } from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

const API = `${process.env.REACT_APP_BACKEND_URL || ""}/api`;

export const ClearCacheButton = ({ language = "en" }) => {
  const cs = language === "cs";
  const [open, setOpen] = useState(false);
  const [total, setTotal] = useState(null);
  const [busy, setBusy] = useState(false);

  const openDialog = async () => {
    setOpen(true);
    setTotal(null);
    try {
      const r = await axios.get(`${API}/cache/stats`);
      setTotal(r.data.total ?? 0);
    } catch {
      setTotal(0);
    }
  };

  const clear = async () => {
    setBusy(true);
    try {
      const r = await axios.post(`${API}/cache/clear`);
      toast.success(cs ? `Cache vymazána. Odebráno záznamů: ${r.data?.deleted ?? 0}.` : `Cache cleared. ${r.data?.deleted ?? 0} entries removed.`);
      setOpen(false);
    } catch (e) {
      toast.error((cs ? "Cache se nepodařilo vymazat: " : "Could not clear cache: ") + (e.response?.data?.detail || e.message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        onClick={openDialog}
        className="h-9 px-3 border border-neutral-700 hover:border-red-500 rounded-sm font-mono text-[11px] uppercase tracking-wider text-neutral-300 hover:text-red-400 transition-colors flex items-center gap-2"
        data-testid="header-clear-cache-btn"
      >
        <Trash2 className="w-3.5 h-3.5" />
        <span>{cs ? "Vymazat cache" : "Clear cache"}</span>
      </button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent className="bg-neutral-950 border-neutral-800 text-neutral-100" data-testid="clear-cache-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>{cs ? "Vymazat překladovou cache?" : "Clear translation cache?"}</AlertDialogTitle>
            <AlertDialogDescription className="text-neutral-400" data-testid="clear-cache-count">
              {total === null ? (cs ? "Načítám…" : "Loading…") : cs ? `Je uloženo záznamů: ${total}. ` : `${total} entries are stored. `}
              {cs ? "Další překlady budou znovu volat AI." : "Future translations will call AI again."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-transparent border-neutral-700 text-neutral-300" data-testid="clear-cache-cancel">
              {cs ? "Zrušit" : "Cancel"}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => { e.preventDefault(); clear(); }}
              disabled={busy}
              className="bg-[#C7305C] hover:bg-[#a92549] text-white"
              data-testid="clear-cache-confirm"
            >
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : (cs ? "Vymazat cache" : "Clear cache")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
};
