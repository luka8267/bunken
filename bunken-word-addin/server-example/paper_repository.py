from dataclasses import dataclass

from models import PaperSummary


@dataclass
class UserSession:
    user_id: str
    email: str
    username: str


class PaperRepository:
    def __init__(self) -> None:
        self._papers = [
            PaperSummary(
                id="paper_001",
                title="Clinical Reasoning in Practice",
                authors="Suzuki, Sato",
                journal="Medical Notes",
                year=2024,
                doi="10.1000/example-001",
            ),
            PaperSummary(
                id="paper_002",
                title="Evidence Synthesis for Care Teams",
                authors="Tanaka, Ito",
                journal="Care Systems Journal",
                year=2023,
                doi="10.1000/example-002",
            ),
        ]

    def search_user_papers(self, user_id: str, query: str) -> list[PaperSummary]:
        normalized_query = (query or "").strip().lower()
        if not normalized_query:
            return self._papers

        matched: list[PaperSummary] = []
        for paper in self._papers:
            haystack = " ".join(
                [
                    paper.title,
                    paper.authors,
                    paper.journal,
                    paper.doi or "",
                ]
            ).lower()
            if normalized_query in haystack:
                matched.append(paper)
        return matched

    def get_user_paper_by_id(self, user_id: str, paper_id: str) -> PaperSummary | None:
        for paper in self._papers:
            if paper.id == paper_id:
                return paper
        return None


def get_current_session() -> UserSession:
    return UserSession(
        user_id="demo-user-id",
        email="demo@example.com",
        username="demo",
    )
