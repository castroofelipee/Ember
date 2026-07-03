from venvalid import bool_, int_, str_, venvalid

env = venvalid(
    {
        "DATABASE_HOST": str_(),
        "DATABASE_PORT": int_(),
        "DATABASE_USER": str_(),
        "DATABASE_PASSWORD": str_(),
        "DATABASE_NAME": str_(),
        "DATABASE_ECHO": bool_(),
    }
)


def database_url() -> str:
    return (
        f"postgresql+psycopg://{env['DATABASE_USER']}:{env['DATABASE_PASSWORD']}"
        f"@{env['DATABASE_HOST']}:{env['DATABASE_PORT']}/{env['DATABASE_NAME']}"
    )
