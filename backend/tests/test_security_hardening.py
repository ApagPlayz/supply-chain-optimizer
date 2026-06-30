"""Tests for HARD-01 (SECRET_KEY validation), HARD-02 (CORS), HARD-03 (DEBUG default)."""
import pytest


def test_secret_key_rejects_known_defaults():
    """HARD-01: ValueError raised for each known default."""
    from app.core.config import Settings

    for bad_key in [
        "your-secret-key-change-in-production",
        "dev-secret-key-change-in-production",
        "secret",
        "changeme",
    ]:
        with pytest.raises(Exception):  # ValidationError wraps ValueError
            Settings(SECRET_KEY=bad_key, _env_file=None)


def test_secret_key_rejects_short_keys():
    """HARD-01: ValueError raised for keys shorter than 32 chars."""
    from app.core.config import Settings
    with pytest.raises(Exception):
        Settings(SECRET_KEY="tooshort", _env_file=None)


def test_secret_key_accepts_valid_key():
    """HARD-01: Valid 64-char key is accepted."""
    from app.core.config import Settings
    s = Settings(SECRET_KEY="a" * 64, _env_file=None)
    assert len(s.SECRET_KEY) == 64


def test_secret_key_error_message_includes_generation_command():
    """HARD-01 / D-09: Error message contains the python -c generation command."""
    from app.core.config import Settings
    try:
        Settings(SECRET_KEY="secret", _env_file=None)
        assert False, "Should have raised"
    except Exception as e:
        assert "secrets.token_hex(32)" in str(e)


def test_debug_defaults_to_false():
    """HARD-03: DEBUG field default is False when not overridden by env var."""
    from app.core.config import Settings
    import inspect
    source = inspect.getsource(Settings)
    assert "DEBUG: bool = False" in source


def test_cors_origins_not_wildcard(client):
    """HARD-02: CORS middleware does not use wildcard origins."""
    from app.main import app
    for mw in app.user_middleware:
        if "CORSMiddleware" in str(mw):
            # Starlette stores middleware options under .kwargs (>=0.28) or
            # .options (<0.28); read whichever this version exposes.
            options = getattr(mw, "kwargs", None)
            if options is None:
                options = getattr(mw, "options", {})
            assert options.get("allow_origins") != ["*"], "CORS still uses wildcard"


def test_allowed_origins_field_exists():
    """HARD-02 / D-04: Settings has ALLOWED_ORIGINS field."""
    from app.core.config import Settings
    s = Settings(SECRET_KEY="a" * 64, _env_file=None)
    assert hasattr(s, "ALLOWED_ORIGINS")
    assert "localhost:5173" in s.ALLOWED_ORIGINS
