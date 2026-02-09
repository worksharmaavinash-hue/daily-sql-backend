from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.execution.router import router as execution_router 
from app.admin.router import router as admin_router
from app.user.router import router as user_router


app = FastAPI()

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://daily-sql.com", # Placeholder for prod
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # For dev simplicity, strict in prod
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
