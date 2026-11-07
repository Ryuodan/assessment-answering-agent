"""The knowledge base, the answer memory, preferences and products, in Arabic (plan 038).

Each page is opened in Arabic in the states its English tests reach: empty,
with data, each dialog and panel open, its status lines, its errors. In each,
nothing on screen is English but names and content (`expect_arabic`), and at a
desktop's width and a phone's, right to left, nothing scrolls sideways or
sticks out of the window.

Two things are another translator's while the pages are translated in
parallel, and left out here, each where it is met:
- what cards.js draws on the knowledge page: the badge on an external
  document (`CARDS`);
- a server's own sentence, an error's message (ar-server.js): the line that
  shows it.

Also the choice of language in Preferences, in English and in Arabic: it turns
the pages Arabic and back, the person keeps it, and unsaved typing is asked
about first.
"""

from __future__ import annotations

import itertools
import json

import pytest
from playwright.sync_api import Page, expect

from src import answer_memory, batches, events, identity, interface_language, knowledge, products, roles, service
from src.config import settings
from src.forms.model import DetectedForm
from src.identity import User
from src.models import IngestResult
from tests.browser.arabic import expect_arabic, in_arabic
from tests.conftest import FakeVectorStore, bare_store

pytestmark = pytest.mark.browser

TEAM = settings.default_team
CODE = "BROWSER-TEST-CODE"
LEAD = "lead@example.test"
MEMBER = "member@example.test"
POLICY_TEXT = "Section 4.2: multi-factor authentication is enforced for every account."
PDF = "application/pdf"


_ids = itertools.count()


def chunk(name: str, source_type: str = "guideline", authority: str = "ours") -> dict:
    metadata = {"source_name": name, "source_type": source_type, "authority": authority}
    return {"text": "text", "metadata": metadata, "id": f"c{next(_ids)}"}


