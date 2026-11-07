"""Opening a page in Arabic, and finding English left on it (plan 038).

For the Arabic browser tests. `in_arabic(page)` makes every page the test opens
start in Arabic, as a device that chose it does. `english_on_screen(page)` lists
the visible text that still has English words: interface left untranslated.

Content is not interface. A question, an answer, a source's text, a file's or
a product's name, an address or a conversation's title sits inside
`data-no-translate`, and is not read. Names, formats, standards and keys in
the interface's own text are allowed (`NAMES`, shared with the catalog test).
"""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from src import identity, interface_language
from tests.test_i18n_catalogs import NAMES

STORED = "interface-language"

# What a page draws, read by the page itself: each visible text node, and the
# placeholder, title and aria-label of each visible element.
_ON_SCREEN = """({ within, besides }) => {
  const besidesThem = besides ? ", " + besides : "";
  const LEFT_ALONE = "[data-no-translate], script, style, textarea, code, pre, kbd, noscript" + besidesThem;
  // A <textarea>'s or a <kbd>'s own text stays as it is; its placeholder or title is translated.
  const CONTENT = "[data-no-translate]" + besidesThem;
  const root = document.querySelector(within);
  if (!root) return [];
  const shown = (element) => {
    const box = element.closest("select") || element;
    if (box.closest("[hidden], dialog:not([open]), details:not([open]) > :not(summary)")) return false;
    return box.checkVisibility ? box.checkVisibility({ visibilityProperty: true }) : box.offsetParent !== null;
  };
  const found = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const parent = node.parentElement;
    const text = node.nodeValue.replace(/\\s+/g, " ").trim();
    if (!parent || !text || !/[A-Za-z]/.test(text) || parent.closest(LEFT_ALONE) || !shown(parent)) continue;
    found.push(text);
  }
  root.querySelectorAll("[placeholder], [title], [aria-label]").forEach((element) => {
    if (element.closest(CONTENT) || !shown(element)) return;
    ["placeholder", "title", "aria-label"].forEach((name) => {
      const value = (element.getAttribute(name) || "").replace(/\\s+/g, " ").trim();
      if (/[A-Za-z]/.test(value)) found.push(name + ": " + value);
    });
  });
  return found;
}"""

_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_NOT_WORDS = re.compile(
    r"[\w.+-]+@[\w.-]+|https?://\S+|[\w*.-]+\.(?:xlsx|xlsm|xls|docx|doc|pdf|csv|txt|md|json)\b", re.I
)


def in_arabic(page: Page, *, person: bool = True) -> None:
    """The test's pages start in Arabic, as on a device that chose it, and so does the person.

    The device's copy is set once per tab, before the first page: a page that
    switches language reloads, and setting it on every load would undo the
    switch. `person` gives the open-access person the same choice on the
    server, or a page would follow the session back to English; a test that
    signs somebody else in chooses for them (`interface_language.choose`).
    """
    page.add_init_script(
        "try { if (!sessionStorage.getItem('arabic-set')) {"
        f" localStorage.setItem('{STORED}', 'ar'); sessionStorage.setItem('arabic-set', '1'); }}"
        " } catch (error) {}"
    )
    if person:
        interface_language.choose(identity.local_user().email, "ar")


_ATTRIBUTES = ("placeholder: ", "title: ", "aria-label: ")


def english_on_screen(
    page: Page, *, within: str = "body", besides: tuple[str, ...] = (), names: tuple[str, ...] = ()
) -> list[str]:
    """The visible interface text inside `within` that still has English words in it.

    `besides`: selectors of areas not read, such as what another check reads on its own.
    `names`: content an attribute holds, such as a product's name in a badge's title or
    a question's place in its card's label. No element can mark part of an attribute
    as content, so these are taken out of an attribute's value before it is read.
    """
    left = []
    for text in page.evaluate(_ON_SCREEN, {"within": within, "besides": ", ".join(besides)}):
        attribute = text.startswith(_ATTRIBUTES)
        spare = text.split(": ", 1)[1] if attribute else text
        if attribute:
            for name in names:
                spare = spare.replace(name, " ")
        if [word for word in _WORD.findall(_NOT_WORDS.sub("", spare)) if word not in NAMES]:
            left.append(text)
    return sorted(set(left))


def expect_arabic(
    page: Page,
    where: str = "",
    *,
    within: str = "body",
    besides: tuple[str, ...] = (),
    names: tuple[str, ...] = (),
) -> None:
    """The page is Arabic, right to left, with no English left on screen (inside `within`)."""
    expect(page.locator("html")).to_have_attribute("dir", "rtl")
    expect(page.locator("html")).to_have_attribute("lang", "ar")
    left = english_on_screen(page, within=within, besides=besides, names=names)
    assert not left, f"English on screen{' ' + where if where else ''}: {len(left)}: {left[:30]}"
