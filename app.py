"""rtl-admin-starter — a small Arabic/RTL admin dashboard starter on FastAPI.

Most admin templates are LTR-first: you flip `direction: rtl` on the body and
the layout "looks" Arabic while the details stay broken — Latin fragments inside
Arabic sentences reorder their punctuation, numbers lose their alignment, and
paddings stay physically left/right so every breakpoint needs a second fix.

This starter is RTL-first instead, and ships the two pieces that are actually
tedious to get right:

  1. A locked-by-default auth gate. Every route is authenticated unless its path
     is listed in PUBLIC_PATHS, so a new endpoint cannot be forgotten open. The
     list is asserted by the test suite, which makes opening a path a reviewed
     decision instead of a silent one.
  2. A server-side table contract (search + pagination + total) that the front
     end renders as a real table on desktop and as cards on a phone.

Run:  uvicorn app:app --reload
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).parent
DB_PATH = Path(os.getenv("RTL_ADMIN_DB", ROOT / "data.db"))

# The signing key must survive restarts, or every token issued before a restart
# silently stops working. Generated once into .env-style config in real use.
SECRET = os.getenv("RTL_ADMIN_SECRET", "dev-only-change-me")
TOKEN_TTL_SECONDS = int(os.getenv("RTL_ADMIN_TOKEN_TTL", "43200"))

ADMIN_USERNAME = os.getenv("RTL_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("RTL_ADMIN_PASSWORD", "admin123")

# The only paths served without a token. Anything not listed here is closed,
# including paths added later — see tests/test_auth_gate.py, which fails when
# this list and the test's own copy drift apart.
PUBLIC_PATHS = {"/", "/health", "/api/auth/login"}


# --------------------------------------------------------------------------- #
#  database                                                                     #
# --------------------------------------------------------------------------- #
SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    item_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    category    TEXT    NOT NULL DEFAULT '',
    quantity    INTEGER NOT NULL DEFAULT 0,
    status      TEXT    NOT NULL DEFAULT 'active',
    updated_at  REAL    NOT NULL
);
"""

DEMO_ROWS = [
    ("أسمنت بورتلاندي", "مواد بناء", 240, "active"),
    ("حديد تسليح 16 مم", "مواد بناء", 85, "active"),
    ("زيت هيدروليك", "قطع غيار", 12, "low"),
    ("فلتر هواء", "قطع غيار", 0, "out"),
    ("خوذة أمان", "سلامة", 60, "active"),
    ("قفاز جلد", "سلامة", 18, "low"),
    ("كابل كهرباء 3×4", "كهرباء", 310, "active"),
    ("لمبة LED 50 وات", "كهرباء", 44, "active"),
]


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(seed: bool = True) -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        if seed and not conn.execute("SELECT 1 FROM items LIMIT 1").fetchone():
            conn.executemany(
                "INSERT INTO items (name, category, quantity, status, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                [(*row, time.time()) for row in DEMO_ROWS],
            )


def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


Db = Annotated[sqlite3.Connection, Depends(get_db)]


# --------------------------------------------------------------------------- #
#  auth                                                                         #
# --------------------------------------------------------------------------- #
def hash_password(password: str, salt: str = "rtl-admin") -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


def issue_token(username: str) -> str:
    expires = int(time.time()) + TOKEN_TTL_SECONDS
    payload = f"{username}:{expires}"
    signature = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def read_token(token: str) -> str | None:
    """Return the username a token belongs to, or None if it is not usable."""
    try:
        username, expires, signature = token.rsplit(":", 2)
    except ValueError:
        return None
    expected = hmac.new(
        SECRET.encode(), f"{username}:{expires}".encode(), hashlib.sha256
    ).hexdigest()
    # compare_digest, not ==: a plain comparison leaks the signature one byte at
    # a time through response timing.
    if not hmac.compare_digest(signature, expected):
        return None
    if int(expires) < time.time():
        return None
    return username


