from __future__ import annotations
import hmac, json, os, shlex, sqlite3, subprocess, time, uuid
from pathlib import Path
from typing import Any
import httpx
from ddgs import DDGS
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.responses import FileResponse
from openai import AsyncOpenAI
import uvicorn
from pydantic import BaseModel, Field

CONFIG_PATH=Path(os.getenv("CONFIG_PATH","config.json"))
try:
    CONFIG=json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
except (OSError,json.JSONDecodeError) as e:
    raise RuntimeError(f"Cannot read {CONFIG_PATH}: {type(e).__name__}") from e

def setting(name: str, env_name: str, default: Any="")->str:
    # config.json is the primary configuration; hosting-panel environment variables can override it.
    return str(os.getenv(env_name,CONFIG.get(name,default)) or "").strip()

HOST=setting("host","APP_HOST","0.0.0.0")
PORT=max(1,min(int(setting("port","APP_PORT","80") or "80"),65535))
APP_API_KEY=setting("app_api_key","APP_API_KEY")
QWEN_BASE_URL=setting("qwen_base_url","QWEN_BASE_URL")
QWEN_API_KEY=setting("qwen_api_key","QWEN_API_KEY") or "not-needed"
QWEN_MODEL=setting("qwen_model","QWEN_MODEL")
IMAGE_API_URL=setting("image_api_url","IMAGE_API_URL")
IMAGE_API_KEY=setting("image_api_key","IMAGE_API_KEY")
DB_PATH=Path(setting("database_path","DATABASE_PATH","/data/agent.db") or "/data/agent.db")
WORKSPACE=Path(setting("workspace_path","WORKSPACE_PATH","/data/workspace") or "/data/workspace").resolve()
MAX_STEPS=max(1,min(int(setting("max_tool_steps","MAX_TOOL_STEPS","6") or "6"),12))
TIMEOUT=max(20,min(int(setting("request_timeout_seconds","REQUEST_TIMEOUT_SECONDS","180") or "180"),300))
WORKSPACE.mkdir(parents=True,exist_ok=True)
DB_PATH.parent.mkdir(parents=True,exist_ok=True)
app=FastAPI(title="Jolgue Harness API",version="0.1.0",docs_url=None,redoc_url=None)

def connect_db():
    c=sqlite3.connect(DB_PATH,timeout=15)
    c.row_factory=sqlite3.Row
    return c

def init_db():
    with connect_db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, created_at REAL NOT NULL, updated_at REAL NOT NULL, title TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL, created_at REAL NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL)")
        c.execute("CREATE INDEX IF NOT EXISTS events_conversation_idx ON events(conversation_id,id)")
init_db()

async def auth(authorization: str|None=Header(default=None)):
    if not APP_API_KEY or APP_API_KEY in {"CHANGE_THIS_TO_A_LONG_RANDOM_SECRET","replace-with-a-long-random-secret"}:
        raise HTTPException(503,"Administrator must set a strong APP_API_KEY.")
    if not authorization or not hmac.compare_digest(authorization,"Bearer "+APP_API_KEY):
        raise HTTPException(401,"Missing or invalid bearer token.")

def model_client():
    if not QWEN_BASE_URL or not QWEN_MODEL:
        raise HTTPException(503,"Configure QWEN_BASE_URL and QWEN_MODEL for the Kaggle inference server.")
    return AsyncOpenAI(base_url=QWEN_BASE_URL,api_key=QWEN_API_KEY,timeout=TIMEOUT,max_retries=1)

class Message(BaseModel):
    role: str
    content: str|None=None
class AgentRequest(BaseModel):
    messages: list[Message]=Field(min_length=1,max_length=60)
    conversation_id: str|None=None
class ImageRequest(BaseModel):
    prompt: str=Field(min_length=1,max_length=3000)
class ChatRequest(BaseModel):
    model: str|None=None
    messages: list[dict[str,Any]]=Field(min_length=1,max_length=80)
    temperature: float|None=None
    max_tokens: int|None=None
    stream: bool=False

def safe_path(name: str)->Path:
    p=(WORKSPACE/name).resolve()
    if p!=WORKSPACE and WORKSPACE not in p.parents:
        raise ValueError("Path escapes workspace.")
    return p

def search_web(query: str)->dict:
    try:
        return {"results":list(DDGS().text(query[:400],max_results=5))}
    except Exception as e:
        return {"error":"Search failed: "+type(e).__name__}