@pytest.fixture
def stores(monkeypatch) -> dict[tuple[str, str], knowledge.KnowledgeStore]:
    """A fake index per (team, product), empty until a test puts chunks in it."""
    made: dict[tuple[str, str], knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        key = (team_id or TEAM, product_id)
        if key not in made:
            made[key] = bare_store(FakeVectorStore([]))
            made[key]._store.delete_collection = lambda key=key: made.pop(key, None)
        return made[key]

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    return made


def holding(product_id: str, *records: dict) -> None:
    """Chunks put straight into a knowledge base, as indexing would, and its catalog read again."""
    store = knowledge.get_store(TEAM, product_id=product_id)
    store._store.records.extend(records)
    store._reset_caches()


@pytest.fixture
def team() -> None:
    identity.ensure_team(TEAM)
    identity.set_access_code(TEAM, CODE)
    identity.add_user(LEAD, role=roles.LEAD)
    identity.add_user(MEMBER)


def sign_in(page: Page, email: str, path: str) -> None:
    """Signed in as `email`, who has chosen Arabic. The sign-in card is Arabic too.

    Only the card is read: behind it the page, signed out, shows the server's
    "Sign in to continue.", which is ar-server.js's.
    """
    interface_language.choose(email, "ar")
    page.goto(path)
    expect(page.locator("#authGate")).to_be_visible()
    expect_arabic(page, "signing in", within="#authGate")
    page.fill("#authEmail", email)
    page.fill("#authCode", CODE)
    page.click("#authSubmit")
    expect(page.locator("#authGate")).to_be_hidden()


def failing(route) -> None:
    """The server down: no JSON, so the page says so in its own words."""
    route.fulfill(status=500, body="down")


# What is wider than the window: the page itself, or a visible element in it.
_OUTSIDE = """() => {
  const shown = (el) => el.getClientRects().length && !el.closest("dialog:not([open]), [hidden]");
  const outside = [...document.body.querySelectorAll("*")].filter(shown)
    .map((el) => ({ el, box: el.getBoundingClientRect() }))
    .filter(({ box }) => box.width && (box.left < -1 || box.right > innerWidth + 1))
    .map(({ el, box }) => (el.id || el.className || el.tagName) + " at " + Math.round(box.left) + "-" + Math.round(box.right));
  return { width: innerWidth, scrolls: document.documentElement.scrollWidth, outside };
}"""


def fits(page: Page, where: str) -> None:
    """Right to left, nothing scrolls sideways and nothing is cut off at either edge."""
    expect(page.locator("html")).to_have_attribute("dir", "rtl")
    measured = page.evaluate(_OUTSIDE)
    assert measured["scrolls"] <= measured["width"], f"{where} scrolls sideways: {measured}"
    assert not measured["outside"], f"{where} cuts off {measured['outside'][:10]}"


def chosen() -> str:
    return interface_language.get(identity.local_user().email)


# --- the knowledge base -------------------------------------------------------


def test_the_knowledge_base_in_arabic_before_one_is_chosen(page: Page, stores) -> None:
    in_arabic(page)
    page.goto("/knowledge")
    expect(page.locator("#kbScope")).to_have_value("")
    expect(page.locator("#kbSummary")).to_have_text("اختر قاعدة معرفة في الأعلى لترى الوثائق التي فيها.")
    expect_arabic(page, "with nothing chosen")

    page.set_input_files("#guidelinesInput", files=[{"name": "Access control.pdf", "mimeType": PDF, "buffer": b"%"}])
    expect(page.locator("#guidelinesChosen")).to_have_text("Access control.pdf")
    expect(page.locator("#guidelinesNeedsScope")).to_be_visible()
    expect(page.locator("#guidelinesBtn")).to_be_disabled()
    expect_arabic(page, "with a file chosen and no knowledge base")


def test_the_knowledge_base_in_arabic_with_its_documents(page: Page, stores, monkeypatch) -> None:
    availo = products.add(None, TEAM, "Availo")
    holding("", chunk("Access control policy.pdf"), chunk("Access control policy.pdf"))
    holding("", chunk("Personal Data Protection Law.pdf", authority="external"))
    holding("", chunk("Answer memory", "prior_answer"))
    holding(availo.id, chunk("Availo standard.pdf"))

    async def indexed(path, source_type, authority="ours", team_id=None, **scope):
        holding(scope.get("product_id", ""), chunk(path.name))
        return IngestResult(source_name=path.name, source_type=source_type, chunks_indexed=3)

    monkeypatch.setattr("src.routes.knowledge.service.ingest", indexed)
    in_arabic(page)
    page.goto("/knowledge?product=general")
    sources, status = page.locator("#kbSources"), page.locator("#kbStatus")
    expect(sources.locator("li")).to_have_count(2)  # the previous answers are counted, not listed
    expect(page.locator("#kbSummary .tag")).to_have_text("ملفان")
    expect(page.locator("#kbSummary a")).to_have_text("إجابة سابقة واحدة")
    expect(page.locator("#kbScopeHint")).to_have_text("تُستخدم لجميع الاستبيانات.")
    expect_arabic(page, "the shared knowledge base, listed")

    page.set_input_files("#guidelinesInput", files=[{"name": "Backup standard.pdf", "mimeType": PDF, "buffer": b"%"}])
    page.click("#guidelinesBtn")
    expect(page.locator("#guidelinesStatus")).to_have_text("تمت فهرسة 1 من أصل 1 من الملفات — عدد المقاطع: 3.")
    expect_arabic(page, "after indexing")

    page.once("dialog", lambda dialog: dialog.accept())
    sources.locator("li", has_text="Backup standard.pdf").get_by_role("button", name="إزالة").click()
    expect(status).to_have_text("تمت إزالة Backup standard.pdf.")
    expect_arabic(page, "after removing a document")

    page.select_option("#kbScope", availo.id)
    expect(page.locator("#kbScopeHint")).to_have_text("تُستخدم لاستبيانات Availo فقط، إلى جانب المشتركة.")
    expect(sources).to_contain_text("Availo standard.pdf")
    expect_arabic(page, "a product's knowledge base")

    page.once("dialog", lambda dialog: dialog.accept())
    page.click("#kbClear")
    expect(status).to_have_text("تمت إزالة جميع وثائق السياسات من قاعدة معرفة Availo.")
    expect(page.locator("#kbSummary")).to_have_text("لا توجد وثائق مفهرسة بعد. ارفع سياساتك في الأعلى.")
    expect_arabic(page, "after removing every policy document")


def test_the_document_viewer_in_arabic(page: Page, stores, monkeypatch) -> None:
    service.save_upload("Access control policy.pdf", b"%PDF-1.4 access", TEAM)
    holding("", chunk("Access control policy.pdf"))

    async def extracted(path):
        return POLICY_TEXT

    monkeypatch.setattr("src.service.extracted_document_text", extracted)
    in_arabic(page)
    page.goto("/knowledge?product=general")
    page.locator("#kbSources li", has_text="Access control policy.pdf").get_by_role("button", name="عرض").click()
    viewer = page.locator("#documentViewer")
    expect(viewer).to_be_visible()
    expect(page.locator("#viewerTitle")).to_have_text("Access control policy")
    expect(page.locator("#viewerMeta")).to_have_text("وثيقة إرشادية مرفوعة · Access control policy.pdf")
    expect(page.locator("#extractedStatus")).to_have_text(f"{len(POLICY_TEXT)} حرفاً مستخرجاً.")
    expect_arabic(page, "the viewer, on the original", within="#documentViewer")

    page.click("#textTab")
    expect(page.locator("#extractedText")).to_have_text(POLICY_TEXT)
    expect_arabic(page, "the viewer, on the extracted text", within="#documentViewer")
    page.click("#viewerClose")
    expect(viewer).to_be_hidden()


def test_the_knowledge_base_says_in_arabic_that_it_could_not_be_read(page: Page, stores) -> None:
    page.route(lambda url: url.endswith("/api/knowledge"), failing)
    in_arabic(page)
    page.goto("/knowledge?product=general")
    expect(page.locator("#kbSummary")).to_have_text("تعذّر تحميل قاعدة المعرفة: تعذّر تنفيذ الطلب (500)")
    expect_arabic(page, "when the knowledge base cannot be read")


@pytest.mark.parametrize("width", [1280, 375])
def test_the_knowledge_base_fits_right_to_left(page: Page, stores, width: int) -> None:
    products.add(None, TEAM, "Availo")
    holding("", chunk("Information security policy for suppliers and contractors.pdf"))
    holding("", chunk("PDPL.pdf", authority="external"), chunk("Answer memory", "prior_answer"))
    page.set_viewport_size({"width": width, "height": 812})
    in_arabic(page)
    page.goto("/knowledge?product=general")
    expect(page.locator("#kbSources li")).to_have_count(2)
    fits(page, f"the knowledge base at {width}px")


# --- the answer memory --------------------------------------------------------


@pytest.fixture
def quiet_sweep(monkeypatch) -> None:
    """The sweep an added answer starts, a model call per entry, does nothing here."""

    async def nothing() -> None:
        return None

    monkeypatch.setattr("src.routes.memory.scan_memory", nothing)


def remembered() -> None:
    """One answer of each kind, one replaced by a newer one, and two that disagree."""
    answer_memory.record(
        "Do you encrypt backups?",
        "Yes, with AES-256.",
        from_file="Vendor review.xlsx",
        origin="approved",
        approved_by=LEAD,
        approved_on="2026-10-19",
        scanned=True,
    )
    answer_memory.record("Is MFA enforced?", "Yes, for every account.", approved_by=LEAD, scanned=True)
    old = answer_memory.record(
        "Do you keep logs?", "For a year.", from_file="Old review.xlsx", origin="import", scanned=True
    )
    new = answer_memory.record("Do you keep logs?", "For two years.", scanned=True)
    answer_memory.supersede(old.entry_id, by=new.entry_id, because="a newer answer to the same question")
    one = answer_memory.record("Is data encrypted at rest?", "Yes.", from_file="A.xlsx", origin="import", scanned=True)
    other = answer_memory.record("Is data encrypted at rest?", "No.", from_file="B.xlsx", origin="import", scanned=True)
    answer_memory.raise_conflict(
        one.entry_id, other.entry_id, "the two answers disagree and nothing says which is current"
    )


def test_the_answer_memory_in_arabic_with_nothing_in_it(page: Page, stores) -> None:
    in_arabic(page)
    page.goto("/memory")
    expect(page.locator("#entries .empty")).to_have_text(
        "لا توجد إجابات محفوظة بعد. أضف إجابة في الأعلى، أو عدّل إجابة واعتمدها في بطاقتها."
    )
    expect(page.locator("#conflictsPanel")).to_be_hidden()
    expect_arabic(page, "with nothing remembered")

    page.click("#add")
    expect(page.locator("#addStatus")).to_have_text("تحتاج الإجابة المحفوظة إلى السؤال والإجابة معاً.")
    expect_arabic(page, "adding an answer with nothing written")


def test_the_answer_memory_in_arabic_with_answers_and_a_disagreement(page: Page, stores, quiet_sweep) -> None:
    availo = products.add(None, TEAM, "Availo")
    remembered()
    in_arabic(page)
    page.goto("/memory")
    entries = page.locator("#entries .entry")
    expect(entries).to_have_count(6)
    expect(page.locator("#conflictsPanel")).to_be_visible()
    expect(page.locator(".conflict .why")).to_have_text("الإجابتان متعارضتان، ولا شيء يبيّن أيهما المعمول بها حالياً")
    expect(page.locator("#listStatus")).to_have_text("عرض 6 من 6")
    expect(page.locator(".entry.replaced .tag.replaced")).to_have_text("مستبدلة")
    meta = page.locator(".entry", has_text="AES-256").locator(".meta")
    expect(meta).to_contain_text(f"اعتمدها {LEAD}")
    # The date in an element of its own: after Arabic words it read "19-10-2026".
    expect(meta.locator("[dir=auto]", has_text="2026-10-19")).to_have_count(1)
    expect_arabic(page, "with answers, one replaced and two that disagree")

    card = entries.filter(has_text="AES-256")
    card.get_by_role("button", name="تعديل").click()
    expect(card.locator(".editing")).to_be_visible()
    expect_arabic(page, "editing an answer")

    asked: list[str] = []
    page.once("dialog", lambda dialog: (asked.append(dialog.message), dialog.dismiss()))
    card.get_by_role("button", name="حذف من الذاكرة").click()
    expect(entries).to_have_count(6)
    assert asked and asked[0].startswith("هل تريد حذف هذه الإجابة من الذاكرة؟"), asked

    page.fill("#search", "nothing like this")
    expect(page.locator("#entries .empty")).to_have_text("لا يوجد ما يطابق ذلك.")
    expect_arabic(page, "a search that matches nothing")
    page.fill("#search", "")
    expect(entries).to_have_count(6)

    found = {"found": [{"kind": "conflict"}, {"kind": "supersedes"}], "stats": {"unscanned": 3}}
    page.route(
        "**/api/memory/scan",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(found)),
    )
    page.click("#scan")
    expect(page.locator("#listStatus")).to_have_text(
        "حالات التعارض التي وُجدت: 1، والإجابات المستبدلة: 1. لا تزال 3 إجابات بانتظار المقارنة — اضغط مجدداً."
    )
    expect_arabic(page, "after checking for conflicts")

    page.fill("#newQuestion", "Do you test your backups?")
    page.fill("#newAnswer", "Yes, every quarter.")
    page.click("#add")
    expect(page.locator("#addStatus")).to_have_text("حُفظت. إنها أول إجابة في القائمة أدناه.")
    expect_arabic(page, "after adding an answer")

    page.select_option("#memoryScope", availo.id)
    expect(page.locator("#memoryScopeHint")).to_have_text("تُستخدم لاستبيانات Availo فقط، إلى جانب المشتركة.")
    expect(page.locator("#entries .empty")).to_be_visible()
    expect_arabic(page, "a product's answer memory")