def enforce_auth(request: Request) -> None:
    """Application-wide gate. Registered once, applies to every route."""
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith("/static/"):
        return
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else ""
    username = read_token(token) if token else None
    if not username:
        raise HTTPException(401, "authentication required")
    request.state.username = username


# --------------------------------------------------------------------------- #
#  schemas                                                                      #
# --------------------------------------------------------------------------- #
class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="", max_length=60)
    quantity: int = Field(default=0, ge=0)
    status: str = Field(default="active", pattern="^(active|low|out)$")


class ItemOut(ItemIn):
    item_id: int
    updated_at: float


class ItemPage(BaseModel):
    """The table contract: the front end needs the total to draw the pager,
    so a bare list of rows is not enough."""

    rows: list[ItemOut]
    total: int
    page: int
    pages: int


# --------------------------------------------------------------------------- #
#  app                                                                          #
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="rtl-admin-starter", lifespan=lifespan,
              dependencies=[Depends(enforce_auth)])
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(ROOT / "templates" / "index.html")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/auth/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    # Both branches run the same hashing work: returning early on an unknown
    # username makes the response measurably faster and hands an attacker a way
    # to enumerate accounts.
    supplied = hash_password(body.password)
    expected = hash_password(ADMIN_PASSWORD)
    if body.username != ADMIN_USERNAME or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "بيانات الدخول غير صحيحة")
    return LoginResponse(token=issue_token(body.username), username=body.username)


@app.get("/api/auth/me")
def me(request: Request) -> dict:
    return {"username": request.state.username}


@app.get("/api/items", response_model=ItemPage)
def list_items(
    db: Db,
    q: str = "",
    page: int = 1,
    per_page: int = 10,
) -> ItemPage:
    page = max(1, page)
    per_page = min(max(1, per_page), 100)
    where, params = "", []
    if q.strip():
        where = " WHERE name LIKE ? OR category LIKE ?"
        params = [f"%{q.strip()}%"] * 2
    total = db.execute(f"SELECT COUNT(*) FROM items{where}", params).fetchone()[0]
    rows = db.execute(
        f"SELECT * FROM items{where} ORDER BY item_id DESC LIMIT ? OFFSET ?",
        [*params, per_page, (page - 1) * per_page],
    ).fetchall()
    return ItemPage(
        rows=[ItemOut(**dict(row)) for row in rows],
        total=total,
        page=page,
        pages=max(1, -(-total // per_page)),
    )


@app.post("/api/items", response_model=ItemOut, status_code=201)
def create_item(body: ItemIn, db: Db) -> ItemOut:
    cur = db.execute(
        "INSERT INTO items (name, category, quantity, status, updated_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (body.name, body.category, body.quantity, body.status, time.time()),
    )
    row = db.execute("SELECT * FROM items WHERE item_id = ?", (cur.lastrowid,)).fetchone()
    return ItemOut(**dict(row))


@app.put("/api/items/{item_id}", response_model=ItemOut)
def update_item(
    item_id: int, body: ItemIn, db: Db
) -> ItemOut:
    if not db.execute("SELECT 1 FROM items WHERE item_id = ?", (item_id,)).fetchone():
        raise HTTPException(404, "not found")
    db.execute(
        "UPDATE items SET name = ?, category = ?, quantity = ?, status = ?,"
        " updated_at = ? WHERE item_id = ?",
        (body.name, body.category, body.quantity, body.status, time.time(), item_id),
    )
    row = db.execute("SELECT * FROM items WHERE item_id = ?", (item_id,)).fetchone()
    return ItemOut(**dict(row))


@app.delete("/api/items/{item_id}", status_code=204)
def delete_item(item_id: int, db: Db) -> None:
    if not db.execute("SELECT 1 FROM items WHERE item_id = ?", (item_id,)).fetchone():
        raise HTTPException(404, "not found")
    db.execute("DELETE FROM items WHERE item_id = ?", (item_id,))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("RTL_ADMIN_HOST", "127.0.0.1"),
                port=int(os.getenv("RTL_ADMIN_PORT", "8099")))
