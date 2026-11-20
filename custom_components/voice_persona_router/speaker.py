# SPDX-FileCopyrightText: 2026 rodavrow
# SPDX-License-Identifier: MIT
"""Decide who is speaking. Pure logic with no Home Assistant imports, so it can be tested alone."""

from collections.abc import Iterable
from typing import Literal

Role = Literal["owner", "wife", "stranger"]
ROLES: tuple[Role, ...] = ("owner", "wife", "stranger")


def _as_role(value: str | None, default: Role) -> Role:
    for role in ROLES:
        if value == role:
            return role
    return default


def resolve_speaker(
    helper_state: str | None,
    user_id: str | None,
    user_map: Iterable[tuple[Role, str | None]],
    no_helper_role: str | None,
) -> tuple[Role, bool]:
    """Return the role of the person speaking and whether a voice match decided it.

    helper_state    final state of the satellite's voice_speaker helper, or None when
                    the device has no helper (phone app, browser, other devices)
    user_id         Home Assistant user that sent the request, or None (voice satellites)
    user_map        (role, user id) pairs from the settings; empty ids are ignored
    no_helper_role  role for a request with no helper and no mapped user

    A helper always wins, so voice decides on satellites. Without a helper, a logged-in
    user mapped to a person is that person. Once any user is mapped, a logged-in user
    who is not mapped counts as a stranger.
    """
    fallback = _as_role(no_helper_role, "owner")

    if helper_state is not None:
        if helper_state == "partner":  # "partner" is accepted as another word for "wife".
            return "wife", True
        if helper_state in ROLES:
            return _as_role(helper_state, fallback), True
        if helper_state == "pending":  # The voice match never arrived.
            return "stranger", False
        return fallback, False

    mapped: list[tuple[Role, str]] = [(role, mapped_id) for role, mapped_id in user_map if mapped_id]
    if user_id and mapped:
        for role, mapped_id in mapped:
            if mapped_id == user_id:
                return role, False
        return "stranger", False
    return fallback, False
