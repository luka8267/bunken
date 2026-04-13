import type { PaperSummary } from "../types/paper";

export function buildFallbackCitationText(paper: PaperSummary, locator?: string) {
  const authorLabel = paper.authors?.split(",")[0]?.trim() || paper.title;
  const yearLabel = paper.year ? String(paper.year) : "n.d.";
  const locatorLabel = locator ? `, ${locator}` : "";
  return `(${authorLabel}, ${yearLabel}${locatorLabel})`;
}
