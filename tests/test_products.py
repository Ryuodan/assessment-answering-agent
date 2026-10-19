"""Products and the team lead (plan 020): the records, the rules, the routes and the upgrade."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import answer_memory, batches, conversations, events, identity, knowledge, products, roles, service, store
from src import uploads
from src.api import app
from src.config import settings
from src.errors import Invalid, ProductNameTaken, ProductNotFound
from src.forms.model import DetectedForm
from src.identity import User
from tests.conftest import FakeVectorStore, bare_store

TEAM = settings.default_team
CODE = "TEAM-CODE-FOR-TESTS"
MEMBER = "member@example.test"
LEAD = "lead@example.test"
ADMIN = "admin@example.test"
ADMIN_PASSWORD = "an-admin-password-for-tests"


@pytest.fixture
def admin() -> identity.User:
    identity.ensure_team(TEAM)
    return identity.add_user(ADMIN, role=roles.ADMIN, password=ADMIN_PASSWORD)


# --- the records ---------------------------------------------------------------


def test_a_product_is_added_listed_edited_and_deleted(admin) -> None:
    added = products.add(admin, TEAM, "  Availo  ", description="Payments")
    assert (added.name, added.description, added.color) == ("Availo", "Payments", products.PALETTE[0])
    assert [p.name for p in products.list_products(TEAM)] == ["Availo"]

    changed = products.update(admin, TEAM, added.id, name="Availo Pay", color="#ABCDEF")
    assert (changed.name, changed.color, changed.description) == ("Availo Pay", "#abcdef", "Payments")

    deleted = products.delete(admin, TEAM, added.id, confirm="confirm")
    assert deleted.product.name == "Availo Pay"
    assert products.list_products(TEAM) == []


def test_a_name_is_unique_in_a_team_whatever_its_case_arabic_included(admin) -> None:
    products.add(admin, TEAM, "RICH")
    products.add(admin, TEAM, "منتج")
    with pytest.raises(ProductNameTaken):
        products.add(admin, TEAM, "rich")
    with pytest.raises(ProductNameTaken):
        products.add(admin, TEAM, " منتج ")
    identity.ensure_team("privacy")
    assert products.add(admin, "privacy", "RICH").name == "RICH", "another team may use the same name"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"name": ""}, "product_name_invalid"),
        ({"name": "x" * 41}, "product_name_invalid"),
        ({"color": "blue"}, "product_color_invalid"),
        ({"description": "x" * 201}, "product_description_too_long"),
    ],
)
def test_what_a_product_may_be(admin, change: dict[str, str], code: str) -> None:
    fields = {"name": "Ole5", "color": "", "description": ""} | change
    with pytest.raises(Invalid) as refused:
        products.add(admin, TEAM, **fields)
    assert refused.value.code == code


def test_deleting_needs_the_word_and_a_product_of_this_team(admin) -> None:
    added = products.add(admin, TEAM, "Msegat")
    for typed in ("", "yes", "Msegat"):
        with pytest.raises(Invalid) as refused:
            products.delete(admin, TEAM, added.id, confirm=typed)
        assert refused.value.code == "confirmation_required"
    identity.ensure_team("privacy")
    with pytest.raises(ProductNotFound):
        products.delete(admin, "privacy", added.id, confirm="confirm")
    assert products.delete(admin, TEAM, added.id, confirm=" Confirm ").product.name == "Msegat"


def test_seeding_happens_once_and_a_deleted_product_stays_deleted(admin, monkeypatch) -> None:
    monkeypatch.setattr(settings, "seed_products", "Availo, Msegat,Ole5,RICH,SouqT2")
    assert [p.name for p in products.seed()] == ["Availo", "Msegat", "Ole5", "RICH", "SouqT2"]
    assert len({p.color for p in products.list_products(TEAM)}) == 5, "each gets its own colour"

    rich = next(p for p in products.list_products(TEAM) if p.name == "RICH")
    products.delete(admin, TEAM, rich.id, confirm="confirm")
    assert products.seed() == []
    assert "RICH" not in [p.name for p in products.list_products(TEAM)]


def test_who_manages_products() -> None:
    assert roles.manages_products(roles.ADMIN, "a", "b"), "an administrator, any team"
    assert roles.manages_products(roles.LEAD, "a", "a"), "a lead, their own team"
    assert not roles.manages_products(roles.LEAD, "a", "b")
    assert not roles.manages_products(roles.MEMBER, "a", "a")


def test_a_version_10_database_upgrades_and_keeps_its_data() -> None:
    conn = store.connect()
    tables = [
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    ]
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript("".join(f"DROP TABLE IF EXISTS {name};" for name in tables))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA user_version = 0")
    for index, step in enumerate(store.MIGRATIONS[:10]):
        getattr(store.migrations, step)(conn) if step.startswith("_") else conn.executescript(step)
        conn.execute(f"PRAGMA user_version = {index + 1}")
    conn.execute("INSERT INTO teams (id, created_at) VALUES (?, '2026-01-01T00:00:00+00:00')", (TEAM,))
    conn.commit()
    store.reset_connection()

    upgraded = store.connect()
    assert upgraded.execute("PRAGMA user_version").fetchone()[0] == len(store.MIGRATIONS) >= 11
    assert upgraded.execute("SELECT id FROM teams").fetchone()[0] == TEAM
    assert upgraded.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0


# --- the routes ------------------------------------------------------------------


@pytest.fixture
def gated(admin) -> None:
    """Sign-in on, a member, a team lead and an administrator."""
    identity.set_access_code(TEAM, CODE)
    identity.add_user(MEMBER)
    identity.add_user(LEAD, role=roles.LEAD)


def signed_in(email: str, secret: str = CODE) -> TestClient:
    client = TestClient(app)
    assert client.post("/api/auth/session", json={"email": email, "code": secret}).status_code == 200
    return client


def test_everyone_on_the_team_lists_but_only_leads_and_administrators_change(gated) -> None:
    member, lead, admin_client = signed_in(MEMBER), signed_in(LEAD), signed_in(ADMIN, ADMIN_PASSWORD)

    listed = member.get("/api/products").json()
    assert listed["products"] == [] and listed["can_manage"] is False
    refused = member.post("/api/products", json={"name": "Availo"})
    assert (refused.status_code, refused.json()["code"]) == (403, "product_manager_required")

    assert lead.get("/api/products").json()["can_manage"] is True
    added = lead.post("/api/products", json={"name": "Availo", "color": "#123456"}).json()["product"]
    assert admin_client.patch(f"/api/products/{added['id']}", json={"description": "Pay"}).status_code == 200
    assert member.patch(f"/api/products/{added['id']}", json={"name": "x"}).status_code == 403
    assert member.delete(f"/api/products/{added['id']}?confirm=confirm").status_code == 403

    taken = lead.post("/api/products", json={"name": "AVAILO"})
    assert (taken.status_code, taken.json()["code"]) == (409, "product_name_taken")
    unconfirmed = lead.delete(f"/api/products/{added['id']}")
    assert (unconfirmed.status_code, unconfirmed.json()["code"]) == (400, "confirmation_required")
    assert lead.delete(f"/api/products/{added['id']}?confirm=confirm").json()["deleted"]["name"] == "Availo"
    gone = lead.delete(f"/api/products/{added['id']}?confirm=confirm")
    assert (gone.status_code, gone.json()["code"]) == (404, "product_not_found")


def test_a_lead_works_on_their_own_team_and_an_administrator_on_any(gated) -> None:
    identity.ensure_team("privacy")
    lead, admin_client = signed_in(LEAD), signed_in(ADMIN, ADMIN_PASSWORD)

    other = lead.post("/api/products?team=privacy", json={"name": "Ole5"})
    assert (other.status_code, other.json()["code"]) == (403, "other_team")
    assert admin_client.post("/api/products?team=privacy", json={"name": "Ole5"}).status_code == 200
    assert [p["name"] for p in admin_client.get("/api/products?team=privacy").json()["products"]] == ["Ole5"]
    assert lead.get("/api/products").json()["products"] == [], "the lead's own team has none"
    missing = admin_client.get("/api/products?team=nobody")
    assert (missing.status_code, missing.json()["code"]) == (404, "team_not_found")


# --- what deleting one takes, counted first (plan 027) ---------------------------


@pytest.fixture
def stores(monkeypatch) -> dict:
    """A fake index per (team, product). A move's sweep is left out: it is a model call."""
    made: dict[tuple[str, str], knowledge.KnowledgeStore] = {}

    def get_store(team_id=None, *, product_id=""):
        key = (team_id or TEAM, product_id)
        if key not in made:
            made[key] = bare_store(FakeVectorStore([]))
            made[key]._store.delete_collection = lambda key=key: made.pop(key, None)
        return made[key]

    async def no_sweep() -> None:
        return None

    monkeypatch.setattr("src.knowledge.get_store", get_store)
    monkeypatch.setattr("src.routes.memory.scan_memory", no_sweep)
    return made


