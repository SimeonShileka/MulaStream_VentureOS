
"""
MulaStream VentureOS platform features.

Two account roles:
    founder
    investor

Authorised investors may activate reviewer access.
Existing administrator memberships are recognised
as authorised reviewers.

Prototype application. Not production hardened.
"""

from fastapi import APIRouter, Request, HTTPException

import os
import secrets
import json
import hashlib
import re
import time

from pathlib import Path

from incubator import STAGES


router = APIRouter(prefix="/api")

_db = None


# ============================================================
# INSTALL PLATFORM FEATURES
# ============================================================

def install(app, conn, auth, csrf, owner, now):
    global _db

    _db = (conn, auth, csrf, owner, now)

    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS admin_audit (
            id INTEGER PRIMARY KEY,
            actor INTEGER NOT NULL,
            action TEXT NOT NULL,
            target TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reviewer_accounts (
            user_id INTEGER PRIMARY KEY
                REFERENCES users(id),
            role TEXT NOT NULL
                CHECK(role IN ('mentor', 'admin'))
        );

        CREATE TABLE IF NOT EXISTS review_events (
            id INTEGER PRIMARY KEY,
            venture_id INTEGER NOT NULL,
            stage INTEGER NOT NULL,
            deliverable TEXT NOT NULL,
            actor INTEGER NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rewards (
            id INTEGER PRIMARY KEY,
            venture_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            event_key TEXT NOT NULL UNIQUE,
            points INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS investor_interest (
            id INTEGER PRIMARY KEY,
            venture_id INTEGER NOT NULL,
            investor_id INTEGER NOT NULL,
            note TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            UNIQUE(venture_id, investor_id)
        );

        CREATE TABLE IF NOT EXISTS published_ventures (
            venture_id INTEGER PRIMARY KEY,
            approved_by INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY,
            venture_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            stage INTEGER,
            deliverable TEXT,
            filename TEXT NOT NULL,
            content_type TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            bytes INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS assessment_runs (
            id INTEGER PRIMARY KEY,
            venture_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            score INTEGER NOT NULL,
            scores_json TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS investor_comments (
            id INTEGER PRIMARY KEY,
            venture_id INTEGER NOT NULL
                REFERENCES ventures(id) ON DELETE CASCADE,
            investor_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            body TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_investor_comments_venture
        ON investor_comments(venture_id, id);

        CREATE TABLE IF NOT EXISTS investor_decisions (
            venture_id INTEGER NOT NULL
                REFERENCES ventures(id) ON DELETE CASCADE,
            investor_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            decision TEXT NOT NULL
                CHECK (
                    decision IN (
                        'invest',
                        'collaborate',
                        'more_information',
                        'decline'
                    )
                ),
            reason TEXT NOT NULL,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY(venture_id, investor_id)
        );
        """)

    app.include_router(router)


def deps():
    if _db is None:
        raise RuntimeError(
            "Platform features not installed"
        )

    return _db


# ============================================================
# REVIEWER AUTHORISATION
# ============================================================

def reviewer(req):
    conn, auth, csrf, owner, now = deps()

    user = auth(req)

    if user["role"] != "investor":
        raise HTTPException(
            403,
            "Investor account required"
        )

    with conn() as c:
        allowed = c.execute(
            """
            SELECT 1
            FROM reviewer_accounts
            WHERE user_id = ?

            UNION

            SELECT 1
            FROM admin_accounts
            WHERE user_id = ?
            """,
            (user["id"], user["id"])
        ).fetchone()

    if not allowed:
        raise HTTPException(
            403,
            "Reviewer access is not activated"
        )

    return user


# ============================================================
# REVIEWER TOKEN ACTIVATION
# ============================================================

@router.post("/reviewer/activate")
async def activate(req: Request):
    conn, auth, csrf, owner, now = deps()

    user = auth(req)

    csrf(req, user)

    if user["role"] != "investor":
        raise HTTPException(
            403,
            "Only investors can activate reviewer access"
        )

    expected = os.getenv(
        "MULASTREAM_REVIEWER_SETUP_SECRET",
        ""
    )

    if len(expected) < 20:
        raise HTTPException(
            503,
            "Reviewer activation token is not configured"
        )

    data = await req.json()

    if not isinstance(data, dict):
        raise HTTPException(
            400,
            "Expected a JSON object"
        )

    supplied = str(
        data.get("token") or ""
    )

    if not secrets.compare_digest(
        supplied,
        expected
    ):
        raise HTTPException(
            403,
            "Invalid reviewer activation token"
        )

    with conn() as c:
        c.execute(
            """
            INSERT OR IGNORE INTO reviewer_accounts(
                user_id,
                role
            )
            VALUES (?, 'mentor')
            """,
            (user["id"],)
        )

    return {
        "ok": True,
        "message": "Reviewer access activated"
    }


# ============================================================
# REVIEWER STATUS
# ============================================================

@router.get("/review/status")
def review_status(req: Request):
    conn, auth, csrf, owner, now = deps()

    user = auth(req)

    if user["role"] != "investor":
        return {
            "allowed": False,
            "role": user["role"]
        }

    with conn() as c:
        allowed = c.execute(
            """
            SELECT 1
            FROM reviewer_accounts
            WHERE user_id = ?

            UNION

            SELECT 1
            FROM admin_accounts
            WHERE user_id = ?
            """,
            (user["id"], user["id"])
        ).fetchone()

    return {
        "allowed": bool(allowed),
        "role": "investor"
    }


# ============================================================
# SUBMISSION REVIEW QUEUE
# ============================================================

@router.get("/review/queue")
def queue(req: Request):
    reviewer(req)

    conn, auth, csrf, owner, now = deps()

    with conn() as c:
        rows = c.execute(
            """
            SELECT
                s.id,
                s.venture_id,
                v.name AS venture,
                s.stage,
                s.deliverable,
                s.narrative,
                s.evidence_ref,
                s.ai_score,
                s.ai_feedback,
                s.reviewer_status

            FROM stage_submissions s

            JOIN ventures v
                ON v.id = s.venture_id

            WHERE s.reviewer_status != 'approved'

            ORDER BY s.created_at DESC

            LIMIT 100
            """
        )

        return [
            dict(row)
            for row in rows
        ]


# ============================================================
# REVIEW SUBMISSION
# ============================================================

@router.post("/review/{submission_id}")
async def review(
    req: Request,
    submission_id: int
):
    user = reviewer(req)

    conn, auth, csrf, owner, now = deps()

    csrf(req, user)

    data = await req.json()

    if not isinstance(data, dict):
        raise HTTPException(
            400,
            "Expected a JSON object"
        )

    decision = str(
        data.get("decision", "")
    )

    reason = str(
        data.get("reason", "")
    ).strip()[:1000]

    allowed_decisions = (
        "approved",
        "needs_changes",
        "rejected"
    )

    if decision not in allowed_decisions:
        raise HTTPException(
            400,
            "Invalid review decision"
        )

    if len(reason) < 12:
        raise HTTPException(
            400,
            "A detailed reason is required"
        )

    with conn() as c:
        submission = c.execute(
            """
            SELECT *
            FROM stage_submissions
            WHERE id = ?
            """,
            (submission_id,)
        ).fetchone()

        if not submission:
            raise HTTPException(
                404,
                "Submission not found"
            )

        if submission["user_id"] == user["id"]:
            raise HTTPException(
                403,
                "You cannot review your own submission"
            )

        if submission["reviewer_status"] == "approved":
            raise HTTPException(
                409,
                "Approved submissions cannot be reviewed again"
            )

        if decision == "approved":
            if (
                submission["ai_score"] < 70
                or not submission["evidence_ref"]
            ):
                raise HTTPException(
                    400,
                    "Provide sufficient work and "
                    "traceable supporting evidence first"
                )

        c.execute(
            """
            UPDATE stage_submissions
            SET reviewer_status = ?
            WHERE id = ?
            """,
            (decision, submission_id)
        )

        c.execute(
            """
            INSERT INTO review_events(
                venture_id,
                stage,
                deliverable,
                actor,
                decision,
                reason,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                submission["venture_id"],
                submission["stage"],
                submission["deliverable"],
                user["id"],
                decision,
                reason,
                now()
            )
        )

        event_key = (
            "deliverable:" +
            str(submission_id)
        )

        if decision == "approved":
            c.execute(
                """
                INSERT OR IGNORE INTO rewards(
                    venture_id,
                    user_id,
                    event_key,
                    points,
                    reason,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    submission["venture_id"],
                    submission["user_id"],
                    event_key,
                    30,
                    "Reviewer-accepted deliverable: " +
                    submission["deliverable"],
                    now()
                )
            )
        else:
            c.execute(
                """
                DELETE FROM rewards
                WHERE event_key = ?
                """,
                (event_key,)
            )

    return {
        "ok": True,
        "status": decision
    }


# ============================================================
# INVESTMENT READINESS ASSESSMENT
# ============================================================

CRITERIA = [
    ("Innovation", 10),
    ("Market opportunity", 10),
    ("Scalability", 8),
    ("Revenue potential", 10),
    ("Profitability", 10),
    ("Competitive advantage", 7),
    ("Customer validation", 15),
    ("Financial viability", 15),
    ("Execution capacity", 8),
    ("Investment readiness", 7)
]

GROUPS = {
    "Innovation": [1, 2],
    "Market opportunity": [2],
    "Scalability": [3, 4],
    "Revenue potential": [3, 5],
    "Profitability": [3, 5],
    "Competitive advantage": [2, 4],
    "Customer validation": [2],
    "Financial viability": [3, 5, 7],
    "Execution capacity": [1, 4, 6],
    "Investment readiness": [6, 7, 8]
}


def calculate(c, vid):
    rows = [
        dict(row)
        for row in c.execute(
            """
            SELECT
                stage,
                ai_score,
                reviewer_status
            FROM stage_submissions
            WHERE venture_id = ?
            """,
            (vid,)
        )
    ]

    results = []

    for label, weight in CRITERIA:
        stages = GROUPS[label]

        expected = sum(
            len(STAGES[s - 1]["deliverables"])
            for s in stages
        )

        verified = sum(
            1
            for row in rows
            if row["stage"] in stages
            and row["reviewer_status"] == "approved"
        )

        reported = sum(
            1
            for row in rows
            if row["stage"] in stages
            and row["reviewer_status"] != "approved"
            and row["ai_score"] >= 70
        )

        score = round(
            100 *
            (verified + 0.15 * reported) /
            max(1, expected)
        )

        results.append({
            "criterion": label,
            "weight": weight,
            "score": score,
            "confidence": (
                "medium"
                if verified
                else "low"
            ),
            "verified_items": verified,
            "unverified_drafts": reported
        })

    overall = round(
        sum(
            result["score"] * result["weight"]
            for result in results
        ) / 100
    )

    return results, overall


# ============================================================
# GET ASSESSMENT
# ============================================================

@router.get("/ventures/{vid}/assessment")
def assessment(req: Request, vid: int):
    conn, auth, csrf, owner, now = deps()

    user = auth(req)

    with conn() as c:
        owner(c, user["id"], vid)

        scores, overall = calculate(c, vid)

        history = [
            dict(row)
            for row in c.execute(
                """
                SELECT
                    score,
                    created_at
                FROM assessment_runs
                WHERE venture_id = ?
                  AND user_id = ?
                ORDER BY id DESC
                LIMIT 20
                """,
                (vid, user["id"])
            )
        ]

    return {
        "overall": overall,
        "criteria": scores,
        "history": history,
        "interpretation": (
            "Evidence coverage proxy, not an "
            "independent assessment of business "
            "quality or investment readiness."
        )
    }


# ============================================================
# SAVE ASSESSMENT
# ============================================================

@router.post("/ventures/{vid}/assessment")
def save_assessment(req: Request, vid: int):
    conn, auth, csrf, owner, now = deps()

    user = auth(req)

    csrf(req, user)

    with conn() as c:
        owner(c, user["id"], vid)

        scores, overall = calculate(c, vid)

        c.execute(
            """
            INSERT INTO assessment_runs(
                venture_id,
                user_id,
                score,
                scores_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                vid,
                user["id"],
                overall,
                json.dumps(scores),
                now()
            )
        )

    return {
        "overall": overall,
        "criteria": scores,
        "saved": True
    }


# ============================================================
# REWARDS AND BADGES
# ============================================================

@router.get("/ventures/{vid}/rewards")
def get_rewards(req: Request, vid: int):
    conn, auth, csrf, owner, now = deps()

    user = auth(req)

    with conn() as c:
        owner(c, user["id"], vid)

        rows = [
            dict(row)
            for row in c.execute(
                """
                SELECT
                    points,
                    reason,
                    created_at
                FROM rewards
                WHERE venture_id = ?
                  AND user_id = ?
                ORDER BY id DESC
                """,
                (vid, user["id"])
            )
        ]

        approved = [
            dict(row)
            for row in c.execute(
                """
                SELECT stage, deliverable
                FROM stage_submissions
                WHERE venture_id = ?
                  AND reviewer_status = 'approved'
                """,
                (vid,)
            )
        ]

    badges = [
        {
            "name": row["deliverable"],
            "stage": row["stage"]
        }
        for row in approved
    ]

    return {
        "points": sum(
            row["points"]
            for row in rows
        ),
        "badge_count": len(badges),
        "badges": badges,
        "events": rows,
        "notice": (
            "Prototype achievement points only. "
            "Not financial tokens."
        )
    }


# ============================================================
# PUBLISH APPROVED VENTURE
# ============================================================

@router.post("/ventures/{vid}/publish")
def publish(req: Request, vid: int):
    user = reviewer(req)

    conn, auth, csrf, owner, now = deps()

    csrf(req, user)

    with conn() as c:
        venture = c.execute(
            """
            SELECT *
            FROM ventures
            WHERE id = ?
            """,
            (vid,)
        ).fetchone()

        if not venture:
            raise HTTPException(
                404,
                "Venture not found"
            )

        approved = c.execute(
            """
            SELECT stage, deliverable
            FROM stage_submissions
            WHERE venture_id = ?
              AND reviewer_status = 'approved'
            """,
            (vid,)
        ).fetchall()

        for stage in STAGES:
            for deliverable in stage["deliverables"]:
                found = any(
                    row["stage"] == stage["number"]
                    and row["deliverable"] == deliverable
                    for row in approved
                )

                if not found:
                    raise HTTPException(
                        400,
                        "Cannot publish: stage " +
                        str(stage["number"]) +
                        " is incomplete"
                    )

        c.execute(
            """
            INSERT OR REPLACE
            INTO published_ventures(
                venture_id,
                approved_by,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (vid, user["id"], now())
        )

    return {
        "ok": True,
        "notice": (
            "Venture published for prototype "
            "investor interest only."
        )
    }


# ============================================================
# INVESTOR OPPORTUNITIES
# ============================================================

def investor_user(req):
    conn, auth, csrf, owner, now = deps()

    user = auth(req)

    if user["role"] != "investor":
        raise HTTPException(
            403,
            "Investor account required"
        )

    return user


def public_opportunity(c, vid):
    row = c.execute(
        """
        SELECT 1
        FROM published_ventures
        WHERE venture_id = ?
        """,
        (vid,)
    ).fetchone()

    if row is None:
        raise HTTPException(
            404,
            "This venture has not been published"
        )


@router.get("/investor/opportunities")
def opportunities(req: Request):
    investor_user(req)

    conn, auth, csrf, owner, now = deps()

    with conn() as c:
        rows = [
            dict(row)
            for row in c.execute(
                """
                SELECT
                    v.id,
                    v.name,
                    v.industry,
                    v.location,
                    v.problem,
                    v.proposition,
                    p.created_at

                FROM published_ventures p

                JOIN ventures v
                    ON v.id = p.venture_id

                ORDER BY p.created_at DESC
                """
            )
        ]

        for row in rows:
            _, row["readiness_score"] = calculate(
                c,
                row["id"]
            )

    return {
        "opportunities": rows,
        "notice": (
            "Prototype listings only. "
            "No real investment commitments."
        )
    }


# ============================================================
# INVESTOR INTEREST
# ============================================================

@router.post(
    "/investor/opportunities/{vid}/interest"
)
async def interest(req: Request, vid: int):
    user = investor_user(req)

    conn, auth, csrf, owner, now = deps()

    csrf(req, user)

    data = await req.json()

    if not isinstance(data, dict):
        raise HTTPException(
            400,
            "Expected a JSON object"
        )

    note = str(
        data.get("note", "")
    )[:1000]

    with conn() as c:
        public_opportunity(c, vid)

        c.execute(
            """
            INSERT INTO investor_interest(
                venture_id,
                investor_id,
                note,
                created_at
            )
            VALUES (?, ?, ?, ?)

            ON CONFLICT(venture_id, investor_id)
            DO UPDATE SET
                note = excluded.note,
                created_at = excluded.created_at
            """,
            (vid, user["id"], note, now())
        )

    return {
        "ok": True,
        "notice": (
            "Expression of interest saved. "
            "No binding financial commitment."
        )
    }


# ============================================================
# FOUNDER VIEWS INVESTOR INTEREST
# ============================================================

@router.get(
    "/ventures/{vid}/investor-interest"
)
def founder_interest(req: Request, vid: int):
    conn, auth, csrf, owner, now = deps()

    user = auth(req)

    with conn() as c:
        owner(c, user["id"], vid)

        return [
            {
                "created_at": row["created_at"],
                "note": row["note"]
            }
            for row in c.execute(
                """
                SELECT created_at, note
                FROM investor_interest
                WHERE venture_id = ?
                ORDER BY created_at DESC
                """,
                (vid,)
            )
        ]


# ============================================================
# EVIDENCE UPLOAD
# ============================================================

@router.post("/ventures/{vid}/upload")
async def upload(req: Request, vid: int):
    conn, auth, csrf, owner, now = deps()

    user = auth(req)

    csrf(req, user)

    form = await req.form()

    file = form.get("file")

    if (
        file is None
        or not hasattr(file, "read")
        or not hasattr(file, "filename")
    ):
        raise HTTPException(
            400,
            "File required"
        )

    filename = Path(
        str(file.filename or "attachment")
    ).name[:120]

    extension = Path(filename).suffix.lower()

    allowed = {
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".csv": "text/csv",
        ".docx": (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        ".xlsx": (
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg"
    }

    if extension not in allowed:
        raise HTTPException(
            400,
            "Unsupported file type"
        )

    blob = await file.read(
        5 * 1024 * 1024 + 1
    )

    if len(blob) > 5 * 1024 * 1024:
        raise HTTPException(
            413,
            "Maximum file size is 5 MB"
        )

    if (
        extension == ".pdf"
        and not blob.startswith(b"%PDF")
    ):
        raise HTTPException(
            400,
            "Invalid PDF file"
        )

    if (
        extension in (".docx", ".xlsx")
        and not blob.startswith(b"PK")
    ):
        raise HTTPException(
            400,
            "Invalid Office file"
        )

    if (
        extension == ".png"
        and not blob.startswith(b"\x89PNG")
    ):
        raise HTTPException(
            400,
            "Invalid PNG file"
        )

    if (
        extension in (".jpg", ".jpeg")
        and not blob.startswith(b"\xff\xd8")
    ):
        raise HTTPException(
            400,
            "Invalid JPEG file"
        )

    try:
        stage = int(
            form.get("stage") or 0
        )
    except (ValueError, TypeError):
        raise HTTPException(
            400,
            "Invalid stage"
        )

    if stage not in range(0, 9):
        raise HTTPException(
            400,
            "Invalid stage"
        )

    label = str(
        form.get("deliverable") or ""
    )[:180]

    sha = hashlib.sha256(blob).hexdigest()

    with conn() as c:
        owner(c, user["id"], vid)

        cursor = c.execute(
            """
            INSERT INTO uploads(
                venture_id,
                user_id,
                stage,
                deliverable,
                filename,
                content_type,
                sha256,
                bytes,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vid,
                user["id"],
                stage,
                label,
                filename,
                allowed[extension],
                sha,
                len(blob),
                now()
            )
        )

        file_id = cursor.lastrowid

    directory = (
        Path(
            os.getenv(
                "VENTUREOS_DATA",
                str(
                    Path(__file__).resolve().parent
                    / "data"
                )
            )
        )
        / "evidence_files"
    )

    directory.mkdir(
        parents=True,
        exist_ok=True
    )

    destination = (
        directory /
        (str(file_id) + extension)
    )

    destination.write_bytes(blob)

    return {
        "id": file_id,
        "sha256": sha,
        "bytes": len(blob),
        "status": "unverified_pending_manual_review",
        "notice": (
            "Evidence saved locally. "
            "Manual verification is still required."
        )
    }


# ============================================================
# LIST UPLOADED EVIDENCE
# ============================================================

@router.get("/ventures/{vid}/uploads")
def list_uploads(req: Request, vid: int):
    conn, auth, csrf, owner, now = deps()

    user = auth(req)

    with conn() as c:
        owner(c, user["id"], vid)

        return [
            dict(row)
            for row in c.execute(
                """
                SELECT
                    id,
                    stage,
                    deliverable,
                    filename,
                    sha256,
                    bytes,
                    created_at
                FROM uploads
                WHERE venture_id = ?
                ORDER BY id DESC
                """,
                (vid,)
            )
        ]


# ============================================================
# LEGACY MANAGEMENT PERMISSIONS
# ============================================================

# No separate Administrator login exists.
# These endpoints remain available only to accounts
# with an existing admin_accounts membership.

def admin_only(req):
    conn, auth, csrf, owner, now = deps()

    user = auth(req)

    if user["role"] != "investor":
        raise HTTPException(
            403,
            "Investor account required"
        )

    with conn() as c:
        permitted = c.execute(
            """
            SELECT 1
            FROM admin_accounts
            WHERE user_id = ?
            """,
            (user["id"],)
        ).fetchone()

    if not permitted:
        raise HTTPException(
            403,
            "Management permission required"
        )

    return user


@router.get("/admin/summary")
def admin_summary(req: Request):
    admin_only(req)

    conn, auth, csrf, owner, now = deps()

    tables = {
        "users": "users",
        "ventures": "ventures",
        "submissions": "stage_submissions",
        "review_events": "review_events",
        "investor_interest": "investor_interest"
    }

    with conn() as c:
        counts = {}

        for key, table in tables.items():
            counts[key] = c.execute(
                "SELECT COUNT(*) FROM " + table
            ).fetchone()[0]

        counts["pending_reviews"] = c.execute(
            """
            SELECT COUNT(*)
            FROM stage_submissions
            WHERE reviewer_status != 'approved'
            """
        ).fetchone()[0]

    return counts


@router.get("/admin/users")
def admin_users(req: Request):
    admin_only(req)

    conn, auth, csrf, owner, now = deps()

    with conn() as c:
        return [
            dict(row)
            for row in c.execute(
                """
                SELECT
                    u.id,
                    u.name,
                    u.email,
                    u.role,
                    u.created_at,

                    EXISTS(
                        SELECT 1
                        FROM admin_accounts a
                        WHERE a.user_id = u.id
                    ) AS is_admin,

                    EXISTS(
                        SELECT 1
                        FROM reviewer_accounts r
                        WHERE r.user_id = u.id
                    ) AS is_reviewer

                FROM users u
                ORDER BY u.id DESC
                LIMIT 300
                """
            )
        ]


@router.post("/admin/users/{uid}/reviewer")
async def admin_set_reviewer(
    req: Request,
    uid: int
):
    user = admin_only(req)

    conn, auth, csrf, owner, now = deps()

    csrf(req, user)

    data = await req.json()

    if not isinstance(data, dict):
        raise HTTPException(
            400,
            "Expected a JSON object"
        )

    enabled = data.get("enabled")

    if not isinstance(enabled, bool):
        raise HTTPException(
            400,
            "enabled must be boolean"
        )

    with conn() as c:
        target = c.execute(
            """
            SELECT role
            FROM users
            WHERE id = ?
            """,
            (uid,)
        ).fetchone()

        if not target:
            raise HTTPException(
                404,
                "Account not found"
            )

        if target["role"] != "investor":
            raise HTTPException(
                400,
                "Only investors may receive reviewer access"
            )

        if enabled:
            c.execute(
                """
                INSERT OR IGNORE INTO reviewer_accounts(
                    user_id,
                    role
                )
                VALUES (?, 'mentor')
                """,
                (uid,)
            )
        else:
            c.execute(
                """
                DELETE FROM reviewer_accounts
                WHERE user_id = ?
                """,
                (uid,)
            )

        c.execute(
            """
            INSERT INTO admin_audit(
                actor,
                action,
                target,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                user["id"],
                (
                    "grant_reviewer"
                    if enabled
                    else "revoke_reviewer"
                ),
                str(uid),
                now()
            )
        )

    return {
        "ok": True,
        "reviewer": enabled
    }


@router.get("/admin/audit")
def admin_audit(req: Request):
    admin_only(req)

    conn, auth, csrf, owner, now = deps()

    with conn() as c:
        reviews = [
            dict(row)
            for row in c.execute(
                """
                SELECT
                    actor,
                    decision AS action,
                    deliverable AS target,
                    created_at
                FROM review_events
                ORDER BY id DESC
                LIMIT 100
                """
            )
        ]

        actions = [
            dict(row)
            for row in c.execute(
                """
                SELECT
                    actor,
                    action,
                    target,
                    created_at
                FROM admin_audit
                ORDER BY id DESC
                LIMIT 100
                """
            )
        ]

    return sorted(
        reviews + actions,
        key=lambda row: row["created_at"],
        reverse=True
    )[:100]


# ============================================================
# INVESTOR DISCUSSIONS
# ============================================================

@router.get(
    "/investor/opportunities/{vid}/discussion"
)
def get_investor_discussion(
    req: Request,
    vid: int
):
    user = investor_user(req)

    conn, auth, csrf, owner, now = deps()

    with conn() as c:
        public_opportunity(c, vid)

        comments = [
            dict(row)
            for row in c.execute(
                """
                SELECT
                    i.id,
                    i.body,
                    i.created_at,
                    u.name AS investor_name

                FROM investor_comments i

                JOIN users u
                    ON u.id = i.investor_id

                WHERE i.venture_id = ?

                ORDER BY i.id ASC
                LIMIT 500
                """,
                (vid,)
            )
        ]

        decisions = [
            dict(row)
            for row in c.execute(
                """
                SELECT
                    d.decision,
                    d.reason,
                    d.updated_at,
                    u.name AS investor_name,
                    d.investor_id

                FROM investor_decisions d

                JOIN users u
                    ON u.id = d.investor_id

                WHERE d.venture_id = ?

                ORDER BY d.updated_at DESC
                """,
                (vid,)
            )
        ]

    my_decision = next(
        (
            item
            for item in decisions
            if item["investor_id"] == user["id"]
        ),
        None
    )

    return {
        "comments": comments,
        "decisions": decisions,
        "my_decision": my_decision,
        "notice": (
            "Investor decisions are nonbinding. "
            "No funds are transferred."
        )
    }


# ============================================================
# POST INVESTOR COMMENT
# ============================================================

@router.post(
    "/investor/opportunities/{vid}/comments"
)
async def post_investor_comment(
    req: Request,
    vid: int
):
    user = investor_user(req)

    conn, auth, csrf, owner, now = deps()

    csrf(req, user)

    data = await req.json()

    if not isinstance(data, dict):
        raise HTTPException(
            400,
            "Expected a JSON object"
        )

    body = str(
        data.get("body") or ""
    ).strip()

    if not 5 <= len(body) <= 2000:
        raise HTTPException(
            400,
            "Comment must contain 5 to 2000 characters"
        )

    with conn() as c:
        public_opportunity(c, vid)

        cursor = c.execute(
            """
            INSERT INTO investor_comments(
                venture_id,
                investor_id,
                body,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                vid,
                user["id"],
                body,
                now()
            )
        )

        comment_id = cursor.lastrowid

    return {
        "ok": True,
        "id": comment_id,
        "message": "Your comment was saved"
    }


# ============================================================
# INVESTOR DECISIONS
# ============================================================

@router.post(
    "/investor/opportunities/{vid}/decision"
)
async def post_investor_decision(
    req: Request,
    vid: int
):
    user = investor_user(req)

    conn, auth, csrf, owner, now = deps()

    csrf(req, user)

    data = await req.json()

    if not isinstance(data, dict):
        raise HTTPException(
            400,
            "Expected a JSON object"
        )

    decision = str(
        data.get("decision") or ""
    )

    reason = str(
        data.get("reason") or ""
    ).strip()

    allowed = (
        "invest",
        "collaborate",
        "more_information",
        "decline"
    )

    if decision not in allowed:
        raise HTTPException(
            400,
            "Invalid investor decision"
        )

    if not 10 <= len(reason) <= 2000:
        raise HTTPException(
            400,
            "Explain your decision in 10 to 2000 characters"
        )

    with conn() as c:
        public_opportunity(c, vid)

        c.execute(
            """
            INSERT INTO investor_decisions(
                venture_id,
                investor_id,
                decision,
                reason,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)

            ON CONFLICT(venture_id, investor_id)
            DO UPDATE SET
                decision = excluded.decision,
                reason = excluded.reason,
                updated_at = excluded.updated_at
            """,
            (
                vid,
                user["id"],
                decision,
                reason,
                now()
            )
        )

    return {
        "ok": True,
        "decision": decision,
        "binding_investment": False
    }


# ============================================================
# FOUNDER VIEWS INVESTOR FEEDBACK
# ============================================================

@router.get(
    "/ventures/{vid}/investor-feedback"
)
def founder_investor_feedback(
    req: Request,
    vid: int
):
    conn, auth, csrf, owner, now = deps()

    user = auth(req)

    with conn() as c:
        owner(c, user["id"], vid)

        comments = [
            dict(row)
            for row in c.execute(
                """
                SELECT
                    u.name AS investor_name,
                    i.body,
                    i.created_at

                FROM investor_comments i

                JOIN users u
                    ON u.id = i.investor_id

                WHERE i.venture_id = ?
                ORDER BY i.id DESC
                LIMIT 100
                """,
                (vid,)
            )
        ]

        decisions = [
            dict(row)
            for row in c.execute(
                """
                SELECT
                    u.name AS investor_name,
                    d.decision,
                    d.reason,
                    d.updated_at

                FROM investor_decisions d

                JOIN users u
                    ON u.id = d.investor_id

                WHERE d.venture_id = ?
                ORDER BY d.updated_at DESC
                """,
                (vid,)
            )
        ]

    return {
        "comments": comments,
        "decisions": decisions
    }


# ============================================================
# LEGACY VENTURE MANAGEMENT VIEW
# ============================================================

@router.get("/admin/ventures")
def admin_ventures(req: Request):
    admin_only(req)

    conn, auth, csrf, owner, now = deps()

    with conn() as c:
        rows = c.execute(
            """
            SELECT
                v.id,
                v.name,
                v.industry,
                u.name AS founder,

                (
                    SELECT COUNT(*)
                    FROM stage_submissions s
                    WHERE s.venture_id = v.id
                      AND s.reviewer_status = 'approved'
                ) AS approved,

                (
                    SELECT COUNT(*)
                    FROM investor_decisions d
                    WHERE d.venture_id = v.id
                ) AS investor_decisions,

                EXISTS(
                    SELECT 1
                    FROM published_ventures p
                    WHERE p.venture_id = v.id
                ) AS published

            FROM ventures v

            JOIN users u
                ON u.id = v.user_id

            ORDER BY v.id DESC
            LIMIT 200
            """
        )

        return [
            dict(row)
            for row in rows
        ]


# ============================================================
# INVESTOR VIEW-ONLY BUSINESS PAGES
# ============================================================

def _visible_investor_venture(c, user, venture_id):
    published = c.execute(
        "SELECT 1 FROM published_ventures WHERE venture_id=?",
        (venture_id,)
    ).fetchone()

    privileged = c.execute(
        """
        SELECT 1
        FROM reviewer_accounts
        WHERE user_id=?

        UNION

        SELECT 1
        FROM admin_accounts
        WHERE user_id=?
        """,
        (user["id"], user["id"])
    ).fetchone()

    if not published and not privileged:
        raise HTTPException(
            404,
            "Venture is not available to this investor"
        )

    venture = c.execute(
        "SELECT * FROM ventures WHERE id=?",
        (venture_id,)
    ).fetchone()

    if not venture:
        raise HTTPException(
            404,
            "Venture not found"
        )

    return dict(venture), bool(privileged)


@router.get("/investor/business-list")
def investor_business_list(req: Request):
    user = investor_user(req)

    conn, auth, csrf, owner, now = deps()

    with conn() as c:
        approved = c.execute(
            """
            SELECT 1
            FROM reviewer_accounts
            WHERE user_id=?

            UNION

            SELECT 1
            FROM admin_accounts
            WHERE user_id=?
            """,
            (user["id"], user["id"])
        ).fetchone()

        if approved:
            rows = c.execute(
                """
                SELECT id, name
                FROM ventures
                ORDER BY id DESC
                """
            )
        else:
            rows = c.execute(
                """
                SELECT v.id, v.name
                FROM ventures v
                JOIN published_ventures p
                    ON v.id=p.venture_id
                ORDER BY v.id DESC
                """
            )

        return {
            "ventures": [
                dict(row)
                for row in rows
            ]
        }


@router.get("/investor/business-view/{vid}")
def investor_business_view(
    req: Request,
    vid: int
):
    user = investor_user(req)

    conn, auth, csrf, owner, now = deps()

    with conn() as c:
        venture, privileged = _visible_investor_venture(
            c,
            user,
            vid
        )

        if privileged:
            rows = c.execute(
                """
                SELECT
                    stage,
                    deliverable,
                    narrative,
                    evidence_ref,
                    ai_score,
                    reviewer_status
                FROM stage_submissions
                WHERE venture_id=?
                ORDER BY stage, id
                """,
                (vid,)
            )
        else:
            rows = c.execute(
                """
                SELECT
                    stage,
                    deliverable,
                    narrative,
                    evidence_ref,
                    ai_score,
                    reviewer_status
                FROM stage_submissions
                WHERE venture_id=?
                    AND reviewer_status='approved'
                ORDER BY stage, id
                """,
                (vid,)
            )

        submissions = [
            dict(row)
            for row in rows
        ]

        if privileged:
            evidence_rows = c.execute(
                """
                SELECT claim, source, status
                FROM evidence
                WHERE venture_id=?
                ORDER BY id DESC
                """,
                (vid,)
            )
        else:
            evidence_rows = c.execute(
                """
                SELECT claim, source, status
                FROM evidence
                WHERE venture_id=?
                    AND status='approved'
                ORDER BY id DESC
                """,
                (vid,)
            )

        evidence = [
            dict(row)
            for row in evidence_rows
        ]

        missions = [
            dict(row)
            for row in c.execute(
                """
                SELECT title, state
                FROM missions
                WHERE venture_id=?
                ORDER BY id
                """,
                (vid,)
            )
        ]

    revenue = round(
        venture["price"] *
        venture["monthly_units"],
        2
    )

    variable = round(
        venture["unit_cost"] *
        venture["monthly_units"],
        2
    )

    return {
        "venture": venture,
        "evidence": evidence,
        "missions": missions,
        "submissions": submissions,
        "financials": {
            "revenue": revenue,
            "variable_cost": variable,
            "fixed_cost": venture["fixed_cost"],
            "estimated_profit": round(
                revenue -
                variable -
                venture["fixed_cost"],
                2
            )
        },
        "approved_count": sum(
            submission["reviewer_status"] == "approved"
            for submission in submissions
        ),
        "read_only": True
    }