def list_files(path: str=".")->dict:
    p=safe_path(path)
    if not p.exists(): return {"path":path,"files":[]}
    if not p.is_dir(): return {"error":"Path is not a directory."}
    return {"path":path,"files":[{"name":x.name,"directory":x.is_dir()} for x in sorted(p.iterdir())[:100]]}

def read_file(path: str)->dict:
    p=safe_path(path)
    if not p.is_file(): return {"error":"File not found."}
    if p.stat().st_size>200000: return {"error":"File exceeds 200 KB limit."}
    return {"path":path,"content":p.read_text(encoding="utf-8",errors="replace")}

def write_file(path: str,content: str)->dict:
    p=safe_path(path)
    if len(content.encode())>200000: return {"error":"Content exceeds 200 KB limit."}
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(content,encoding="utf-8")
    return {"path":path,"bytes_written":p.stat().st_size}

ALLOWED={"pwd","ls","cat","head","tail","grep","find","python","python3","pytest","wc","whoami","date","git"}
def terminal(command: str)->dict:
    if len(command)>1200:return {"error":"Command too long."}
    try:
        args=shlex.split(command)
        if not args:return {"error":"Empty command."}
        if args[0] not in ALLOWED:return {"error":"Command not allowed. Available: "+", ".join(sorted(ALLOWED))}
        if any(a.startswith("/") or ".." in Path(a).parts for a in args[1:]): return {"error":"Absolute paths and parent-directory traversal are disabled; use paths inside the workspace."}
        if any(x in command for x in ("&&","||",";","|",">","<","\x60","$(","\n","\r")):
            return {"error":"Shell operators/chaining are disabled."}
        if args[0] in {"python","python3"} and (len(args)<2 or args[1].startswith("-") or not args[1].endswith(".py")):
            return {"error":"Run a .py file inside the workspace; inline Python is disabled."}
        if args[0]=="git" and (len(args)<2 or args[1] not in {"status","diff","log"}):
            return {"error":"Only git status, diff, and log are allowed."}
        # No shell; terminal is restricted and runs with the workspace as cwd.
        r=subprocess.run(args,cwd=WORKSPACE,capture_output=True,text=True,timeout=20,check=False,
            env={"PATH":os.getenv("PATH","/usr/bin:/bin"),"HOME":str(WORKSPACE),"PYTHONUNBUFFERED":"1"})
        return {"returncode":r.returncode,"stdout":r.stdout[-10000:],"stderr":r.stderr[-5000:]}
    except subprocess.TimeoutExpired:return {"error":"Command timed out after 20 seconds."}
    except Exception as e:return {"error":"Terminal error: "+type(e).__name__+": "+str(e)[:300]}

