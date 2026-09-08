/* The answer card: one question, its answer, the clauses it cites and why the
   reviewer flagged it.

   Shared by the workbench and the chat page, because it is the thing worth
   looking at in both and two renderings of it would drift within a week. It
   was extracted from the workbench rather than rewritten, so nothing about
   what a card shows has changed.

   Everything here is deliberately about *drawing*. The three things a card
   does that depend on which page it is on are hooks with harmless defaults:

     Cards.onDiscard(key)              throw a question away
     Cards.onRetry(keys, button)       answer a failed one again
     Cards.onOpenDocument(descriptor)  open the file a source came from
     Cards.onEdit(item, index, text)      an answer is being edited, per keystroke
     Cards.onEditDone(item, index, text)  the editor was left: worth storing
     Cards.onBlank(item, index, blank)    leave this answer deliberately empty

   A page that can honour one assigns it; a page that cannot leaves it, and the
   control simply does nothing rather than throwing.
*/

const Cards = (window.Cards = {
  onDiscard() {},
  onRetry() {},
  onOpenDocument() {},
  onEdit() {},
  onEditDone() {},
  onBlank() {},
  /* Where the page keeps the answer being edited. The card shows and writes
     through this rather than owning it, because the workbench holds a whole
     run in memory and the chat page holds a batch. */
  answerText(item) { return item.answer || ""; },
});

