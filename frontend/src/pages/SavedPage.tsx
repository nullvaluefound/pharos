import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bookmark } from "lucide-react";

import { ArticleCard } from "../components/ArticleCard";
import { Empty } from "../components/Empty";
import { PageHeader } from "../components/PageHeader";
import { api } from "../lib/api";
import { useArticleNav } from "../lib/articleNav";
import type { StreamPage } from "../lib/types";

export function SavedPage() {
  const { data, isLoading } = useQuery<StreamPage>({
    queryKey: ["saved"],
    queryFn: () => api<StreamPage>("/stream?view=flat&only_saved=1&limit=100"),
  });

  const setNavList = useArticleNav((s) => s.setList);
  useEffect(() => {
    const ids = (data?.items || [])
      .map((it: any) => (typeof it?.id === "number" ? it.id : it?.representative?.id))
      .filter((n: any) => typeof n === "number");
    setNavList(ids, ["saved"]);
  }, [data, setNavList]);

  return (
    <div className="mx-auto max-w-3xl px-5 py-6">
      <PageHeader title="Saved" subtitle="Articles you've bookmarked." />
      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="card h-28 animate-pulse bg-ink-100/50" />
          ))}
        </div>
      ) : !data || data.items.length === 0 ? (
        <Empty
          icon={Bookmark}
          title="No saved articles yet"
          hint="Click the bookmark icon on any article to save it for later."
        />
      ) : (
        <div className="space-y-3">
          {data.items.map((it: any) => (
            <ArticleCard key={it.id} item={it} />
          ))}
        </div>
      )}
    </div>
  );
}
