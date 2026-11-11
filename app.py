
"""MulaStream VentureOS: local-first proof-of-concept. Not production hardened."""

import os
import sqlite3
import secrets
import hashlib
import json
import time
import re

from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager

import httpx

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


BASE = Path(__file__).resolve().parent

DEFAULT_GEMINI_KEY = 'AQ.Ab8RN6LwtDba4vrb4S2aHp12CnhuHrote9JtoQsPzhhkgbm7RQ'
DEFAULT_GEMINI_MODEL = 'gemini-3.5-flash-lite'

# Auto-load .env configuration if present
_env_file = BASE / '.env'
if _env_file.exists():
    for _l in _env_file.read_text(encoding='utf-8').splitlines():
        _l = _l.strip()
        if _l and not _l.startswith('#') and '=' in _l:
            _k, _v = _l.split('=', 1)
            _key_name = _k.strip()
            _val = _v.strip()
            if not os.environ.get(_key_name, '').strip():
                os.environ[_key_name] = _val

# Guarantee non-empty Gemini API key and model fallback
if not os.environ.get('GEMINI_API_KEY', '').strip():
    os.environ['GEMINI_API_KEY'] = DEFAULT_GEMINI_KEY

if os.environ.get('GEMINI_MODEL', '').strip() in ('', 'gemini-2.5-flash-lite', 'gemini-2.5-flash'):
    os.environ['GEMINI_MODEL'] = DEFAULT_GEMINI_MODEL

DATA = Path(
    os.getenv('VENTUREOS_DATA', str(BASE / 'data'))
)

DATA.mkdir(parents=True, exist_ok=True)

DB = DATA / 'ventureos.sqlite3'

MODEL = os.getenv('OLLAMA_MODEL', 'qwen3:4b')
OLLAMA = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434')
SECURE_COOKIE = os.getenv('COOKIE_SECURE', '0') == '1'

SESSION_SECONDS = 60 * 60 * 8

ph = PasswordHasher(
    time_cost=2,
    memory_cost=19456,
    parallelism=2
)

app = FastAPI(
    title='MulaStream VentureOS',
    docs_url=None,
    redoc_url=None
)

app.mount(
    '/static',
    StaticFiles(directory=str(BASE / 'static')),
    name='static'
)


# ============================================================
# DATABASE CONNECTION
# ============================================================

@contextmanager
def conn():
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=15000')

    try:
        yield c
        c.commit()
    finally:
        c.close()


# ============================================================
# DATABASE INITIALISATION
# ============================================================

