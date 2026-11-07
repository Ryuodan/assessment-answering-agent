"""Every string the pages show has its Arabic, in the glossary's terms (plan 038).

The pages are written in English and translated from the catalogs in
`src/static/i18n/`: their markup once it has loaded, and what their scripts
draw through `I18n.t("...")`. A string with no Arabic would show its English
in an Arabic page. This reads every page's markup and every `t("...")` in its
scripts, and fails on one the page's catalogs do not have. A visible string
that is content rather than interface (a question, an answer, a file's name)
sits inside `data-no-translate`.

It also reads the catalogs themselves:
- each is plain JSON inside `I18n.add(...)`;
- the Arabic has no English words, other than names;
- the `{placeholders}` are the English's;
- the same English is the same Arabic in every catalog: one term, one translation.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from src.config import PROJECT_ROOT

STATIC = PROJECT_ROOT / "src" / "static"
CATALOGS = STATIC / "i18n"
PAGES = ["chat.html", "index.html", "knowledge.html", "memory.html", "preferences.html", "products.html"]
SCRIPTS = {"cards.js": ["index.html", "chat.html", "knowledge.html"]}  # a shared script, and the pages that load it

# Each file's own catalog. A file is checked once its catalog has entries: its
# translator fills it, and nobody edits a list here. When all are filled,
# `test_every_page_is_translated` passes and its xfail comes off (plan 038).
OWN_CATALOG = {
    "chat.html": "ar-chat.js",
    "index.html": "ar-workbench.js",
    "knowledge.html": "ar-knowledge.js",
    "memory.html": "ar-memory.js",
    "preferences.html": "ar-preferences.js",
    "products.html": "ar-products.js",
    "cards.js": "ar-cards.js",
}


def translated(name: str) -> bool:
    return bool(all_catalogs().get(OWN_CATALOG[name]))


# English words an Arabic page may show: names, formats, standards and keys.
NAMES = {
    "PDF",
    "Excel",
    "Word",
    "CSV",
    "XLSX",
    "XLS",
    "DOCX",
    "DOC",
    "JSON",
    "TXT",
    "MD",
    "NCA",
    "ECC",
    "PDPL",
    "ISO",
    "IEC",
    "SOC",
    "NIST",
    "SAMA",
    "CST",
    "CITC",
    "SDAIA",
    "GDPR",
    "PCI",
    "DSS",
    "Groq",
    "Chroma",
    "API",
    "URL",
    "ID",
    "IDs",
    "J",
    "K",
    "A",
    "E",
    "Esc",
    "Enter",
    "Shift",
    "Tab",
    "Ctrl",
}
LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
PLACEHOLDER = re.compile(r"\{(\w+)\}")
PLURAL_FORMS = {"zero", "one", "two", "few", "many", "other"}


def catalog_blocks(path: Path) -> list[dict]:
    """Each `I18n.add(...)`'s object, read as JSON. A call starts its line; one in a comment does not."""
    text = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    blocks = []
    for found in re.finditer(r"^I18n\.add\(", text, re.MULTILINE):
        value, _ = decoder.raw_decode(text, found.end())
        assert isinstance(value, dict), f"{path.name}: I18n.add takes one object"
        blocks.append(value)
    return blocks


def all_catalogs() -> dict[str, dict]:
    return {
        path.name: {key: value for block in catalog_blocks(path) for key, value in block.items()}
        for path in sorted(CATALOGS.glob("ar-*.js"))
    }


def loaded_by(page: str) -> list[str]:
    html = (STATIC / page).read_text(encoding="utf-8")
    return re.findall(r'<script src="static/i18n/(ar-[\w-]+\.js)"', html)


def catalog_for(page: str) -> dict:
    catalogs = all_catalogs()
    merged: dict = {}
    for name in loaded_by(page):
        merged.update(catalogs.get(name, {}))
    return merged


