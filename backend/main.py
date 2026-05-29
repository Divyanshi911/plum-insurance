# backend/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes.claims import router as claims_router


app = FastAPI(title="Plum Claims Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount claims router under /claims
app.include_router(claims_router, prefix="/claims", tags=["claims"])


@app.get("/health")
def health():
    return {"status": "ok"}