from venvalid import bool_, int_, str_, venvalid

env = venvalid(
    {
        # Deployment environment — drives the fastapi-env-banner traceability
        # banner (local / development / staging / production / testing).
        "ENVIRONMENT": str_(default="local"),
        "DATABASE_URL": str_(default=""),
        "DATABASE_DIRECT_URL": str_(default=""),
        "DATABASE_HOST": str_(default="localhost"),
        "DATABASE_PORT": int_(default=5432),
        "DATABASE_USER": str_(default=""),
        "DATABASE_PASSWORD": str_(default=""),
        "DATABASE_NAME": str_(default="ember"),
        "DATABASE_ECHO": bool_(default=False),
        "JWT_SECRET_KEY": str_(),
        "JWT_ACCESS_TOKEN_TTL_MINUTES": int_(default=15),
        "REFRESH_TOKEN_TTL_DAYS": int_(default=30),
        "INVITE_CODE_TTL_DAYS": int_(default=7),
        # Mail module (docs/rfc/mail-module.md). Ember never speaks SMTP/IMAP
        # itself — it delegates to an external mail server (Stalwart) and talks
        # to its management API. Disabled by default: no mail server is required
        # to run Ember, and none is wired up yet.
        "MAIL_ENABLED": bool_(default=False),
        "MAIL_SERVER_URL": str_(default=""),
        "MAIL_ADMIN_TOKEN": str_(default=""),
        # Timeout (seconds) for HTTP calls to the mail server's management API.
        "MAIL_HTTP_TIMEOUT_SECONDS": int_(default=10),
        # Outbound delivery can be delegated independently from mailbox
        # storage/reading. Stalwart remains the compatibility default.
        "MAIL_OUTBOUND_PROVIDER": str_(default="stalwart"),
        "RESEND_API_KEY": str_(default=""),
        "RESEND_TIMEOUT_SECONDS": int_(default=10),
    }
)

_ASYNC_DRIVER = "postgresql+psycopg"


def _with_async_driver(url: str) -> str:
    if url.startswith(f"{_ASYNC_DRIVER}://"):
        return url
    if url.startswith("postgresql://"):
        return _ASYNC_DRIVER + url[len("postgresql") :]
    if url.startswith("postgres://"):
        return _ASYNC_DRIVER + url[len("postgres") :]
    return url


def database_url(*, database: str | None = None) -> str:
    if env["DATABASE_URL"] and database is None:
        return _with_async_driver(env["DATABASE_URL"])
    return (
        f"{_ASYNC_DRIVER}://{env['DATABASE_USER']}:{env['DATABASE_PASSWORD']}"
        f"@{env['DATABASE_HOST']}:{env['DATABASE_PORT']}/{database or env['DATABASE_NAME']}"
    )


def database_direct_url() -> str:
    if env["DATABASE_DIRECT_URL"]:
        return _with_async_driver(env["DATABASE_DIRECT_URL"])
    return database_url()


def mail_enabled() -> bool:
    """Whether a mail server is configured. Lets callers avoid importing `env`
    directly and keeps the on/off decision in one place."""
    return env["MAIL_ENABLED"]


def psycopg_dsn() -> str:
    """A plain psycopg connection string (no SQLAlchemy `+psycopg` driver tag),
    for libraries that use psycopg directly rather than through SQLAlchemy —
    e.g. the background-job queue. Same database as the app."""
    return database_url().replace(f"{_ASYNC_DRIVER}://", "postgresql://", 1)
