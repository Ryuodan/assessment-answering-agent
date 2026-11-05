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
     Cards.onEdit(item, index, text, which)      an answer is being edited, per keystroke
     Cards.onEditDone(item, index, text, which)  the editor was left: worth storing
                                          (`which`: "answer" or "brief", what the card shows)
     Cards.onBlank(item, index, blank)    leave this answer deliberately empty
     Cards.onApprove(item, index, ok)     accept it as it stands: fill writes it, memory keeps it
     Cards.onLength(item, index, prefer)  write this one answer full or brief
     Cards.onRestoreDraft(item, index)    put back the answer as it was drafted
     Cards.onSetAside(item, index, skip)  leave the question out of the file, or bring it back
     Cards.canSetAside                    whether the page offers that on the card
     Cards.readOnly                       the answers are to read, not change: a deleted
                                          product's (plan 027), so no control that changes one

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
  onApprove() {},
  onLength() {},
  onRestoreDraft() {},
  onSetAside() {},
  canSetAside: false,
  readOnly: false,
  /* Which text the card shows, and so edits: `{ text, which }`, `which` being
     "brief" only when the brief is what is shown, else "answer". The card shows
     and writes through this rather than owning it, because the workbench holds
     a whole run in memory and the chat page holds a batch. The editor opened
     on the full answer under a brief card, and saved it as the brief (plan 029). */
  shownAnswer(item) { return { text: item.answer || "", which: "answer" }; },
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

  /* Full or Brief, for one questionnaire.

     Switching to Brief condenses every answer that has not been condensed yet,
     which costs a model call each and is worth saying out loud rather than
     leaving the button dead for a minute. Switching back is instant: the full
     answer was never replaced. */
  /* A batch question, as the card wants it.

     `inspect` returns the answer nested inside the question, with the facts a
     card needs to draw its state sitting beside it rather than on it. Copying
     those across by hand is what three call sites each did differently. */
  function fromQuestion(question, extra) {
    if (!question || !question.answered) return null;
    return Object.assign({}, question.answered, {
      blanked: question.blanked,
      brief: question.brief,
      approved: question.approved,
      remembered: question.remembered,
      by_hand: question.by_hand,
      will_be_written: question.will_be_written,
      held_back_because: question.held_back_because,
      edited_by: question.edited_by,  // a person's edit: the Workbench's "Done by a person" (plan 029)
      set_aside: question.skip,
      prefer: question.prefer,
      // What the server resolved this answer's length to: its own preference if
      // it has one, otherwise the questionnaire's. Left off, the pages fell
      // back to the file's default and the per-answer choice did nothing.
      length: question.length,
    }, extra || {});
  }

  /* What withdrawing an approval did, from the question as the server now has
     it. Three different outcomes, and "it will be held back again" was said of
     all of them -- including an answer a person wrote, which still goes in. */
  function withdrawnMessage(question) {
    if (question && question.will_be_written) {
      return question.by_hand
        ? "Approval withdrawn. A person wrote this answer, so it still goes into the file; it is out of the answer memory."
        : "Approval withdrawn. It is confident enough to go into the file without a person looking.";
    }
    return "Approval withdrawn. It will be held back until somebody edits or approves it.";
  }

  function detailPicker(current, onPick) {
    const wrap = document.createElement("div");
    wrap.className = "detail-pick";
    const label = document.createElement("span");
    label.textContent = "Answers:";
    const seg = document.createElement("div");
    seg.className = "seg";

    const buttons = [["full", "Full"], ["brief", "Brief"]].map(([value, text]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = text;
      button.setAttribute("aria-pressed", String((current || "full") === value));
      button.title = value === "brief"
        ? "One sentence each, condensed from the full answer"
        : "The full answer, with its supporting detail";
      button.onclick = async () => {
        if (button.getAttribute("aria-pressed") === "true") return;
        buttons.forEach((b) => { b.disabled = true; });
        if (value === "brief") button.textContent = "Shortening…";
        try {
          await onPick(value);
        } finally {
          button.textContent = text;
          buttons.forEach((b) => { b.disabled = false; });
        }
      };
      seg.append(button);
      return button;
    });

    wrap.append(label, seg);
    return wrap;
  }

  /* One of the person's saved skills, over the answers on screen. Nothing at
     all for someone who has saved none: an empty menu is a control that offers
     to do nothing, and the link to create one lives on the preferences page. */
  function skillPicker(skills, onApply) {
    const wrap = document.createElement("div");
    wrap.className = "skill-pick";
    if (!skills || !skills.length) {
      wrap.hidden = true;
      return wrap;
    }
    const label = document.createElement("span");
    label.textContent = "Skills:";
    const select = document.createElement("select");
    select.setAttribute("aria-label", "Choose one of your skills");
    select.append(new Option("Choose a skill…", ""));
    // Two groups, because they are two different promises: the built-in ones
    // are the same for everybody, and "Yours" are nobody else's.
    [["Built in", skills.filter((s) => s.builtin)], ["Yours", skills.filter((s) => !s.builtin)]]
      .forEach(([label, group]) => {
        if (!group.length) return;
        const holder = document.createElement("optgroup");
        holder.label = label;
        group.forEach((skill) => {
          const option = new Option(skill.name, skill.skill_id);
          if (skill.description) option.title = skill.description;
          holder.append(option);
        });
        select.append(holder);
      });
    const apply = document.createElement("button");
    apply.type = "button";
    apply.className = "ghost";
    apply.dataset.mutates = "true";
    apply.textContent = "Reword with it";
    apply.title = "Rewords the answers shown here. Answers somebody wrote by hand are left as they are.";
    apply.onclick = async () => {
      if (!select.value) { select.focus(); return; }
      const name = select.options[select.selectedIndex].text;
      apply.disabled = true;
      select.disabled = true;
      try {
        await onApply(select.value, name);
      } finally {
        apply.disabled = false;
        select.disabled = false;
      }
    };
    const manage = document.createElement("a");
    manage.href = "preferences";
    manage.textContent = "Manage";
    wrap.append(label, select, apply, manage);
    return wrap;
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

  /* A chunk is only checkable if you can open the file it came from — and some
     of them have no file. The document viewer serves PDFs and Word documents
     out of the upload directory, which is what a policy is; a remembered answer
     is a row in the answer memory, and a questionnaire it was extracted from is
     a spreadsheet the viewer does not serve. Both used to get a button that
     opened an error. */
  const OPENABLE = /\.(pdf|docx)$/i;

  function canOpenDocument(sourceName) {
    return OPENABLE.test(sourceName || "");
  }

  function openDocumentButton(sourceName, sourceType) {
    if (!canOpenDocument(sourceName)) return null;
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

  let refusedNotes = 0;  // each editor's refusal note has an id of its own, for aria-describedby

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
      const text = Cards.shownAnswer(item, index).text;
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

    /* Held back, and why. `will_be_written` is absent on an answer that never
       came through `inspect` -- a loose question answered in the workbench, an
       imported run -- and absent must not read as "held", or every card on
       those pages would grow a warning about a file it will never be written
       into. */
    const gated = !item.set_aside && item.will_be_written === false && !item.blanked && item.answer;
    if (item.set_aside) {
      /* Said on the card, with the way back beside it. Setting a question aside
         used to change nothing anyone could see beside the assistant: the card
         stayed exactly as it was, so "leave that one out" looked ignored. */
      const aside = document.createElement("div");
      aside.className = "held aside";
      const what = document.createElement("strong");
      what.textContent = "Set aside.";
      const why = document.createElement("span");
      why.textContent = " Nothing is written to the file for this question, whatever its answer says.";
      aside.append(what, why);
      if (Cards.canSetAside && !Cards.readOnly) {
        const back = document.createElement("button");
        back.className = "quiet";
        back.dataset.mutates = "true";
        back.textContent = "Include it again";
        back.onclick = () => Cards.onSetAside(item, index, false);
        aside.append(back);
      }
      field.append(aside);
    } else if (gated) {
      const held = document.createElement("div");
      held.className = "held";
      const what = document.createElement("strong");
      what.textContent = "Not going into the file yet.";
      const why = document.createElement("span");
      why.textContent = item.held_back_because
        ? " " + item.held_back_because[0].toUpperCase() + item.held_back_because.slice(1) + "."
        : " Nobody has confirmed this answer.";
      held.append(what, why);
      if (!Cards.readOnly) {
        const how = document.createElement("span");
        how.className = "how";
        how.textContent = "Edit it, or approve it as it stands.";
        held.append(how);
      }
      field.append(held);
    }

    /* Read-only: a deleted product's answers (plan 027). What they say, and
       whether they were approved, is shown; nothing that would change one is. */
    if (Cards.readOnly) {
      if (item.approved) {
        const approved = document.createElement("span");
        approved.className = "tag";
        approved.textContent = "approved";
        field.querySelector(".field-label").append(approved);
      }
      toggle.hidden = true;
      editor.readOnly = true;
    }

    /* Full or brief, for this one answer. The questionnaire-level control is
       the bulk action -- 183 rows, make them short -- and it is the wrong unit
       for the answer somebody actually cares about, which is usually the one
       the assessor will read closely.

       On every answer of a questionnaire, whether or not a brief form exists
       yet. It used to appear only once one did, which meant only after the
       whole file had been switched to Brief at least once: the per-answer
       choice was reachable only through the bulk one it exists to avoid.
       Choosing Brief here shortens this one answer on the spot. */
    if (item.length && !item.blanked && (item.answer || "").trim() && !Cards.readOnly) {
      const lengths = document.createElement("span");
      lengths.className = "len-pick";
      const buttons = [["full", "Full"], ["brief", "Brief"]].map(([value, text]) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "quiet";
        button.textContent = text;
        button.dataset.mutates = "true";
        button.setAttribute("aria-pressed", String(item.length === value));
        button.title = value === "brief"
          ? item.brief
            ? "Write this one briefly, whatever the rest of the file does"
            : "Shorten this one answer and write it briefly, whatever the rest of the file does"
          : "Write this one in full, whatever the rest of the file does";
        button.onclick = async () => {
          if (button.getAttribute("aria-pressed") === "true") return;
          buttons.forEach((b) => { b.disabled = true; });
          // Deriving a brief form is a model call; a button that sits there
          // for five seconds reads as a button that did nothing.
          if (value === "brief" && !item.brief) button.textContent = "Shortening…";
          try {
            await Cards.onLength(item, index, value);
          } finally {
            button.textContent = text;
            buttons.forEach((b) => { b.disabled = false; });
          }
        };
        lengths.append(button);
        return button;
      });
      field.querySelector(".field-label").append(lengths);
    }

    /* Approving is the other half of editing: an answer that is right as
       written should not have to be retyped to be released.

       It has a second effect on an answer somebody wrote: that one joins the
       answer memory, and is what the next questionnaire asking this question is
       answered from. A draft nobody touched does not, however sure the reviewer
       is -- remembering the model's own output would feed it back as a
       "previous answer" at a confidence the loop manufactured rather than
       earned. The title says which of the two effects apply here, because the
       difference is invisible otherwise. */
    if (!Cards.readOnly) {
      const byHand = item.by_hand || item.confidence_reason === "written by hand";
      const approve = document.createElement("button");
      approve.className = item.approved ? "quiet" : "quiet approve";
      approve.textContent = item.approved ? "Approved ✓" : "Approve";
      approve.title = item.approved
        ? byHand
          ? "You approved this answer, and it is in the answer memory. Click to withdraw both."
          : "You approved this answer. It is not in the answer memory — the memory only keeps answers a person wrote."
        : byHand
          ? "Confirm this answer, and remember your wording for next time"
          : gated
            ? "Accept this answer as it stands, so it goes into the file. It is not added to the answer memory: nobody has changed a word of it."
            : "Confirm this answer is right. It is not added to the answer memory: nobody has changed a word of it.";
      approve.dataset.mutates = "true";
      approve.onclick = () => Cards.onApprove(item, index, !item.approved);
      field.querySelector(".field-label").append(approve);

      /* The second effect, on the card rather than in a message that scrolls
         away: this wording is what the next questionnaire asking this question
         gets answered from, and there was nothing anywhere that said so once
         the click was over. */
      if (item.remembered) {
        const kept = document.createElement("span");
        kept.className = "tag memory";
        kept.textContent = "in the answer memory";
        kept.title = "Your wording is saved. The next questionnaire asking this is answered from it.";
        field.querySelector(".field-label").append(kept);
      }
    }

    /* Leaving it blank on purpose. Beside Edit because it is the same kind of
       decision -- what this question should say -- and because a control that
       empties an answer belongs next to the answer and nowhere else. */
    if (!Cards.readOnly) {
      const blank = document.createElement("button");
      blank.className = "quiet";
      blank.textContent = item.blanked ? "Write an answer" : "Leave blank";
      blank.onclick = () => Cards.onBlank(item, index, !item.blanked);
      field.querySelector(".field-label").append(blank);
    }

    /* The editor holds the text the card shows: the brief on a brief card, and
       says which back to the page, so an edit lands where it was made. */
    let shown = Cards.shownAnswer(item, index);
    /* Said to a screen reader too (plan 029's review): the text going back is
       otherwise silent. A live region in place before it speaks, empty and
       drawn at no height until then, and the editor's description. */
    const refused = document.createElement("p");
    refused.className = "held edit-refused";
    refused.id = "edit-refused-" + (++refusedNotes);
    refused.setAttribute("role", "status");
    editor.setAttribute("aria-describedby", refused.id);
    const sayRefused = (yes) => {
      refused.textContent = yes ? "A brief answer cannot be empty. To write nothing here, use Leave blank." : "";
    };

    let editing = false;
    const setMode = (next) => {
      editing = next;
      if (editing) {
        shown = Cards.shownAnswer(item, index);
        editor.value = shown.text;
        editor.dir = isArabic(shown.text) ? "rtl" : "ltr";
        sayRefused(false);
      }
      rendered.hidden = editing;
      editor.hidden = !editing;
      toggle.textContent = editing ? "Done editing" : "Edit";
      if (editing) { editor.focus(); } else { paint(); }
    };

    editor.value = shown.text;
    editor.hidden = true;
    if (isArabic(shown.text)) editor.dir = "rtl";
    editor.addEventListener("input", () => Cards.onEdit(item, index, editor.value, shown.which));
    /* `input` fires on every keystroke, which is right for keeping the page in
       step and wrong for anything that leaves the browser. `change` fires once,
       when the editor is left and the text actually differs, which is the point
       at which an edit is worth storing. Leaving by the button fires it too,
       because blur precedes the click.

       An emptied brief is not sent: saved, it released the model's full answer
       as a person's (TD-055). The brief comes back, and the card says why. */
    editor.addEventListener("change", () => {
      if (shown.which === "brief" && !editor.value.trim()) {
        editor.value = shown.text;
        Cards.onEdit(item, index, shown.text, shown.which);
        sayRefused(true);
        return;
      }
      sayRefused(false);
      Cards.onEditDone(item, index, editor.value, shown.which);
    });
    toggle.onclick = () => setMode(!editing);

    field.append(rendered, editor, refused);
    setMode(false);
    return field;
  }

  /* What removing from a knowledge base asks first (plan 029), in one wording
     for the workbench and the chat drawer. A shared document is used by every
     questionnaire and chat, General and every product, so that is said; its
     file stays. A product's takes its file with it (TD-039). */
  const SHARED_IMPACT = "Every questionnaire and chat, General and every product, stops using ";
  const PRODUCT_FILES = "cannot be recovered from here — unless the shared knowledge base, " +
    "another product or a questionnaire also uses ";

  function removalQuestion(name, productName) {
    if (productName) {
      return "Remove “" + name + "” from " + productName + "'s knowledge base?\n\n" +
        "Its file is deleted too, and " + PRODUCT_FILES + "it.";
    }
    return "Remove “" + name + "” from the shared knowledge base?\n\n" + SHARED_IMPACT +
      "it from now on. Answers already written are not changed.\n\n" +
      "Its file stays on the server; to use it again, add it again.";
  }

  function clearQuestion(count, productName) {
    const which = productName ? productName + "'s knowledge base" : "the shared knowledge base";
    const what = count === 1 ? "the 1 policy document" : count > 1 ? "all " + count + " policy documents"
      : "every policy document";
    const impact = productName
      ? "Their files are deleted too, and " + PRODUCT_FILES + "them."
      : SHARED_IMPACT + "them from now on. Answers already written are not changed.";
    return "Remove " + what + " from " + which + "?\n\n" + impact + "\n\nThe answer memory is not affected.";
  }

  /* Whose document a source is. Only drawn for external ones: "our policy" is
     the unmarked case and badging all four sources under every answer would
     make the exception invisible again. */
  function authorityBadge(authority) {
    if (authority !== "external") return null;
    const tag = document.createElement("span");
    tag.className = "tag external";
    tag.textContent = "law / external";
    tag.title = "A regulation or framework we are subject to, not a document we wrote. "
      + "It says what we are required to do, which is not evidence that we do it.";
    return tag;
  }

  /* Which product something is for (plan 024): a source from a product's own
     knowledge base, or a chat or questionnaire in a list. The page hands over
     the team's products, and those deleted since plan 027 -- whose work is
     kept, read-only, and badged as theirs, marked deleted. An id among
     neither, General, gets no badge. */
  let products = {};

  function setProducts(list, deleted) {
    products = {};
    (deleted || []).forEach((product) => { products[product.id] = Object.assign({}, product, { deleted: true }); });
    (list || []).forEach((product) => { products[product.id] = product; });
  }

  /* The product with this id, live or deleted (`deleted` is then true), or null. */
  function product(productId) {
    return (productId && products[productId]) || null;
  }

  function productBadge(productId, title) {
    const found = product(productId);
    if (!found) return null;
    const tag = document.createElement("span");
    tag.className = "tag product" + (found.deleted ? " deleted" : "");
    tag.textContent = found.deleted ? found.name + " · deleted" : found.name;
    if (found.color) tag.style.setProperty("--product", found.color);
    tag.title = found.deleted
      ? found.name + " has been deleted. What was done for it is kept to read, and its filled files " +
        "to download; it can no longer be changed."
      : title || "For " + found.name;
    return tag;
  }

  function ownSourceBadge(source) {
    return productBadge(source && source.product_id,
      "From this product's own knowledge base. The drafter was told it takes precedence over the shared one.");
  }

  /* A product choice on a page (plan 029, 2): the user's rule is no silent
     General. "" is nothing chosen yet, GENERAL is General chosen on purpose,
     anything else a product's id. The server still reads "" as General
     (TD-066), so a page sends serverProduct(choice), and a record's
     product_id comes back as a choice through choiceOf. When the server
     learns to refuse a missing product, only serverProduct changes. */
  const GENERAL = "general";  // never a product's id: those are 12 hex characters (products.add)
  const GENERAL_LABEL = "General (shared policies only)";

  function serverProduct(choice) { return choice === GENERAL ? "" : choice || ""; }
  function choiceOf(productId) { return productId || GENERAL; }

  /* General, or a live product the page has listed. A deleted product is
     never offered, and nor is one the page has not listed yet. */
  function choosable(choice) {
    if (choice === GENERAL) return true;
    const found = product(choice);
    return Boolean(found && !found.deleted);
  }

  /* The first of `choices` (most recent first) that can still be chosen, or "". */
  function lastUsed(choices) {
    return (choices || []).find((choice) => choice && choosable(choice)) || "";
  }

  /* A choice as a label: a product's badge, or General's, in the neutral colour. */
  function choiceTag(choice, title) {
    if (choice !== GENERAL) return productBadge(choice, title);
    const tag = document.createElement("span");
    tag.className = "tag product general";
    tag.textContent = "General";
    tag.title = title || "General: answered from the shared policies and answer memory only";
    return tag;
  }

  /* "Last used: <label>". One click fills the choice; nothing is chosen until
     then, because a choice carried over silently is how a questionnaire came
     to be answered for General, or for yesterday's product, by accident. */
  function lastUsedButton(choice, onPick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "last-used";
    button.dataset.choice = choice;
    const name = choice === GENERAL ? "General" : (product(choice) || {}).name || "";
    button.append("Last used: ", choiceTag(choice, "Choose " + name));
    button.title = "Choose " + name + ", the product of your most recent work. Nothing is chosen until you click.";
    button.onclick = () => onPick(choice);
    return button;
  }

  /* The source behind each citation, in the citations' order. A citation is a
     locator, and remembered answers approved on one day share one -- "Answer
     memory (2026-10-19)" -- so each is cited, and here takes the next source
     with that locator not yet taken (plan 027). Found by locator alone, every
     such chip opened the first, and a product's own answer cited after a
     shared one could not be read. Several chunks of one clause are one
     citation, which takes the first of them, as it always did. */
  function citedSources(item) {
    const taken = new Set();
    return item.citations.map((citation) => {
      const source = (item.evidence || []).find((e) => !taken.has(e) && (e.locator || e.source_name) === citation);
      if (source) taken.add(source);
      return source;
    });
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
    const sources = citedSources(item);

    item.citations.forEach((citation, position) => {
      const source = sources[position];
      const mark = authorityBadge(source && source.authority);
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
      // Before the caret, so it reads as part of the source's name rather than
      // as another control.
      if (mark) chip.append(mark);
      const own = ownSourceBadge(source);
      if (own) chip.append(own);
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
        showChunk(panel, citation, source);
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
    card.className = "answer" + (item.needs_review ? " review" : "") + (item.set_aside ? " set-aside" : "");

    // --- head: number, question, confidence
    const head = document.createElement("div");
    head.className = "answer-head";

    const number = document.createElement("div");
    number.className = "qnum";
    number.textContent = item.question.id || String(index + 1);

    const body = document.createElement("div");
    body.className = "qbody";

    /* A questionnaire item can be a paragraph: the brand-protection question in
       this corpus runs to six lines of bold text, which pushes the answer --
       the thing the card is about -- below the fold, and strands the confidence
       meter at the top of an empty column. So a long question is clamped to
       three lines with a control to see the rest.

       Whether it needs clamping is measured after layout rather than guessed
       from a character count: the same two hundred characters are two lines on
       a wide screen and five on a phone. It starts clamped so a long one never
       flashes open, and un-clamps itself when there was nothing to hide. */
    const question = document.createElement("div");
    question.className = "qtext clamped";
    question.textContent = item.question.text;
    if (isArabic(item.question.text)) question.dir = "rtl";

    const more = document.createElement("button");
    more.className = "quiet qmore";
    more.hidden = true;
    more.textContent = "show the whole question";
    more.onclick = () => {
      const clamped = question.classList.toggle("clamped");
      more.textContent = clamped ? "show the whole question" : "show less";
    };
    requestAnimationFrame(() => {
      if (question.scrollHeight > question.clientHeight + 1) more.hidden = false;
      else question.classList.remove("clamped");
    });

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
    meta.append(detail, more);
    /* Beside the question, because it is a decision about the question: leave
       it out of the file, whatever the answer says. */
    if (Cards.canSetAside && !Cards.readOnly && !item.set_aside) {
      const aside = document.createElement("button");
      aside.className = "quiet";
      aside.dataset.mutates = "true";
      aside.textContent = "Set aside";
      aside.title = "Leave this question out of the file. Its answer is kept, and it can be brought back.";
      aside.onclick = () => Cards.onSetAside(item, index, true);
      meta.append(aside);
    }

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
    if (item.__key && !Cards.readOnly) {
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

    /* Something reworded this answer after it was drafted -- preferences, a
       skill, a "make them shorter". Said on the card and undoable from it: each
       of those runs over many answers at once, so the one place an odd result
       gets noticed has to be the place it can be put right. Which one it was is
       in the reasoning below. */
    if (item.drafted && !item.blanked) {
      const field = labelledField("Reworded after drafting", "accent");
      const box = document.createElement("details");
      box.className = "drafted";
      const summary = document.createElement("summary");
      summary.textContent = "See the answer as it was drafted";
      const original = document.createElement("div");
      original.className = "rationale";
      original.textContent = item.drafted;
      if (isArabic(item.drafted)) original.dir = "rtl";
      const back = document.createElement("button");
      back.type = "button";
      back.className = "ghost";
      back.dataset.mutates = "true";
      back.textContent = "Put the draft back";
      back.title = "Replace the reworded answer with the original draft, for this question only";
      back.onclick = () => Cards.onRestoreDraft(item, index);
      box.append(summary, original);
      if (!Cards.readOnly) box.append(back);
      field.append(box);
      content.append(field);
    }

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
      if (item.__key && !Cards.readOnly) {
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
    //
    // The same field also carries what a *person* did — approved it, wrote it —
    // and those are not explanations of a score either. A hand-written answer
    // scores 100% and was arriving under a red "why the confidence is low:
    // approved by a reviewer". The button and the tag beside it already say
    // that, and say it in the right place.
    const decision = ["approved by a reviewer", "written by hand"].includes(item.confidence_reason);
    if (item.confidence_reason && !item.blanked && !decision) {
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

    /* There was a second list here, "All n retrieved source(s)". It showed
       the same sources as the bubbles above, a second time: `finalize` keeps
       only the chunks the answer cited, so an answer's evidence *is* its
       citations -- true of every one of the 1,817 answers stored when it
       was removed. Each bubble opens the clause with its relevance, the
       formatted/raw switch and the document, which is all the list had. */

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

  /* `source` is the citation's own, from `citedSources`; undefined when the
     chunk behind it was not kept. */
  function showChunk(panel, citation, source) {
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
      const own = ownSourceBadge(source);
      if (own) kind.after(own);

      if (typeof source.score === "number") {
        const score = document.createElement("span");
        score.textContent = "relevance " + source.score.toFixed(2);
        head.append(score);
      }

      const open = openDocumentButton(source.source_name, source.source_type);
      if (open) head.append(open);
    }

    const body = renderChunk(source
      ? source.snippet
      : "This clause was named in the answer, but the chunk behind it is not in the exported evidence.");

    panel.append(head, body);
  }

  // What the pages use. Everything else above is private to the card.
  Object.assign(Cards, {
    render: renderAnswer,
    withdrawnMessage: withdrawnMessage,
    stat: statCard,
    chunk: renderChunk,
    isArabic: isArabic,
    viewToggle: viewToggle,
    fromQuestion: fromQuestion,
    detailPicker: detailPicker,
    skillPicker: skillPicker,
    authorityBadge: authorityBadge,
    removalQuestion: removalQuestion,
    clearQuestion: clearQuestion,
    setProducts: setProducts,
    product: product,
    productBadge: productBadge,
    ownSourceBadge: ownSourceBadge,
    GENERAL: GENERAL,
    GENERAL_LABEL: GENERAL_LABEL,
    serverProduct: serverProduct,
    choiceOf: choiceOf,
    choosable: choosable,
    lastUsed: lastUsed,
    choiceTag: choiceTag,
    lastUsedButton: lastUsedButton,
    openDocumentButton: openDocumentButton,
    canOpenDocument: canOpenDocument,
    markdown: renderMarkdown,
    view: chunkView,
    setView: setChunkView,
  });
})();
