"""Shared fixtures and test session tokens for Digital Heirloom backend tests."""
import os
import pytest
import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
           "https://voice-clone-hub-20.preview.emergentagent.com"

# Iteration 2 tokens (Phase 2 testing) — seeded fresh via mongosh
TOKEN_USER1 = "p2_sess_1_1782367420509"
USER_ID_1 = "p2-user-1-1782367420509"
TOKEN_USER2 = "p2_sess_2_1782367420509"
USER_ID_2 = "p2-user-2-1782367420509"


def _client(token: str | None = None) -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture
def anon_client():
    return _client()


@pytest.fixture
def user1_client():
    return _client(TOKEN_USER1)


@pytest.fixture
def user2_client():
    return _client(TOKEN_USER2)


@pytest.fixture
def user1_token():
    return TOKEN_USER1


@pytest.fixture
def user2_token():
    return TOKEN_USER2
