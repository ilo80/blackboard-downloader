"""Offline Blackboard responses and reusable course fixtures."""

import httpx
import pytest

from blackboard_downloader.client import BlackboardClient
from blackboard_downloader.models import Course

BASE = "https://blackboard.example"


@pytest.fixture
def course():
    return Course("_1_1", "Linear Algebra")


@pytest.fixture
def client_factory():
    def create(handler, **kwargs):
        return BlackboardClient(BASE, transport=httpx.MockTransport(handler), **kwargs)

    return create
