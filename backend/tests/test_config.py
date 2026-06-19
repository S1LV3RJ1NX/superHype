import pytest

from app.config import Settings

_REQUIRED_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
    "REDIS_URL": "redis://localhost:6379/0",
    "APP_URL": "http://localhost:8000",
    "FRONTEND_URL": "http://localhost:5173",
    "CORS_ORIGINS": "http://localhost:5173",
    "JWT_SECRET": "test-secret",
    "TOKEN_ENCRYPTION_KEY": "test-encryption-key",
    "COMPANY_EMAIL_DOMAIN": "test.local",
    "BOOTSTRAP_ADMIN_EMAILS": "admin@test.local",
    "GOOGLE_CLIENT_ID": "test-google-id",
    "GOOGLE_CLIENT_SECRET": "test-google-secret",
    "LINKEDIN_CLIENT_ID": "test-linkedin-id",
    "LINKEDIN_CLIENT_SECRET": "test-linkedin-secret",
    "LLM_GATEWAY_URL": "https://gateway.test.local",
    "LLM_API_KEY": "test-llm-key",
    "LLM_MODEL_NAME": "test-model",
}


@pytest.fixture(autouse=True)
def _set_required_env(monkeypatch):
    """Ensure all required Settings fields have values for isolated tests."""
    for key, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


def test_bootstrap_admin_emails_parsed(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAILS", "Alice@x.com, bob@x.com ,")
    settings = Settings(_env_file=None)
    assert settings.bootstrap_admin_emails == ["alice@x.com", "bob@x.com"]


def test_is_production_flag(monkeypatch):
    assert Settings(_env_file=None, ENV="production").is_production is True
    assert Settings(_env_file=None, ENV="local").is_production is False
    monkeypatch.delenv("ENV", raising=False)
    assert Settings(_env_file=None).is_production is True


def test_cors_origins_parsed():
    settings = Settings(_env_file=None, CORS_ORIGINS="http://a.com, http://b.com")
    assert settings.cors_origins == ["http://a.com", "http://b.com"]


def test_docs_disabled_in_production(monkeypatch):
    from app import main

    monkeypatch.setattr(
        type(main.settings), "is_production", property(lambda _self: True)
    )
    app = main.create_app()
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None


def test_docs_enabled_outside_production(monkeypatch):
    from app import main

    monkeypatch.setattr(
        type(main.settings), "is_production", property(lambda _self: False)
    )
    app = main.create_app()
    assert app.docs_url == "/docs"
    assert app.openapi_url == "/openapi.json"
