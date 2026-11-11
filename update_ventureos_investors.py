
"""
MulaStream VentureOS
Investor Collaboration and Three-Month Incubator Update

Run inside the EXISTING VentureOS project folder.

This updater:
1. Preserves the SQLite database and saved ventures.
2. Preserves Gemini and WhatsApp integration files.
3. Preserves the eight-stage, three-month incubator.
4. Keeps incubation approvals under administrator control.
5. Allows multiple investors to comment independently.
6. Allows each investor to record an individual decision.
7. Shows investor feedback to venture founders.
8. Gives administrators control over venture publication.
9. Creates backups of source files before updating them.

Requires the existing Administrator Portal backend.
"""

from pathlib import Path
from datetime import datetime
import shutil
import sys


ROOT = Path(__file__).resolve().parent

BACKEND = ROOT / "platform_features.py"
FRONTEND = ROOT / "static" / "app.js"
MAIN = ROOT / "app.py"


# ============================================================
# CHECK THE EXISTING PROJECT
# ============================================================

for file in (BACKEND, FRONTEND, MAIN):
    if not file.is_file():
        sys.exit(
            f"Missing {file.name}. "
            "Place this script in your existing VentureOS main folder."
        )

py = BACKEND.read_text(encoding="utf-8")
js = FRONTEND.read_text(encoding="utf-8")
main = MAIN.read_text(encoding="utf-8")

if (
    "admin_accounts" not in main
    or "/admin/users" not in py
    or "STAGES[:stage_num-1]" not in main
):
    sys.exit(
        "Install the Administrator Portal backend first. "
        "Your current code lacks administrator permissions "
        "or incubator stage locks. No files were changed."
    )

if (
    "# INVESTOR_COLLABORATION_V2" in py
    or "/* INVESTOR_COLLABORATION_V2 */" in js
):
    sys.exit(
        "This investor upgrade is already installed. "
        "No files were changed."
    )

if (
    "app.include_router(router)" not in py
    or "def reviewer(req):" not in py
    or "async function renderInvestors()" not in js
):
    sys.exit(
        "Your current backend or frontend is incompatible. "
        "No files were changed."
    )


# ============================================================
# ADMINISTRATOR APPROVAL PERMISSIONS
# ============================================================

start = py.index("def reviewer(req):")
end = py.index("@router.get('/review/queue')", start)

py = py[:start] + """
def reviewer(req):
    conn, auth, csrf, owner, now = deps()
    user = auth(req)

    if user["role"] != "admin":
        raise HTTPException(
            403,
            "Only administrators approve incubation deliverables"
        )

    return user


@router.post("/reviewer/activate")
async def activate(req: Request):
    raise HTTPException(
        403,
        "Investor activation tokens are discontinued. "
        "Investors can comment and express interest after login."
    )


""" + py[end:]


# ============================================================
# DATABASE TABLES FOR MULTIPLE INVESTORS
# ============================================================

sql = """
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
"""

position = py.index(
    "  CREATE TABLE IF NOT EXISTS assessment_runs"
)

script_end = py.index("'''", position)

py = py[:script_end] + sql + py[script_end:]


# ============================================================
# REVIEW MENU ACCESS
# ============================================================

status_start = py.index("@router.get('/review/status')")

py = py[:status_start] + """
@router.get("/review/status")
def review_status(req: Request):
    conn, auth, csrf, owner, now = deps()
    user = auth(req)

    return {
        "allowed": user["role"] == "admin",
        "role": user["role"]
    }


"""


# ============================================================
# COMPLETE INVESTOR API EXTENSION
# ============================================================

