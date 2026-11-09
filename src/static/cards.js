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
     Cards.fileless                       a list of questions (plan 033): no file to write
                                          into, so a confident answer reads "Ready to use"
     Cards.renderReadOnly(item, index)    one card drawn that way whatever the page's setting:
                                          a question answered in the chat (plan 030)

   A page that can honour one assigns it; a page that cannot leaves it, and the
   control simply does nothing rather than throwing.

   One thing every page sets before it draws (plan 030):

     Cards.setReviewThreshold(value)      the server's review threshold, from the
                                          session the page reads on load

   A card asks one thing: is this answer right? (plan 041.) Its status and why
   in one line, the question, the answer, the sources, then the two things a
   reviewer does, Approve and Edit, after what they have read. Everything else
   is one click away: "Why this answer" holds the reasoning and the checks,
   "More" the rarer actions. Colour says one thing each (plan 042): green is
   fine, amber a person should look, red low or failed, blue the knowledge base,
   plum the answer memory. Where the server has said
   whether the fill writes an answer (`will_be_written`), the card says the
   same; elsewhere it applies the server's own rule with that threshold.

   The review's tabs are shared too (plan 037): `Cards.reviewBucket(item)` says
   which tab an answer is in, `Cards.reviewTabs(...)` draws the tabs and
   `Cards.emptyTab(...)` what an empty one says.

   A page that drives the cards from the keyboard (the Workbench, plan 033)
   finds a card's controls by `data-card-action`: "approve" and "edit", the
   latter with `data-editing` while its editor is open.

   In the interface's language (plan 038): every word the card writes goes
   through `t()`, with its Arabic in `i18n/ar-cards.js`, and the server's
   sentences it shows (the review's reasons, why an answer is held back, why
   the confidence is low) through `I18n.server`. What the card shows of the
   questionnaire and the answer -- the question, the answer, a source's text,
   name and locator, a person's address, the model's own words -- is content:
   inside `data-no-translate`, in its own direction. The helpers a page calls
   with words (`stat`, a badge's title) are given them in the page's language.
   `Cards.serverInto(element, sentence)` puts a server's sentence into a
   page's own element the same way.
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
  fileless: false,  // a list of questions (plan 033): no file, so a confident answer is "Ready to use"
  reviewThreshold: null,  // the server's, once the page has set it; never a number of the card's own
  /* Which text the card shows, and so edits: `{ text, which }`, `which` being
     "brief" only when the brief is what is shown, else "answer". The card shows
     and writes through this rather than owning it, because the workbench holds
     a whole run in memory and the chat page holds a batch. The editor opened
     on the full answer under a brief card, and saved it as the brief (plan 029). */
  shownAnswer(item) { return { text: item.answer || "", which: "answer" }; },
});

