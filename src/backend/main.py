import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.endpoints.banaan import router as banaan_router
from backend.endpoints.examples import router as examples_router
from backend.endpoints.roster import router as roster_router

app = FastAPI(root_path=os.getenv("ROOT_PATH", ""))

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(banaan_router)
app.include_router(roster_router)
app.include_router(examples_router)

@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))