from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.execution.router import router as execution_router 
from app.admin.router import router as admin_router
from app.user.router import router as user_router


import os

app = FastAPI()

# Load CORS origins from environment variable
cors_origins_env = os.getenv("ALLOWED_CORS_ORIGINS", "")
if cors_origins_env:
    origins = [origin.strip() for origin in cors_origins_env.split(",")]
else:
    # Fallback to defaults if not set
    origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://www.dailysql.in",
        "https://dailysql.in",
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
