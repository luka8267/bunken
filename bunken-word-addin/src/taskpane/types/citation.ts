export type CitationStyle = "apa" | "vancouver" | "nature";

export type CitationItemRequest = {
  paperId: string;
  locator?: string;
  prefix?: string;
  suffix?: string;
};

export type CitationFormatRequest = {
  style: CitationStyle;
  items: CitationItemRequest[];
};

export type CitationFormatResponse = {
  text: string;
  items: Array<{
    paperId: string;
    renderedText: string;
  }>;
};
