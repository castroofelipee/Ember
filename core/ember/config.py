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
