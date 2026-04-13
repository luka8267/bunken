from fastapi import FastAPI, HTTPException, Query

from citation_service import format_bibliography, format_citation
from models import (
    BibliographyFormatRequest,
    CitationFormatRequest,
    PaperSearchResponse,
    SessionResponse,
)
from paper_repository import PaperRepository, get_current_session

app = FastAPI(title="bunken add-in API example")
paper_repository = PaperRepository()


@app.post("/api/addin/auth/session", response_model=SessionResponse)
def get_session() -> SessionResponse:
    session = get_current_session()
    return SessionResponse(
        userId=session.user_id,
        email=session.email,
        username=session.username,
    )


@app.get("/api/addin/papers", response_model=PaperSearchResponse)
def search_papers(q: str = Query(default="")) -> PaperSearchResponse:
    session = get_current_session()
    papers = paper_repository.search_user_papers(session.user_id, q)
    return PaperSearchResponse(items=papers)


@app.get("/api/addin/papers/{paper_id}")
def get_paper(paper_id: str):
    session = get_current_session()
    paper = paper_repository.get_user_paper_by_id(session.user_id, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="paper not found")
    return paper


@app.post("/api/addin/citations/format")
def create_citation(payload: CitationFormatRequest):
    session = get_current_session()
    papers = []
    for item in payload.items:
        paper = paper_repository.get_user_paper_by_id(session.user_id, item.paperId)
        if paper is None:
            raise HTTPException(status_code=404, detail=f"paper not found: {item.paperId}")
        papers.append(paper)
    return format_citation(payload, papers)


@app.post("/api/addin/bibliography/format")
def create_bibliography(payload: BibliographyFormatRequest):
    session = get_current_session()
    papers = []
    seen_ids: set[str] = set()
    for paper_id in payload.paperIds:
        if paper_id in seen_ids:
            continue
        seen_ids.add(paper_id)
        paper = paper_repository.get_user_paper_by_id(session.user_id, paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail=f"paper not found: {paper_id}")
        papers.append(paper)
    return format_bibliography(payload, papers)
