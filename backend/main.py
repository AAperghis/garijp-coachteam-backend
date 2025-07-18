import os
from fastapi import FastAPI
from src.webhook import router as webhook_router

app = FastAPI(root_path=f"/{os.getenv('APP_NAME')}/api")
app.include_router(webhook_router)

@app.get("/hello")
def read_root():
    return {"msg": "Hello from FastAPI!"}
