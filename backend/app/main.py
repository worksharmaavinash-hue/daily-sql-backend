from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.execution.router import router as execution_router 
from app.admin.router import router as admin_router
from app.user.router import router as user_router
import os


import os

app = FastAPI()

# CORS origins: configurable via CORS_ORIGINS env var (comma-separated)
# Defaults to localhost + production domains
_default_origins = "http://localhost:3000,http://127.0.0.1:3000,https://www.dailysql.in,https://dailysql.in"
origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", _default_origins).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)
app.include_router(execution_router)
app.include_router(user_router)


@app.get("/health")
def health():
    return {"status": "ok"}
