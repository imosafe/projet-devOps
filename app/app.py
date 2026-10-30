"""MiniShop : application FastAPI VOLONTAIREMENT VULNÉRABLE (support du TP Cours 7).

Ne jamais déployer ce code tel quel. Votre mission : le rendre conforme.
Documentation interactive : http://localhost:5000/docs
"""
import base64
import hashlib
import logging
import os
import pickle
import random
import sqlite3
import subprocess
import traceback
import ast
import yaml
import requests
import uvicorn
import html

from urllib.parse import urlparse
from fastapi import Body, FastAPI, Request, HTTPException, Depends
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from starlette.middleware.sessions import SessionMiddleware
from argon2 import PasswordHasher
from pydantic import BaseModel, IPvAnyAddress
from argon2.exceptions import VerifyMismatchError

SECRET_KEY = os.environ["SECRET_KEY"]
DB_PATH = os.environ.get("DB_PATH", "shop.db")
UPLOAD_DIR = (Path(__file__).resolve().parent / "uploads").resolve()s
FETCH_ALLOWED_HOSTS = {"example.com","api.github.com"}

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("minishop")

app = FastAPI(title="MiniShop", debug=True)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, https_only=True, same_site="lax")

ph=PasswordHasher()

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

class Profile(BaseModel):
    name: str
    age: int

def init_db():
    conn = db()
    conn.executescript(
        """
        DROP TABLE IF EXISTS users;
        DROP TABLE IF EXISTS products;
        DROP TABLE IF EXISTS invoices;
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE,
                            password TEXT, is_admin INTEGER DEFAULT 0);
        CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price REAL);
        CREATE TABLE invoices (id INTEGER PRIMARY KEY, owner_id INTEGER,
                               label TEXT, amount REAL);
        """
    )
    conn.execute("INSERT INTO users (username, password, is_admin) VALUES (?, ?, 1)",
                 ("admin", ph.hash("admin123")))
    conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", ("alice", ph.hash("alice123")))
    conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", ("bob", ph.hash("bob123")))
    conn.executemany("INSERT INTO products (name, price) VALUES (?, ?)",
                     [("apple", 1.2), ("banana", 0.8), ("cherry", 3.5)])
    conn.executemany("INSERT INTO invoices (owner_id, label, amount) VALUES (?, ?, ?)",
                     [(2, "Facture Alice", 42.0), (3, "Facture Bob", 99.0)])
    conn.commit()
    conn.close()

def current_user(request:Request):
    uid= request.session.get("user_id")
    if uid is None :
        raise HTTPException(status_code=401, detail="login required")
    row = db().execute("SELECT id, username, is_admin FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="login required")
    return dict(row)

ROLE_PERMS = {
    "user": {"invoice:read"},
    "admin": {"invoice:read", "admin:read", "admin:delete"},
}
def require(perm: str):
    def checker(user=Depends(current_user)):
        role = "admin" if user["is_admin"] else "user"
        if perm not in ROLE_PERMS.get(user["role"], set()):
            raise HTTPException(status_code=403, detail ="access forbidden")
        return user
    return checker

@app.middleware("http")
async def headers(request: Request, call_next):
    r = await call_next(request)
    r.headers["Content-Security-Policy"] = "default-src 'self'"
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Strict-Transport-Security"]= "max-age=63072000; includeSubDomains"
    r.headers["X-Frame-Options"]= "DENY"
    return r

@app.exception_handler(Exception)
async def handle_error(request: Request, exc: Exception):
    return HTMLResponse("<pre>" + traceback.format_exc() + "</pre>", status_code=500)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/login")
def login(request: Request, data: dict = Body(...)):
    username, password = data["username"], data["password"]
    log.info("login attempt user=%s",username)
    row = db().execute("SELECT * FROM users WHERE username=?", (username,)
    ).fetchone()
    try :
        if not row:
            raise VerifyMismatchError()
        ph.verify(row["password"], password)
    except VerifyMismatchError:
        log.warning("failed login user=%s", username)
        return JSONResponse({"error": "bad credentials"}, status_code=401)
    request.session["user_id"] = row["id"]
    request.session["token"] = secrets.token_urlsafe(32)
    return {"status": "logged in", "user": row["username"]}


@app.get("/search")
def search(q: str = ""):
    rows = db().execute("SELECT id, name, price FROM products WHERE name LIKE ?",(f"%{q}%",)).fetchall();
    return [dict(r) for r in rows] 



@app.get("/ping")
def ping(host: IPvAnyAddress):
    try: 
        out = subprocess.run(["ping","-c","1",str(host)], check=False, timeout=5, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="ping timeout")
    return PlainTextResponse(out.stdout + out.stderr)


@app.get("/hello")
def hello(name: str = ""):
    return HTMLResponse(f"<h1>Bonjour {html.escape(name)}</h1>")

@app.get("/files/{name:path}")
def get_file(name: str):
    target = (UPLOAD_DIR / name).resolve()
    if not target.is_relative_to(UPLOAD_DIR):
        raise hTTPException(status_code=403, detail="forbidden")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(target)


@app.post("/calc")
def calc(data: dict = Body(...)):
    expr = data.get("expr")
    if not isinstance(expr, str) or len(expr)>200:
        raise HTTPException(status_code=422, detail="invalid Expression")
    try : 
        res =  ast.literal_eval(expr)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        raise HTTPException(status_code=400, detail="invalid expression") 
    return {"result": str(res)}


@app.post("/import-yaml")
async def import_yaml(request: Request):
    try:
        cfg = yaml.safe_load(await request.body())
    except yaml.YAMLError:
      raise HTTPException(status_code=400, detail="invalid yaml")
    return {"keys": list(cfg.keys()) if isinstance(cfg, dict) else str(type(cfg))}


@app.post("/import-profile")
async def import_profile(request: Request):
    profile = pickle.loads(base64.b64decode(await request.body()))
    return {"profile": str(profile)}


@app.get("/fetch")
def fetch(url: str):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parse.hostname not in FETCH_ALLOWED_HOSTS:
        raise HTTPException(status_code=400, detail="url not allowed")
    try:
        r = requests.get(url, timeout=5, verify=True, allow_redirects=False)
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="upstream error")
    return PlainTextResponse(r.text[:500])


@app.get("/invoices/{invoice_id}")
def invoice(invoice_id: int, user=Depends(current_user)):
    row = db().execute("SELECT * FROM invoices WHERE id = ? AND owner_id=?", (invoice_id,user["id"])).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    return dict(row)


@app.get("/admin/users")
def admin_users(user=Depends(require("admin:read"))):
    rows = db().execute("SELECT id, username, is_admin FROM users").fetchall()
    return [dict(r) for r in rows]


@app.delete("/users/{user_id}")
def delete_user(user_id: int, user=Depends(require("admin:delete"))):
    conn = db()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    return {"deleted": user_id}

@app.get("/boom")
def boom():
    return 1 / 0


if __name__ == "__main__":
    init_db()
    uvicorn.run("app:app", host="0.0.0.0", port=5000, reload=True)
