# SPDX-FileCopyrightText: 2026 rodavrow
# SPDX-License-Identifier: MIT
"""Shared fixtures for the Voice Persona Router tests."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load the integration from custom_components/."""
    yield
