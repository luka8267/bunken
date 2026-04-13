import type { CitationFormatRequest, CitationFormatResponse } from "../types/citation";
import type { BibliographyFormatResponse } from "../types/documentState";
import type { PaperSummary } from "../types/paper";

const API_BASE_URL =
  (globalThis as typeof globalThis & { BUNKEN_API_BASE_URL?: string }).BUNKEN_API_BASE_URL ??
  "http://127.0.0.1:8765";

export async function searchPapers(query: string): Promise<PaperSummary[]> {
  const url = new URL("/api/addin/papers", API_BASE_URL);
  url.searchParams.set("q", query);
  const response = await fetchJson<{ items: PaperSummary[] }>(url.toString(), {
    method: "GET",
  });
  return response.items;
}

export async function formatCitation(
  payload: CitationFormatRequest,
): Promise<CitationFormatResponse> {
  return fetchJson<CitationFormatResponse>(`${API_BASE_URL}/api/addin/citations/format`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function formatBibliography(
  paperIds: string[],
  style: CitationFormatRequest["style"],
): Promise<BibliographyFormatResponse> {
  return fetchJson<BibliographyFormatResponse>(
    `${API_BASE_URL}/api/addin/bibliography/format`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        paperIds,
        style,
      }),
    },
  );
}

async function fetchJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    credentials: "include",
    ...init,
  });

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}
