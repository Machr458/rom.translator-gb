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

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const ClearCacheButton = () => {
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
      toast.success(`Cache smazána — ${r.data?.deleted ?? 0} záznamů odstraněno.`);
      setOpen(false);
    } catch (e) {
      toast.error("Chyba při mazání cache: " + (e.response?.data?.detail || e.message));
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
        <span className="hidden sm:inline">Smazat cache</span>
      </button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent className="bg-neutral-950 border-neutral-800 text-neutral-100" data-testid="clear-cache-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>Smazat cache překladů?</AlertDialogTitle>
            <AlertDialogDescription className="text-neutral-400" data-testid="clear-cache-count">
              {total === null ? "Načítám..." : `Uloženo záznamů: ${total}. `}
              Další překlad pak znovu zavolá AI (a bude stát kredity).
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-transparent border-neutral-700 text-neutral-300" data-testid="clear-cache-cancel">
              Zrušit
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => { e.preventDefault(); clear(); }}
              disabled={busy}
              className="bg-red-600 hover:bg-red-700 text-white"
              data-testid="clear-cache-confirm"
            >
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Smazat"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
};
