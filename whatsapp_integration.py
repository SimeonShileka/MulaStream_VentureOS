"""MulaStream VentureOS: signed Twilio WhatsApp webhook and outgoing replies.

Modes:
  trial: send a Twilio-provided ContentSid and required ContentVariables.
  full:  send free-form Gemini answer using Body when the account supports it.

The trial appointment template is a connectivity demonstration, not an AI reply.
WhatsApp participants are not linked to authenticated VentureOS users.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from urllib.parse import quote

import httpx
from fastapi import BackgroundTasks, HTTPException, Request
from fastapi.responses import Response

from chatbot2_engine.service import reply as mentor_reply

logger = logging.getLogger("ventureos.whatsapp")


def verify_twilio_signature(url, fields, supplied, token):
    """Verify Twilio's signature of a form-encoded incoming webhook."""
    if not supplied or not token:
        return False
    signed_text = url + "".join(k + str(fields[k]) for k in sorted(fields))
    expected = base64.b64encode(
        hmac.new(token.encode("utf-8"), signed_text.encode("utf-8"), hashlib.sha1).digest()
    ).decode("ascii")
    return hmac.compare_digest(expected, supplied)


def short_answer(text, limit=115):
    words = str(text or "").strip().split()
    if not words:
        return "I could not prepare an answer. Please try again."
    if len(words) > limit:
        return " ".join(words[:limit]).rstrip(" ,;:") + "..."
    return " ".join(words)


