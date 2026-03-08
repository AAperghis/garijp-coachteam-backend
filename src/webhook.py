import hmac
import hashlib
import os
import subprocess
import json
from fastapi import Header, HTTPException, Request, APIRouter

router = APIRouter(prefix="/webhook")

GITHUB_SECRET = os.getenv("GITHUB_SECRET", "your_webhook_secret")
APP_PATH = "/app"  # This is the mounted volume path in the container

def verify_signature(payload_body, signature):
    if not signature:
        return False
    mac = hmac.new(GITHUB_SECRET.encode(), msg=payload_body, digestmod=hashlib.sha256)
    return hmac.compare_digest("sha256=" + mac.hexdigest(), signature)

@router.post("")
async def webhook(request: Request, x_hub_signature_256: str = Header(None)):
    body = await request.body()
    
    # Verify GitHub signature
    if not verify_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        # Parse the webhook payload
        payload = json.loads(body)
        
        # Only process pushes to main branch
        if payload.get("ref") != "refs/heads/main":
            return {"status": "ignored", "detail": "Not a push to main branch"}
        
        # Pull latest changes from the mounted repository
        subprocess.run(
            ["git", "-C", APP_PATH, "pull", "origin", "main"], 
            check=True, 
            capture_output=True, 
            text=True
        )
        
        # Rebuild and restart containers using docker compose
        # Run from the app directory where docker-compose.yml is located
        subprocess.run(
            ["docker", "compose", "up", "--build", "-d"], 
            cwd=APP_PATH,
            check=True, 
            capture_output=True, 
            text=True
        )
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except subprocess.CalledProcessError as e:
        return {
            "status": "error", 
            "detail": f"Command failed: {e.cmd}",
            "output": e.output if hasattr(e, 'output') else str(e)
        }
    except Exception as e:
        return {"status": "error", "detail": f"Unexpected error: {str(e)}"}

    return {"status": "success", "detail": "Application updated and redeployed"}
