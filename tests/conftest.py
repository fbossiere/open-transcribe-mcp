from pathlib import Path

import pytest

from open_transcribe.settings import Settings


@pytest.fixture
def config_dir() -> Path:
    return Path(__file__).parents[1] / "config"


@pytest.fixture
def settings(config_dir: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        config_dir=config_dir,
        security={"auth_mode": "none"},
        microsoft={
            "endpoint": "https://speech.example.com",
            "api_key": "microsoft-secret",
        },
        elevenlabs={"api_key": "eleven-secret"},
        groq={"api_key": "groq-secret"},
        result_store={
            "backend": "memory",
            "cursor_secret": "cursor-secret-with-sufficient-entropy",
            "ttl_seconds": 3600,
        },
    )
