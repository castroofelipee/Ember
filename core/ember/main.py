from fastapi import FastAPI
# pyrefly: ignore [missing-import]
from fastapi_env_banner import EnvBannerConfig, EnvBannerMiddleware, setup_swagger_ui
from fastapi.middleware.cors import CORSMiddleware

from ember.config import env
from ember.routers.auth import router as auth_router
from ember.routers.events import router as events_router
from ember.routers.invites import router as invites_router
from ember.routers.knowledge import router as knowledge_router
from ember.routers.mail import router as mail_router
from ember.routers.users import router as users_router
from ember.routers.workspaces import router as workspaces_router

banner_config = EnvBannerConfig.from_env("ENVIRONMENT")
app = FastAPI(title=f"Ember ({env['ENVIRONMENT']})", docs_url=None)

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
app.include_router(invites_router)
app.include_router(knowledge_router)
app.include_router(mail_router)
app.include_router(users_router)
app.include_router(workspaces_router)
