import { formatBibliography, formatCitation } from "./bunkenApi";
import type { CitationRecord, CitationStyle, DocumentState } from "../types/documentState";
import type { PaperSummary } from "../types/paper";

const DOCUMENT_STATE_KEY = "bunkenDocumentState";
const BIBLIOGRAPHY_TAG = "BUNKEN_BIBLIOGRAPHY";
const CITATION_TAG = "BUNKEN_CITATION";

export async function createCitation(
  paper: PaperSummary,
  options: { locator?: string; style: CitationStyle },
) {
  const citation = await formatCitation({
    style: options.style,
    items: [
      {
        paperId: paper.id,
        locator: options.locator,
        prefix: "",
        suffix: "",
      },
    ],
  });

  await Word.run(async (context) => {
    const selection = context.document.getSelection();
    const insertedRange = selection.insertText(citation.text, Word.InsertLocation.replace);
    const control = insertedRange.insertContentControl();
    control.tag = CITATION_TAG;
    control.title = "bunken citation";
    context.load(control, "id");
    await context.sync();

    const state = await loadDocumentState();
    const nextRecord: CitationRecord = {
      citationId: buildCitationId(),
      controlId: control.id,
      paperIds: [paper.id],
      style: options.style,
      locator: options.locator,
      renderedText: citation.text,
    };

    state.citations.push(nextRecord);
    await saveDocumentState(state);
  });
}

export async function refreshBibliography(style: CitationStyle) {
  const state = await loadDocumentState();
  const uniquePaperIds = [...new Set(state.citations.flatMap((citation) => citation.paperIds))];
  const bibliography = await formatBibliography(uniquePaperIds, style);

  await Word.run(async (context) => {
    const controls = context.document.contentControls;
    context.load(controls, "items/id,items/tag");
    await context.sync();

    const existing = controls.items.find((item) => item.tag === BIBLIOGRAPHY_TAG);
    const content = `${bibliography.title}\n\n${bibliography.entries.join("\n")}`;

    if (existing) {
      existing.insertText(content, Word.InsertLocation.replace);
      state.bibliographyControlId = existing.id;
    } else {
      const bodyEnd = context.document.body.getRange(Word.RangeLocation.end);
      const range = bodyEnd.insertText(`\n\n${content}`, Word.InsertLocation.after);
      const control = range.insertContentControl();
      control.tag = BIBLIOGRAPHY_TAG;
      control.title = "bunken bibliography";
      context.load(control, "id");
      await context.sync();
      state.bibliographyControlId = control.id;
    }

    state.style = style;
    await saveDocumentState(state);
  });
}

export function loadDocumentState(): Promise<DocumentState> {
  return new Promise((resolve, reject) => {
    Office.context.document.settings.refreshAsync((refreshResult) => {
      if (refreshResult.status !== Office.AsyncResultStatus.Succeeded) {
        reject(new Error("document settings refresh failed"));
        return;
      }

      const rawValue = Office.context.document.settings.get(DOCUMENT_STATE_KEY);
      if (!rawValue) {
        resolve({
          version: 1,
          style: "apa",
          citations: [],
        });
        return;
      }

      resolve(rawValue as DocumentState);
    });
  });
}

export function saveDocumentState(state: DocumentState): Promise<void> {
  return new Promise((resolve, reject) => {
    Office.context.document.settings.set(DOCUMENT_STATE_KEY, state);
    Office.context.document.settings.saveAsync((saveResult) => {
      if (saveResult.status !== Office.AsyncResultStatus.Succeeded) {
        reject(new Error("document settings save failed"));
        return;
      }

      resolve();
    });
  });
}

function buildCitationId() {
  return `cit_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}