def a_product_with_work(lead: TestClient) -> products.Product:
    """Availo: two files in its folder and one from before it had a folder, three
    remembered answers (one moved in from Shared), two questionnaires (one a
    colleague's) and a chat."""
    availo = products.add(identity.find_user(LEAD), TEAM, "Availo")
    for name in ("Availo policy.pdf", "Availo standard.docx"):
        service.save_upload(name, b"%PDF-1.4 " + name.encode(), TEAM, product_id=availo.id)
    (settings.team_upload_dir(TEAM) / "Availo legacy.pdf").write_bytes(b"%PDF-1.4 from before")
    index = knowledge.get_store(TEAM, product_id=availo.id)._store
    for name, chunk in (("Availo policy.pdf", 0), ("Availo policy.pdf", 1), ("Availo standard.docx", 0)):
        metadata = {"source_name": name, "source_type": "guideline", "chunk": chunk}
        index.records.append({"text": name, "metadata": metadata, "id": f"{name}:{chunk}"})
    metadata = {"source_name": "Availo legacy.pdf", "source_type": "guideline", "chunk": 0}
    index.records.append({"text": "legacy", "metadata": metadata, "id": "legacy"})

    shared = answer_memory.record("Is MFA enforced?", "Yes, for every account.", team_id=TEAM)
    answer_memory.record("Do you pen-test?", "Yes, yearly.", team_id=TEAM, product_id=availo.id)
    answer_memory.record("Is data encrypted?", "Yes, AES-256.", team_id=TEAM, product_id=availo.id)
    assert lead.post(f"/api/memory/{shared.entry_id}/move", json={"product": availo.id}).status_code == 200

    form = DetectedForm(source_name="Vendor.xlsx", format="xlsx")
    for email in (LEAD, MEMBER):
        batches.create(User(email=email, team_id=TEAM), settings.upload_dir / "Vendor.xlsx", form, availo.id)
    conversations.create(User(email=MEMBER, team_id=TEAM), "Do we encrypt backups?", product_id=availo.id)
    return availo