class Markup(HTMLParser):
    """A page's own text: text nodes, and the attributes a person sees or hears."""

    LEFT_ALONE = {"script", "style", "textarea", "code", "pre", "kbd"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
    ATTRIBUTES = ("title", "placeholder", "aria-label", "alt")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # (tag, its text left alone, its attributes left alone), as `I18n.translate` reads them:
        # a <textarea>'s or a <kbd>'s own text stays, its placeholder or title is translated.
        self.stack: list[tuple[str, bool, bool]] = []
        self.texts: list[str] = []
        self.html_keys: list[str] = []
        self.scripts: list[str] = []
        self._script: list[str] | None = None

    def _skipping(self) -> bool:
        return any(text for _, text, _ in self.stack)

    def _content(self) -> bool:
        return any(attributes for _, _, attributes in self.stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        named = dict(attrs)
        content = "data-no-translate" in named or self._content()
        skip = tag in self.LEFT_ALONE or content or "data-i18n-html" in named
        if "data-i18n-html" in named and not self._skipping():
            self.html_keys.append(" ".join((named["data-i18n-html"] or "").split()))
        if not content:
            for name in self.ATTRIBUTES:
                if named.get(name):
                    self.texts.append(" ".join(named[name].split()))
        if tag == "script" and "src" not in named:
            self._script = []
        if tag not in self.VOID:
            self.stack.append((tag, skip, content))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script is not None:
            self.scripts.append("".join(self._script))
            self._script = None
        while self.stack:
            open_tag, _, _ = self.stack.pop()
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script.append(data)
            return
        if self._skipping():
            return
        text = " ".join(data.split())
        if text:
            self.texts.append(text)


def markup_of(page: str) -> Markup:
    parser = Markup()
    parser.feed((STATIC / page).read_text(encoding="utf-8"))
    return parser


def interface_text(text: str) -> bool:
    """Words a person reads, not an address, a file pattern or a symbol."""
    if not re.search(r"[A-Za-z]", text):
        return False
    return not re.fullmatch(r"[\w.+-]+@[\w.-]+|https?://\S+|[\w*.-]+\.\w{2,4}", text)


T_CALL = re.compile(r"""(?<![\w.])(?:I18n\.)?t\(\s*("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`[^`]*`)""")


def t_literals(source: str) -> list[str]:
    found = []
    for match in T_CALL.finditer(source):
        quoted = match.group(1)
        if quoted.startswith("`"):
            assert "${" not in quoted, f"t() with a template's ${{...}}: use {{name}} and params: {quoted[:80]}"
            found.append(quoted[1:-1])
        elif quoted.startswith("'"):
            inner = re.sub(r'(?<!\\)"', '\\"', quoted[1:-1].replace("\\'", "'"))
            found.append(json.loads('"' + inner + '"'))
        else:
            found.append(json.loads(quoted))
    return found


def scripts_of(name: str) -> str:
    if name.endswith(".js"):
        return (STATIC / name).read_text(encoding="utf-8")
    return "\n".join(markup_of(name).scripts)


# --- the catalogs ------------------------------------------------------------


def test_the_catalogs_are_json_and_arabic() -> None:
    catalogs = all_catalogs()
    assert "ar-common.js" in catalogs
    for name, entries in catalogs.items():
        for english, arabic in entries.items():
            forms = arabic if isinstance(arabic, dict) else {"other": arabic}
            assert isinstance(arabic, (str, dict)), f"{name}: {english!r}"
            assert "other" in forms and set(forms) <= PLURAL_FORMS, f"{name}: {english!r} has forms {set(forms)}"
            for form in forms.values():
                assert isinstance(form, str) and form.strip(), f"{name}: {english!r} is empty"
                assert re.search(r"[؀-ۿ]", form), f"{name}: {english!r} has no Arabic: {form!r}"
                spare = re.sub(r"<[^>]*>", "", PLACEHOLDER.sub("", form))  # data-i18n-html's tags are not words
                english_words = [w for w in LATIN_WORD.findall(spare) if w not in NAMES]
                assert not english_words, f"{name}: {english!r} keeps English words {english_words}: {form!r}"
                assert set(PLACEHOLDER.findall(form)) <= set(PLACEHOLDER.findall(english)), (
                    f"{name}: {english!r}'s Arabic names a placeholder the English does not: {form!r}"
                )


def test_one_english_term_is_one_arabic_term_everywhere() -> None:
    seen: dict[str, tuple[str, object]] = {}
    for name, entries in all_catalogs().items():
        for english, arabic in entries.items():
            if english in seen:
                first, before = seen[english]
                assert before == arabic, f"{english!r} is {before!r} in {first} and {arabic!r} in {name}"
            else:
                seen[english] = (name, arabic)


@pytest.mark.parametrize("page", PAGES)
def test_every_page_reads_its_language_first(page: str) -> None:
    """i18n.js before any other script: the page is right to left from its first paint."""
    html = (STATIC / page).read_text(encoding="utf-8")
    head = html.split("</head>", 1)[0]
    scripts = re.findall(r'<script src="static/([\w/.-]+)"', head)
    assert scripts and scripts[0] == "i18n.js", f"{page}: {scripts}"
    assert "i18n/ar-common.js" in scripts, page
    for shared, pages in SCRIPTS.items():
        if page in pages:
            assert "i18n/ar-cards.js" in scripts, f"{page} loads {shared}, so its catalog"


@pytest.mark.parametrize("page", PAGES)
def test_every_page_follows_the_persons_choice(page: str) -> None:
    assert "I18n.follow(" in scripts_of(page), f"{page} reads the session and never follows its language"


# --- the pages ---------------------------------------------------------------


@pytest.mark.parametrize("page", PAGES)
def test_a_translated_pages_markup_has_its_arabic(page: str) -> None:
    if not translated(page):
        pytest.skip(f"{page} is not translated yet: {OWN_CATALOG[page]} is empty (plan 038)")
    catalog = catalog_for(page)
    markup = markup_of(page)
    missing = sorted({text for text in markup.texts if interface_text(text) and text not in catalog})
    missing += [f"data-i18n-html: {key}" for key in markup.html_keys if key not in catalog]
    assert not missing, f"{page}: {len(missing)} without Arabic: {missing[:25]}"


@pytest.mark.parametrize("name", PAGES + list(SCRIPTS))
def test_a_translated_scripts_strings_have_their_arabic(name: str) -> None:
    if not translated(name):
        pytest.skip(f"{name} is not translated yet: {OWN_CATALOG[name]} is empty (plan 038)")
    pages = SCRIPTS.get(name, [name])
    for page in pages:
        catalog = catalog_for(page)
        missing = sorted({text for text in t_literals(scripts_of(name)) if text not in catalog})
        assert not missing, f"{name} in {page}: {len(missing)} t() without Arabic: {missing[:25]}"


@pytest.mark.xfail(strict=True, reason="plan 038: the pages are being translated")
def test_every_page_is_translated() -> None:
    assert all(translated(name) for name in OWN_CATALOG)


def test_the_reading_finds_what_it_should() -> None:
    """The test's own parsing, on a page of its own making."""
    parser = Markup()
    parser.feed(
        '<h1 title="Hint">Needs review</h1><kbd>J</kbd><p data-no-translate>Our answer</p>'
        '<p data-i18n-html="Keys: <kbd>J</kbd>">Keys: <kbd>J</kbd></p><input placeholder="Type it">'
        '<textarea placeholder="Ask">typed</textarea><kbd title="Next">J</kbd>'
        '<div data-no-translate><span title="A name">Name</span></div>'
        '<script>const a = t(\'It’s {n}\', { n: 1 }); I18n.t("Two"); format(x); b.t("No");</script>'
    )
    assert parser.texts == ["Hint", "Needs review", "Type it", "Ask", "Next"]
    assert parser.html_keys == ["Keys: <kbd>J</kbd>"]
    assert t_literals(parser.scripts[0]) == ["It’s {n}", "Two"]