py += """
# INVESTOR_COLLABORATION_V2

# Investor decisions are nonbinding expressions of interest.
# They do not execute investments or transfer money.


def investor_user(req):
    conn, auth, csrf, owner, now = deps()
    user = auth(req)

    if user["role"] != "investor":
        raise HTTPException(
            403,
            "Investor login required"
        )

    return user


def public_opportunity(c, vid):
    record = c.execute(
        '''
        SELECT 1
        FROM published_ventures
        WHERE venture_id = ?
        ''',
        (vid,)
    ).fetchone()

    if record is None:
        raise HTTPException(
            404,
            "This venture has not been published"
        )


@router.get(
    "/investor/opportunities/{vid}/discussion"
)
def get_investor_discussion(req: Request, vid: int):
    user = investor_user(req)
    conn, auth, csrf, owner, now = deps()

    with conn() as c:
        public_opportunity(c, vid)

        comments = [
            dict(row)
            for row in c.execute(
                '''
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
                ''',
                (vid,)
            )
        ]

        decisions = [
            dict(row)
            for row in c.execute(
                '''
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
                ''',
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
            "Expected an object"
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
            '''
            INSERT INTO investor_comments (
                venture_id,
                investor_id,
                body,
                created_at
            )
            VALUES (?, ?, ?, ?)
            ''',
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
            "Expected an object"
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
            '''
            INSERT INTO investor_decisions (
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
            ''',
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
                '''
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
                ''',
                (vid,)
            )
        ]

        decisions = [
            dict(row)
            for row in c.execute(
                '''
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
                ''',
                (vid,)
            )
        ]

    return {
        "comments": comments,
        "decisions": decisions
    }


@router.get("/admin/ventures")
def admin_ventures(req: Request):
    admin_only(req)

    conn, auth, csrf, owner, now = deps()

    with conn() as c:
        rows = c.execute(
            '''
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
            '''
        )

        return [
            dict(row)
            for row in rows
        ]
"""


# ============================================================
# COMPLETE INVESTOR FRONTEND EXTENSION
# ============================================================

