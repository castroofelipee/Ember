from venvalid import bool_, int_, str_, venvalid

env = venvalid(
    {
        "DATABASE_HOST": str_(),
        "DATABASE_PORT": int_(),
        "DATABASE_USER": str_(),
        "DATABASE_PASSWORD": str_(),
        "DATABASE_NAME": str_(),
        "DATABASE_ECHO": bool_(),
        "JWT_SECRET_KEY": str_(),
        "JWT_ACCESS_TOKEN_TTL_MINUTES": int_(default=15),
        "REFRESH_TOKEN_TTL_DAYS": int_(default=30),
    }
)


def database_url(*, database: str | None = None) -> str:
    return (
        f"postgresql+psycopg://{env['DATABASE_USER']}:{env['DATABASE_PASSWORD']}"
        f"@{env['DATABASE_HOST']}:{env['DATABASE_PORT']}/{database or env['DATABASE_NAME']}"
    )
