import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from webhook import router as webhook_router
from endpoints.banaan import router as banaan_router
from endpoints.roster import router as roster_router

app = FastAPI(root_path=os.getenv("ROOT_PATH", ""))

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router)
app.include_router(banaan_router)
app.include_router(roster_router)

@app.get("/health")
def health():
    return {"status": "ok"}