def test_the_answer_memory_says_in_arabic_that_it_could_not_be_read(page: Page, stores) -> None:
    page.route(lambda url: "/api/memory?" in url, failing)
    in_arabic(page)
    page.goto("/memory")
    expect(page.locator("#listStatus")).to_have_text("تعذّر تنفيذ الطلب (500)")
    expect_arabic(page, "when the memory cannot be read")


@pytest.mark.parametrize("width", [1280, 375])
def test_the_answer_memory_fits_right_to_left(page: Page, stores, width: int) -> None:
    products.add(None, TEAM, "Availo")
    remembered()
    page.set_viewport_size({"width": width, "height": 812})
    in_arabic(page)
    page.goto("/memory")
    expect(page.locator("#entries .entry")).to_have_count(6)
    expect(page.locator(".conflict")).to_have_count(1)
    fits(page, f"the answer memory at {width}px")


# --- preferences --------------------------------------------------------------


def test_preferences_in_arabic(page: Page) -> None:
    in_arabic(page)
    page.goto("/preferences")
    expect(page.locator("#builtinSkills .skill")).to_have_count(4)
    expect(page.locator("#builtinSkills")).to_contain_text("ملخص تنفيذي")
    expect(page.locator("input[name=interface_language][value=ar]")).to_be_checked()
    expect(page.locator("#asks")).to_have_text("لا شيء — تبقى إجاباتك كما صيغت تماماً.")
    expect_arabic(page, "as it opens")

    page.locator("input[name=tone][value=plain]").check()
    expect(page.locator("#asks")).to_have_attribute("data-no-translate", "")  # the instruction: content
    expect(page.locator("#preferencesStatus")).to_have_text("لم تُحفظ بعد.")
    expect_arabic(page, "with a choice changed")

    page.click("#useRecommended")
    expect(page.locator("#preferencesStatus")).to_have_text("تمت التعبئة. احفظ لاستخدامه، أو جرّبه على مثال أولاً.")
    expect_arabic(page, "with the recommended setup filled in")

    page.click("#savePreferences")
    expect(page.locator("#preferencesStatus")).to_have_text("حُفظت. ستُعاد بها صياغة الإجابات التي تصوغها من الآن.")
    expect_arabic(page, "saved")

    # One of the limits the server holds the preferences to, said in Arabic.
    page.fill("#referTo", '"T2"')
    page.click("#savePreferences")
    expect(page.locator("#preferencesStatus")).to_have_text("اكتب تسمية المنظمة دون علامات اقتباس.")
    expect_arabic(page, "a choice the server refuses")


