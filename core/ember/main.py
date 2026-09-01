from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI

# pyrefly: ignore [missing-import]
from fastapi_env_banner import EnvBannerConfig, EnvBannerMiddleware, setup_swagger_ui
from fastapi.middleware.cors import CORSMiddleware

from ember.config import env, sentry_enabled
from ember.jobs.app import app as jobs_app
from ember.routers.auth import router as auth_router
from ember.routers.events import router as events_router
from ember.routers.github import router as github_router
from ember.routers.invites import router as invites_router
from ember.routers.knowledge import router as knowledge_router
from ember.routers.mail import router as mail_router
from ember.routers.users import router as users_router
from ember.routers.workspaces import router as workspaces_router
from ember.routers.personal import router as personal_router

if sentry_enabled():
    sentry_sdk.init(
        dsn=env["SENTRY_DSN"],
        environment=env["ENVIRONMENT"],
        send_default_pii=True,
        enable_logs=True,
        traces_sample_rate=float(env["SENTRY_TRACES_SAMPLE_RATE"]),
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """Hold the Procrastinate connection pool open for the process lifetime.

    Deferring a job (`task.defer_async(...)`) reads `connector.pool`, which
    raises `AppNotOpen` until the app has been opened — the API process has to
    open it explicitly, the same way the worker command does.
    """
    async with jobs_app.open_async():
        yield


banner_config = EnvBannerConfig.from_env("ENVIRONMENT")
app = FastAPI(title=f"Ember ({env['ENVIRONMENT']})", docs_url=None, lifespan=lifespan)

app.add_middleware(EnvBannerMiddleware, config=banner_config)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_swagger_ui(app, banner_config)

app.include_router(auth_router)
app.include_router(events_router)
app.include_router(github_router)
app.include_router(invites_router)
app.include_router(knowledge_router)
app.include_router(mail_router)
app.include_router(users_router)
app.include_router(workspaces_router)
app.include_router(personal_router)


@app.get("/sentry-debug")
async def trigger_error():
    division_by_zero = 1 / 0
