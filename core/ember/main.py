from fastapi import FastAPI

from ember.routers.auth import router as auth_router

app = FastAPI(title="Ember")
app.include_router(auth_router)
