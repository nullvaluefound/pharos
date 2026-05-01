import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * The drawer is driven entirely by the `?article=<id>` query string. This
 * keeps URLs shareable, lets the browser back button close the drawer, and
 * leaves the page underneath the drawer untouched (its own search params
 * for filters/views are preserved).
 */
export function useArticleParam() {
  const [params, setParams] = useSearchParams();
  const raw = params.get("article");
  const id = useMemo(() => {
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }, [raw]);

  const open = useCallback(
    (next: number) => {
      const sp = new URLSearchParams(params);
      sp.set("article", String(next));
      setParams(sp, { replace: false });
    },
    [params, setParams],
  );

  const replace = useCallback(
    (next: number) => {
      const sp = new URLSearchParams(params);
      sp.set("article", String(next));
      // replace history entry so prev/next inside the drawer doesn't
      // create a pile of back-button steps.
      setParams(sp, { replace: true });
    },
    [params, setParams],
  );

  const close = useCallback(() => {
    const sp = new URLSearchParams(params);
    sp.delete("article");
    setParams(sp, { replace: false });
  }, [params, setParams]);

  return { id, open, replace, close };
}