def install(app, conn):
    """Register the webhook against the existing FastAPI app and SQLite connection."""
    with conn() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS whatsapp_messages (
                message_sid TEXT PRIMARY KEY,
                sender TEXT NOT NULL,
                direction TEXT NOT NULL CHECK(direction IN ('in','out')),
                body TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_whatsapp_sender
            ON whatsapp_messages(sender, created_at)
        """)

    async def send_reply(sender, answer):
        account = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        from_number = os.getenv("TWILIO_WHATSAPP_FROM", "").strip()
        mode = os.getenv("TWILIO_SEND_MODE", "trial").strip().lower()
        if not account or not token or not from_number:
            logger.error("Outgoing WhatsApp unavailable: Twilio settings missing")
            return False
        if not re.fullmatch(r"AC[a-fA-F0-9]{32}", account):
            logger.error("Outgoing WhatsApp unavailable: invalid Account SID format")
            return False
        endpoint = (
            "https://api.twilio.com/2010-04-01/Accounts/"
            + quote(account, safe="") + "/Messages.json"
        )
        request_data = {"From": from_number, "To": sender}
        if mode == "trial":
            sid = os.getenv("TWILIO_TRIAL_CONTENT_SID", "").strip()
            if not re.fullmatch(r"HX[a-fA-F0-9]{32}", sid):
                logger.error("Trial template missing: set TWILIO_TRIAL_CONTENT_SID to an HX SID")
                return False
            # The provided Appointment Reminders template has two placeholders:
            # {{1}} = date, {{2}} = time. These are MESSAGE TEXT, not scheduling.
            # The guided trial may accept only Twilio's predefined templates.
            request_data["ContentSid"] = sid
            request_data["ContentVariables"] = json.dumps(
                {"1": "12/1", "2": "3pm"}, separators=(",", ":")
            )
        elif mode == "full":
            request_data["Body"] = short_answer(answer)
        else:
            logger.error("Invalid TWILIO_SEND_MODE (use trial or full)")
            return False

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=8.0)) as client:
                result = await client.post(endpoint, data=request_data, auth=(account, token))
            if result.status_code not in (200, 201):
                error_code = "unknown"
                explanation = "No explanation returned"
                try:
                    body = result.json()
                    error_code = str(body.get("code", "unknown"))
                    explanation = str(body.get("message", explanation))
                except (ValueError, AttributeError, TypeError):
                    pass
                for secret in (account, token, from_number, sender):
                    if secret:
                        explanation = explanation.replace(secret, "[REDACTED]")
                logger.error("Twilio outgoing rejected: HTTP %s; code %s", result.status_code, error_code)
                logger.error("Twilio explanation: %s", explanation[:500])
                return False
            logger.info("Twilio accepted the WhatsApp outgoing message")
            return True
        except httpx.TimeoutException:
            logger.error("Twilio outgoing request timed out")
        except httpx.RequestError as exc:
            logger.error("Twilio connection error: %s", type(exc).__name__)
        return False

    async def process_message(message_sid, sender, question):
        try:
            with conn() as db:
                rows = db.execute("""
                    SELECT direction, body FROM whatsapp_messages
                    WHERE sender=? AND message_sid!=?
                    ORDER BY created_at DESC, rowid DESC LIMIT 8
                """, (sender, message_sid)).fetchall()
            history = [
                {"role": "user" if row["direction"] == "in" else "assistant", "content": row["body"]}
                for row in reversed(rows)
            ]
            mode = os.getenv("TWILIO_SEND_MODE", "trial").strip().lower()
            if mode == "full":
                logger.info("Generating Gemini answer for incoming WhatsApp message")
                answer = await mentor_reply(
                    question, history, role="founder",
                    context=("Unauthenticated WhatsApp guest; no private account data. "
                             "Reply in under 120 words, with one focused follow-up question."),
                )
                answer = short_answer(answer)
            else:
                # Twilio's guided trial only sends the approved fixed template.
                # Do not generate a Gemini answer and pretend the template contains it.
                answer = "[Twilio trial appointment reminder template]"
                logger.info("Using Twilio trial template (not a personalised Gemini reply)")
            sent = await send_reply(sender, answer)
            if sent:
                with conn() as db:
                    db.execute("""
                        INSERT OR IGNORE INTO whatsapp_messages
                            (message_sid, sender, direction, body, created_at)
                        VALUES (?, ?, 'out', ?, ?)
                    """, ("reply:" + message_sid, sender, answer, int(time.time())))
                logger.info("WhatsApp outgoing request accepted by Twilio")
            else:
                logger.error("WhatsApp reply not sent; see Twilio diagnostic above")
        except Exception:
            logger.exception("WhatsApp background processing failed")

    @app.post("/api/whatsapp/webhook", include_in_schema=False)
    async def whatsapp_webhook(req: Request, background_tasks: BackgroundTasks):
        token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        public_url = os.getenv("TWILIO_WEBHOOK_URL", "").strip()
        if not token or not public_url.startswith("https://"):
            raise HTTPException(503, "WhatsApp integration not configured")
        if req.headers.get("content-type", "").split(";")[0].strip().lower() != "application/x-www-form-urlencoded":
            raise HTTPException(415, "Expected Twilio form")
        raw = await req.body()
        if len(raw) > 20_000:
            raise HTTPException(413, "Request too large")
        form = await req.form()
        pairs = list(form.multi_items())
        fields = {str(k): str(v) for k, v in pairs}
        if len(fields) != len(pairs):
            raise HTTPException(400, "Duplicate form fields")
        if not verify_twilio_signature(
            public_url, fields, req.headers.get("x-twilio-signature", ""), token
        ):
            raise HTTPException(403, "Invalid Twilio signature")
        message_sid = fields.get("MessageSid", "")
        sender = fields.get("From", "")
        destination = fields.get("To", "")
        expected_destination = os.getenv("TWILIO_WHATSAPP_FROM", "").strip()
        if not re.fullmatch(r"(?:SM|MM)[a-fA-F0-9]{32}", message_sid):
            raise HTTPException(400, "Invalid message ID")
        if not re.fullmatch(r"whatsapp:\+[1-9][0-9]{6,14}", sender):
            raise HTTPException(400, "Invalid sender")
        if not expected_destination or destination != expected_destination:
            raise HTTPException(403, "Unexpected destination")
        if not os.getenv("TWILIO_ACCOUNT_SID", "").strip():
            raise HTTPException(503, "WhatsApp account not configured")
        question = fields.get("Body", "").strip()[:3000]
        if not question:
            question = "Please help me get started with my business."
        with conn() as db:
            result = db.execute("""
                INSERT OR IGNORE INTO whatsapp_messages
                    (message_sid, sender, direction, body, created_at)
                VALUES (?, ?, 'in', ?, ?)
            """, (message_sid, sender, question, int(time.time())))
            is_new = result.rowcount == 1
        if is_new:
            background_tasks.add_task(process_message, message_sid, sender, question)
            logger.info("WhatsApp request accepted and queued")
        else:
            logger.info("Duplicate WhatsApp message ignored")
        # Immediate acknowledgement; outgoing Twilio API call happens separately.
        return Response(content="<Response></Response>", media_type="application/xml")