def test_trying_a_style_on_a_sample_in_arabic(page: Page) -> None:
    reworded = {
        "before": "The organisation encrypts data.",
        "after": "We encrypt data.",
        "changed": True,
        "failed": False,
    }
    page.route(
        "**/api/preferences/try",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(reworded)),
    )
    in_arabic(page)
    page.goto("/preferences")
    page.locator("input[name=tone][value=formal]").check()
    expect(page.locator("#asks")).to_have_attribute("data-no-translate", "")
    trying = page.locator("#preferencesTry")

    page.click("#tryPreferences")
    expect(trying.locator("h4")).to_have_text("تجربة تفضيلاتك على مثال. لا يُحفظ شيء.")
    expect_arabic(page, "trying the preferences on a sample")

    trying.get_by_role("button", name="إعادة صياغتها").click()
    expect(trying.locator(".compare")).to_be_visible()
    expect(trying.locator(".compare .side.after p")).to_have_text("We encrypt data.")
    expect_arabic(page, "the sample, reworded")

    trying.locator("select").select_option("3")  # one of your own
    trying.get_by_role("button", name="إعادة صياغتها").click()
    expect(trying.locator(".status")).to_have_text("الصق سؤالاً وإجابة لتجربتها عليهما.")
    expect_arabic(page, "one's own sample, with nothing pasted")


