import { Navigate, useParams } from "react-router-dom";

/**
 * Direct-link compatibility: previously `/article/:id` rendered a full
 * page. Now article view is a slide-in drawer driven by `?article=<id>`,
 * so we just rewrite the URL to `/stream?article=<id>` so the user lands
 * on the article list with the drawer open.
 *
 * Kept as its own component (not inlined into the Routes table) so
 * bookmarks and external shares to the old /article/<n> URLs keep working.
 */
export function ArticlePage() {
  const { id } = useParams<{ id: string }>();
  if (!id || !/^\d+$/.test(id)) return <Navigate to="/stream" replace />;
  return <Navigate to={`/stream?article=${id}`} replace />;
}
