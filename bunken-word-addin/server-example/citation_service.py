from models import (
    BibliographyFormatRequest,
    BibliographyFormatResponse,
    CitationFormatRequest,
    CitationFormatResponse,
    CitationRenderedItem,
    PaperSummary,
)


def format_citation(
    request: CitationFormatRequest,
    papers: list[PaperSummary],
) -> CitationFormatResponse:
    rendered_items: list[CitationRenderedItem] = []
    joined_parts: list[str] = []

    for item, paper in zip(request.items, papers):
        text = _render_single_citation(
            paper=paper,
            style=request.style,
            locator=item.locator,
            prefix=item.prefix,
            suffix=item.suffix,
        )
        rendered_items.append(
            CitationRenderedItem(
                paperId=paper.id,
                renderedText=text,
            )
        )
        joined_parts.append(text)

    return CitationFormatResponse(
        text="; ".join(joined_parts),
        items=rendered_items,
    )


def format_bibliography(
    request: BibliographyFormatRequest,
    papers: list[PaperSummary],
) -> BibliographyFormatResponse:
    entries = [_render_bibliography_entry(request.style, paper) for paper in papers]
    title = "References" if request.style in ("apa", "nature") else "Bibliography"
    return BibliographyFormatResponse(title=title, entries=entries)


def _render_single_citation(
    paper: PaperSummary,
    style: str,
    locator: str | None = None,
    prefix: str | None = None,
    suffix: str | None = None,
) -> str:
    lead_author = _first_author_label(paper.authors)
    locator_part = f", {locator}" if locator else ""
    prefix_part = f"{prefix} " if prefix else ""
    suffix_part = f", {suffix}" if suffix else ""

    if style == "vancouver":
        core = f"[{paper.id}]"
    else:
        core = f"({lead_author}, {paper.year}{locator_part}{suffix_part})"

    return f"{prefix_part}{core}".strip()


def _render_bibliography_entry(style: str, paper: PaperSummary) -> str:
    doi_part = f" https://doi.org/{paper.doi}" if paper.doi else ""

    if style == "vancouver":
        return f"{paper.authors}. {paper.title}. {paper.journal}. {paper.year}.{doi_part}".strip()
    if style == "nature":
        return f"{paper.authors} {paper.title}. {paper.journal} ({paper.year}).{doi_part}".strip()
    return f"{paper.authors} ({paper.year}). {paper.title}. {paper.journal}.{doi_part}".strip()


def _first_author_label(authors: str) -> str:
    parts = [part.strip() for part in authors.split(",") if part.strip()]
    return parts[0] if parts else "Unknown"
