# SPDX-FileCopyrightText: 2026 rodavrow
# SPDX-License-Identifier: MIT
"""Tests for resolve_speaker: who is speaking, from the helper, the logged-in user or the fallback."""

import pytest

from custom_components.voice_persona_router.speaker import resolve_speaker

PERSON_1_USER = "user-person-1"
PERSON_2_USER = "user-person-2"
GUEST_USER = "user-guest"
BOTH_MAPPED = [("owner", PERSON_1_USER), ("wife", PERSON_2_USER)]
NONE_MAPPED = [("owner", None), ("wife", None)]


# A helper exists: voice decides, whoever is logged in.


@pytest.mark.parametrize(
    ("helper_state", "expected_role"),
    [("owner", "owner"), ("wife", "wife"), ("partner", "wife"), ("stranger", "stranger")],
)
def test_helper_role_is_used_and_counts_as_voice_match(helper_state, expected_role):
    assert resolve_speaker(helper_state, None, NONE_MAPPED, "owner") == (expected_role, True)


def test_helper_wins_over_mapped_logged_in_user():
    assert resolve_speaker("stranger", PERSON_1_USER, BOTH_MAPPED, "owner") == ("stranger", True)


def test_helper_still_pending_after_wait_is_stranger_without_voice_match():
    assert resolve_speaker("pending", PERSON_1_USER, BOTH_MAPPED, "owner") == ("stranger", False)


@pytest.mark.parametrize(
    "helper_state", ["", "unknown", "unavailable", "Owner", "Stranger", "guest", " owner"]
)
def test_regression_review_5_unexpected_helper_value_is_refused_as_a_stranger(helper_state):
    # A helper that exists but holds something else must fail closed, not fall back
    # to the no-helper role, whoever is logged in.
    assert resolve_speaker(helper_state, PERSON_1_USER, BOTH_MAPPED, "owner") == (
        "stranger",
        False,
    )


# No helper: the logged-in user decides once any user is mapped.


@pytest.mark.parametrize(
    ("user_id", "expected_role"),
    [(PERSON_1_USER, "owner"), (PERSON_2_USER, "wife")],
)
def test_mapped_user_without_helper_is_that_person(user_id, expected_role):
    assert resolve_speaker(None, user_id, BOTH_MAPPED, "owner") == (expected_role, False)


def test_unmapped_user_without_helper_is_stranger_once_any_user_is_mapped():
    only_person_1 = [("owner", PERSON_1_USER), ("wife", None)]
    assert resolve_speaker(None, GUEST_USER, only_person_1, "owner") == ("stranger", False)


def test_unmapped_user_without_helper_uses_fallback_when_nobody_is_mapped():
    assert resolve_speaker(None, GUEST_USER, NONE_MAPPED, "wife") == ("wife", False)


def test_empty_string_mapping_counts_as_not_mapped():
    assert resolve_speaker(None, GUEST_USER, [("owner", ""), ("wife", "")], "owner") == ("owner", False)


@pytest.mark.parametrize("user_id", [None, ""])
def test_no_user_and_no_helper_uses_fallback_even_when_users_are_mapped(user_id):
    assert resolve_speaker(None, user_id, BOTH_MAPPED, "stranger") == ("stranger", False)


def test_same_user_mapped_twice_resolves_to_person_1():
    both_same = [("owner", PERSON_1_USER), ("wife", PERSON_1_USER)]
    assert resolve_speaker(None, PERSON_1_USER, both_same, "stranger") == ("owner", False)


# The no-helper fallback setting itself.


@pytest.mark.parametrize("no_helper_role", [None, "", "partner", "nobody"])
def test_missing_or_invalid_fallback_setting_defaults_to_person_1(no_helper_role):
    assert resolve_speaker(None, None, NONE_MAPPED, no_helper_role) == ("owner", False)
