import { create } from "zustand";

/**
 * Tracks the ordered list of article IDs currently visible on the page so
 * the article drawer can paginate prev/next without forcing the user back
 * to the list. Each list-rendering page (Stream, Saved, Search, etc.)
 * pushes its current list into here whenever its data changes.
 *
 * The queryKey is captured so the drawer can invalidate the right cache
 * when the user toggles `is_read` / `is_saved` from the drawer.
 */
type ArticleNavState = {
  ids: number[];
  queryKey: unknown[] | null;
  setList: (ids: number[], queryKey?: unknown[]) => void;
  clear: () => void;
  indexOf: (id: number | null) => number;
  prevId: (id: number | null) => number | null;
  nextId: (id: number | null) => number | null;
};

export const useArticleNav = create<ArticleNavState>((set, get) => ({
  ids: [],
  queryKey: null,
  setList: (ids, queryKey) =>
    set({
      ids: Array.from(new Set(ids.filter((n) => Number.isFinite(n)))),
      queryKey: queryKey ?? null,
    }),
  clear: () => set({ ids: [], queryKey: null }),
  indexOf: (id) => {
    if (id == null) return -1;
    return get().ids.indexOf(id);
  },
  prevId: (id) => {
    if (id == null) return null;
    const i = get().ids.indexOf(id);
    if (i <= 0) return null;
    return get().ids[i - 1];
  },
  nextId: (id) => {
    if (id == null) return null;
    const i = get().ids.indexOf(id);
    if (i < 0 || i >= get().ids.length - 1) return null;
    return get().ids[i + 1];
  },
}));
