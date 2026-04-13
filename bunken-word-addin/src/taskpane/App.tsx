import { useEffect, useState } from "react";
import { CitationActions } from "./components/CitationActions";
import { CitationSearchPanel } from "./components/CitationSearchPanel";
import { BibliographyPanel } from "./components/BibliographyPanel";
import type { PaperSummary } from "./types/paper";
import { createCitation, refreshBibliography } from "./services/officeWord";
import { getSession } from "./services/auth";

export function App() {
  const [selectedPaper, setSelectedPaper] = useState<PaperSummary | null>(null);
  const [statusMessage, setStatusMessage] = useState("Word を待機中です。");
  const [isReady, setIsReady] = useState(false);
  const [isBusy, setIsBusy] = useState(false);

  useEffect(() => {
    Office.onReady(async (info) => {
      if (info.host !== Office.HostType.Word) {
        setStatusMessage("このアドインは Word 専用です。");
        return;
      }

      try {
        await getSession();
        setStatusMessage("bunken に接続しました。");
      } catch {
        setStatusMessage("bunken のセッション確認に失敗しました。");
      }

      setIsReady(true);
    });
  }, []);

  async function handleInsertCitation(locator?: string) {
    if (!selectedPaper) {
      setStatusMessage("先に文献を選択してください。");
      return;
    }

    setIsBusy(true);
    setStatusMessage("引用を挿入しています。");

    try {
      await createCitation(selectedPaper, {
        locator,
        style: "apa",
      });
      setStatusMessage(`引用を挿入しました: ${selectedPaper.title}`);
    } catch (error) {
      setStatusMessage(getErrorMessage(error, "引用の挿入に失敗しました。"));
    } finally {
      setIsBusy(false);
    }
  }

  async function handleRefreshBibliography() {
    setIsBusy(true);
    setStatusMessage("参考文献を更新しています。");

    try {
      await refreshBibliography("apa");
      setStatusMessage("参考文献を更新しました。");
    } catch (error) {
      setStatusMessage(getErrorMessage(error, "参考文献の更新に失敗しました。"));
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <main style={styles.page}>
      <header style={styles.header}>
        <div>
          <h1 style={styles.title}>bunken Word</h1>
          <p style={styles.subtitle}>Word で引用と参考文献を管理します。</p>
        </div>
        <span style={styles.statusBadge(isReady)}>{isReady ? "Ready" : "Loading"}</span>
      </header>

      <section style={styles.card}>
        <CitationSearchPanel
          disabled={!isReady || isBusy}
          selectedPaperId={selectedPaper?.id}
          onSelectPaper={setSelectedPaper}
        />
      </section>

      <section style={styles.card}>
        <CitationActions
          disabled={!isReady || isBusy}
          selectedPaper={selectedPaper}
          onInsertCitation={handleInsertCitation}
        />
      </section>

      <section style={styles.card}>
        <BibliographyPanel
          disabled={!isReady || isBusy}
          onRefreshBibliography={handleRefreshBibliography}
        />
      </section>

      <footer style={styles.footer}>{statusMessage}</footer>
    </main>
  );
}

function getErrorMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

const styles = {
  page: {
    minHeight: "100vh",
    margin: 0,
    padding: "20px",
    fontFamily: "'Segoe UI', 'Hiragino Sans', sans-serif",
    background:
      "linear-gradient(180deg, rgb(248 246 240) 0%, rgb(239 235 226) 100%)",
    color: "#1f2933",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: "12px",
    marginBottom: "16px",
  },
  title: {
    margin: 0,
    fontSize: "24px",
  },
  subtitle: {
    margin: "6px 0 0",
    fontSize: "13px",
    color: "#52606d",
  },
  statusBadge: (isReady: boolean) => ({
    padding: "6px 10px",
    borderRadius: "999px",
    fontSize: "12px",
    fontWeight: 700,
    backgroundColor: isReady ? "#d9f99d" : "#fde68a",
    color: "#243b53",
  }),
  card: {
    marginBottom: "14px",
    padding: "16px",
    borderRadius: "18px",
    backgroundColor: "rgba(255, 255, 255, 0.86)",
    boxShadow: "0 12px 30px rgba(15, 23, 42, 0.08)",
  },
  footer: {
    fontSize: "13px",
    color: "#334e68",
    padding: "8px 2px 0",
  },
} satisfies Record<string, unknown>;
