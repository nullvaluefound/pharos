import { formatDistanceToNowStrict, parseISO } from "date-fns";

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return formatDistanceToNowStrict(parseISO(iso), { addSuffix: true });
  } catch {
    return iso;
  }
}

export function severityClass(s: string | null | undefined): string {
  switch ((s || "").toLowerCase()) {
    case "critical":
      return "chip-red";
    case "high":
      return "chip-amber";
    case "medium":
      return "chip-blue";
    case "low":
      return "chip-green";
    default:
      return "chip";
  }
}

export function hostFromUrl(u: string): string {
  try {
    return new URL(u).hostname.replace(/^www\./, "");
  } catch {
    return u;
  }
}