(function () {
  const t = I18n.t;

  // Where the Formatted/Raw choice is remembered, per browser.
  const VIEW_KEY = "assessment-chunk-view";

  function isArabic(text) {
    return /[؀-ۿ]/.test(text || "");
  }

  /* Content keeps its own direction in an Arabic page (plan 038): Arabic right
     to left, anything else by its own first letter, so an English answer reads
     left to right there. An English page is as it was. */
  function ownWay(node, text) {
    if (I18n.rtl) node.dir = isArabic(text) ? "rtl" : "auto";
    return node;
  }

  /* The same, for content that has always been drawn right to left when it is
     Arabic: the question, the answer, a source's text, the drafter's words. */
  function directed(node, text) {
    if (isArabic(text)) node.dir = "rtl";
    return ownWay(node, text);
  }

  /* An element holding content: the questionnaire's, the answer's, a source's.
     Never translated, and in its own direction in an Arabic page. */
  function asContent(tag, text) {
    const node = document.createElement(tag);
    node.setAttribute("data-no-translate", "");
    node.textContent = text;
    return ownWay(node, text);
  }

  /* A sentence the server wrote, into `element` in the page's language
     (`I18n.server`); `shape` dresses it (a capital, a full stop). In Arabic,
     what the sentence carries from the case itself -- clause numbers, the
     drafter's or the reviewer's own words, left as they came -- is content: a
     run of Latin text in the Arabic sentence gets an element of its own. A
     sentence with no Arabic is shown as it came, for the catalog to catch. */
  const CARRIED = /[A-Za-z][^؀-ۿ\n]*?(?=[\s.,;:!?)\]"'»]*(?:[؀-ۿ\n]|$))/g;

  function serverInto(element, english, shape) {
    const text = I18n.server(english);
    const shown = shape ? shape(text) : text;
    if (!I18n.rtl || text === english) {
      element.append(shown);
      return element;
    }
    let at = 0;
    for (const found of shown.matchAll(CARRIED)) {
      element.append(shown.slice(at, found.index), asContent("span", found[0]));
      at = found.index + found[0].length;
    }
    element.append(shown.slice(at));
    return element;
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
      node.replaceWith(renderChunk(node.getAttribute("data-chunk-source"), view, node.hasAttribute("data-chunk-ours")));
    });
  }

  function words(text) {
    return (text || "").match(/[\p{L}\p{N}]+/gu) || [];
  }

  function flatText(node) {
    const parts = [];
    const walk = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    while (walk.nextNode()) {
      // A figure stands for the source's "<!-- image -->", in whichever language it is named.
      const figure = walk.currentNode.parentElement && walk.currentNode.parentElement.closest(".figure");
      parts.push(figure ? "image" : walk.currentNode.nodeValue);
    }
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
        directed(cell, value);
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
        directed(element, rest);
        box.append(element);
        index += 1;
        continue;
      }

      if (/^<!--\s*image\s*-->$/.test(trimmed)) {
        list = null;
        const figure = document.createElement("div");
        figure.className = "figure";
        figure.textContent = t("image");
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
        directed(item, bullet[1]);
        list.append(item);
        index += 1;
        continue;
      }

      list = null;
      const paragraph = document.createElement("p");
      paragraph.textContent = trimmed;
      directed(paragraph, trimmed);
      box.append(paragraph);
      index += 1;
    }

    return box;
  }

  function buildRaw(text) {
    const pre = document.createElement("pre");
    pre.className = "snippet";
    pre.textContent = text;
    directed(pre, text);
    return pre;
  }

  /* A source's text, formatted or raw. It is content (plan 038): never
     translated, and in its own direction, a table's columns too. `ours` is a
     sentence of the card's own drawn the same way, in the page's language. */
  function renderChunk(text, view, ours) {
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
    if (ours) {
      node.setAttribute("data-chunk-ours", "");
    } else {
      node.setAttribute("data-no-translate", "");
      if (I18n.rtl) node.dir = isArabic(source) ? "rtl" : "ltr";
    }
    return node;
  }

  /* The review's tabs: which answers to show, by what the fill does with each
     (plan 029, 1.3). One set for the Workbench and the chat's answers panel
     (plan 037), so the same answer is in the same tab on both pages. */
  const REVIEW_TABS = ["review", "written", "person", "blank", "all"];

  /* A tab's name with its count, and what it holds. One literal string each,
     for the catalogs. A list has no file to write into: its confident answers
     are ready to use (plan 033). */
  function tabName(key, n) {
    if (key === "review") return t("Needs review ({n})", { n });
    if (key === "written") return Cards.fileless ? t("Ready to use ({n})", { n }) : t("Will be written ({n})", { n });
    if (key === "person") return t("Done by a person ({n})", { n });
    if (key === "blank") return t("Blank or set aside ({n})", { n });
    return t("All ({n})", { n });
  }

  function tabAbout(key) {
    if (key === "review") return t("Held back until a person edits or approves them, and the ones that failed");
    if (key === "written") {
      return Cards.fileless
        ? t("Confident answers nobody has checked: ready to use as drafted")
        : t("Confident answers nobody has checked: they go into the file as drafted");
    }
    if (key === "person") return t("Approved, edited or written by a person");
    if (key === "blank") return t("Left blank on purpose, and rows set aside: nothing goes in for them");
    return t("Every answer, in the file's order");
  }

  /* An answer's tab, from the card's own facts. */
  function reviewBucket(item) {
    if (item.set_aside || item.blanked) return "blank";
    // Typed beside the file: never written, so in a tab only when it needs a person.
    if (item.will_be_written === undefined) return item.error || item.needs_review ? "review" : null;
    if (item.error || !item.will_be_written) return "review";
    return item.approved || item.by_hand || item.edited_by ? "person" : "written";
  }

  /* The tabs, drawn into `tabs` with each one's count from `counted`, the one
     shown pressed. Drawn again with each count, so the keyboard's place goes
     with it: on the tab chosen (`keepFocus` for a page that rebuilt them, which
     cannot tell). Left alone, it dropped to the page and the next Tab began
     again at the first tab (plan 029's review). */
  function reviewTabs(tabs, counted, tab, onPick, keepFocus) {
    const hadFocus = keepFocus || tabs.contains(document.activeElement);
    tabs.replaceChildren();
    REVIEW_TABS.forEach((key) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = tabName(key, counted[key] || 0);
      button.title = tabAbout(key);
      button.dataset.tab = key;
      button.dataset.empty = String(!counted[key]);  // drawn quieter: nothing to go and look at (plan 041)
      button.setAttribute("aria-pressed", String(key === tab));
      button.onclick = () => onPick(key);
      tabs.append(button);
    });
    if (hadFocus) {
      const chosen = tabs.querySelector('[data-tab="' + tab + '"]');
      if (chosen) chosen.focus({ preventScroll: true });
    }
  }

  /* What an empty tab says: where the answers are instead. */
  function emptyTab(tab, counted) {
    const n = (counted.written || 0) + (counted.person || 0);
    const review = counted.review || 0;
    if (tab === "review") {
      return Cards.fileless
        ? t("Nothing needs review. {n} answer(s) ready to use.", { n })
        : t("Nothing needs review. {n} answer(s) will be written.", { n });
    }
    return Cards.fileless
      ? t("No answers here. {review} need review, {n} ready to use.", { review, n })
      : t("No answers here. {review} need review, {n} will be written.", { review, n });
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
        ? t("Approval withdrawn. A person wrote this answer, so it still goes into the file; it is out of the answer memory.")
        : t("Approval withdrawn. It is confident enough to go into the file without a person looking.");
    }
    return t("Approval withdrawn. It will be held back until somebody edits or approves it.");
  }

  function detailPicker(current, onPick) {
    const wrap = document.createElement("div");
    wrap.className = "detail-pick";
    const label = document.createElement("span");
    label.textContent = t("Answers:");
    const seg = document.createElement("div");
    seg.className = "seg";

    const buttons = [["full", t("Full")], ["brief", t("Brief")]].map(([value, text]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = text;
      button.setAttribute("aria-pressed", String((current || "full") === value));
      button.title = value === "brief"
        ? t("One sentence each, condensed from the full answer")
        : t("The full answer, with its supporting detail");
      button.onclick = async () => {
        if (button.getAttribute("aria-pressed") === "true") return;
        buttons.forEach((b) => { b.disabled = true; });
        if (value === "brief") button.textContent = t("Shortening…");
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
    label.textContent = t("Skills:");
    const select = document.createElement("select");
    select.setAttribute("aria-label", t("Choose one of your skills"));
    select.append(new Option(t("Choose a skill…"), ""));
    // Two groups, because they are two different promises: the built-in ones
    // are the same for everybody, and "Yours" are nobody else's.
    [[t("Built in"), skills.filter((s) => s.builtin)], [t("Yours"), skills.filter((s) => !s.builtin)]]
      .forEach(([label, group]) => {
        if (!group.length) return;
        const holder = document.createElement("optgroup");
        holder.label = label;
        group.forEach((skill) => {
          /* A built-in skill's name and description are the server's, in the
             page's language; a person's own are theirs (plan 038). */
          const name = skill.builtin ? I18n.server(skill.name) : skill.name;
          const option = new Option(name, skill.skill_id);
          if (!skill.builtin) ownWay(option, name).setAttribute("data-no-translate", "");
          if (skill.description) option.title = skill.builtin ? I18n.server(skill.description) : skill.description;
          holder.append(option);
        });
        select.append(holder);
      });
    const apply = document.createElement("button");
    apply.type = "button";
    apply.className = "ghost";
    apply.dataset.mutates = "true";
    apply.textContent = t("Reword with it");
    apply.title = t("Rewords the answers shown here. Answers somebody wrote by hand are left as they are.");
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
    manage.textContent = t("Manage");
    wrap.append(label, select, apply, manage);
    return wrap;
  }

  function viewToggle() {
    const box = document.createElement("div");
    box.className = "view-toggle";
    box.setAttribute("role", "group");
    box.setAttribute("aria-label", t("How to show the text"));
    [["pretty", t("Formatted")], ["raw", t("Raw")]].forEach(([mode, label]) => {
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
    button.textContent = t("open document");
    button.onclick = () => Cards.onOpenDocument({
      name: sourceName,
      title: sourceName.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " "),
      origin: "uploaded",
      category: "uploaded",
      label: sourceType === "prior_answer" ? t("Uploaded completed assessment") : t("Uploaded guideline"),
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

  /* --- the status a card leads with (plan 030) ----------------------------

     The card coloured its score by band, with 0.6 written in here, so an
     answer the gate held could read "High confidence 90%" beside "needs
     review". It now says first what happens to the answer, and why, and the
     score follows. The threshold is the server's (`setReviewThreshold`). */

  function setReviewThreshold(value) {
    Cards.reviewThreshold = typeof value === "number" && Number.isFinite(value) ? value : null;
  }

  /* The server's one rule (`verification.held_by_score`): at or under the threshold is held. */
  function heldByScore(confidence) {
    const threshold = Cards.reviewThreshold;
    return typeof threshold === "number" && (confidence || 0) <= threshold;
  }

  /* Each check's reason, as `review_reasons` words it (`verification.py`), as a
     short chip. Matched on the words that say which check it was, so answers
     stored under earlier wordings read the same. */
  const REASON_CHIPS = [
    [/not consistent|disagree/i, "disagree"],
    [/not find the answer grounded|not grounded/i, "ungrounded"],
    [/rests only on what we told/i, "memory"],
    [/part of a split source/i, "partial"],
    [/cites clauses not covered|not covered by its sources/i, "clauses"],
  ];

  function chipName(check) {
    if (check === "disagree") return t("Sources disagree");
    if (check === "ungrounded") return t("Not backed by our documents");
    if (check === "memory") return t("Only from previous answers");
    if (check === "partial") return t("Partial source");
    if (check === "clauses") return t("Cites clauses not in its sources");
    return check === "low" ? t("Low confidence") : t("Flagged");
  }

  function reasonChips(item) {
    const chips = [];
    (item.review_reasons || []).forEach((reason) => {
      const known = REASON_CHIPS.find(([pattern]) => pattern.test(reason));
      const check = known ? known[1] : "flagged";
      const same = chips.find((chip) => chip.check === check);
      if (same) same.why.push(reason); else chips.push({ check, label: chipName(check), why: [reason] });
    });
    // No check spoke: held for the score itself, unless it is above the line,
    // which only an answer flagged by hand before the checks had reasons is.
    if (!chips.length) {
      const above = typeof Cards.reviewThreshold === "number" && !heldByScore(item.confidence);
      const check = above ? "flagged" : "low";
      chips.push({ check, label: chipName(check), why: [item.held_back_because || ""] });
    }
    return chips;
  }

  function byAPerson(item) {
    return Boolean(item.approved || item.by_hand || item.edited_by)
      || ["approved by a reviewer", "written by hand"].includes(item.confidence_reason);
  }

  /* `will_be_written` is the fill gate's own verdict, from `inspect`; an answer
     that never came through it -- one typed on the Workbench, one in the chat
     -- is judged by the same rule here, and goes into no file. */
  function statusOf(item) {
    if (item.blanked) return { key: "blank", word: t("Left blank") };
    if (item.set_aside) return { key: "aside", word: t("Set aside") };
    if (item.error) return { key: "failed", word: t("Could not be answered") };
    if (byAPerson(item)) return { key: "person", word: t("Done by a person") };
    const judged = item.will_be_written !== undefined;
    const held = judged ? !item.will_be_written : Boolean(item.needs_review) || heldByScore(item.confidence);
    if (held) return { key: "review", word: t("Needs review"), chips: reasonChips(item) };
    // A list's answers go into no file either (plan 033): judged by the gate, and ready to use.
    return { key: "ready", word: judged && !Cards.fileless ? t("Will be written") : t("Ready to use") };
  }

  /* The score's colour (plan 042), from the server's threshold and never a
     number of the card's own: red at or under it, green in the top half of what
     is above it, amber between. A check that held the answer caps it at amber:
     green beside "Needs review" is the contradiction plan 030 took away. What a
     person decided is theirs, so the draft's score goes uncoloured. */
  function confidenceTone(item, status) {
    const threshold = Cards.reviewThreshold;
    if (typeof threshold !== "number" || !["review", "ready"].includes(status.key)) return "plain";
    if (heldByScore(item.confidence)) return "low";
    if (status.key === "review") return "mid";
    return item.confidence >= threshold + (1 - threshold) / 2 ? "high" : "mid";
  }

  /* The card's first line: what happens to the answer, why, and how sure. */
  function statusBar(item, status) {
    const bar = document.createElement("div");
    bar.className = "answer-status " + status.key;
    const word = document.createElement("strong");
    word.className = "status-word";
    word.textContent = status.word;
    bar.append(word);
    (status.chips || []).forEach((chip) => {
      const tag = document.createElement("span");
      tag.className = "reason-chip";
      tag.textContent = chip.label;
      // The server's sentences, each in the page's language.
      const why = chip.why.filter(Boolean).map((reason) => I18n.server(reason)).join("\n");
      if (why) tag.title = why;
      bar.append(tag);
    });
    /* Facts that stay with an answer, after the file's own status. Each said
       once, here, rather than in a row of its own. */
    const fact = (className, words, about) => {
      const tag = document.createElement("span");
      tag.className = "tag " + className;
      tag.textContent = words;
      if (about) tag.title = about;
      bar.append(tag);
    };
    if (Cards.readOnly && item.approved) fact("", t("approved"));
    if (item.drafted && !item.blanked) {
      fact("reworded", t("card|Reworded"), t("Changed after it was drafted. The draft, and the way to put it back, are under Why this answer."));
    }
    if (item.remembered && !Cards.readOnly) {
      fact("memory", t("in the answer memory"), t("Your wording is saved. The next questionnaire asking this is answered from it."));
    }
    // Nothing was drafted for a blank or a failure, so there is no score to show.
    if (status.key !== "blank" && status.key !== "failed") {
      const score = document.createElement("span");
      score.className = "status-score " + confidenceTone(item, status);
      score.textContent = t("{n}% confidence", { n: Math.round((item.confidence || 0) * 100) });
      score.title = t("How well the models found the sources support the answer. Whether it goes in is the status.");
      bar.append(score);
    }
    return bar;
  }

  /* A card's button. Not the page's own `button`, which is the page's main action. */
  function cardButton(words, kind) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "card-btn" + (kind ? " " + kind : "");
    button.textContent = words;
    return button;
  }

  let refusedNotes = 0;  // each editor's refusal note has an id of its own, for aria-describedby

  /* The answer itself, and the editor that takes its place. Returns the two
     parts a card lays out: the text, and the button that opens the editor. */
  function answerField(item, index) {
    const field = document.createElement("div");
    field.className = "field answer-text";
    const rendered = document.createElement("div");
    rendered.className = "rendered";
    const editor = document.createElement("textarea");
    const edit = cardButton("");
    edit.dataset.cardAction = "edit";  // what a page's keys press (plan 033)

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
        note.textContent = t("This answer will be left blank.");
        rendered.append(note);
      } else if (!text.trim()) {
        const empty = document.createElement("p");
        empty.className = "empty";
        empty.textContent = t("No answer was produced — see the note below.");
        rendered.append(empty);
      } else {
        renderMarkdown(text).forEach((node) => rendered.append(node));
      }
      /* The answer is content, in its own direction (plan 038); the card's own
         note in its place is in the page's. */
      const answered = Boolean(!item.blanked && text.trim());
      rendered.toggleAttribute("data-no-translate", answered);
      rendered.classList.toggle("no-answer", !answered);  // a note in its place is not set apart as an answer
      rendered.dir = !answered && I18n.rtl ? "rtl" : isArabic(text) ? "rtl" : "ltr";
    };

    if (Cards.readOnly) editor.readOnly = true;

    /* The editor holds the text the card shows: the brief on a brief card, and
       says which back to the page, so an edit lands where it was made. */
    let shown = Cards.shownAnswer(item, index);
    /* Said to a screen reader too (plan 029's review): the text going back is
       otherwise silent. A live region in place before it speaks, empty and
       drawn at no height until then, and the editor's description. */
    const refused = document.createElement("p");
    refused.className = "edit-refused";
    refused.id = "edit-refused-" + (++refusedNotes);
    refused.setAttribute("role", "status");
    editor.setAttribute("aria-describedby", refused.id);
    const sayRefused = (yes) => {
      refused.textContent = yes ? t("A brief answer cannot be empty. To write nothing here, use Leave blank.") : "";
    };

    let editing = false;
    const setMode = (next) => {
      editing = next;
      if (editing) {
        shown = Cards.shownAnswer(item, index);
        editor.value = shown.text;
        // Nothing written yet, in an Arabic page: whichever way the person starts typing (plan 038).
        editor.dir = isArabic(shown.text) ? "rtl" : I18n.rtl && !shown.text.trim() ? "auto" : "ltr";
        sayRefused(false);
      }
      rendered.hidden = editing;
      editor.hidden = !editing;
      edit.textContent = editing ? t("Done editing") : t("Edit");
      edit.dataset.editing = String(editing);
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
    edit.onclick = () => setMode(!editing);

    field.append(rendered, editor, refused);
    setMode(false);
    return { field, edit };
  }

  /* Full or brief, for this one answer. The questionnaire-level control is
     the bulk action -- 183 rows, make them short -- and it is the wrong unit
     for the answer somebody actually cares about, which is usually the one
     the assessor will read closely.

     On every answer of a questionnaire, whether or not a brief form exists
     yet: choosing Brief here shortens this one answer on the spot. */
  function lengthPicker(item, index, closeMenu) {
    const row = document.createElement("div");
    row.className = "card-menu-row";
    const label = document.createElement("span");
    label.textContent = t("This answer:");
    const lengths = document.createElement("span");
    lengths.className = "len-pick";
    const buttons = [["full", t("Full")], ["brief", t("Brief")]].map(([value, words]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "quiet";
      button.textContent = words;
      button.dataset.mutates = "true";
      button.setAttribute("aria-pressed", String(item.length === value));
      button.title = value === "brief"
        ? item.brief
          ? t("Write this one briefly, whatever the rest of the file does")
          : t("Shorten this one answer and write it briefly, whatever the rest of the file does")
        : t("Write this one in full, whatever the rest of the file does");
      button.onclick = async () => {
        if (button.getAttribute("aria-pressed") === "true") return;
        buttons.forEach((b) => { b.disabled = true; });
        // Deriving a brief form is a model call; a button that sits there
        // for five seconds reads as a button that did nothing.
        if (value === "brief" && !item.brief) button.textContent = t("Shortening…");
        try {
          await Cards.onLength(item, index, value);
        } finally {
          button.textContent = words;
          buttons.forEach((b) => { b.disabled = false; });
          closeMenu();
        }
      };
      lengths.append(button);
      return button;
    });
    row.append(label, lengths);
    return row;
  }

  /* The rarer actions, out of the way until asked for: how long this one is,
     leaving it blank, leaving it out, removing it. Null when there are none. */
  function moreMenu(item, index) {
    const menu = document.createElement("div");
    menu.className = "card-menu";
    const more = document.createElement("details");
    more.className = "card-more";
    const summary = document.createElement("summary");
    summary.textContent = t("More");
    const close = () => { more.open = false; };
    const add = (words, about, act, kind) => {
      const button = cardButton(words, "menu-item" + (kind ? " " + kind : ""));
      if (about) button.title = about;
      button.dataset.mutates = "true";
      button.addEventListener("click", () => { close(); act(); });
      menu.append(button);
      return button;
    };

    if (item.length && !item.blanked && !item.set_aside && (item.answer || "").trim()) {
      menu.append(lengthPicker(item, index, close));
    }
    if (!item.blanked && !item.set_aside) {
      const blank = add(t("Leave blank"), "", () => Cards.onBlank(item, index, true));
      delete blank.dataset.mutates;  // as it always was: it never waited for a run
    }
    if (Cards.canSetAside && !item.set_aside) {
      add(t("action|Set aside"), t("Leave this question out of the file. Its answer is kept, and it can be brought back."),
        () => Cards.onSetAside(item, index, true));
    }
    // Only for answers this session produced: an imported result has no question row to keep in step.
    if (item.__key) {
      add(t("Remove this question and its answer"), "", () => Cards.onDiscard(item.__key), "danger qdelete");
    }
    if (!menu.childElementCount) return null;
    more.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || !more.open) return;
      event.stopPropagation();
      close();
      summary.focus();
    });
    more.append(summary, menu);
    return more;
  }

  // A menu open on one card closes when the person goes elsewhere.
  document.addEventListener("click", (event) => {
    document.querySelectorAll("details.card-more[open]").forEach((more) => {
      if (!more.contains(event.target)) more.open = false;
    });
  });

  /* What the card's reviewer can do, after what they have read: Approve and
     Edit, or whichever single action this state leaves. */
  function cardActions(item, index, edit, why) {
    const row = document.createElement("div");
    row.className = "card-actions";
    const controls = document.createElement("span");
    controls.className = "card-controls";
    row.append(controls);

    if (!Cards.readOnly) {
      const answered = Boolean((item.answer || "").trim());
      const held = !item.set_aside && item.will_be_written === false && !item.blanked && answered;
      const hint = (words) => {
        const note = document.createElement("span");
        note.className = "card-hint";
        note.textContent = words;
        row.append(note);
      };

      if (item.set_aside) {
        /* Said on the card, with the way back beside it. Setting a question aside
           used to change nothing anyone could see beside the assistant. */
        if (Cards.canSetAside) {
          const back = cardButton(t("Include it again"), "primary-plain");
          back.dataset.mutates = "true";
          back.onclick = () => Cards.onSetAside(item, index, false);
          controls.append(back);
        }
        hint(t("Nothing is written to the file for this question, whatever its answer says."));
      } else if (item.blanked) {
        const write = cardButton(t("Write an answer"), "primary-plain");
        write.onclick = () => Cards.onBlank(item, index, false);
        controls.append(write);
      } else {
        if (item.error && item.__key) {
          /* A question that never produced an answer has nothing to judge. A
             rate limit or a withdrawn model is transient: offer another go. */
          const again = cardButton(t("Try this question again"), "primary-plain");
          again.dataset.mutates = "true";
          again.onclick = () => Cards.onRetry([item.__key], again);
          controls.append(again);
        }
        /* Approving is the other half of editing: an answer that is right as
           written should not have to be retyped to be released.

           It has a second effect on an answer somebody wrote: that one joins the
           answer memory, and is what the next questionnaire asking this question is
           answered from. A draft nobody touched does not, however sure the reviewer
           is -- remembering the model's own output would feed it back as a
           "previous answer" at a confidence the loop manufactured rather than
           earned. The title says which of the two effects apply here, because the
           difference is invisible otherwise. Nothing to approve, no button: the
           server refuses an empty answer. */
        if (answered) {
          const byHand = item.by_hand || item.confidence_reason === "written by hand";
          const approve = cardButton(item.approved ? t("Approved ✓") : t("Approve"),
            item.approved ? "approved" : held ? "primary" : "");
          approve.title = item.approved
            ? byHand
              ? t("You approved this answer, and it is in the answer memory. Click to withdraw both.")
              : t("You approved this answer. It is not in the answer memory — the memory only keeps answers a person wrote.")
            : byHand
              ? t("Confirm this answer, and remember your wording for next time")
              : held
                ? Cards.fileless
                  ? t("Accept this answer as it stands. It is not added to the answer memory: nobody has changed a word of it.")
                  : t("Accept this answer as it stands, so it goes into the file. It is not added to the answer memory: nobody has changed a word of it.")
                : t("Confirm this answer is right. It is not added to the answer memory: nobody has changed a word of it.");
          approve.dataset.mutates = "true";
          approve.dataset.cardAction = "approve";  // what a page's A key presses (plan 033)
          approve.onclick = () => Cards.onApprove(item, index, !item.approved);
          controls.append(approve);
        }
        controls.append(edit);
        // What the two buttons are for, once, beside them.
        if (held) hint(Cards.fileless ? t("Not confirmed yet.") : t("Not going into the file yet."));
      }
    }

    const side = document.createElement("span");
    side.className = "card-side";
    if (why) side.append(why.toggle);
    const more = Cards.readOnly ? null : moreMenu(item, index);
    if (more) side.append(more);
    if (side.childElementCount) row.append(side);
    return row.childElementCount > 1 || controls.childElementCount ? row : null;
  }

  /* What removing from a knowledge base asks first (plan 029), in one wording
     for the workbench and the chat drawer. A shared document is used by every
     questionnaire and chat, General and every product, so that is said; its
     file stays. A product's takes its file with it (TD-039). Each question is
     one whole sentence, for the catalogs (plan 038). */
  function removalQuestion(name, productName) {
    if (productName) {
      return t("Remove “{name}” from {product}'s knowledge base?\n\nIts file is deleted too, and cannot be recovered from here — unless the shared knowledge base, another product or a questionnaire also uses it.", { name, product: productName });
    }
    return t("Remove “{name}” from the shared knowledge base?\n\nEvery questionnaire and chat, General and every product, stops using it from now on. Answers already written are not changed.\n\nIts file stays on the server; to use it again, add it again.", { name });
  }

  function clearQuestion(count, productName) {
    const n = count;
    if (productName) {
      const product = productName;
      if (count === 1) return t("Remove the 1 policy document from {product}'s knowledge base?\n\nTheir files are deleted too, and cannot be recovered from here — unless the shared knowledge base, another product or a questionnaire also uses them.\n\nThe answer memory is not affected.", { product });
      if (count > 1) return t("Remove all {n} policy documents from {product}'s knowledge base?\n\nTheir files are deleted too, and cannot be recovered from here — unless the shared knowledge base, another product or a questionnaire also uses them.\n\nThe answer memory is not affected.", { n, product });
      return t("Remove every policy document from {product}'s knowledge base?\n\nTheir files are deleted too, and cannot be recovered from here — unless the shared knowledge base, another product or a questionnaire also uses them.\n\nThe answer memory is not affected.", { product });
    }
    if (count === 1) return t("Remove the 1 policy document from the shared knowledge base?\n\nEvery questionnaire and chat, General and every product, stops using them from now on. Answers already written are not changed.\n\nThe answer memory is not affected.");
    if (count > 1) return t("Remove all {n} policy documents from the shared knowledge base?\n\nEvery questionnaire and chat, General and every product, stops using them from now on. Answers already written are not changed.\n\nThe answer memory is not affected.", { n });
    return t("Remove every policy document from the shared knowledge base?\n\nEvery questionnaire and chat, General and every product, stops using them from now on. Answers already written are not changed.\n\nThe answer memory is not affected.");
  }

  /* Whose document a source is. Only drawn for external ones: "our policy" is
     the unmarked case and badging all four sources under every answer would
     make the exception invisible again. */
  function authorityBadge(authority) {
    if (authority !== "external") return null;
    const tag = document.createElement("span");
    tag.className = "tag external";
    tag.textContent = t("law / external");
    tag.title = t("A regulation or framework we are subject to, not a document we wrote. It says what we are required to do, which is not evidence that we do it.");
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
    // The product's name is a name (plan 038): as it was written, in its own direction.
    tag.append(asContent("span", found.name));
    if (found.deleted) tag.append(" · " + t("deleted"));
    if (found.color) tag.style.setProperty("--product", found.color);
    tag.title = found.deleted
      ? t("{name} has been deleted. What was done for it is kept to read, and its filled files to download; it can no longer be changed.", { name: found.name })
      : title || t("For {name}", { name: found.name });
    return tag;
  }

  function ownSourceBadge(source) {
    return productBadge(source && source.product_id,
      t("From this product's own knowledge base. The drafter was told it takes precedence over the shared one."));
  }

  /* A product choice on a page (plan 029, 2): the user's rule is no silent
     General. "" is nothing chosen yet, GENERAL is General chosen on purpose,
     anything else a product's id. The server still reads "" as General
     (TD-066), so a page sends serverProduct(choice), and a record's
     product_id comes back as a choice through choiceOf. When the server
     learns to refuse a missing product, only serverProduct changes. */
  const GENERAL = "general";  // never a product's id: those are 12 hex characters (products.add)
  // In the page's language: every page loads its catalogs before this script (plan 038).
  const GENERAL_LABEL = t("General (shared policies only)");

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
    tag.textContent = t("General");
    tag.title = title || t("General: answered from the shared policies and answer memory only");
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
    const name = choice === GENERAL ? t("General") : (product(choice) || {}).name || "";
    button.append(t("Last used:") + " ", choiceTag(choice, t("Choose {name}", { name })));
    button.title = t("Choose {name}, the product of your most recent work. Nothing is chosen until you click.", { name });
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

  /* Where a source came from, in the words of the pages that manage it. */
  function sourceHome(kind) {
    if (kind === "guideline") return t("Knowledge base");
    return kind === "prior_answer" ? t("Answer memory") : t("Sources");
  }

  /* The sources, a row for each place they came from, each chip opening its
     clause. The row's first word says the place, and its colour is the chips'
     (plan 042), so nothing relies on the colour alone. */
  function citationsField(item) {
    const field = document.createElement("div");
    field.className = "field sources-field";
    const rows = new Map(["guideline", "prior_answer", "unknown"].map((kind) => [kind, document.createElement("div")]));
    rows.forEach((cites, kind) => {
      cites.className = "cites " + kind;
      const label = document.createElement("span");
      label.className = "field-label cites-label";
      label.textContent = sourceHome(kind);
      label.title = t("Click a source to read the clause it names");
      cites.append(label);
    });
    const panel = document.createElement("div");
    panel.className = "cite-panel";
    panel.hidden = true;

    let openButton = null;
    const sources = citedSources(item);

    item.citations.forEach((citation, position) => {
      const source = sources[position];
      const mark = authorityBadge(source && source.authority);
      const kind = source ? source.source_type : "unknown";

      const chip = document.createElement("button");
      chip.className = "cite " + kind;
      chip.title = kind === "prior_answer"
        ? t("From a previously answered assessment — click to read it")
        : kind === "guideline"
          ? t("From an indexed guideline — click to read the clause")
          : t("Named in the answer; the chunk is not in the exported evidence");
      chip.type = "button";
      chip.setAttribute("aria-expanded", "false");
      // The locator is the source's own (plan 038): a file's name and its clause, as written.
      chip.append(asContent("span", citation));
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

      rows.get(kind).append(chip);
    });

    rows.forEach((cites) => { if (cites.childElementCount > 1) field.append(cites); });
    field.append(panel);
    return field;
  }

  /* A question's kind (`models.QuestionType`), in words. One the card does not
     know yet reads as the server names it. */
  function questionKind(kind) {
    if (kind === "free_text") return t("free text");
    if (kind === "yes_no") return t("yes no");
    if (kind === "single_choice") return t("single choice");
    if (kind === "multi_choice") return t("multi choice");
    return String(kind || "").replace(/_/g, " ");
  }

  /* Where the question is in the file. A spreadsheet's id is `Sheet!row`, read
     as a person would say it; any other id is the file's own number. */
  function placeOf(id, index) {
    const cell = /^(.+)!(\d+)$/.exec(id || "");
    if (cell) return asContent("span", t("{sheet}, row {row}", { sheet: cell[1], row: cell[2] }));
    return asContent("span", id || String(index + 1));
  }

  /* Why the answer says what it says, and why it was held: everything a
     reviewer may want when the answer alone does not settle it, and does not
     want on every card. It was up to five coloured boxes, three of them saying
     why the answer was held; only the two that say what is wrong are coloured
     now (plan 042). Null when there is nothing to tell. */
  function whyPanel(item, index) {
    const panel = document.createElement("div");
    panel.className = "why-panel";
    panel.hidden = true;
    const block = (label, tone) => {
      const field = labelledField(label);
      if (tone) field.classList.add("why-" + tone);
      panel.append(field);
      return field;
    };

    const heldBecause = item.will_be_written === false && item.held_back_because;
    if ((item.needs_review || heldBecause) && !item.error && !item.blanked && !item.set_aside) {
      const field = block(t("Why this is flagged"), "warn");
      const reasons = document.createElement("div");
      reasons.className = "reasons";
      if (item.review_reasons && item.review_reasons.length) {
        // The review's own sentences, each in the page's language.
        item.review_reasons.forEach((reason, at) => {
          if (at) reasons.append(t("; "));
          serverInto(reasons, reason);
        });
      } else if (heldBecause) {
        // The server's sentence (`selection.ready_to_write`), in the page's language.
        serverInto(reasons, item.held_back_because, (because) => because[0].toUpperCase() + because.slice(1) + ".");
      } else {
        reasons.textContent = t("The confidence score is below the level set for automatic acceptance.");
      }
      field.append(reasons);
    }

    // Plain-English cause of the score itself, computed server-side so the
    // interface and both exports say exactly the same thing. Not for a blank,
    // nor for what a *person* did: approved or written by hand are decisions,
    // and that field keeps them too.
    const decision = ["approved by a reviewer", "written by hand"].includes(item.confidence_reason);
    if (item.confidence_reason && !item.blanked && !decision) {
      const why = document.createElement("div");
      why.className = "reasons why";
      serverInto(why, item.confidence_reason);  // the server's sentence (`explain_confidence`)
      block(t("Why the confidence is low"), heldByScore(item.confidence) ? "err" : "warn").append(why);
    }

    if (item.rationale) {
      /* The drafter's own words: content. A failed answer's is the server's
         sentence ("Answering failed: ..."), in the page's language. */
      const said = I18n.server(item.rationale) !== item.rationale;
      const rationale = said
        ? serverInto(document.createElement("div"), item.rationale)
        : directed(asContent("div", item.rationale), item.rationale);
      rationale.className = "rationale";
      block(t("Reasoning")).append(rationale);
    }

    /* Something reworded this answer after it was drafted -- preferences, a
       skill, a "make them shorter". Undoable from the card: each of those runs
       over many answers at once, so the one place an odd result gets noticed
       has to be the place it can be put right. */
    if (item.drafted && !item.blanked) {
      const field = block(t("As it was first drafted"));
      const original = directed(asContent("div", item.drafted), item.drafted);
      original.className = "rationale";
      field.append(original);
      if (!Cards.readOnly) {
        const back = cardButton(t("Put the draft back"));
        back.dataset.mutates = "true";
        back.title = t("Replace the reworded answer with the original draft, for this question only");
        back.onclick = () => Cards.onRestoreDraft(item, index);
        field.append(back);
      }
    }

    if (!panel.childElementCount) return null;

    const facts = [questionKind(item.question.question_type)];
    if (item.attempts > 1) facts.push(t("{n} retrieval rounds", { n: item.attempts }));
    const line = document.createElement("div");
    line.className = "why-facts";
    line.textContent = facts.join(" · ");
    panel.append(line);

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "card-link";
    toggle.textContent = t("Why this answer");
    toggle.setAttribute("aria-expanded", "false");
    panel.id = "why-" + (++whyPanels);
    toggle.setAttribute("aria-controls", panel.id);
    toggle.onclick = () => {
      panel.hidden = !panel.hidden;
      toggle.setAttribute("aria-expanded", String(!panel.hidden));
    };
    return { panel, toggle };
  }
  let whyPanels = 0;

  function renderAnswer(item, index) {
    const card = document.createElement("div");
    // The card's colour follows its status, not the score (plan 030).
    const status = statusOf(item);
    const held = status.key === "review" || status.key === "failed";
    card.className = "answer" + (held ? " review" : "") + (item.set_aside ? " set-aside" : "");

    const head = document.createElement("div");
    head.className = "answer-head";
    const body = document.createElement("div");
    body.className = "qbody";

    /* A questionnaire item can be a paragraph, which pushes the answer -- the
       thing the card is about -- below the fold. So a long question is clamped
       to two lines with a control to see the rest.

       Whether it needs clamping is measured after layout rather than guessed
       from a character count: the same two hundred characters are two lines on
       a wide screen and five on a phone. It starts clamped so a long one never
       flashes open, and un-clamps itself when there was nothing to hide. */
    const question = directed(asContent("div", item.question.text), item.question.text);
    question.className = "qtext clamped";

    const more = document.createElement("button");
    more.type = "button";
    more.className = "card-link qmore";
    more.hidden = true;
    more.textContent = t("show the whole question");
    more.onclick = () => {
      const clamped = question.classList.toggle("clamped");
      more.textContent = clamped ? t("show the whole question") : t("show less");
    };
    requestAnimationFrame(() => {
      if (question.scrollHeight > question.clientHeight + 1) more.hidden = false;
      else question.classList.remove("clamped");
    });

    // Where it is in the file, and the file's own heading for it.
    const meta = document.createElement("div");
    meta.className = "qmeta";
    const place = document.createElement("span");
    place.append(placeOf(item.question.id, index));
    if (item.question.section) place.append(" · ", asContent("span", item.question.section));
    meta.append(place, more);

    body.append(question, meta);
    head.append(body);

    const content = document.createElement("div");
    content.className = "answer-body";
    const answer = answerField(item, index);
    content.append(answer.field);

    // What went wrong, as the model's service said it: content (plan 038).
    if (item.error) {
      const problem = asContent("div", item.error);
      problem.className = "card-error";
      content.append(problem);
    }

    if (item.citations && item.citations.length) {
      content.append(citationsField(item));
    }

    const why = whyPanel(item, index);
    const actions = cardActions(item, index, answer.edit, why);
    if (actions) content.append(actions);
    if (why) content.append(why.panel);

    /* There was a second list here, "All n retrieved source(s)". It showed
       the same sources as the bubbles above, a second time: `finalize` keeps
       only the chunks the answer cited, so an answer's evidence *is* its
       citations -- true of every one of the 1,817 answers stored when it
       was removed. Each bubble opens the clause with its relevance, the
       formatted/raw switch and the document, which is all the list had. */

    // The status first, above the question: what happens to this answer, and why.
    card.append(statusBar(item, status), head, content);
    return card;
  }

  /* One card with no control that changes it, whatever the page's own cards
     may do (plan 030): a question answered in the chat has no questionnaire to
     approve, edit, blank or set it aside in. Drawn through `Cards.readOnly`, as
     a deleted product's answers are, and the page's setting is put back. */
  function renderReadOnly(item, index) {
    const page = { readOnly: Cards.readOnly, canSetAside: Cards.canSetAside };
    Object.assign(Cards, { readOnly: true, canSetAside: false });
    try {
      return renderAnswer(item, index);
    } finally {
      Object.assign(Cards, page);
    }
  }

  /* --- Approve all (plan 041) ----------------------------------------------

     The answers held back that a person could approve one at a time. Asked for
     by the user, with a confirmation, and kept out of the answer memory: the
     server's `approve_held` never teaches it. Not a failed answer (nothing to
     approve), nor one that will be written anyway: an approval changes nothing
     for those but the name against them, and nobody will have read them. */
  function canApproveAll(item) {
    return item.will_be_written === false && !item.error && !item.blanked && !item.set_aside
      && Boolean((item.answer || "").trim());
  }

  /* A question for the person, in the page. Resolves true or false. Cancel has
     the focus, so Enter on a dialog nobody read does nothing. */
  function confirmDialog({ title, lines, confirm }) {
    return new Promise((resolve) => {
      const dialog = document.createElement("dialog");
      dialog.className = "card-dialog";
      const heading = document.createElement("h3");
      heading.textContent = title;
      const list = document.createElement("ul");
      lines.forEach((line) => {
        const entry = document.createElement("li");
        entry.textContent = line;
        list.append(entry);
      });
      const buttons = document.createElement("div");
      buttons.className = "card-dialog-buttons";
      const no = cardButton(t("Cancel"));
      const yes = cardButton(confirm, "primary");
      const finish = (answer) => {
        dialog.close();
        dialog.remove();
        resolve(answer);
      };
      no.onclick = () => finish(false);
      yes.onclick = () => finish(true);
      dialog.addEventListener("cancel", (event) => { event.preventDefault(); finish(false); });
      buttons.append(no, yes);
      dialog.append(heading, list, buttons);
      document.body.append(dialog);
      dialog.showModal();
      no.focus();
    });
  }

  /* Draws a page's Approve all button for these answers. `review` is how many
     the Needs review tab holds, so the question can say how many it leaves.
     `onApprove(items)` does the work, once the person has said yes. */
  function paintApproveAll(button, answers, review, onApprove) {
    const ready = answers.filter(canApproveAll);
    const n = ready.length;
    button.hidden = Cards.readOnly || !n;
    if (button.hidden) return;
    button.textContent = t("Approve all ({n})", { n });
    button.title = t("Approve every answer under Needs review, after asking you to confirm");
    const stays = review - n;
    button.onclick = async () => {
      const lines = [
        t("Answers to approve: {n}", { n }),
        Cards.fileless
          ? t("They are marked as confirmed under your name, even though nobody has read them one by one.")
          : t("They go into the file under your name, even though nobody has read them one by one."),
        t("They are not added to the answer memory."),
      ];
      if (stays > 0) lines.push(t("Questions that could not be answered stay under Needs review: {n}", { n: stays }));
      const yes = await confirmDialog({
        title: t("Approve every answer that needs review?"),
        lines,
        confirm: t("Approve all ({n})", { n }),
      });
      if (!yes) return;
      button.disabled = true;
      try {
        await onApprove(ready);
      } finally {
        button.disabled = false;
      }
    };
  }

  function approvedAllMessage(n) {
    return Cards.fileless
      ? t("Approved {n} answer(s). None were added to the answer memory.", { n })
      : t("Approved {n} answer(s). They will be written into the file. None were added to the answer memory.", { n });
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

    const who = asContent("span", citation);  // the source's locator, as written (plan 038)
    who.className = "who";
    head.append(who);

    head.append(viewToggle());

    if (source) {
      const kind = document.createElement("span");
      kind.className = "tag from " + source.source_type;
      kind.textContent = sourceHome(source.source_type);
      head.prepend(kind);
      const own = ownSourceBadge(source);
      if (own) kind.after(own);

      if (typeof source.score === "number") {
        const score = document.createElement("span");
        score.textContent = t("relevance {score}", { score: source.score.toFixed(2) });
        head.append(score);
      }

      const open = openDocumentButton(source.source_name, source.source_type);
      if (open) head.append(open);
    }

    const body = source
      ? renderChunk(source.snippet)
      : renderChunk(t("This clause was named in the answer, but the chunk behind it is not in the exported evidence."), null, true);

    panel.append(head, body);
  }

  // What the pages use. Everything else above is private to the card.
  Object.assign(Cards, {
    render: renderAnswer,
    paintApproveAll: paintApproveAll,
    approvedAllMessage: approvedAllMessage,
    renderReadOnly: renderReadOnly,
    setReviewThreshold: setReviewThreshold,
    withdrawnMessage: withdrawnMessage,
    stat: statCard,
    chunk: renderChunk,
    isArabic: isArabic,
    viewToggle: viewToggle,
    fromQuestion: fromQuestion,
    reviewBucket: reviewBucket,
    reviewTabs: reviewTabs,
    emptyTab: emptyTab,
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
    serverInto: serverInto,
  });
})();
