from app.config import Settings


def test_bootstrap_admin_emails_parsed(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAILS", "Alice@x.com, bob@x.com ,")
    settings = Settings(_env_file=None)
    assert settings.bootstrap_admin_emails == ["alice@x.com", "bob@x.com"]


def test_is_production_flag(monkeypatch):
    assert Settings(_env_file=None, ENV="production").is_production is True
    assert Settings(_env_file=None, ENV="local").is_production is False
    # Defaults to production when ENV is unset, so docs stay locked down. Clear
    # any ENV from the process/CI environment so we test the real default.
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
