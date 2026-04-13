(function () {
  const API_BASE_URL = globalThis.BUNKEN_API_BASE_URL || "http://127.0.0.1:8765";
  const DOCUMENT_STATE_KEY = "bunkenDocumentState";
  const BIBLIOGRAPHY_TAG = "BUNKEN_BIBLIOGRAPHY";
  const CITATION_TAG = "BUNKEN_CITATION";
  const STYLE = "apa";

  const state = {
    isReady: false,
    isBusy: false,
    searchTimerId: null,
    selectedPaper: null,
    results: [],
  };

  const readyBadge = document.getElementById("ready-badge");
  const status = document.getElementById("status");
  const searchInput = document.getElementById("search-input");
  const searchMessage = document.getElementById("search-message");
  const searchResults = document.getElementById("search-results");
  const locatorInput = document.getElementById("locator-input");
  const selectionMessage = document.getElementById("selection-message");
  const insertCitationButton = document.getElementById("insert-citation-button");
  const refreshBibliographyButton = document.getElementById("refresh-bibliography-button");

  function setStatus(message) {
    status.textContent = message;
  }

  function setReady(isReady) {
    state.isReady = isReady;
    readyBadge.textContent = isReady ? "Ready" : "Loading";
    readyBadge.classList.toggle("ready", isReady);
    updateDisabledState();
  }

  function setBusy(isBusy) {
    state.isBusy = isBusy;
    updateDisabledState();
  }

  function updateDisabledState() {
    const disabled = !state.isReady || state.isBusy;
    searchInput.disabled = disabled;
    locatorInput.disabled = disabled;
    insertCitationButton.disabled = disabled || !state.selectedPaper;
    refreshBibliographyButton.disabled = disabled;
  }

  function renderResults() {
    searchResults.innerHTML = "";

    for (const paper of state.results) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "paper-item";
      if (state.selectedPaper && state.selectedPaper.id === paper.id) {
        button.classList.add("selected");
      }
      button.innerHTML = `
        <strong class="paper-title"></strong>
        <span class="paper-meta"></span>
        <span class="paper-meta"></span>
      `;
      const nodes = button.querySelectorAll("strong, span");
      nodes[0].textContent = paper.title;
      nodes[1].textContent = paper.authors;
      nodes[2].textContent = `${paper.journal} ${paper.year ? `(${paper.year})` : ""}`;
      button.addEventListener("click", function () {
        state.selectedPaper = paper;
        selectionMessage.textContent = `選択中: ${paper.title}`;
        renderResults();
        updateDisabledState();
      });
      searchResults.appendChild(button);
    }
  }

  async function fetchJson(url, init) {
    const response = await fetch(url, Object.assign({ credentials: "include" }, init || {}));
    if (!response.ok) {
      throw new Error(`API request failed: ${response.status}`);
    }
    return response.json();
  }

  function buildCitationId() {
    return `cit_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  }

  function loadDocumentState() {
    return new Promise(function (resolve, reject) {
      Office.context.document.settings.refreshAsync(function (result) {
        if (result.status !== Office.AsyncResultStatus.Succeeded) {
          reject(new Error("document settings refresh failed"));
          return;
        }
        resolve(
          Office.context.document.settings.get(DOCUMENT_STATE_KEY) || {
            version: 1,
            style: STYLE,
            citations: [],
          },
        );
      });
    });
  }

  function saveDocumentState(nextState) {
    return new Promise(function (resolve, reject) {
      Office.context.document.settings.set(DOCUMENT_STATE_KEY, nextState);
      Office.context.document.settings.saveAsync(function (result) {
        if (result.status !== Office.AsyncResultStatus.Succeeded) {
          reject(new Error("document settings save failed"));
          return;
        }
        resolve();
      });
    });
  }

  async function searchPapers(query) {
    const url = new URL("/api/addin/papers", API_BASE_URL);
    url.searchParams.set("q", query);
    const response = await fetchJson(url.toString(), { method: "GET" });
    return response.items || [];
  }

  async function formatCitation(payload) {
    return fetchJson(`${API_BASE_URL}/api/addin/citations/format`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  async function formatBibliography(paperIds, style) {
    return fetchJson(`${API_BASE_URL}/api/addin/bibliography/format`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paperIds, style }),
    });
  }

  searchInput.addEventListener("input", function () {
    const query = searchInput.value.trim();

    if (state.searchTimerId) {
      window.clearTimeout(state.searchTimerId);
    }

    if (!query) {
      state.results = [];
      searchMessage.textContent = "タイトル、著者、雑誌名で検索できます。";
      renderResults();
      return;
    }

    state.searchTimerId = window.setTimeout(async function () {
      setBusy(true);
      searchMessage.textContent = "検索中...";
      try {
        state.results = await searchPapers(query);
        searchMessage.textContent =
          state.results.length === 0
            ? "一致する文献はありません。"
            : `${state.results.length} 件見つかりました。`;
        renderResults();
      } catch (error) {
        searchMessage.textContent = error && error.message ? error.message : "検索に失敗しました。";
      } finally {
        setBusy(false);
      }
    }, 350);
  });

  insertCitationButton.addEventListener("click", async function () {
    if (!state.selectedPaper) {
      setStatus("先に文献を選択してください。");
      return;
    }

    setBusy(true);
    setStatus("引用を挿入しています。");

    try {
      const citation = await formatCitation({
        style: STYLE,
        items: [
          {
            paperId: state.selectedPaper.id,
            locator: locatorInput.value.trim() || undefined,
            prefix: "",
            suffix: "",
          },
        ],
      });

      await Word.run(async function (context) {
        const selection = context.document.getSelection();
        const insertedRange = selection.insertText(citation.text, Word.InsertLocation.replace);
        const control = insertedRange.insertContentControl();
        control.tag = CITATION_TAG;
        control.title = "bunken citation";
        context.load(control, "id");
        await context.sync();

        const documentState = await loadDocumentState();
        documentState.citations.push({
          citationId: buildCitationId(),
          controlId: control.id,
          paperIds: [state.selectedPaper.id],
          style: STYLE,
          locator: locatorInput.value.trim() || undefined,
          renderedText: citation.text,
        });
        await saveDocumentState(documentState);
      });

      setStatus(`引用を挿入しました: ${state.selectedPaper.title}`);
    } catch (error) {
      setStatus(error && error.message ? error.message : "引用の挿入に失敗しました。");
    } finally {
      setBusy(false);
    }
  });

  refreshBibliographyButton.addEventListener("click", async function () {
    setBusy(true);
    setStatus("参考文献を更新しています。");

    try {
      const documentState = await loadDocumentState();
      const uniquePaperIds = Array.from(
        new Set(
          (documentState.citations || []).flatMap(function (citation) {
            return citation.paperIds || [];
          }),
        ),
      );
      const bibliography = await formatBibliography(uniquePaperIds, STYLE);

      await Word.run(async function (context) {
        const controls = context.document.contentControls;
        context.load(controls, "items/id,items/tag");
        await context.sync();

        const existing = controls.items.find(function (item) {
          return item.tag === BIBLIOGRAPHY_TAG;
        });
        const content = `${bibliography.title}\n\n${bibliography.entries.join("\n")}`;

        if (existing) {
          existing.insertText(content, Word.InsertLocation.replace);
          documentState.bibliographyControlId = existing.id;
        } else {
          const bodyEnd = context.document.body.getRange(Word.RangeLocation.end);
          const range = bodyEnd.insertText(`\n\n${content}`, Word.InsertLocation.after);
          const control = range.insertContentControl();
          control.tag = BIBLIOGRAPHY_TAG;
          control.title = "bunken bibliography";
          context.load(control, "id");
          await context.sync();
          documentState.bibliographyControlId = control.id;
        }

        documentState.style = STYLE;
        await saveDocumentState(documentState);
      });

      setStatus("参考文献を更新しました。");
    } catch (error) {
      setStatus(error && error.message ? error.message : "参考文献の更新に失敗しました。");
    } finally {
      setBusy(false);
    }
  });

  Office.onReady(async function (info) {
    if (info.host !== Office.HostType.Word) {
      setStatus("このアドインは Word 専用です。");
      return;
    }

    try {
      await fetchJson(`${API_BASE_URL}/api/addin/auth/session`, { method: "POST" });
      setStatus("bunken に接続しました。");
      setReady(true);
    } catch (error) {
      setStatus(error && error.message ? error.message : "bunken のセッション確認に失敗しました。");
    }
  });
})();
