import type { PaperSummary } from "../types/paper";

type Props = {
  items: PaperSummary[];
  selectedPaperId?: string;
  onSelectPaper: (paper: PaperSummary) => void;
};

export function CitationResultList({
  items,
  selectedPaperId,
  onSelectPaper,
}: Props) {
  if (items.length === 0) {
    return null;
  }

  return (
    <div style={styles.list}>
      {items.map((paper) => {
        const isSelected = selectedPaperId === paper.id;
        return (
          <button
            key={paper.id}
            type="button"
            onClick={() => onSelectPaper(paper)}
            style={styles.item(isSelected)}
          >
            <strong style={styles.paperTitle}>{paper.title}</strong>
            <span style={styles.meta}>{paper.authors}</span>
            <span style={styles.meta}>
              {paper.journal} {paper.year ? `(${paper.year})` : ""}
            </span>
          </button>
        );
      })}
    </div>
  );
}

const styles = {
  list: {
    display: "grid",
    gap: "10px",
  },
  item: (isSelected: boolean) => ({
    textAlign: "left" as const,
    width: "100%",
    borderRadius: "14px",
    border: isSelected ? "1px solid #127fbf" : "1px solid #d9e2ec",
    background: isSelected ? "#e0f2fe" : "#ffffff",
    padding: "12px",
    cursor: "pointer",
  }),
  paperTitle: {
    display: "block",
    marginBottom: "6px",
    fontSize: "14px",
    color: "#102a43",
  },
  meta: {
    display: "block",
    fontSize: "12px",
    color: "#52606d",
  },
};