def test_skills_in_arabic(page: Page) -> None:
    in_arabic(page)
    page.goto("/preferences")
    expect(page.locator("#ownSkills .empty")).to_be_visible()
    builtin = page.locator("#builtinSkills .skill").first
    builtin.locator("summary").click()
    expect(builtin.locator(".instr")).to_be_visible()
    expect(builtin.locator(".instr")).to_have_attribute("data-no-translate", "")
    expect_arabic(page, "a built-in skill's instruction, open")

    builtin.get_by_role("button", name="جرّبها").click()
    expect(builtin.locator(".try h4")).to_have_text("تجربة «تفاصيل للمدقق» على مثال. لا يُحفظ شيء.")
    expect_arabic(page, "trying a built-in skill")

    form = page.locator("#newSkillForm")
    page.locator("#newSkill summary").click()
    expect(form.locator("input").first).to_be_visible()
    expect_arabic(page, "writing a new skill")

    # A name of spaces only: the server's own limit (src/preferences.py), in Arabic. Nothing
    # typed at all is refused by the request's validation instead ("validation_failed"),
    # whose Arabic is ar-server.js's.
    form.locator("input").first.fill("   ")
    form.locator("textarea").fill("Open with Yes or No.")
    form.get_by_role("button", name="حفظ المهارة").click()
    expect(form.locator(".status.err")).to_have_text("تحتاج المهارة إلى اسم.")
    expect_arabic(page, "a skill saved without a name")

    form.locator("input").first.fill("Tailspin format")
    form.locator("textarea").fill("Open with Yes or No. Then one short sentence.")
    form.get_by_role("button", name="حفظ المهارة").click()
    own = page.locator("#ownSkills .skill", has_text="Tailspin format")
    expect(own).to_be_visible()
    expect_arabic(page, "with a skill of one's own")

    asked: list[str] = []
    page.once("dialog", lambda dialog: (asked.append(dialog.message), dialog.dismiss()))
    own.get_by_role("button", name="حذف", exact=True).click()
    expect(own).to_be_visible()
    assert asked and asked[0].startswith("هل تريد حذف المهارة «Tailspin format»؟"), asked

    own.get_by_role("button", name="تعديل").click()
    expect(page.locator("#ownSkills label.field-name").first).to_be_visible()
    expect_arabic(page, "editing a skill")


