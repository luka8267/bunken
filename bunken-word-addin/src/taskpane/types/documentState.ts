import type { CitationStyle } from "./citation";

export type CitationRecord = {
  citationId: string;
  controlId?: number;
  paperIds: string[];
  style: CitationStyle;
  locator?: string;
  prefix?: string;
  suffix?: string;
  renderedText: string;
};

export type DocumentState = {
  version: 1;
  bibliographyControlId?: number;
  style: CitationStyle;
  citations: CitationRecord[];
};

export type BibliographyFormatResponse = {
  title: string;
  entries: string[];
};