(function () {
  // Where the Formatted/Raw choice is remembered, per browser.
  const VIEW_KEY = "assessment-chunk-view";

  function isArabic(text) {
    return /[؀-ۿ]/.test(text || "");
  }

  function chunkView() {
    try { return localStorage.getItem(VIEW_KEY) || "pretty"; } catch (error) { return "pretty"; }
  }

  function setChunkView(view) {
    try { localStorage.setItem(VIEW_KEY, view); } catch (error) { /* private mode */ }
    document.querySelectorAll("[data-view]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.view === view));
    });
    document.querySelectorAll("[data-chunk-source]").forEach((node) => {
      node.replaceWith(renderChunk(node.getAttribute("data-chunk-source"), view));
    });
  }

  function words(text) {
    return (text || "").match(/[\p{L}\p{N}]+/gu) || [];
  }

  function flatText(node) {
    const parts = [];
    const walk = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    while (walk.nextNode()) parts.push(walk.currentNode.nodeValue);
    return parts.join(" ");
  }

  function buildTable(rows) {
    const table = document.createElement("table");
    const body = document.createElement("tbody");
    let head = null;

    rows.forEach((line, index) => {
      if (isSeparatorRow(line)) return;
      const values = cells(line);
      const isHead = index === 0 && rows.length > 1 && isSeparatorRow(rows[1]);
      const row = document.createElement("tr");
      values.forEach((value) => {
        const cell = document.createElement(isHead ? "th" : "td");
        cell.textContent = value;
        if (isArabic(value)) cell.dir = "rtl";
        row.append(cell);
      });
      if (isHead) {
        head = document.createElement("thead");
        head.append(row);
      } else {
        body.append(row);
      }
    });

    if (head) table.append(head);
    if (body.childElementCount) table.append(body);
    const wrap = document.createElement("div");
    wrap.className = "tablewrap";
    wrap.append(table);
    return wrap;
  }

  function buildPretty(text) {
    const box = document.createElement("div");
    box.className = "chunk";
    const lines = String(text).split("\n");
    let index = 0;
    let list = null;

    while (index < lines.length) {
      const line = lines[index];
      const trimmed = line.trim();

      if (!trimmed) { list = null; index += 1; continue; }

      if (trimmed.charAt(0) === "|") {
        list = null;
        const rows = [];
        while (index < lines.length && lines[index].trim().charAt(0) === "|") {
          rows.push(lines[index]);
          index += 1;
        }
        box.append(buildTable(rows));
        continue;
      }

      const heading = trimmed.match(/^#{1,6}\s+(.*)$/);
      if (heading) {
        list = null;
        const element = document.createElement("h4");
        const rest = heading[1];
        const numbered = rest.match(/^(\d+(?:[.\-]\d+)*)\s+(.*)$/);
        if (numbered) {
          const clause = document.createElement("span");
          clause.className = "clause";
          clause.textContent = numbered[1] + " ";
          element.append(clause, document.createTextNode(numbered[2]));
        } else {
          element.textContent = rest;
        }
        if (isArabic(rest)) element.dir = "rtl";
        box.append(element);
        index += 1;
        continue;
      }

      if (/^<!--\s*image\s*-->$/.test(trimmed)) {
        list = null;
        const figure = document.createElement("div");
        figure.className = "figure";
        figure.textContent = "image";
        box.append(figure);
        index += 1;
        continue;
      }

      const bullet = trimmed.match(/^[-*•]\s+(.*)$/);
      if (bullet) {
        if (!list) {
          list = document.createElement("ul");
          box.append(list);
        }
        const item = document.createElement("li");
        item.textContent = bullet[1];
        if (isArabic(bullet[1])) item.dir = "rtl";
        list.append(item);
        index += 1;
        continue;
      }

      list = null;
      const paragraph = document.createElement("p");
      paragraph.textContent = trimmed;
      if (isArabic(trimmed)) paragraph.dir = "rtl";
      box.append(paragraph);
      index += 1;
    }

    return box;
  }

  function buildRaw(text) {
    const pre = document.createElement("pre");
    pre.className = "snippet";
    pre.textContent = text;
    if (isArabic(text)) pre.dir = "rtl";
    return pre;
  }

  function renderChunk(text, view) {
    const source = String(text == null ? "" : text);
    let node;
    if ((view || chunkView()) !== "pretty") {
      node = buildRaw(source);
    } else {
      node = buildPretty(source);
      // Self-check: a formatted view that loses words is worse than an ugly
      // one, and the loss is invisible by inspection.
      const counts = new Map();
      words(flatText(node)).forEach((word) => counts.set(word, (counts.get(word) || 0) + 1));
      const lost = words(source).some((word) => {
        const left = counts.get(word) || 0;
        if (!left) return true;
        counts.set(word, left - 1);
        return false;
      });
      if (lost) {
        console.warn("Formatted view dropped content; showing raw text instead.");
        node = buildRaw(source);
      }
    }
    node.setAttribute("data-chunk-source", source);
    return node;
  }

  function viewToggle() {
    const box = document.createElement("div");
    box.className = "view-toggle";
    box.setAttribute("role", "group");
    box.setAttribute("aria-label", "How to show the text");
    [["pretty", "Formatted"], ["raw", "Raw"]].forEach(([mode, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.view = mode;
      button.textContent = label;
      button.setAttribute("aria-pressed", String(chunkView() === mode));
      button.onclick = () => setChunkView(mode);
      box.append(button);
    });
    return box;
  }

  /* A chunk is only checkable if you can open the file it came from. */
  function openDocumentButton(sourceName, sourceType) {
    const button = document.createElement("button");
    button.className = "quiet";
    button.textContent = "open document";
    button.onclick = () => Cards.onOpenDocument({
      name: sourceName,
      title: sourceName.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " "),
      origin: "uploaded",
      category: "uploaded",
      label: sourceType === "prior_answer" ? "Uploaded completed assessment" : "Uploaded guideline",
      extension: sourceName.split(".").pop().toLowerCase(),
      size_bytes: 0,
    });
    return button;
  }

  function renderMarkdown(text) {
    const nodes = [];
    let list = null;

    const boldInto = (parent, line) => {
      const pattern = /(\*\*|__)(?=\S)([\s\S]+?)(?<=\S)\1/g;
      let at = 0, match;
      while ((match = pattern.exec(line)) !== null) {
        if (match.index > at) parent.append(line.slice(at, match.index));
        const strong = document.createElement("strong");
        strong.textContent = match[2];
        parent.append(strong);
        at = pattern.lastIndex;
      }
      if (at < line.length) parent.append(line.slice(at));
    };

    const closeList = () => { if (list) { nodes.push(list); list = null; } };

    text.split("\n").forEach((raw) => {
      const line = raw.trim();
      if (!line) { closeList(); return; }

      const heading = line.match(/^#{1,6}\s+(.*)$/);
      const bullet = line.match(/^[-*•]\s+(.*)$/);
      const numbered = line.match(/^(\d{1,3})[.)]\s+(.*)$/);

      if (heading) {
        closeList();
        const node = document.createElement("h4");
        boldInto(node, heading[1]);
        nodes.push(node);
      } else if (bullet || numbered) {
        const wanted = bullet ? "UL" : "OL";
        if (!list || list.tagName !== wanted) { closeList(); list = document.createElement(wanted.toLowerCase()); }
        const item = document.createElement("li");
        boldInto(item, (bullet || numbered)[bullet ? 1 : 2]);
        list.append(item);
      } else {
        closeList();
        const node = document.createElement("p");
        boldInto(node, line);
        nodes.push(node);
      }
    });

    closeList();
    return nodes;
  }

  function labelledField(text, tone) {
    const wrap = document.createElement("div");
    wrap.className = "field";
    const label = document.createElement("span");
    label.className = "field-label" + (tone ? " " + tone : "");
    label.textContent = text;
    wrap.append(label);
    return wrap;
  }

  function confidenceBand(value) {
    if (value >= 0.75) return { key: "high", word: "High confidence" };
    if (value > 0.6) return { key: "medium", word: "Moderate" };
    return { key: "low", word: "Low confidence" };
  }

  function answerField(item, index) {
    const field = labelledField("Answer", "");
    const rendered = document.createElement("div");
    rendered.className = "rendered";
    const editor = document.createElement("textarea");
    const toggle = document.createElement("button");
    toggle.className = "quiet";

    const grow = document.createElement("span");
    grow.className = "grow";
    field.querySelector(".field-label").append(grow, toggle);

    const paint = () => {
      const text = Cards.answerText(item, index);
      rendered.innerHTML = "";
      if (item.blanked) {
        /* Deliberately empty is not the same as never answered, and the card
           has to say which -- one is a decision, the other is work still to
           do. The cell is still written, with nothing in it, so a stale answer
           already in the file gets cleared. */
        const note = document.createElement("p");
        note.className = "empty";
        note.textContent = "This answer will be left blank.";
        rendered.append(note);
      } else if (!text.trim()) {
        const empty = document.createElement("p");
        empty.className = "empty";
        empty.textContent = "No answer was produced — see the note below.";
        rendered.append(empty);
      } else {
        renderMarkdown(text).forEach((node) => rendered.append(node));
      }
      rendered.dir = isArabic(text) ? "rtl" : "ltr";
    };
    Cards.repaint = paint;

    /* Leaving it blank on purpose. Beside Edit because it is the same kind of
       decision -- what this question should say -- and because a control that
       empties an answer belongs next to the answer and nowhere else. */
    const blank = document.createElement("button");
    blank.className = "quiet";
    blank.textContent = item.blanked ? "Write an answer" : "Leave blank";
    blank.onclick = () => Cards.onBlank(item, index, !item.blanked);
    field.querySelector(".field-label").append(blank);

    let editing = false;
    const setMode = (next) => {
      editing = next;
      rendered.hidden = editing;
      editor.hidden = !editing;
      toggle.textContent = editing ? "Done editing" : "Edit";
      if (editing) { editor.focus(); } else { paint(); }
    };

    editor.value = item.answer;
    editor.hidden = true;
    if (isArabic(item.answer)) editor.dir = "rtl";
    editor.addEventListener("input", () => Cards.onEdit(item, index, editor.value));
    /* `input` fires on every keystroke, which is right for keeping the page in
       step and wrong for anything that leaves the browser. `change` fires once,
       when the editor is left and the text actually differs, which is the point
       at which an edit is worth storing. Leaving by the button fires it too,
       because blur precedes the click. */
    editor.addEventListener("change", () => Cards.onEditDone(item, index, editor.value));
    toggle.onclick = () => setMode(!editing);

    field.append(rendered, editor);
    setMode(false);
    return field;
  }

  function citationsField(item) {
    const field = labelledField("Sources cited — click to read the clause", "accent");
    const cites = document.createElement("div");
    cites.className = "cites";
    const panel = document.createElement("div");
    panel.className = "cite-panel";
    panel.hidden = true;

    let openButton = null;
    const sourceTypes = new Set();

    item.citations.forEach((citation) => {
      const source = (item.evidence || []).find((e) => (e.locator || e.source_name) === citation);
      const kind = source ? source.source_type : "unknown";
      if (source) sourceTypes.add(kind);

      const chip = document.createElement("button");
      chip.className = "cite " + kind;
      chip.title = kind === "prior_answer"
        ? "From a previously answered assessment — click to read it"
        : kind === "guideline"
          ? "From an indexed guideline — click to read the clause"
          : "Named in the answer; the chunk is not in the exported evidence";
      chip.type = "button";
      chip.setAttribute("aria-expanded", "false");
      chip.append(document.createTextNode(citation));
      const caret = document.createElement("span");
      caret.className = "caret";
      caret.textContent = "▾";
      chip.append(caret);

      chip.onclick = () => {
        if (openButton === chip) {
          chip.setAttribute("aria-expanded", "false");
          panel.hidden = true;
          openButton = null;
          return;
        }
        if (openButton) openButton.setAttribute("aria-expanded", "false");
        openButton = chip;
        chip.setAttribute("aria-expanded", "true");
        showChunk(panel, item, citation);
      };

      cites.append(chip);
    });

    // A two-colour scheme needs a key, but only when both colours are present.
    if (sourceTypes.size > 1) {
      const key = document.createElement("div");
      key.className = "cite-key";
      key.innerHTML =
        '<span><i class="guideline"></i>guideline</span>' +
        '<span><i class="prior_answer"></i>previous answer</span>';
      cites.append(key);
    }

    field.append(cites, panel);
    return field;
  }

  function renderAnswer(item, index) {
    const card = document.createElement("div");
    card.className = "answer" + (item.needs_review ? " review" : "");

    // --- head: number, question, confidence
    const head = document.createElement("div");
    head.className = "answer-head";

    const number = document.createElement("div");
    number.className = "qnum";
    number.textContent = item.question.id || String(index + 1);

    const body = document.createElement("div");
    body.className = "qbody";

    const question = document.createElement("div");
    question.className = "qtext";
    question.textContent = item.question.text;
    if (isArabic(item.question.text)) question.dir = "rtl";

    const meta = document.createElement("div");
    meta.className = "qmeta";
    if (item.needs_review) {
      const chip = document.createElement("span");
      chip.className = "tag warn";
      chip.textContent = "needs review";
      meta.append(chip);
    }
    const bits = [];
    if (item.question.section) bits.push(item.question.section);
    bits.push(item.question.question_type.replace(/_/g, " "));
    if (item.attempts > 1) bits.push(item.attempts + " retrieval rounds");
    const detail = document.createElement("span");
    detail.textContent = bits.join(" · ");
    meta.append(detail);

    body.append(question, meta);

    const percent = Math.round(item.confidence * 100);
    const band = confidenceBand(item.confidence);
    const confidence = document.createElement("div");
    confidence.className = "confidence " + band.key;
    /* Nothing was drafted, so there is nothing to be confident about. The card
       said "100% — High confidence" over an answer somebody had deliberately
       emptied, which is a score for a decision rather than for an answer. */
    if (item.blanked) {
      confidence.className = "confidence blanked";
      const caption = document.createElement("div");
      caption.className = "caption";
      caption.textContent = "Left blank";
      confidence.append(caption);
    } else {
      const value = document.createElement("div");
      value.className = "value";
      value.textContent = percent + "%";
      const caption = document.createElement("div");
      caption.className = "caption";
      caption.textContent = band.word;
      const meter = document.createElement("div");
      meter.className = "meter";
      const fill = document.createElement("span");
      fill.style.width = percent + "%";
      meter.append(fill);
      confidence.append(value, caption, meter);
    }

    // Removing the pair belongs here, beside what it removes. Only offered for
    // answers this session produced, since an imported result has no question
    // row behind it to keep in step.
    if (item.__key) {
      const remove = document.createElement("button");
      remove.className = "quiet danger qdelete";
      remove.dataset.mutates = "true";
      remove.textContent = "✕";
      remove.title = "Remove this question and its answer";
      remove.onclick = () => Cards.onDiscard(item.__key);
      head.append(number, body, confidence, remove);
    } else {
      head.append(number, body, confidence);
    }

    // --- body: answer, citations, flags, reasoning, evidence
    const content = document.createElement("div");
    content.className = "answer-body";
    content.append(answerField(item, index));

    if (item.citations && item.citations.length) {
      content.append(citationsField(item));
    }

    // A flag with no explanation is what a reviewer cannot act on. The
    // mechanical checks only speak when something is demonstrably wrong, so an
    // answer flagged purely for scoring low used to arrive with an empty
    // reason list and showed nothing here at all — the one place it was most
    // needed. Fall back to the same wording the exports use.
    if (item.needs_review) {
      const reasonText = (item.review_reasons && item.review_reasons.length)
        ? item.review_reasons.join("; ")
        : "The confidence score is below the level set for automatic acceptance.";
      const field = labelledField("Why this is flagged", "warn");
      const reasons = document.createElement("div");
      reasons.className = "reasons";
      reasons.textContent = reasonText;
      field.append(reasons);
      content.append(field);
    }

    // A question that never produced an answer is not a weak answer — there is
    // nothing to read, judge or edit. A rate limit or a withdrawn model is
    // transient, so the only useful thing to offer is another go.
    if (item.error) {
      const field = labelledField("Could not be answered", "err");
      const box = document.createElement("div");
      box.className = "reasons why";
      box.textContent = item.error;
      field.append(box);
      if (item.__key) {
        const again = document.createElement("button");
        again.className = "ghost";
        again.dataset.mutates = "true";
        again.style.marginTop = "9px";
        again.textContent = "Try this question again";
        again.onclick = () => Cards.onRetry([item.__key], again);
        field.append(again);
      }
      content.append(field);
    }

    // Plain-English cause of the score itself, computed server-side so the
    // interface and both exports say exactly the same thing. Not for a blank:
    // "left blank on purpose" is where that field keeps the decision, and
    // reading it back as a reason the confidence is low is nonsense.
    if (item.confidence_reason && !item.blanked) {
      const field = labelledField("Why the confidence is low", "err");
      const why = document.createElement("div");
      why.className = "reasons why";
      why.textContent = item.confidence_reason;
      field.append(why);
      content.append(field);
    }

    if (item.rationale) {
      const field = labelledField("Reasoning", "accent");
      const rationale = document.createElement("div");
      rationale.className = "rationale";
      rationale.textContent = item.rationale;
      if (isArabic(item.rationale)) rationale.dir = "rtl";
      field.append(rationale);
      content.append(field);
    }

    if (item.evidence && item.evidence.length) {
      const details = document.createElement("details");
      details.className = "evidence";
      const summary = document.createElement("summary");
      summary.textContent = "All " + item.evidence.length + " retrieved source(s)";
      details.append(summary);

      // The same controls as a citation bubble: this list shows the same kind
      // of thing, and offering the switch in one place and not the other made
      // the formatted view look like a property of some chunks and not others.
      const evHead = document.createElement("div");
      evHead.className = "ev-controls";
      evHead.append(viewToggle());
      details.append(evHead);

      item.evidence.forEach((evidence) => {
        const block = document.createElement("div");
        block.className = "ev";
        const label = document.createElement("span");
        label.className = "src";
        label.textContent =
          (evidence.source_type === "prior_answer" ? "Previous answer" : "Guideline") +
          " — " + (evidence.locator || evidence.source_name) + " (score " + evidence.score + ")";
        const open = openDocumentButton(evidence.source_name, evidence.source_type);
        const labelRow = document.createElement("div");
        labelRow.className = "ev-head";
        labelRow.append(label, open);
        block.append(labelRow, renderChunk(evidence.snippet));
        details.append(block);
      });

      content.append(details);
    }

    card.append(head, content);
    return card;
  }

  function statCard(value, label, tone) {
    const stat = document.createElement("div");
    stat.className = "stat" + (tone ? " " + tone : "");
    const number = document.createElement("span");
    number.className = "value";
    number.textContent = value;
    const caption = document.createElement("span");
    caption.className = "label";
    caption.textContent = label;
    stat.append(number, caption);
    return stat;
  }

  function cells(line) {
    let row = line.trim();
    if (row.startsWith("|")) row = row.slice(1);
    if (row.endsWith("|")) row = row.slice(0, -1);
    return row.split("|").map((cell) => cell.trim());
  }

  function isSeparatorRow(line) {
    return /^\|?[\s:|-]+\|?$/.test(line.trim()) && line.indexOf("-") >= 0;
  }

  function showChunk(panel, item, citation) {
    const source = (item.evidence || []).find((e) => (e.locator || e.source_name) === citation);
    panel.innerHTML = "";
    panel.hidden = false;

    const head = document.createElement("div");
    head.className = "cite-head";

    const who = document.createElement("span");
    who.className = "who";
    who.textContent = citation;
    head.append(who);

    head.append(viewToggle());

    if (source) {
      const kind = document.createElement("span");
      kind.className = "tag " + source.source_type;
      kind.textContent = source.source_type === "prior_answer" ? "previous answer" : "guideline";
      head.prepend(kind);

      if (typeof source.score === "number") {
        const score = document.createElement("span");
        score.textContent = "relevance " + source.score.toFixed(2);
        head.append(score);
      }

      const open = document.createElement("button");
      open.className = "quiet";
      open.textContent = "open document";
      open.onclick = () => Cards.onOpenDocument({
        name: source.source_name,
        title: source.source_name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " "),
        origin: "uploaded",
        category: "uploaded",
        label: source.source_type === "prior_answer" ? "Uploaded completed assessment" : "Uploaded guideline",
        extension: source.source_name.split(".").pop().toLowerCase(),
        size_bytes: 0,
      });
      head.append(open);
    }

    const body = renderChunk(source
      ? source.snippet
      : "This clause was named in the answer, but the chunk behind it is not in the exported evidence.");

    panel.append(head, body);
  }

  // What the pages use. Everything else above is private to the card.
  Object.assign(Cards, {
    render: renderAnswer,
    stat: statCard,
    chunk: renderChunk,
    isArabic: isArabic,
    viewToggle: viewToggle,
    openDocumentButton: openDocumentButton,
    markdown: renderMarkdown,
    view: chunkView,
    setView: setChunkView,
  });
})();
