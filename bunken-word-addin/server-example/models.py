from typing import Literal

from pydantic import BaseModel, Field


CitationStyle = Literal["apa", "vancouver", "nature"]


class SessionResponse(BaseModel):
    userId: str
    email: str
    username: str


class PaperSummary(BaseModel):
    id: str
    title: str
    authors: str
    journal: str
    year: int
    doi: str | None = None


class PaperSearchResponse(BaseModel):
    items: list[PaperSummary]


class CitationItemRequest(BaseModel):
    paperId: str
    locator: str | None = None
    prefix: str | None = None
    suffix: str | None = None


class CitationFormatRequest(BaseModel):
    style: CitationStyle
    items: list[CitationItemRequest] = Field(default_factory=list)


class CitationRenderedItem(BaseModel):
    paperId: str
    renderedText: str


class CitationFormatResponse(BaseModel):
    text: str
    items: list[CitationRenderedItem]


class BibliographyFormatRequest(BaseModel):
    style: CitationStyle
    paperIds: list[str] = Field(default_factory=list)


class BibliographyFormatResponse(BaseModel):
    title: str
    entries: list[str]
