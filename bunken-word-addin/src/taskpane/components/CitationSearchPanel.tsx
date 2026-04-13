import { useEffect, useState } from "react";
import { searchPapers } from "../services/bunkenApi";
import type { PaperSummary } from "../types/paper";
import { CitationResultList } from "./CitationResultList";

type Props = {
  disabled: boolean;
  selectedPaperId?: string;
  onSelectPaper: (paper: PaperSummary) => void;
};

export function CitationSearchPanel({
  disabled,
  selectedPaperId,
  onSelectPaper,
}: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PaperSummary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState("タイトル、著者、DOI で検索できます。");

  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      return;
    }

    const timeoutId = window.setTimeout(async () => {
      setIsLoading(true);
      try {
        const items = await searchPapers(query);
        setResults(items);
        setMessage(items.length === 0 ? "一致する文献はありません。" : `${items.length} 件見つかりました。`);
      } catch {
        setMessage("検索に失敗しました。");
      } finally {
        setIsLoading(false);
      }
    }, 350);

    return () => window.clearTimeout(timeoutId);
  }, [query]);

  return (
    <section>
      <h2 style={styles.heading}>文献検索</h2>
      <input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="例: Suzuki 2024"
        disabled={disabled}
        style={styles.input}
      />
      <p style={styles.message}>{isLoading ? "検索中..." : message}</p>
      <CitationResultList
        items={results}
        selectedPaperId={selectedPaperId}
        onSelectPaper={onSelectPaper}
      />
    </section>
  );
}

const styles = {
  heading: {
    margin: "0 0 10px",
    fontSize: "17px",
  },
  input: {
    width: "100%",
    padding: "11px 12px",
    borderRadius: "12px",
    border: "1px solid #cbd2d9",
    fontSize: "14px",
    backgroundColor: "#fffdf8",
    boxSizing: "border-box" as const,
  },
  message: {
    margin: "10px 0 12px",
    fontSize: "12px",
    color: "#52606d",
  },
};
