"""Shared fixtures and test session tokens for the Digital Heirloom backend tests."""
import os
import pytest
import requests
from dotenv import load_dotenv
from pathlib import Path

# Load backend .env for any required values
load_dotenv(Path(__file__).parent.parent / ".env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
           "https://voice-clone-hub-20.preview.emergentagent.com"


# Tokens minted in mongosh before test run
TOKEN_USER1 = "test_session_1_1782358256086"
USER_ID_1 = "test-user-1-1782358256086"
TOKEN_USER2 = "test_session_2_1782358256086"
USER_ID_2 = "test-user-2-1782358256086"


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
