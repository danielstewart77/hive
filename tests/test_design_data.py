"""Tests for the design-session store.

Every test here drives `design_data` itself. The store is the whole of the
protection Daniel is buying — a revision that cannot overwrite what he left
alone, a save that cannot clobber another tab, a Build that cannot be sent
twice — so these assert on what it stored, never on what a caller passed in.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import design_data


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("HIVE_DB_PATH", str(tmp_path / "hive.db"))
    return design_data


def _requirements(*texts: str) -> dict:
    return {
        f"r{index}": {"order": index, "text": text}
        for index, text in enumerate(texts, start=1)
    }


# --- Requirement 1, 2: the list and its lifetime -----------------------------


def test_listing_reports_title_binding_and_recency(store):
    first = store.create_design_session("Older design", conversation_id="conv-a")
    second = store.create_design_session("Newer design", conversation_id="conv-b")

    listed = store.list_design_sessions()

    assert [row["id"] for row in listed] == [second["id"], first["id"]]
    assert [row["title"] for row in listed] == ["Newer design", "Older design"]
    assert [row["conversation_id"] for row in listed] == ["conv-b", "conv-a"]
    assert listed[0]["updated_at"] >= listed[1]["updated_at"]


def test_reading_a_design_session_does_not_move_it_up_the_list(store):
    first = store.create_design_session("First")
    second = store.create_design_session("Second")

    store.get_design_session(first["id"])

    assert [row["id"] for row in store.list_design_sessions()] == [
        second["id"],
        first["id"],
    ]


def test_delete_removes_the_session(store):
    record = store.create_design_session("Doomed")

    store.delete_design_session(record["id"])

    assert store.list_design_sessions() == []


def test_delete_of_an_id_the_store_does_not_hold_is_refused(store):
    record = store.create_design_session("Doomed")
    store.delete_design_session(record["id"])
    absent = record["id"]
    assert absent not in {row["id"] for row in store.list_design_sessions()}

    with pytest.raises(store.DesignNotFound):
        store.delete_design_session(absent)


# --- Requirement 3, 7: re-binding --------------------------------------------


def test_rebinding_keeps_the_same_record_and_its_content(store):
    record = store.create_design_session("Design", conversation_id="conv-old")
    published = store.publish_page(
        record["id"],
        "requirements",
        _requirements("The page lists design sessions"),
        revision=record["revision"],
    )

    rebound = store.attach_design_session(
        record["id"], "conv-new", surface="telegram"
    )

    assert rebound["id"] == record["id"]
    assert rebound["conversation_id"] == "conv-new"
    assert rebound["surface"] == "telegram"
    assert rebound["requirements"] == published["requirements"]


# --- Requirement 8, 9, 10, 12, 13: the requirements loop ----------------------


def test_published_requirements_read_back_in_display_order(store):
    record = store.create_design_session("Design")

    published = store.publish_page(
        record["id"],
        "requirements",
        {
            "r2": {"order": 2, "text": "Second"},
            "r1": {"order": 1, "text": "First"},
        },
        revision=record["revision"],
    )

    assert [item["text"] for item in store.ordered_items(published, "requirements")] == [
        "First",
        "Second",
    ]


def test_submitting_replaces_the_minds_wording_with_daniels(store):
    record = store.create_design_session("Design")
    published = store.publish_page(
        record["id"],
        "requirements",
        _requirements("Sessions are listed", "Sessions can be deleted"),
        revision=record["revision"],
    )

    submitted = store.submit_page(
        published["id"],
        "requirements",
        items={
            "r1": {"text": "Every design session is listed"},
            "r2": {"feedback": "Does delete remove the notices too?"},
        },
        revision=published["revision"],
    )

    assert submitted["requirements"]["r1"]["text"] == "Every design session is listed"
    assert (
        submitted["requirements"]["r2"]["feedback"]
        == "Does delete remove the notices too?"
    )
    assert submitted["requirements"]["r2"]["text"] == "Sessions can be deleted"


def test_a_revision_clears_feedback_and_keeps_the_question_beside_its_answer(store):
    record = store.create_design_session("Design")
    published = store.publish_page(
        record["id"],
        "requirements",
        _requirements("Sessions are listed"),
        revision=record["revision"],
    )
    submitted = store.submit_page(
        published["id"],
        "requirements",
        items={"r1": {"feedback": "Listed in what order?"}},
        revision=published["revision"],
    )

    revised = store.publish_page(
        submitted["id"],
        "requirements",
        {
            "r1": {
                "order": 1,
                "text": "Sessions are listed, most recently written first",
                "answer": "Most recently written first.",
            }
        },
        revision=submitted["revision"],
    )

    item = revised["requirements"]["r1"]
    assert item["feedback"] == ""
    assert item["question_answered"] == "Listed in what order?"
    assert item["answer"] == "Most recently written first."
    assert item["text"] == "Sessions are listed, most recently written first"


# --- Requirement 31: a revision may only change what Daniel touched ----------


def test_a_revision_refuses_to_rewrite_a_requirement_with_no_feedback(store):
    record = store.create_design_session("Design")
    published = store.publish_page(
        record["id"],
        "requirements",
        _requirements("Sessions are listed", "Sessions can be deleted"),
        revision=record["revision"],
    )
    submitted = store.submit_page(
        published["id"],
        "requirements",
        items={"r1": {"feedback": "In what order?"}},
        revision=published["revision"],
    )

    with pytest.raises(store.DesignRefused) as refusal:
        store.publish_page(
            submitted["id"],
            "requirements",
            {
                "r1": {"order": 1, "text": "Sessions are listed newest first"},
                "r2": {"order": 2, "text": "Sessions can be deleted and archived"},
            },
            revision=submitted["revision"],
        )

    assert refusal.value.keys == ["r2"]
    after = store.get_design_session(submitted["id"])
    assert after["requirements"]["r2"]["text"] == "Sessions can be deleted"
    assert after["requirements"]["r1"]["text"] == "Sessions are listed"


def test_a_revision_changes_the_item_that_carries_feedback(store):
    record = store.create_design_session("Design")
    published = store.publish_page(
        record["id"],
        "requirements",
        _requirements("Sessions are listed", "Sessions can be deleted"),
        revision=record["revision"],
    )
    submitted = store.submit_page(
        published["id"],
        "requirements",
        items={"r1": {"feedback": "In what order?"}},
        revision=published["revision"],
    )

    revised = store.publish_page(
        submitted["id"],
        "requirements",
        {
            "r1": {"order": 1, "text": "Sessions are listed newest first"},
            "r2": {"order": 2, "text": "Sessions can be deleted"},
        },
        revision=submitted["revision"],
    )

    assert revised["requirements"]["r1"]["text"] == "Sessions are listed newest first"
    assert revised["requirements"]["r2"]["text"] == "Sessions can be deleted"


def test_an_edit_with_no_question_still_lets_the_mind_revise_that_item(store):
    record = store.create_design_session("Design")
    published = store.publish_page(
        record["id"],
        "requirements",
        _requirements("Sessions are listed"),
        revision=record["revision"],
    )
    submitted = store.submit_page(
        published["id"],
        "requirements",
        items={"r1": {"text": "Every session is listed"}},
        revision=published["revision"],
    )

    revised = store.publish_page(
        submitted["id"],
        "requirements",
        {"r1": {"order": 1, "text": "Every design session is listed"}},
        revision=submitted["revision"],
    )

    assert revised["requirements"]["r1"]["text"] == "Every design session is listed"


def test_a_revision_may_not_delete_a_requirement_daniel_left_alone(store):
    record = store.create_design_session("Design")
    published = store.publish_page(
        record["id"],
        "requirements",
        _requirements("Sessions are listed", "Sessions can be deleted"),
        revision=record["revision"],
    )

    revised = store.publish_page(
        published["id"],
        "requirements",
        {"r1": {"order": 1, "text": "Sessions are listed"}},
        revision=published["revision"],
    )

    assert set(revised["requirements"]) == {"r1", "r2"}


def test_the_mind_owns_the_tests_page_outright(store):
    record = store.create_design_session("Design")
    published = store.publish_page(
        record["id"],
        "tests",
        {"t1": {"order": 1, "sentence": "Listing reports every session"}},
        revision=record["revision"],
    )

    revised = store.publish_page(
        published["id"],
        "tests",
        {"t1": {"order": 1, "sentence": "Listing reports every session, newest first"}},
        revision=published["revision"],
    )

    assert (
        revised["tests"]["t1"]["sentence"]
        == "Listing reports every session, newest first"
    )


# --- Two writers ------------------------------------------------------------


def test_a_write_carrying_a_stale_revision_is_refused(store):
    record = store.create_design_session("Design")
    published = store.publish_page(
        record["id"],
        "requirements",
        _requirements("Sessions are listed"),
        revision=record["revision"],
    )
    stale_revision = published["revision"]
    store.submit_page(
        published["id"],
        "requirements",
        items={"r1": {"feedback": "First tab"}},
        revision=stale_revision,
    )

    with pytest.raises(store.DesignConflict):
        store.submit_page(
            published["id"],
            "requirements",
            items={"r1": {"feedback": "Second tab"}},
            revision=stale_revision,
        )

    after = store.get_design_session(published["id"])
    assert after["requirements"]["r1"]["feedback"] == "First tab"


def test_a_write_with_no_revision_is_refused(store):
    record = store.create_design_session("Design")

    with pytest.raises(store.DesignConflict):
        store.publish_page(
            record["id"], "requirements", _requirements("Sessions are listed")
        )


def test_submissions_against_different_items_both_survive(store):
    record = store.create_design_session("Design")
    published = store.publish_page(
        record["id"],
        "requirements",
        _requirements("One", "Two"),
        revision=record["revision"],
    )

    first = store.submit_page(
        published["id"],
        "requirements",
        items={"r1": {"feedback": "About one"}},
        revision=published["revision"],
    )
    second = store.submit_page(
        first["id"],
        "requirements",
        items={"r2": {"feedback": "About two"}},
        revision=first["revision"],
    )

    assert second["requirements"]["r1"]["feedback"] == "About one"
    assert second["requirements"]["r2"]["feedback"] == "About two"


# --- Staleness --------------------------------------------------------------


def test_editing_a_requirement_marks_the_later_pages_stale(store):
    record = store.create_design_session("Design")
    with_reqs = store.publish_page(
        record["id"],
        "requirements",
        _requirements("Sessions are listed"),
        revision=record["revision"],
    )
    with_tests = store.publish_page(
        with_reqs["id"],
        "tests",
        {"t1": {"order": 1, "sentence": "Listing reports every session"}},
        revision=with_reqs["revision"],
    )

    submitted = store.submit_page(
        with_tests["id"],
        "requirements",
        items={"r1": {"text": "Sessions are listed newest first"}},
        revision=with_tests["revision"],
    )

    assert submitted["stale"]["tests"] is True


def test_a_question_with_no_wording_change_leaves_the_later_pages_fresh(store):
    record = store.create_design_session("Design")
    with_reqs = store.publish_page(
        record["id"],
        "requirements",
        _requirements("Sessions are listed"),
        revision=record["revision"],
    )
    with_tests = store.publish_page(
        with_reqs["id"],
        "tests",
        {"t1": {"order": 1, "sentence": "Listing reports every session"}},
        revision=with_reqs["revision"],
    )

    submitted = store.submit_page(
        with_tests["id"],
        "requirements",
        items={"r1": {"feedback": "Listed in what order?"}},
        revision=with_tests["revision"],
    )

    assert submitted["stale"].get("tests") is not True


def test_republishing_the_tests_page_clears_its_stale_mark(store):
    record = store.create_design_session("Design")
    with_reqs = store.publish_page(
        record["id"],
        "requirements",
        _requirements("Sessions are listed"),
        revision=record["revision"],
    )
    with_tests = store.publish_page(
        with_reqs["id"],
        "tests",
        {"t1": {"order": 1, "sentence": "Listing reports every session"}},
        revision=with_reqs["revision"],
    )
    submitted = store.submit_page(
        with_tests["id"],
        "requirements",
        items={"r1": {"text": "Sessions are listed newest first"}},
        revision=with_tests["revision"],
    )

    republished = store.publish_page(
        submitted["id"],
        "tests",
        {"t1": {"order": 1, "sentence": "Listing reports every session, newest first"}},
        revision=submitted["revision"],
    )

    assert republished["stale"]["tests"] is False


# --- Requirement 18: the tests gate -----------------------------------------


def _resolved_test(name: str, resolved: bool, kind: str = "existing") -> dict:
    return {
        "order": 1,
        "sentence": f"{name} behaves",
        "symbol": {"name": name, "kind": kind, "resolved": resolved},
    }


def test_a_tests_page_naming_a_function_that_resolved_can_be_accepted(store):
    record = store.create_design_session("Design")
    published = store.publish_page(
        record["id"],
        "tests",
        {"t1": _resolved_test("list_design_sessions", True)},
        revision=record["revision"],
    )

    allowed, reason = store.can_advance(published["id"], "tests")

    assert allowed is True
    assert reason == ""


def test_a_tests_page_naming_an_unresolved_function_cannot_be_accepted(store):
    record = store.create_design_session("Design")
    published = store.publish_page(
        record["id"],
        "tests",
        {"t1": _resolved_test("list_desgin_sessions", False)},
        revision=record["revision"],
    )

    allowed, reason = store.can_advance(published["id"], "tests")

    assert allowed is False
    assert "list_desgin_sessions" in reason
    with pytest.raises(store.DesignError):
        store.accept_page(published["id"], "tests", revision=published["revision"])


def test_a_test_naming_a_function_specified_on_page_three_may_be_accepted(store):
    record = store.create_design_session("Design")
    with_functions = store.publish_page(
        record["id"],
        "functions",
        {"f1": {"order": 1, "name": "publish_page", "changed": True}},
        revision=record["revision"],
    )
    published = store.publish_page(
        with_functions["id"],
        "tests",
        {"t1": _resolved_test("publish_page", False, kind="planned")},
        revision=with_functions["revision"],
    )

    allowed, reason = store.can_advance(published["id"], "tests")

    assert allowed is True
    assert reason == ""


def test_a_planned_function_absent_from_page_three_still_blocks_the_page(store):
    record = store.create_design_session("Design")
    with_functions = store.publish_page(
        record["id"],
        "functions",
        {"f1": {"order": 1, "name": "publish_page", "changed": True}},
        revision=record["revision"],
    )
    published = store.publish_page(
        with_functions["id"],
        "tests",
        {"t1": _resolved_test("publish_pages", False, kind="planned")},
        revision=with_functions["revision"],
    )

    allowed, reason = store.can_advance(published["id"], "tests")

    assert allowed is False
    assert "publish_pages" in reason


def test_a_submission_un_accepts_the_page_it_lands_on(store):
    record = store.create_design_session("Design")
    published = store.publish_page(
        record["id"],
        "requirements",
        _requirements("Sessions are listed"),
        revision=record["revision"],
    )
    accepted = store.accept_page(
        published["id"], "requirements", revision=published["revision"]
    )
    assert accepted["accepted"]["requirements"] is True

    submitted = store.submit_page(
        accepted["id"],
        "requirements",
        items={"r1": {"feedback": "Actually, one more thing"}},
        revision=accepted["revision"],
    )

    assert submitted["accepted"]["requirements"] is False


# --- Requirement 25, 30: notices and delivery -------------------------------


def _built(store, **kwargs):
    record = store.create_design_session("Design", **kwargs)
    with_functions = store.publish_page(
        record["id"],
        "functions",
        {"f1": {"order": 1, "name": "publish_page", "changed": True}},
        revision=record["revision"],
    )
    return with_functions


def test_feedback_and_build_queue_different_notices(store):
    record = _built(store, conversation_id="conv-a")

    feedback = store.submit_page(
        record["id"],
        "functions",
        items={"f1": {"feedback": "Why does this call the store twice?"}},
        revision=record["revision"],
    )
    store.submit_page(
        feedback["id"], "functions", items={}, action="build",
        revision=feedback["revision"],
    )

    kinds = [notice["kind"] for notice in store.pending_notices(record["id"])]
    assert kinds == ["feedback", "build"]


def test_build_is_refused_when_no_conversation_is_attached(store):
    record = _built(store)

    with pytest.raises(store.DesignError):
        store.submit_page(
            record["id"], "functions", items={}, action="build",
            revision=record["revision"],
        )

    assert store.pending_notices(record["id"]) == []


def test_a_notice_can_only_be_claimed_once(store):
    record = _built(store, conversation_id="conv-a")
    store.submit_page(
        record["id"], "functions", items={}, action="build",
        revision=record["revision"],
    )
    notice_id = store.pending_notices(record["id"])[0]["id"]

    claimed = store.claim_notice(notice_id)
    assert claimed["kind"] == "build"

    with pytest.raises(store.DesignNotFound):
        store.claim_notice(notice_id)


def test_a_released_notice_can_be_claimed_again(store):
    record = _built(store, conversation_id="conv-a")
    store.submit_page(
        record["id"], "functions", items={}, action="build",
        revision=record["revision"],
    )
    notice_id = store.pending_notices(record["id"])[0]["id"]
    store.claim_notice(notice_id)

    store.release_notice(notice_id)

    assert store.claim_notice(notice_id)["id"] == notice_id


def test_a_delivered_notice_stops_being_pending(store):
    record = _built(store, conversation_id="conv-a")
    store.submit_page(
        record["id"], "functions", items={}, action="build",
        revision=record["revision"],
    )
    notice_id = store.pending_notices(record["id"])[0]["id"]
    store.claim_notice(notice_id)

    store.mark_delivered(notice_id)

    assert store.pending_notices(record["id"]) == []
    with pytest.raises(store.DesignNotFound):
        store.mark_delivered(notice_id)


def test_a_submission_survives_a_conversation_that_no_longer_exists(store):
    record = _built(store, conversation_id="conv-gone")
    submitted = store.submit_page(
        record["id"],
        "functions",
        items={"f1": {"feedback": "Asked while the conversation was dead"}},
        revision=record["revision"],
    )
    store.attach_design_session(submitted["id"], None)

    pending = store.pending_notices(submitted["id"])

    assert [notice["kind"] for notice in pending] == ["feedback"]
    assert (
        store.get_design_session(submitted["id"])["functions"]["f1"]["feedback"]
        == "Asked while the conversation was dead"
    )