@pytest.mark.parametrize("width", [1280, 375])
def test_preferences_fit_right_to_left(page: Page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 812})
    in_arabic(page)
    page.goto("/preferences")
    expect(page.locator("#builtinSkills .skill")).to_have_count(4)
    page.click("#tryPreferences")
    page.locator("#newSkill summary").click()
    expect(page.locator("#newSkillForm input").first).to_be_visible()
    fits(page, f"preferences at {width}px")


# --- the language of the pages, chosen in Preferences ---------------------------


def test_the_language_is_chosen_in_preferences_and_kept_with_the_person(page: Page) -> None:
    page.goto("/preferences")
    panel = page.locator("#languagePanel")
    expect(panel).to_contain_text("Language of the pages")
    expect(panel).to_contain_text("Answers are not changed by it: they follow the question’s language.")
    expect(page.locator("input[name=interface_language][value=en]")).to_be_checked()

    panel.get_by_text("العربية").click()

    expect(page.locator("html")).to_have_attribute("dir", "rtl")
    expect(page.locator("input[name=interface_language][value=ar]")).to_be_checked()
    expect(panel).to_contain_text("لغة الصفحات")
    assert chosen() == "ar", "kept with the person, not only on this device"
    assert page.request.get("/api/auth/session").json()["interface_language"] == "ar"
    expect_arabic(page, "after choosing Arabic in Preferences")

    panel.get_by_text("English").click()

    expect(page.locator("html")).to_have_attribute("dir", "ltr")
    expect(page.locator("input[name=interface_language][value=en]")).to_be_checked()
    expect(panel).to_contain_text("Language of the pages")
    assert chosen() == "en"
    assert page.request.get("/api/auth/session").json()["interface_language"] == "en"


