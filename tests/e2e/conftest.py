"""Fixtures de los tests de extremo a extremo (ver harness.py y README.md)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from .harness import Residence, SystemUnderTest, system_under_test


@pytest.fixture(scope="session")
def sut() -> Iterator[SystemUnderTest]:
    with system_under_test() as system:
        yield system


@pytest.fixture
def residence(sut: SystemUnderTest) -> Residence:
    return Residence(sut)