def init():
    with conn() as c:
        c.execute('PRAGMA journal_mode=WAL')

        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(
                role IN ('founder', 'investor')
            ),
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS admin_accounts (
            user_id INTEGER PRIMARY KEY
                REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            csrf TEXT NOT NULL,
            expires_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ventures (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            location TEXT NOT NULL DEFAULT '',
            industry TEXT NOT NULL DEFAULT '',
            problem TEXT NOT NULL DEFAULT '',
            customers TEXT NOT NULL DEFAULT '',
            proposition TEXT NOT NULL DEFAULT '',
            price REAL NOT NULL DEFAULT 0,
            unit_cost REAL NOT NULL DEFAULT 0,
            monthly_units INTEGER NOT NULL DEFAULT 0,
            fixed_cost REAL NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            venture_id INTEGER
                REFERENCES ventures(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            chat_id INTEGER NOT NULL
                REFERENCES chats(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(
                role IN ('user', 'assistant')
            ),
            body TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS evidence (
            id INTEGER PRIMARY KEY,
            venture_id INTEGER NOT NULL
                REFERENCES ventures(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            claim TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'unreviewed',
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS missions (
            id INTEGER PRIMARY KEY,
            venture_id INTEGER NOT NULL
                REFERENCES ventures(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'todo',
            created_at INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_chat_user
        ON chats(user_id, updated_at);

        CREATE INDEX IF NOT EXISTS idx_evidence_venture
        ON evidence(venture_id, user_id);
        """)


init()

print(
    f'[VentureOS] Backend loaded from: '
    f'{Path(__file__).resolve()}'
)
print(f'[VentureOS] Database in use: {DB.resolve()}')


def now():
    return int(time.time())


def clean(x, n=6000):
    return str(x or '').strip()[:n]


def row_dict(r):
    return dict(r) if r else None


# ============================================================
# AUTHENTICATION
# ============================================================

def auth(req):
    raw = req.cookies.get('vos_session', '')

    if not raw:
        raise HTTPException(401, 'Please sign in')

    digest = hashlib.sha256(
        raw.encode()
    ).hexdigest()

    with conn() as c:
        r = c.execute(
            """
            SELECT
                u.id,
                u.name,
                u.email,
                u.role,
                s.csrf,
                s.expires_at
            FROM sessions s
            JOIN users u
                ON u.id = s.user_id
            WHERE s.token_hash = ?
            """,
            (digest,)
        ).fetchone()

    if not r or r['expires_at'] <= now():
        raise HTTPException(
            401,
            'Session expired; please sign in'
        )

    # The original account role is either founder or investor.
    # Reviewer permissions are checked separately in
    # platform_features.py.
    return dict(r)


def csrf_check(req, u):
    if not secrets.compare_digest(
        req.headers.get('x-csrf-token', ''),
        u['csrf']
    ):
        raise HTTPException(
            403,
            'Invalid CSRF token'
        )


async def payload(req):
    try:
        data = await req.json()
    except Exception:
        raise HTTPException(
            400,
            'Expected JSON'
        )

    if not isinstance(data, dict):
        raise HTTPException(
            400,
            'Expected an object'
        )

    return data


def venture_owned(c, uid, vid):
    r = c.execute(
        """
        SELECT *
        FROM ventures
        WHERE id = ? AND user_id = ?
        """,
        (vid, uid)
    ).fetchone()

    if not r:
        raise HTTPException(
            404,
            'Venture not found'
        )

    return r


def chat_owned(c, uid, cid):
    r = c.execute(
        """
        SELECT *
        FROM chats
        WHERE id = ? AND user_id = ?
        """,
        (cid, uid)
    ).fetchone()

    if not r:
        raise HTTPException(
            404,
            'Conversation not found'
        )

    return r


# ============================================================
# HOME
# ============================================================

@app.get('/', response_class=HTMLResponse)
def home():
    return (
        BASE / 'static' / 'index.html'
    ).read_text(encoding='utf-8')


# ============================================================
# REGISTRATION
# ============================================================

@app.post('/api/register')
async def register(req: Request):
    d = await payload(req)

    name = clean(d.get('name'), 80)
    email = clean(d.get('email'), 200).lower()
    password = str(d.get('password') or '')
    role = d.get('role', 'founder')

    if (
        len(name) < 2
        or not re.fullmatch(
            r'[^@\s]+@[^@\s]+\.[^@\s]+',
            email
        )
        or not (12 <= len(password) <= 256)
        or role not in ('founder', 'investor')
    ):
        raise HTTPException(
            400,
            'Name, valid email, account type and a '
            'password of at least 12 characters are required'
        )

    with conn() as c:
        try:
            c.execute(
                """
                INSERT INTO users(
                    name,
                    email,
                    password_hash,
                    role,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    name,
                    email,
                    ph.hash(password),
                    role,
                    now()
                )
            )
        except sqlite3.IntegrityError:
            raise HTTPException(
                409,
                'Email already registered'
            )

    return {
        'ok': True,
        'message': 'Account created. Please sign in.'
    }


# ============================================================
# LOGIN — TWO ACCOUNT TYPES
# ============================================================

@app.post('/api/login')
async def login(req: Request):
    d = await payload(req)

    email = clean(d.get('email'), 200).lower()
    password = str(d.get('password') or '')

    selected_role = str(
        d.get('role') or ''
    ).strip().lower()

    with conn() as c:
        user = c.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            """,
            (email,)
        ).fetchone()

    try:
        if not user:
            # Perform password verification work for
            # accounts that do not exist.
            try:
                ph.verify(
                    ph.hash('dummy-password-value'),
                    password
                )
            except (VerifyMismatchError, VerificationError):
                pass

            raise HTTPException(
                401,
                'Invalid credentials'
            )

        ph.verify(
            user['password_hash'],
            password
        )

    except (VerifyMismatchError, VerificationError):
        raise HTTPException(
            401,
            'Invalid credentials'
        )

    actual_role = user['role']

    if actual_role not in ('founder', 'investor'):
        raise HTTPException(
            403,
            'Unsupported account role'
        )

    # The selected login option is not a source
    # of permissions. The database remains authoritative.
    if selected_role:
        if selected_role not in ('founder', 'investor'):
            raise HTTPException(
                400,
                'Choose Entrepreneur or Investor'
            )

        if selected_role != actual_role:
            raise HTTPException(
                403,
                'This account belongs to the other '
                'login option. Choose the correct account type.'
            )

    raw = secrets.token_urlsafe(40)
    csrf = secrets.token_urlsafe(32)

    with conn() as c:
        c.execute(
            """
            INSERT INTO sessions(
                token_hash,
                user_id,
                csrf,
                expires_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                hashlib.sha256(
                    raw.encode()
                ).hexdigest(),
                user['id'],
                csrf,
                now() + SESSION_SECONDS
            )
        )

    response = JSONResponse({
        'ok': True,
        'csrf': csrf,
        'name': user['name'],
        'role': actual_role
    })

    response.set_cookie(
        'vos_session',
        raw,
        httponly=True,
        samesite='strict',
        secure=SECURE_COOKIE,
        max_age=SESSION_SECONDS,
        path='/'
    )

    return response


@app.get('/api/me')
def me(req: Request):
    return auth(req)


@app.post('/api/logout')
def logout(req: Request):
    u = auth(req)
    csrf_check(req, u)

    raw = req.cookies.get('vos_session', '')

    with conn() as c:
        c.execute(
            """
            DELETE FROM sessions
            WHERE token_hash = ?
            """,
            (
                hashlib.sha256(
                    raw.encode()
                ).hexdigest(),
            )
        )

    response = JSONResponse({'ok': True})
    response.delete_cookie(
        'vos_session',
        path='/'
    )

    return response


# ============================================================
# VENTURES
# ============================================================

@app.get('/api/ventures')
def ventures(req: Request):
    u = auth(req)

    with conn() as c:
        return [
            dict(x)
            for x in c.execute(
                """
                SELECT *
                FROM ventures
                WHERE user_id = ?
                ORDER BY id DESC
                """,
                (u['id'],)
            )
        ]


@app.post('/api/ventures')
async def create_venture(req: Request):
    u = auth(req)
    csrf_check(req, u)

    d = await payload(req)
    name = clean(d.get('name'), 120)

    if not name:
        raise HTTPException(
            400,
            'Venture name required'
        )

    if u['role'] != 'founder':
        raise HTTPException(
            403,
            'Only founders can create ventures'
        )

    with conn() as c:
        cur = c.execute(
            """
            INSERT INTO ventures(
                user_id,
                name,
                location,
                industry,
                problem,
                customers,
                proposition,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                u['id'],
                name,
                clean(d.get('location'), 120),
                clean(d.get('industry'), 120),
                clean(d.get('problem'), 1000),
                clean(d.get('customers'), 1000),
                clean(d.get('proposition'), 1000),
                now()
            )
        )

        vid = cur.lastrowid

        titles = [
            'Interview five potential customers',
            'Record your top three business assumptions',
            'Collect evidence for customer demand'
        ]

        for title in titles:
            c.execute(
                """
                INSERT INTO missions(
                    venture_id,
                    user_id,
                    title,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (vid, u['id'], title, now())
            )

    return {'id': vid}


@app.patch('/api/ventures/{vid}')
async def update_venture(req: Request, vid: int):
    u = auth(req)
    csrf_check(req, u)
    d = await payload(req)

    fields = [
        'name',
        'location',
        'industry',
        'problem',
        'customers',
        'proposition',
        'price',
        'unit_cost',
        'monthly_units',
        'fixed_cost'
    ]

    patch = {}

    for f in fields:
        if f in d:
            if f in (
                'price',
                'unit_cost',
                'fixed_cost',
                'monthly_units'
            ):
                try:
                    v = float(d[f])
                    assert 0 <= v <= 1e10
                except (
                    ValueError,
                    TypeError,
                    AssertionError
                ):
                    raise HTTPException(
                        400,
                        'Financial values must be nonnegative'
                    )

                patch[f] = (
                    int(v)
                    if f == 'monthly_units'
                    else round(v, 2)
                )
            else:
                patch[f] = clean(d[f], 1000)

    if not patch:
        return {'ok': True}

    with conn() as c:
        venture_owned(c, u['id'], vid)

        sql = (
            'UPDATE ventures SET ' +
            ','.join(
                f'{f}=?'
                for f in patch
            ) +
            ' WHERE id=? AND user_id=?'
        )

        c.execute(
            sql,
            (
                *patch.values(),
                vid,
                u['id']
            )
        )

    return {'ok': True}


@app.get('/api/ventures/{vid}/dashboard')
def dashboard(req: Request, vid: int):
    u = auth(req)

    with conn() as c:
        v = dict(
            venture_owned(
                c,
                u['id'],
                vid
            )
        )

        evidence = [
            dict(x)
            for x in c.execute(
                """
                SELECT *
                FROM evidence
                WHERE venture_id = ?
                    AND user_id = ?
                ORDER BY id DESC
                """,
                (vid, u['id'])
            )
        ]

        missions = [
            dict(x)
            for x in c.execute(
                """
                SELECT *
                FROM missions
                WHERE venture_id = ?
                    AND user_id = ?
                ORDER BY id
                """,
                (vid, u['id'])
            )
        ]

    revenue = round(
        v['price'] * v['monthly_units'],
        2
    )

    variable = round(
        v['unit_cost'] * v['monthly_units'],
        2
    )

    profit = round(
        revenue - variable - v['fixed_cost'],
        2
    )

    return {
        'venture': v,
        'evidence': evidence,
        'missions': missions,
        'financials': {
            'revenue': revenue,
            'variable_cost': variable,
            'fixed_cost': v['fixed_cost'],
            'estimated_profit': profit,
            'currency': 'NAD',
            'note': (
                'Illustrative estimate only; '
                'not an investment recommendation.'
            )
        }
    }


# ============================================================
# EVIDENCE
# ============================================================

@app.post('/api/ventures/{vid}/evidence')
async def add_evidence(req: Request, vid: int):
    u = auth(req)
    csrf_check(req, u)
    d = await payload(req)

    claim = clean(d.get('claim'), 1000)

    if not claim:
        raise HTTPException(
            400,
            'Enter the claim or observation'
        )

    with conn() as c:
        venture_owned(c, u['id'], vid)

        c.execute(
            """
            INSERT INTO evidence(
                venture_id,
                user_id,
                claim,
                source,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                vid,
                u['id'],
                claim,
                clean(d.get('source'), 500),
                now()
            )
        )

    return {
        'ok': True,
        'status': 'unreviewed'
    }


@app.patch('/api/ventures/{vid}/evidence/{eid}')
async def edit_evidence(
    req: Request,
    vid: int,
    eid: int
):
    u = auth(req)
    csrf_check(req, u)
    d = await payload(req)

    claim = clean(d.get('claim'), 1000)
    source = clean(d.get('source'), 500)

    if not claim:
        raise HTTPException(
            400,
            'Claim cannot be empty'
        )

    with conn() as c:
        venture_owned(c, u['id'], vid)

        record = c.execute(
            """
            SELECT status
            FROM evidence
            WHERE id = ?
              AND venture_id = ?
              AND user_id = ?
            """,
            (eid, vid, u['id'])
        ).fetchone()

        if not record:
            raise HTTPException(
                404,
                'Evidence record not found'
            )

        if record['status'] != 'unreviewed':
            raise HTTPException(
                409,
                'Reviewed evidence cannot be altered'
            )

        c.execute(
            """
            UPDATE evidence
            SET claim = ?, source = ?
            WHERE id = ?
            """,
            (claim, source, eid)
        )

    return {
        'ok': True,
        'status': 'unreviewed'
    }


@app.delete('/api/ventures/{vid}/evidence/{eid}')
def remove_evidence(
    req: Request,
    vid: int,
    eid: int
):
    u = auth(req)
    csrf_check(req, u)

    with conn() as c:
        venture_owned(c, u['id'], vid)

        record = c.execute(
            """
            SELECT status
            FROM evidence
            WHERE id = ?
              AND venture_id = ?
              AND user_id = ?
            """,
            (eid, vid, u['id'])
        ).fetchone()

        if not record:
            raise HTTPException(
                404,
                'Evidence record not found'
            )

        if record['status'] != 'unreviewed':
            raise HTTPException(
                409,
                'Reviewed evidence cannot be deleted'
            )

        c.execute(
            """
            DELETE FROM evidence
            WHERE id = ?
            """,
            (eid,)
        )

    return {'ok': True}


# ============================================================
# MISSIONS
# ============================================================

@app.post('/api/missions/{mid}/toggle')
def toggle_mission(req: Request, mid: int):
    u = auth(req)
    csrf_check(req, u)

    with conn() as c:
        m = c.execute(
            """
            SELECT *
            FROM missions
            WHERE id = ?
              AND user_id = ?
            """,
            (mid, u['id'])
        ).fetchone()

        if not m:
            raise HTTPException(
                404,
                'Mission not found'
            )

        new_state = (
            'todo'
            if m['state'] == 'done'
            else 'done'
        )

        c.execute(
            """
            UPDATE missions
            SET state = ?
            WHERE id = ?
              AND user_id = ?
            """,
            (new_state, mid, u['id'])
        )

    return {
        'ok': True,
        'note': (
            'Self-reported task completion, '
            'not verified evidence'
        )
    }


# ============================================================
# PRIVATE CHATS
# ============================================================

@app.get('/api/chats')
def chats(req: Request):
    u = auth(req)

    with conn() as c:
        return [
            dict(x)
            for x in c.execute(
                """
                SELECT *
                FROM chats
                WHERE user_id = ?
                ORDER BY updated_at DESC
                """,
                (u['id'],)
            )
        ]


@app.post('/api/chats')
async def create_chat(req: Request):
    u = auth(req)
    csrf_check(req, u)
    d = await payload(req)

    vid = d.get('venture_id') or None

    with conn() as c:
        if vid:
            venture_owned(
                c,
                u['id'],
                int(vid)
            )

        cur = c.execute(
            """
            INSERT INTO chats(
                user_id,
                venture_id,
                title,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                u['id'],
                vid,
                clean(d.get('title'), 100)
                or 'New conversation',
                now(),
                now()
            )
        )

        return {'id': cur.lastrowid}


@app.get('/api/chats/{cid}')
def get_chat(req: Request, cid: int):
    u = auth(req)

    with conn() as c:
        chat = dict(
            chat_owned(
                c,
                u['id'],
                cid
            )
        )

        messages = [
            dict(x)
            for x in c.execute(
                """
                SELECT
                    id,
                    role,
                    body,
                    created_at
                FROM messages
                WHERE chat_id = ?
                ORDER BY id
                """,
                (cid,)
            )
        ]

    return {
        'chat': chat,
        'messages': messages
    }


@app.patch('/api/chats/{cid}')
async def rename_chat(req: Request, cid: int):
    u = auth(req)
    csrf_check(req, u)
    d = await payload(req)

    title = clean(d.get('title'), 100)

    if not title:
        raise HTTPException(
            400,
            'Title required'
        )

    with conn() as c:
        chat_owned(
            c,
            u['id'],
            cid
        )

        c.execute(
            """
            UPDATE chats
            SET title = ?, updated_at = ?
            WHERE id = ?
              AND user_id = ?
            """,
            (title, now(), cid, u['id'])
        )

    return {'ok': True}


@app.delete('/api/chats/{cid}')
def delete_chat(req: Request, cid: int):
    u = auth(req)
    csrf_check(req, u)

    with conn() as c:
        chat_owned(
            c,
            u['id'],
            cid
        )

        c.execute(
            """
            DELETE FROM chats
            WHERE id = ?
              AND user_id = ?
            """,
            (cid, u['id'])
        )

    return {'ok': True}


# ============================================================
# AI MENTOR
# ============================================================

from chatbot2_engine.service import reply as mentor_reply


@app.post('/api/chats/{cid}/send')
async def send(req: Request, cid: int):
    u = auth(req)
    csrf_check(req, u)
    d = await payload(req)

    body = clean(d.get('message'), 3000)

    if not body:
        raise HTTPException(
            400,
            'Message required'
        )

    with conn() as c:
        chat = chat_owned(
            c,
            u['id'],
            cid
        )

        if chat['venture_id']:
            v = venture_owned(
                c,
                u['id'],
                chat['venture_id']
            )

            context = (
                f"Business name {v['name']}; "
                f"location {v['location']}; "
                f"industry {v['industry']}; "
                f"customers {v['customers']}; "
                f"value {v['proposition']}"
            )
        else:
            context = 'No venture linked.'

        previous = [
            {
                'role': m['role'],
                'content': m['body']
            }
            for m in reversed(
                c.execute(
                    """
                    SELECT role, body
                    FROM messages
                    WHERE chat_id = ?
                    ORDER BY id DESC
                    LIMIT 6
                    """,
                    (cid,)
                ).fetchall()
            )
        ]

        c.execute(
            """
            INSERT INTO messages(
                chat_id,
                role,
                body,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (cid, 'user', body, now())
        )

        c.execute(
            """
            UPDATE chats
            SET updated_at = ?
            WHERE id = ?
            """,
            (now(), cid)
        )

    answer = await mentor_reply(
        body,
        previous,
        u['role'],
        context
    )

    with conn() as c:
        chat_owned(
            c,
            u['id'],
            cid
        )

        c.execute(
            """
            INSERT INTO messages(
                chat_id,
                role,
                body,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (cid, 'assistant', answer, now())
        )

        if chat['title'] == 'New conversation':
            c.execute(
                """
                UPDATE chats
                SET title = ?
                WHERE id = ?
                """,
                (body[:65], cid)
            )

    return {'reply': answer}


# ============================================================
# EIGHT-STAGE INCUBATOR
# ============================================================

from incubator import STAGES, assess, roadmap


def init_incubator():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS stage_submissions (
            id INTEGER PRIMARY KEY,
            venture_id INTEGER NOT NULL
                REFERENCES ventures(id) ON DELETE CASCADE,
            stage INTEGER NOT NULL,
            user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            deliverable TEXT NOT NULL,
            narrative TEXT NOT NULL,
            evidence_ref TEXT NOT NULL DEFAULT '',
            ai_score INTEGER NOT NULL DEFAULT 0,
            ai_feedback TEXT NOT NULL DEFAULT '',
            reviewer_status TEXT NOT NULL DEFAULT 'pending',
            created_at INTEGER NOT NULL,
            UNIQUE(venture_id, stage, deliverable)
        );
        """)


init_incubator()


@app.get('/api/ventures/{vid}/incubator')
def incubator_status(req: Request, vid: int):
    u = auth(req)

    with conn() as c:
        v = dict(
            venture_owned(c, u['id'], vid)
        )

        rows = [
            dict(r)
            for r in c.execute(
                """
                SELECT *
                FROM stage_submissions
                WHERE venture_id = ?
                  AND user_id = ?
                """,
                (vid, u['id'])
            )
        ]

    grouped = []
    eligible = True

    for stage in STAGES:
        submissions = [
            r
            for r in rows
            if r['stage'] == stage['number']
        ]

        missing = [
            d
            for d in stage['deliverables']
            if not any(
                r['deliverable'] == d
                and r['ai_score'] >= 70
                and r['reviewer_status'] == 'approved'
                for r in submissions
            )
        ]

        pending = [
            r
            for r in submissions
            if r['ai_score'] >= 70
            and r['reviewer_status'] == 'pending'
        ]

        blocked = bool(missing or pending)

        state = (
            'reviewed'
            if not missing
            else (
                'awaiting_mentor_review'
                if pending
                else 'needs_work'
            )
        )

        grouped.append({
            **stage,
            'submissions': submissions,
            'missing': missing,
            'status': state,
            'unlocked': eligible
        })

        if blocked:
            eligible = False

    passed = sum(
        x['status'] == 'reviewed'
        for x in grouped
    )

    readiness = round(
        sum(
            min(
                100,
                len([
                    r
                    for r in rows
                    if r['stage'] == stage['number']
                    and r['ai_score'] >= 70
                ])
                / len(stage['deliverables'])
                * 100
            )
            for stage in STAGES
        ) / 8
    )

    return {
        'venture': v['name'],
        'stages': grouped,
        'readiness_score': readiness,
        'reviewed_stages': passed,
        'total_stages': 8,
        'roadmap': roadmap(v),
        'notice': (
            'Automated scores are provisional. '
            'Reviewer approval and authentic evidence '
            'are required before a stage can be verified.'
        )
    }


@app.post('/api/ventures/{vid}/incubator/{stage_num}/submit')
async def submit_stage(
    req: Request,
    vid: int,
    stage_num: int
):
    u = auth(req)
    csrf_check(req, u)
    d = await payload(req)

    with conn() as c:
        venture_owned(c, u['id'], vid)

    if u['role'] != 'founder':
        raise HTTPException(
            403,
            'Founders only'
        )

    if stage_num not in range(1, 9):
        raise HTTPException(
            404,
            'Invalid stage'
        )

    stage = STAGES[stage_num - 1]

    deliverable = clean(
        d.get('deliverable'),
        180
    )

    if deliverable not in stage['deliverables']:
        raise HTTPException(
            400,
            'Choose a listed deliverable'
        )

    narrative = clean(
        d.get('narrative'),
        12000
    )

    source = clean(
        d.get('evidence_ref'),
        500
    )

    if len(narrative) < 40:
        raise HTTPException(
            400,
            'Please provide at least 40 characters '
            'of substantive work'
        )

    result = assess(
        stage_num,
        deliverable,
        narrative,
        source
    )

    with conn() as c:
        # Server-side stage progression validation.
        for prior in STAGES[:stage_num - 1]:
            approved = {
                r['deliverable']
                for r in c.execute(
                    """
                    SELECT deliverable
                    FROM stage_submissions
                    WHERE venture_id = ?
                      AND stage = ?
                      AND reviewer_status = ?
                      AND ai_score >= 70
                    """,
                    (vid, prior['number'], 'approved')
                )
            }

            if any(
                required not in approved
                for required in prior['deliverables']
            ):
                raise HTTPException(
                    403,
                    'Earlier incubation stage '
                    'requires reviewer approval'
                )

        existing = c.execute(
            """
            SELECT reviewer_status
            FROM stage_submissions
            WHERE venture_id = ?
              AND stage = ?
              AND deliverable = ?
            """,
            (vid, stage_num, deliverable)
        ).fetchone()

        if (
            existing
            and existing['reviewer_status'] == 'approved'
        ):
            raise HTTPException(
                409,
                'Approved deliverable is read-only'
            )

        c.execute(
            """
            INSERT INTO stage_submissions(
                venture_id,
                stage,
                user_id,
                deliverable,
                narrative,
                evidence_ref,
                ai_score,
                ai_feedback,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(
                venture_id,
                stage,
                deliverable
            )
            DO UPDATE SET
                narrative = excluded.narrative,
                evidence_ref = excluded.evidence_ref,
                ai_score = excluded.ai_score,
                ai_feedback = excluded.ai_feedback,
                reviewer_status = 'pending',
                created_at = excluded.created_at
            """,
            (
                vid,
                stage_num,
                u['id'],
                deliverable,
                narrative,
                source,
                result['score'],
                result['feedback'],
                now()
            )
        )

    return {
        **result,
        'status': 'provisional_only',
        'mentor_validation_required': True
    }


@app.get('/api/ventures/{vid}/investor-package')
def investor_package(req: Request, vid: int):
    u = auth(req)

    with conn() as c:
        v = dict(
            venture_owned(
                c,
                u['id'],
                vid
            )
        )

        rows = [
            dict(r)
            for r in c.execute(
                """
                SELECT
                    stage,
                    deliverable,
                    narrative,
                    evidence_ref,
                    ai_score,
                    reviewer_status
                FROM stage_submissions
                WHERE venture_id = ?
                  AND user_id = ?
                ORDER BY stage, deliverable
                """,
                (vid, u['id'])
            )
        ]

    outstanding = [
        {
            'stage': x['number'],
            'required': d
        }
        for x in STAGES
        for d in x['deliverables']
        if not any(
            r['stage'] == x['number']
            and r['deliverable'] == d
            and r['reviewer_status'] == 'approved'
            for r in rows
        )
    ]

    return {
        'venture': v,
        'deliverables': rows,
        'outstanding': outstanding,
        'disclaimer': (
            'Draft due diligence dossier, not verified '
            'investor readiness. Requires independent '
            'review and supporting authentic documents.'
        )
    }


# ============================================================
# SYSTEM HEALTH
# ============================================================

@app.get('/api/health')
def health():
    key = os.getenv('GEMINI_API_KEY', '').strip() or DEFAULT_GEMINI_KEY
    model = os.getenv('GEMINI_MODEL', '').strip() or DEFAULT_GEMINI_MODEL
    return {
        'app': 'online',
        'ai': 'configured' if key else 'not configured',
        'model': model,
        'database': 'local SQLite',
        'note': 'Configured and active.'
    }


# ============================================================
# STARTUP CAPITAL PLANNER
# ============================================================

@app.get('/api/business-budget')
def business_budget(
    req: Request,
    amount: float = 10000,
    kind: str = 'retail'
):
    auth(req)

    if not 100 <= amount <= 1_000_000:
        raise HTTPException(
            400,
            'Amount must be between N$100 '
            'and N$1,000,000'
        )

    patterns = {
        'retail': [
            ('Opening inventory', 45),
            ('Marketing and customer tests', 10),
            ('Premises/market stall', 15),
            ('Transport and packaging', 10),
            ('Permits and administration reserve', 5),
            ('Emergency working capital', 15)
        ],
        'service': [
            ('Tools and setup', 30),
            ('Marketing and customer tests', 20),
            ('Transport and delivery', 10),
            ('Software/communications', 10),
            ('Permits and administration reserve', 5),
            ('Emergency working capital', 25)
        ],
        'food': [
            ('Initial ingredients and stock', 35),
            ('Equipment and food safety setup', 25),
            ('Marketing and customer tests', 10),
            ('Transport and packaging', 10),
            ('Permits and administration reserve', 10),
            ('Emergency working capital', 10)
        ]
    }

    if kind not in patterns:
        raise HTTPException(
            400,
            'Unknown business category'
        )

    values = []
    used = 0

    for label, percent in patterns[kind][:-1]:
        value = round(
            amount * percent / 100,
            2
        )

        used += value

        values.append({
            'category': label,
            'percentage': percent,
            'amount_nad': value
        })

    label, percent = patterns[kind][-1]

    values.append({
        'category': label,
        'percentage': percent,
        'amount_nad': round(amount - used, 2)
    })

    return {
        'starting_capital_nad': amount,
        'category': kind,
        'allocations': values,
        'total_nad': round(
            sum(
                x['amount_nad']
                for x in values
            ),
            2
        ),
        'caution': (
            'Illustrative budgeting framework, '
            'not current Namibian market prices. '
            'Check supplier quotes, customer demand, '
            'licence requirements and actual fixed costs '
            'before spending.'
        )
    }


# ============================================================
# PLATFORM FEATURES
# ============================================================

# Additional routes for investor interactions, evidence
# uploads, assessment, publication and reviewer access.

import platform_features

platform_features.install(
    app,
    conn,
    auth,
    csrf_check,
    venture_owned,
    now
)


# ============================================================
# WHATSAPP INTEGRATION
# ============================================================

# The WhatsApp bridge is isolated from private web chats.

import whatsapp_integration

whatsapp_integration.install(app, conn)