def test_the_language_choice_in_arabic_brings_english_back(page: Page) -> None:
    in_arabic(page)
    page.goto("/preferences")
    panel = page.locator("#languagePanel")
    expect(page.locator("input[name=interface_language][value=ar]")).to_be_checked()
    expect(panel).to_contain_text("لا تتغير بها الإجابات: فهي تتبع لغة السؤال.")
    expect_arabic(page, "the language panel", within="#languagePanel")

    panel.get_by_text("English").click()

    expect(page.locator("html")).to_have_attribute("dir", "ltr")
    expect(page).to_have_title("Preferences — Assessment Answering")
    assert chosen() == "en"


def test_switching_with_unsaved_preferences_asks_first(page: Page) -> None:
    page.goto("/preferences")
    page.locator("input[name=tone][value=formal]").check()
    expect(page.locator("#preferencesStatus")).to_have_text("Not saved yet.")
    asked: list[str] = []
    page.once("dialog", lambda dialog: (asked.append(dialog.message), dialog.dismiss()))

    page.locator("#languagePanel").get_by_text("العربية").click()

    expect(page.locator("input[name=interface_language][value=en]")).to_be_checked()
    assert asked and "not saved" in asked[0], asked
    expect(page.locator("html")).to_have_attribute("dir", "ltr")
    expect(page.locator("input[name=tone][value=formal]")).to_be_checked()  # the typing is still there
    assert chosen() == "en"

    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#languagePanel").get_by_text("العربية").click()
    expect(page.locator("html")).to_have_attribute("dir", "rtl")
    assert chosen() == "ar"


# --- products -----------------------------------------------------------------


def give_it_work(product: products.Product) -> None:
    """A document with its file, an answer moved in from Shared, and a questionnaire."""
    service.save_upload("Availo policy.pdf", b"%PDF-1.4 availo", TEAM, product_id=product.id)
    holding(product.id, chunk("Availo policy.pdf"))
    entry = answer_memory.record("Is MFA enforced?", "Yes.", team_id=TEAM, product_id=product.id, index=False)
    lead = identity.find_user(LEAD)
    events.record(
        lead, events.MEMORY_EDITED, subject_type="memory_entry", subject_id=entry.entry_id, moved_to=product.id
    )
    form = DetectedForm(source_name="Vendor.xlsx", format="xlsx")
    batches.create(User(email=MEMBER, team_id=TEAM), settings.upload_dir / "Vendor.xlsx", form, product.id)


def test_products_in_arabic_for_a_member(page: Page, stores, team) -> None:
    products.add(identity.find_user(LEAD), TEAM, "Msegat", description="Bulk messaging")
    in_arabic(page, person=False)
    sign_in(page, MEMBER, "/products")
    expect(page.locator(".product", has_text="Msegat")).to_be_visible()
    expect(page.locator("#addPanel")).to_be_hidden()
    expect(page.locator("#listHint")).to_have_text("لا يستطيع تغيير المنتجات إلا قادة الفريق ومسؤولو النظام.")
    expect_arabic(page, "for a member")