TOOL_DEFS=[
 {"type":"function","function":{"name":"search_web","description":"Search the public web for current information.","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},
 {"type":"function","function":{"name":"workspace_list","description":"List files in the agent workspace.","parameters":{"type":"object","properties":{"path":{"type":"string"}}}}},
 {"type":"function","function":{"name":"workspace_read","description":"Read a UTF-8 text file in the workspace.","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
 {"type":"function","function":{"name":"workspace_write","description":"Create or replace a text file in the workspace.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}},
 {"type":"function","function":{"name":"terminal","description":"Run one approved command in the restricted workspace. No shell operators or command chaining.","parameters":{"type":"object","properties":{"command":{"type":"string"}},"required":["command"]}}},
 {"type":"function","function":{"name":"generate_image","description":"Generate an image using the configured Z-Image-Turbo endpoint.","parameters":{"type":"object","properties":{"prompt":{"type":"string"}},"required":["prompt"]}}}
]
def run_tool(name: str,args: dict)->dict:
    try:
        if name=="search_web":return search_web(str(args.get("query","")))
        if name=="workspace_list":return list_files(str(args.get("path",".")))
        if name=="workspace_read":return read_file(str(args["path"]))
        if name=="workspace_write":return write_file(str(args["path"]),str(args["content"]))
        if name=="terminal":return terminal(str(args["command"]))
        if name=="generate_image":
            # Called through the same configured image endpoint as the public image API.
            return {"image_request":True,"prompt":str(args["prompt"])[:3000]}
        return {"error":"Unknown tool"}
    except Exception as e:return {"error":str(e)[:500]}

async def generate_image(prompt: str)->dict:
    if not IMAGE_API_URL:raise HTTPException(503,"Configure IMAGE_API_URL for the Kaggle Z-Image-Turbo endpoint.")
    headers={}
    if IMAGE_API_KEY:headers["Authorization"]="Bearer "+IMAGE_API_KEY
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT,follow_redirects=False) as c:
            r=await c.post(IMAGE_API_URL,json={"prompt":prompt},headers=headers)
            r.raise_for_status()
            data=r.json()
    except httpx.HTTPError as e:raise HTTPException(502,"Image endpoint request failed: "+type(e).__name__)
    if "image_url" in data:return {"image_url":data["image_url"]}
    if "image_base64" in data:return {"image_base64":data["image_base64"],"mime_type":data.get("mime_type","image/png")}
    if data.get("data") and isinstance(data["data"],list):
        item=data["data"][0]
        if "url" in item:return {"image_url":item["url"]}
        if "b64_json" in item:return {"image_base64":item["b64_json"],"mime_type":"image/png"}
    raise HTTPException(502,"Image endpoint returned an unsupported response format.")

def save_events(cid: str,messages: list[dict]):
    now=time.time()
    with connect_db() as c:
        row=c.execute("SELECT id FROM conversations WHERE id=?",(cid,)).fetchone()
        title=" ".join(str(messages[-1].get("content") or "New conversation").split())[:80] if messages else "New conversation"
        if row:c.execute("UPDATE conversations SET updated_at=?,title=? WHERE id=?",(now,title,cid))
        else:c.execute("INSERT INTO conversations(id,created_at,updated_at,title) VALUES(?,?,?,?)",(cid,now,now,title))
        for m in messages[-2:]:
            role=str(m.get("role","user"))[:30]
            content=m.get("content","")
            if isinstance(content,(dict,list)):content=json.dumps(content,ensure_ascii=False)
            c.execute("INSERT INTO events(conversation_id,created_at,role,content) VALUES(?,?,?,?)",(cid,now,role,str(content)[:20000]))

@app.get("/health")
async def health():
    return {"ok":True,"qwen_configured":bool(QWEN_BASE_URL and QWEN_MODEL),"image_configured":bool(IMAGE_API_URL),"port":80}

@app.get("/")
async def home():
    return FileResponse("static/index.html")

@app.post("/v1/agent/run")
async def agent_run(req: AgentRequest, _:None=Depends(auth)):
    c=model_client()
    cid=req.conversation_id or str(uuid.uuid4())
    messages=[{"role":m.role,"content":m.content or ""} for m in req.messages]
    # Keep the context bounded to reduce memory and token usage.
    messages=messages[-30:]
    images=[]
    try:
        for _step in range(MAX_STEPS):
            result=await c.chat.completions.create(model=QWEN_MODEL,messages=messages,tools=TOOL_DEFS,tool_choice="auto")
            msg=result.choices[0].message
            if not msg.tool_calls:
                answer=msg.content or ""
                save_events(cid,messages+[{"role":"assistant","content":answer}])
                images=[]
                return {"conversation_id":cid,"content":answer,"images":images,"steps":_step+1}
            messages.append({"role":"assistant","content":msg.content,"tool_calls":[{"id":tc.id,"type":"function","function":{"name":tc.function.name,"arguments":tc.function.arguments}} for tc in msg.tool_calls]})
            for tc in msg.tool_calls:
                try:args=json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:args={}
                if tc.function.name=="generate_image":
                    try:
                        output=await generate_image(str(args.get("prompt","")))
                        if "image_url" in output or "image_base64" in output: images.append(output)
                    except HTTPException as e:output={"error":e.detail}
                else:output=run_tool(tc.function.name,args)
                messages.append({"role":"tool","tool_call_id":tc.id,"content":json.dumps(output,ensure_ascii=False)[:18000]})
        save_events(cid,messages)
        return {"conversation_id":cid,"content":"Stopped after reaching the configured tool-step limit. Ask me to continue if needed.","images":[],"steps":MAX_STEPS}
    except HTTPException:raise
    except Exception as e:raise HTTPException(502,"Qwen request failed: "+type(e).__name__+": "+str(e)[:300])

@app.post("/v1/images/generations")
async def image_generation(req: ImageRequest, _:None=Depends(auth)):
    return await generate_image(req.prompt)

@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest, _:None=Depends(auth)):
    if req.stream:raise HTTPException(400,"Streaming is not supported by this initial API adapter.")
    c=model_client()
    try:
        result=await c.chat.completions.create(model=req.model or QWEN_MODEL,messages=req.messages,
            temperature=req.temperature,max_tokens=req.max_tokens)
        return result.model_dump()
    except Exception as e:raise HTTPException(502,"Qwen request failed: "+type(e).__name__+": "+str(e)[:300])


if __name__ == "__main__":
    # ShardCloud's launcher executes "python app.py", so start the server here.
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