js += """
/* INVESTOR_COLLABORATION_V2 */

const investorDecisionLabels = {
    invest: "Interested in investing",
    collaborate: "Interested in collaborating",
    more_information: "Request more information",
    decline: "Not interested"
};


// ------------------------------------------------------------
// INVESTOR OPPORTUNITIES
// ------------------------------------------------------------

async function renderInvestors() {
    try {
        const data = await api(
            "/investor/opportunities"
        );

        $("content").innerHTML = `
            <div class="hero">
                <h1>Investor Opportunities</h1>

                <p>${esc(data.notice)}</p>

                <p>
                    Read published business ideas,
                    discuss them with other investors,
                    and record your own decision.
                </p>

                <p class="hint">
                    Expressions of interest are not
                    binding investments.
                </p>
            </div>

            ${
                data.opportunities.map(venture => `
                    <div
                        class="card"
                        style="margin-top:16px"
                    >
                        <h3>${esc(venture.name)}</h3>

                        <p>
                            ${esc(venture.industry)}
                            ·
                            ${esc(venture.location)}
                        </p>

                        <p>
                            Readiness:
                            ${Number(
                                venture.readiness_score
                            )}/100
                        </p>

                        <p>
                            <strong>Problem:</strong>
                            ${esc(venture.problem)}
                        </p>

                        <p>
                            <strong>Solution:</strong>
                            ${esc(venture.proposition)}
                        </p>

                        <button
                            class="primary"
                            onclick="openInvestorDiscussion(
                                ${Number(venture.id)}
                            )"
                        >
                            Review Idea · Comment · Decide
                        </button>
                    </div>
                `).join("")
                ||
                `
                    <div class="card">
                        No administrator-published
                        opportunities yet.

                        Entrepreneurs must complete
                        the three-month incubator
                        and receive approval before
                        publication.
                    </div>
                `
            }
        `;

    } catch (error) {
        $("content").textContent = error.message;
    }
}


// ------------------------------------------------------------
// MULTIPLE INVESTOR COMMENTS AND DECISIONS
// ------------------------------------------------------------

async function openInvestorDiscussion(ventureId) {
    try {
        const data = await api(
            `/investor/opportunities/${ventureId}/discussion`
        );

        const currentDecision =
            data.my_decision?.decision
            || "more_information";

        $("content").innerHTML = `
            <div class="hero">
                <h1>Investor Discussion</h1>

                <p>
                    Multiple investors can comment
                    independently.

                    Each investor maintains their
                    own investment or collaboration
                    decision.
                </p>

                <button
                    class="ghost"
                    onclick="renderInvestors()"
                >
                    Back to Opportunities
                </button>
            </div>

            <div class="card">
                <h3>Your Response</h3>

                <form id="decisionForm">

                    <label>
                        Your decision

                        <select name="decision">
                            ${
                                Object.entries(
                                    investorDecisionLabels
                                ).map(([key, label]) => `
                                    <option
                                        value="${key}"
                                        ${
                                            currentDecision === key
                                            ? "selected"
                                            : ""
                                        }
                                    >
                                        ${esc(label)}
                                    </option>
                                `).join("")
                            }
                        </select>
                    </label>

                    <label>
                        Explain your decision

                        <textarea
                            name="reason"
                            required
                            minlength="10"
                            maxlength="2000"
                            rows="3"
                        >${esc(
                            data.my_decision?.reason || ""
                        )}</textarea>
                    </label>

                    <button class="primary">
                        Save My Decision
                    </button>
                </form>

                <p class="hint">
                    This is an expression of interest,
                    not a signed investment agreement.
                </p>
            </div>

            <div class="card">
                <h3>
                    Investor Comments
                    (${data.comments.length})
                </h3>

                ${
                    data.comments.map(comment => `
                        <div class="record">
                            <strong>
                                ${esc(
                                    comment.investor_name
                                )}
                            </strong>

                            <small>
                                ${
                                    new Date(
                                        comment.created_at * 1000
                                    ).toLocaleString()
                                }
                            </small>

                            <p>
                                ${esc(comment.body)}
                            </p>
                        </div>
                    `).join("")
                    ||
                    "<p>No comments yet.</p>"
                }

                <form id="investorCommentForm">
                    <label>
                        Write a comment

                        <textarea
                            name="body"
                            minlength="5"
                            maxlength="2000"
                            required
                            rows="3"
                            placeholder="Your feedback on the entrepreneurial idea..."
                        ></textarea>
                    </label>

                    <button class="primary">
                        Post Comment
                    </button>
                </form>
            </div>

            <div class="card">
                <h3>
                    Investor Decisions
                    (${data.decisions.length})
                </h3>

                ${
                    data.decisions.map(item => `
                        <div class="record">
                            <strong>
                                ${esc(item.investor_name)}
                            </strong>

                            —
                            ${esc(
                                investorDecisionLabels[
                                    item.decision
                                ] || item.decision
                            )}

                            <p>
                                ${esc(item.reason)}
                            </p>
                        </div>
                    `).join("")
                    ||
                    "<p>No investor decisions yet.</p>"
                }
            </div>
        `;

        $("decisionForm").onsubmit = async event => {
            event.preventDefault();

            try {
                await api(
                    `/investor/opportunities/${ventureId}/decision`,
                    "POST",
                    Object.fromEntries(
                        new FormData(event.target)
                    )
                );

                await openInvestorDiscussion(
                    ventureId
                );

            } catch (error) {
                err(error);
            }
        };

        $("investorCommentForm").onsubmit =
            async event => {
                event.preventDefault();

                try {
                    await api(
                        `/investor/opportunities/${ventureId}/comments`,
                        "POST",
                        Object.fromEntries(
                            new FormData(event.target)
                        )
                    );

                    await openInvestorDiscussion(
                        ventureId
                    );

                } catch (error) {
                    err(error);
                }
            };

    } catch (error) {
        err(error);
    }
}


// ------------------------------------------------------------
// ENTREPRENEUR CAN VIEW INVESTOR FEEDBACK
// ------------------------------------------------------------

const originalRenderReadiness =
    renderReadiness;

renderReadiness = async function () {
    await originalRenderReadiness();

    if (!selected || view !== "readiness") {
        return;
    }

    try {
        const feedback = await api(
            `/ventures/${selected}/investor-feedback`
        );

        const container = $("content");

        if (!container || view !== "readiness") {
            return;
        }

        const section =
            document.createElement("section");

        section.className = "card";

        section.innerHTML = `
            <h3>
                Investor Feedback on Your Venture
            </h3>

            <p>
                Each investor's comments and
                decisions are stored separately.
            </p>

            <h4>Investor Decisions</h4>

            ${
                feedback.decisions.map(item => `
                    <div class="record">
                        <strong>
                            ${esc(item.investor_name)}
                        </strong>

                        —
                        ${esc(
                            investorDecisionLabels[
                                item.decision
                            ] || item.decision
                        )}

                        <p>
                            ${esc(item.reason)}
                        </p>
                    </div>
                `).join("")
                ||
                "<p>No investor decisions yet.</p>"
            }

            <h4>Comments</h4>

            ${
                feedback.comments.map(item => `
                    <div class="record">
                        <strong>
                            ${esc(item.investor_name)}
                        </strong>

                        <p>
                            ${esc(item.body)}
                        </p>
                    </div>
                `).join("")
                ||
                "<p>No investor comments yet.</p>"
            }
        `;

        container.append(section);

    } catch (error) {
        console.warn(
            "Investor feedback:",
            error.message
        );
    }
};


// ------------------------------------------------------------
// ADMINISTRATOR VENTURE MANAGEMENT
// ------------------------------------------------------------

const originalRenderAdmin = renderAdmin;

renderAdmin = async function () {
    await originalRenderAdmin();

    if (view !== "admin") {
        return;
    }

    try {
        const ventures = await api(
            "/admin/ventures"
        );

        const section =
            document.createElement("section");

        section.className = "card";

        section.innerHTML = `
            <h3>
                Venture Management and Publication
            </h3>

            <p>
                Approve all eight incubation stages
                in Mentor Reviews first.

                Then publish the venture for
                investor discussion.
            </p>

            ${
                ventures.map(venture => `
                    <div class="record">
                        <strong>
                            ${esc(venture.name)}
                        </strong>

                        · Founder:
                        ${esc(venture.founder)}

                        ·
                        ${Number(venture.approved)}
                        approved deliverables

                        ·
                        ${Number(
                            venture.investor_decisions
                        )}
                        investor decisions

                        ·
                        ${
                            venture.published
                            ? "Published"
                            : "Not published"
                        }

                        <div class="toolbar">
                            ${
                                venture.published
                                ? ""
                                : `
                                    <button
                                        class="primary"
                                        onclick="publishVenture(
                                            ${Number(venture.id)}
                                        )"
                                    >
                                        Publish After Full Approval
                                    </button>
                                `
                            }
                        </div>
                    </div>
                `).join("")
                ||
                "<p>No ventures found.</p>"
            }
        `;

        $("content").append(section);

    } catch (error) {
        console.warn(
            "Administrator ventures:",
            error.message
        );
    }
};


async function publishVenture(ventureId) {
    if (!confirm(
        "Publish this venture for investor review? " +
        "All incubator stages must already be approved."
    )) {
        return;
    }

    try {
        await api(
            `/ventures/${ventureId}/publish`,
            "POST",
            {}
        );

        await renderAdmin();

        alert(
            "Venture published. Investors can now " +
            "comment and record their decisions."
        );

    } catch (error) {
        err(error);
    }
}
"""


# ============================================================
# BACK UP THE EXISTING FILES
# ============================================================

stamp = datetime.now().strftime(
    "%Y%m%d_%H%M%S"
)

for file in (BACKEND, FRONTEND):
    backup = file.with_name(
        file.name
        + ".before_investor_update_"
        + stamp
        + ".bak"
    )

    shutil.copy2(file, backup)


# ============================================================
# SAVE THE COMPLETE UPDATES
# ============================================================

BACKEND.write_text(
    py,
    encoding="utf-8"
)

FRONTEND.write_text(
    js,
    encoding="utf-8"
)


print()
print("SUCCESS: VentureOS investor update installed.")
print()

print("Updated:")
print("  platform_features.py")
print("  static/app.js")

print()
print("Preserved:")
print("  Existing SQLite database")
print("  Existing ventures and user accounts")
print("  Gemini chatbot")
print("  WhatsApp integration")
print("  Three-month incubator")
print("  Eight incubation stages")
print("  Administrator approval requirements")

print()
print("Restart VentureOS to use the new features.")
