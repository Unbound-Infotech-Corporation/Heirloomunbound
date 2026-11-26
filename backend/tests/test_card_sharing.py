"""Owner sharing of approved memory cards with heirs, the default setting, and family names."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import card_sharing as cs  # noqa: E402
import heir_grounding as hg  # noqa: E402
import life_story as ls  # noqa: E402
import memory_cards as mc  # noqa: E402
from tests.test_heir_grounding import FERRIS, HEIR, OWNER, fake_model  # noqa: E402


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _no_embeddings(monkeypatch):
    # Keyword recall only: a box with a live embedding model would otherwise match "adored Grandma" to June by meaning.
    monkeypatch.setattr(mc, "should_embed", lambda *a, **k: False)


def _match(doc, query):
    for key, want in (query or {}).items():
        have = doc.get(key)
        if isinstance(want, dict) and "$in" in want:
            if have not in want["$in"]:
                return False
        elif have != want:
            return False
    return True


class Coll:
    def __init__(self, docs=()):
        self.docs = [dict(d) for d in docs]

    async def find_one(self, query, projection=None):
        return next((dict(d) for d in self.docs if _match(d, query)), None)

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def update_one(self, query, update, upsert=False):
        for d in self.docs:
            if _match(d, query):
                d.update(update.get("$set") or {})
                return
        if upsert:
            self.docs.append({**query, **(update.get("$set") or {})})

    async def count_documents(self, query):
        return sum(1 for d in self.docs if _match(d, query))


class Store:
    def __init__(self, cards=(), heirs=(), users=()):
        self.memory_cards, self.heirs, self.users, self.entries = Coll(cards), Coll(heirs), Coll(users), Coll()


EMMA = {"heir_id": "h_emma", "user_id": "u1", "name": "Emma"}
SAM = {"heir_id": "h_sam", "user_id": "u1", "name": "Sam"}


def card(cid="c1", status="approved", **kw):
    return {"card_id": cid, "user_id": "u1", "status": status, "visibility": "owner", "title": "T",
            "story": "June and I met at the State Fair.", "people": [], "era": "", **kw}


def who(store, heir_id):
    return [c["card_id"] for c in hg.heir_cards(store.memory_cards.docs, heir_id)]


def test_new_approved_cards_are_owner_only_and_nobody_hears_them():
    store = Store([card()], [EMMA, SAM])
    assert who(store, "h_emma") == [] and who(store, "h_sam") == []


def test_share_with_all_heirs_then_pick_specific_then_unshare():
    store = Store([card()], [EMMA, SAM])
    run(cs.share_cards(store, "u1", ["c1"], "family", []))
    assert who(store, "h_emma") == ["c1"] and who(store, "h_sam") == ["c1"]
    run(cs.share_cards(store, "u1", ["c1"], "family", ["h_emma"]))
    assert who(store, "h_emma") == ["c1"] and who(store, "h_sam") == []
    out = run(cs.share_cards(store, "u1", ["c1"], "owner", ["h_emma"]))  # unshare also clears the list
    assert out["heir_ids"] == [] and who(store, "h_emma") == [] and store.memory_cards.docs[0]["heir_ids"] == []


def test_bulk_share_skips_pending_and_other_owners_and_unknown_heirs_are_refused():
    store = Store([card("a"), card("b"), card("p", status="pending"), card("x", user_id="u2")], [EMMA, SAM])
    out = run(cs.share_cards(store, "u1", ["a", "b", "p", "x", "missing"], "family", []))
    assert out["shared"] == ["a", "b"]
    by = {c["card_id"]: c for c in store.memory_cards.docs}
    assert by["p"]["visibility"] == "owner" and by["x"]["visibility"] == "owner"
    with pytest.raises(ValueError, match="Unknown heir"):
        run(cs.share_cards(store, "u1", ["a"], "family", ["h_nobody"]))
    with pytest.raises(ValueError):
        run(cs.share_cards(store, "u1", ["a"], "public", []))
    # An heir that belongs to another owner is not "known".
    store.heirs.docs.append({"heir_id": "h_far", "user_id": "u2", "name": "Far"})
    with pytest.raises(ValueError, match="Unknown heir"):
        run(cs.share_cards(store, "u1", ["a"], "family", ["h_far"]))


def test_default_is_off_and_turning_it_on_shares_only_cards_approved_afterwards():
    async def complete(system, user):
        return json.dumps({"title": "Fair", "era": "", "people": [], "story": "We met at the State Fair."})

    store = Store(heirs=[EMMA], users=[{"user_id": "u1"}])
    assert run(cs.get_default(store, "u1")) is False
    first = run(ls.draft_pending_card("u1", "We met at the State Fair in 1961.", "How did you meet?", complete, source="interview"))
    run(store.memory_cards.insert_one(first))
    run(ls.approve_card(store, "u1", first["card_id"]))
    assert who(store, "h_emma") == []                      # off: owner-only
    assert run(cs.set_default(store, "u1", True)) is True and run(cs.get_default(store, "u1")) is True
    second = run(ls.draft_pending_card("u1", "We danced at the fair.", "What did you do?", complete, source="interview"))
    run(store.memory_cards.insert_one(second))
    run(ls.approve_card(store, "u1", second["card_id"]))
    assert who(store, "h_emma") == [second["card_id"]]     # on: shared with all heirs
    assert [c for c in store.memory_cards.docs if c["card_id"] == first["card_id"]][0]["visibility"] == "owner"
    run(cs.set_default(store, "u1", False))
    assert run(cs.get_default(store, "u1")) is False
    assert who(store, "h_emma") == [second["card_id"]]     # turning it off does not unshare


def test_editing_or_reapproving_never_changes_who_can_hear_a_card():
    shared = card(visibility="family", heir_ids=["h_emma"])
    again = mc.approve_fields(shared, {"story": "June and I met at the State Fair in 1961."})
    assert again["visibility"] == "family" and again["heir_ids"] == ["h_emma"]
    assert mc.approve_fields(card())["visibility"] == "owner"
    assert mc.approve_fields(card(status="pending"), share_new=True)["visibility"] == "family"


def test_a_shared_cards_vault_entry_stays_owner_private():
    store = Store(heirs=[EMMA], users=[{"user_id": "u1", "share_new_cards_with_heirs": True}])
    c = card("n", status="pending")
    run(store.memory_cards.insert_one(c))
    run(ls.approve_card(store, "u1", "n"))
    assert store.entries.docs[0]["visibility"] == "owner"


# ---- family names (aliases)

SAM_HEIR = {"heir_id": "h_sam", "name": "Sam", "relationship": "grandson",
            "names": [{"person": "June", "called": "Grandma"}]}


def test_family_names_are_cleaned():
    got = hg.clean_family_names([{"person": " June ", "called": "Grandma"}, {"person": "june", "called": "grandma"},
                                 {"person": "", "called": "x"}, {"person": "Walt", "called": "Walt"}, {}])
    assert got == [{"person": "June", "called": "Grandma"}]
    assert hg.alias_lines(SAM_HEIR) == ['Sam calls June "Grandma".']
    assert hg.expand_aliases("Tell me about the day you met Grandma.", SAM_HEIR) == \
        "Tell me about the day you met Grandma (June)."
    assert hg.expand_aliases("Tell me about June", SAM_HEIR) == "Tell me about June"
    assert hg.expand_aliases("Hello", HEIR) == "Hello"


def _recall(heir, text="Tell me about the day you adored Grandma."):
    rows = hg.heir_cards([FERRIS], heir["heir_id"])
    answer = "June and I met at the State Fair. We got stuck together at the top of the Ferris wheel."

    async def draft(used):
        return answer

    return run(hg.heir_reply(text, owner=OWNER, heir=heir, rows=rows, draft=draft, ask=fake_model(answer)))


def test_grandma_alias_lets_the_twin_find_the_june_memory():
    without = _recall({**SAM_HEIR, "names": []})
    assert without["reply"] == "I don't have that memory yet." and without["cited"] == []
    out = _recall(SAM_HEIR)
    assert out["cited"] and out["cited"][0]["id"] == "c_ferris" and "Ferris wheel" in out["reply"]


def test_an_alias_is_a_name_not_a_fact():
    # Knowing Sam calls June "Grandma" must not let the Twin invent a story about her.
    async def draft(used):
        return "Grandma June loved baking pies for the church picnic every Sunday."

    out = run(hg.heir_reply("Tell me about Grandma.", owner=OWNER, heir=SAM_HEIR, rows=[], draft=draft,
                            ask=fake_model("Grandma June loved baking pies for the church picnic every Sunday.")))
    assert "pies" not in out["reply"] and out["cited"] == []


def test_names_route_is_owner_authenticated_and_stores_cleaned_names_only():
    src = (Path(__file__).resolve().parents[1] / "routers" / "heirs.py").read_text()
    block = src.split("async def set_family_names", 1)
    assert "Depends(get_current_user)" in block[1].split("\n", 1)[0]
    assert "clean_family_names" in block[1] and '{"$set": {"names": names}}' in block[1]
