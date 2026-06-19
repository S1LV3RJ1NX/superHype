from app.config import Settings


def test_bootstrap_admin_emails_parsed(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAILS", "Alice@x.com, bob@x.com ,")
    settings = Settings(_env_file=None)
    assert settings.bootstrap_admin_emails == ["alice@x.com", "bob@x.com"]


def test_is_production_flag():
    assert Settings(_env_file=None, ENVIRONMENT="production").is_production is True
    assert Settings(_env_file=None, ENVIRONMENT="development").is_production is False


def test_cors_origins_parsed():
    settings = Settings(_env_file=None, CORS_ORIGINS="http://a.com, http://b.com")
    assert settings.cors_origins == ["http://a.com", "http://b.com"]