def test_the_deletion_preview_counts_what_goes_and_what_returns_to_general(gated, stores) -> None:
    lead, member = signed_in(LEAD), signed_in(MEMBER)
    availo = a_product_with_work(lead)

    response = lead.get(f"/api/products/{availo.id}/deletion")

    assert response.status_code == 200
    preview = response.json()
    assert (preview["product"]["name"], preview["confirm_word"]) == ("Availo", "confirm")
    assert preview["documents"] == {
        "files": 3,
        "names": ["Availo legacy.pdf", "Availo policy.pdf", "Availo standard.docx"],
        "indexed": 3,
        "chunks": 4,
    }
    assert preview["answers"] == {"remembered": 3, "moved_from_shared": 1}
    assert (preview["questionnaires"], preview["conversations"]) == (2, 1), "everyone's, not only the lead's"

    refused = member.get(f"/api/products/{availo.id}/deletion")
    assert (refused.status_code, refused.json()["code"]) == (403, "product_manager_required")
    identity.ensure_team("privacy")
    theirs = products.add(None, "privacy", "Ole5")
    absent = lead.get(f"/api/products/{theirs.id}/deletion")
    assert (absent.status_code, absent.json()["code"]) == (404, "product_not_found")

    assert lead.get(f"/api/products/{availo.id}/deletion").json() == preview, "counting changes nothing"
    assert [p.name for p in products.list_products(TEAM)] == ["Availo"]
    assert len(uploads.document_files(settings.product_upload_dir(TEAM, availo.id))) == 2
    assert (settings.team_upload_dir(TEAM) / "Availo legacy.pdf").exists()


def test_deleting_reports_what_it_removed(gated, stores) -> None:
    lead = signed_in(LEAD)
    availo = a_product_with_work(lead)
    preview = lead.get(f"/api/products/{availo.id}/deletion").json()

    response = lead.delete(f"/api/products/{availo.id}?confirm=confirm").json()

    assert response["deleted"]["name"] == "Availo"
    assert response["removed"] == {
        "files_removed": preview["documents"]["files"],
        "files_left": [],
        "answers_forgotten": preview["answers"]["remembered"],
        "moved_from_shared": preview["answers"]["moved_from_shared"],
        "questionnaires": preview["questionnaires"],
        "conversations": preview["conversations"],
    }
    assert events.recent(TEAM, kind=events.PRODUCT_DELETED)[0].payload == {"name": "Availo", **response["removed"]}
    assert not settings.product_upload_dir(TEAM, availo.id).exists()
    assert not (settings.team_upload_dir(TEAM) / "Availo legacy.pdf").exists()


def test_an_administrator_can_make_someone_a_team_lead_but_not_demote_the_last_administrator(gated) -> None:
    admin_client = signed_in(ADMIN, ADMIN_PASSWORD)
    assert admin_client.patch(f"/api/admin/users/{MEMBER}", json={"role": "lead"}).json()["role"] == "lead"
    assert identity.find_user(MEMBER).role == roles.LEAD
    refused = admin_client.patch(f"/api/admin/users/{ADMIN}", json={"role": "lead"})
    assert (refused.status_code, refused.json()["code"]) == (400, "last_administrator")


def test_the_page_is_served() -> None:
    page = TestClient(app).get("/products")
    assert page.status_code == 200 and 'id="deleteDialog"' in page.text
    assert 'id="deleteConsequences"' in page.text, "the counted list of what deleting takes"
