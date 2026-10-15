import os
import hmac
from urllib.parse import urljoin
import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response

# This gateway runs on port 80. Model servers remain private on loopback ports.
QWEN_LOCAL_BASE_URL=os.getenv("QWEN_LOCAL_BASE_URL","http://127.0.0.1:8000/v1").rstrip("/")+"/"
IMAGE_LOCAL_URL=os.getenv("IMAGE_LOCAL_URL","").strip()
KAGGLE_API_KEY=os.getenv("KAGGLE_API_KEY","").strip()
TIMEOUT=float(os.getenv("GATEWAY_TIMEOUT_SECONDS","240"))
app=FastAPI(title="Kaggle Model Gateway",docs_url=None,redoc_url=None)

async def auth(authorization: str|None=Header(default=None)):
    if not KAGGLE_API_KEY:
        raise HTTPException(503,"Set KAGGLE_API_KEY before exposing this gateway.")
    if not authorization or not hmac.compare_digest(authorization,"Bearer "+KAGGLE_API_KEY):
        raise HTTPException(401,"Missing or invalid bearer token.")

@app.get("/health")
async def health():
    return {"ok":True,"qwen_base_url_configured":bool(QWEN_LOCAL_BASE_URL),"image_configured":bool(IMAGE_LOCAL_URL),"port":80}

@app.post("/v1/chat/completions")
async def chat(request: Request, _:None=__import__("fastapi").Depends(auth)):
    body=await request.body()
    target=urljoin(QWEN_LOCAL_BASE_URL, "chat/completions")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            upstream=await client.post(target,content=body,headers={"Content-Type":"application/json","Authorization":"Bearer "+os.getenv("QWEN_LOCAL_API_KEY","not-needed")})
        return Response(content=upstream.content,status_code=upstream.status_code,media_type=upstream.headers.get("content-type","application/json"))
    except httpx.HTTPError as e:
        raise HTTPException(502,"Qwen inference server unavailable: "+type(e).__name__)

@app.post("/v1/images/generations")
async def images(request: Request, _:None=__import__("fastapi").Depends(auth)):
    if not IMAGE_LOCAL_URL:
        raise HTTPException(503,"Set IMAGE_LOCAL_URL to your Z-Image-Turbo image API endpoint.")
    body=await request.body()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT,follow_redirects=False) as client:
            upstream=await client.post(IMAGE_LOCAL_URL,content=body,headers={"Content-Type":"application/json","Authorization":"Bearer "+os.getenv("IMAGE_LOCAL_API_KEY","not-needed")})
        return Response(content=upstream.content,status_code=upstream.status_code,media_type=upstream.headers.get("content-type","application/json"))
    except httpx.HTTPError as e:
        raise HTTPException(502,"Image inference server unavailable: "+type(e).__name__)
