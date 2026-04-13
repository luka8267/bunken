import { useState } from "react";
import type { PaperSummary } from "../types/paper";

type Props = {
  disabled: boolean;
  selectedPaper: PaperSummary | null;
  onInsertCitation: (locator?: string) => Promise<void>;
};

export function CitationActions({
  disabled,
  selectedPaper,
  onInsertCitation,
}: Props) {
  const [locator, setLocator] = useState("");

  return (
    <section>
      <h2 style={styles.heading}>引用挿入</h2>
      <p style={styles.message}>
        {selectedPaper
          ? `選択中: ${selectedPaper.title}`
          : "文献を選択すると引用を挿入できます。"}
      </p>
      <input
        value={locator}
        onChange={(event) => setLocator(event.target.value)}
        placeholder="例: p. 25"
        disabled={disabled}
        style={styles.input}
      />
      <button
        type="button"
        disabled={disabled || !selectedPaper}
        onClick={() => onInsertCitation(locator.trim() || undefined)}
        style={styles.button}
      >
        本文に引用を挿入
      </button>
    </section>
  );
}

const styles = {
  heading: {
    margin: "0 0 10px",
    fontSize: "17px",
  },
  message: {
    margin: "0 0 10px",
    fontSize: "12px",
    color: "#52606d",
  },
  input: {
    width: "100%",
    padding: "11px 12px",
    borderRadius: "12px",
    border: "1px solid #cbd2d9",
    fontSize: "14px",
    marginBottom: "12px",
    boxSizing: "border-box" as const,
  },
  button: {
    width: "100%",
    padding: "12px",
    borderRadius: "999px",
    border: "none",
    backgroundColor: "#0f766e",
    color: "#fff",
    fontWeight: 700,
    cursor: "pointer",
  },
};