def test_products_in_arabic_for_a_lead_who_adds_and_deletes_one(page: Page, stores, team) -> None:
    in_arabic(page, person=False)
    sign_in(page, LEAD, "/products")
    expect(page.locator("#productList .empty")).to_be_visible()
    expect_arabic(page, "with no products")

    page.click("#addProduct")  # no name: the server's sentence, ar-server.js's
    expect(page.locator("#addStatus.error")).not_to_be_empty()
    expect_arabic(page, "a product added without a name")

    page.fill("#productName", "Availo")
    page.fill("#productDescription", "Payments for merchants")
    page.click("#addProduct")
    expect(page.locator("#addStatus")).to_have_text("تمت إضافة Availo.")
    card = page.locator(".product", has_text="Availo")
    expect(card.locator(".meta")).to_contain_text(f"أضافه {LEAD} في ")
    expect(card.locator(".meta [dir=auto]")).to_have_count(2)  # the address, and the date kept in its order
    expect_arabic(page, "with a product")

    card.get_by_role("button", name="تعديل").click()
    expect(page.locator("#productList .fields")).to_be_visible()
    expect_arabic(page, "editing a product")
    page.locator("#productList").get_by_role("button", name="إلغاء").click()

    give_it_work(products.list_products(TEAM)[0])
    page.locator(".product", has_text="Availo").get_by_role("button", name="حذف", exact=True).click()
    dialog = page.locator("#deleteDialog")
    expect(dialog).to_be_visible()
    warning = dialog.locator(".danger-box")
    expect(warning).to_contain_text("قاعدة معرفته: وثيقة واحدة (مقطع واحد)، وملفها على الخادم.")
    expect(warning).to_contain_text("ذاكرة إجاباته: إجابة محفوظة واحدة، منها ما نُقل إليها من «المشتركة»: 1.")
    expect(dialog.locator("#deleteStays")).to_contain_text("ما يبقى: استبيان واحد و0 محادثة للمنتج Availo")
    expect(dialog.locator("#deleteLabel")).to_have_text("اكتب تأكيد لحذف Availo وكل ما ورد أعلاه")
    expect_arabic(page, "the warning before deleting", within="#deleteDialog")

    # The word in Arabic, and the English one a person may have read elsewhere.
    go = dialog.get_by_role("button", name="حذف نهائي")
    expect(go).to_be_disabled()
    for typed, ready in (("تأك", False), ("تأكيد", True), ("confirm", True), ("conf", False), ("تاكيد", True)):
        page.fill("#deleteConfirm", typed)
        if ready:
            expect(go, f"typed {typed!r}").to_be_enabled()
        else:
            expect(go, f"typed {typed!r}").to_be_disabled()
    go.click()  # with "تاكيد" typed: the server is sent its own word

    expect(dialog).to_be_hidden()
    expect(page.locator("#listStatus")).to_have_text(
        "حُذف Availo. ما أُزيل: ملف واحد وإجابة محفوظة واحدة؛ وما بقي للقراءة فقط: استبيان واحد و0 محادثة."
    )
    assert products.list_products(TEAM) == []
    expect_arabic(page, "after deleting a product")


def test_the_delete_warning_in_arabic_when_the_counts_cannot_be_read(page: Page, stores, team) -> None:
    products.add(identity.find_user(LEAD), TEAM, "Msegat")
    page.route("**/deletion", failing)
    in_arabic(page, person=False)
    sign_in(page, LEAD, "/products")
    page.locator(".product", has_text="Msegat").get_by_role("button", name="حذف", exact=True).click()
    dialog = page.locator("#deleteDialog")
    expect(dialog.locator("#deleteStatus")).to_have_text(
        "تعذّر حصر ما سيُحذف (تعذّر تنفيذ الطلب (500)). سيزيل الحذف مع ذلك كل ما ورد."
    )
    expect(dialog.locator(".danger-box")).to_contain_text("قاعدة معرفته: كل وثيقة")
    expect_arabic(page, "the warning, with nothing counted", within="#deleteDialog")

    page.fill("#deleteConfirm", "تأكيد")
    dialog.get_by_role("button", name="حذف نهائي").click()
    expect(dialog).to_be_hidden()
    assert products.list_products(TEAM) == []


@pytest.mark.parametrize("width", [1280, 375])
def test_products_fit_right_to_left(page: Page, stores, team, width: int) -> None:
    products.add(identity.find_user(LEAD), TEAM, "Msegat", description="Bulk messaging for every channel")
    products.add(identity.find_user(LEAD), TEAM, "Availo")
    page.set_viewport_size({"width": width, "height": 812})
    in_arabic(page, person=False)
    sign_in(page, LEAD, "/products")
    expect(page.locator(".product")).to_have_count(2)
    fits(page, f"products at {width}px")
    page.locator(".product", has_text="Msegat").get_by_role("button", name="حذف", exact=True).click()
    expect(page.locator("#deleteDialog #deleteStays")).not_to_be_empty()
    fits(page, f"the delete warning at {width}px")
