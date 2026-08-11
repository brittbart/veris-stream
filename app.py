"""
veris-stream/app.py — Verum Signal, standalone live-debate SSE service
========================================================================
D1 (Session 9 Implementation Brief): the SSE endpoint for live debate
claim feeds, extracted from the main verisreports app into its own
service with its own worker pool, so a busy debate can never starve
the website, leaderboard, /api/source, or the mobile API again.

Full background, the Aug 8 measurement, and why the old evidence was
wrong: D1_LIVE_DEBATE_INFRASTRUCTURE_HANDOFF.docx (Session 9, 2026-08-10).

WHAT THIS SERVICE DOES: exactly one thing -- serve
GET /v1/debates/<slug>/stream
Nothing else. Every other mobile/web/API endpoint stays on the main
verisreports service; only this one route, which is the only one that
holds a connection open for the length of a debate, moves.

WHAT THIS SERVICE DOES NOT DO: it does not run debate_stream.py's
ingestion (transcription/extraction/claim-writing). That's a separate,
unrelated background process on the main service and is unaffected by
this move -- see the handoff doc, §4.1.

mobile_sse.py in this directory is a VERBATIM copy of
verisreports/mobile_sse.py as of commit 01eadb3 -- byte-for-byte
identical, not reproduced from memory, specifically so the tested,
working streaming logic (event shapes, S9-006's pagination fix,
S9-024's sort-order decision, etc.) carries over with zero risk of
transcription drift. Its docstring and internal naming still say
"Mobile SSE" -- that's inherited from the original file, not a claim
about this service's actual scope: templates/debate.html (the public
website's live debate page) connects to this exact same stream via
browser EventSource, confirmed directly in the handoff doc's §3. Do
not rename or edit mobile_sse.py without a clear reason; treat it as
the source of truth this service is built around.
"""

import os
from flask import Flask, jsonify, request
from flask_cors import CORS
import psycopg2
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# --- CORS: explicit allow-list -------------------------------------------
# The website's live debate page (templates/debate.html on verisreports)
# connects here with EventSource from https://verumsignal.com, which is a
# cross-origin request. Browsers block it silently without these headers.
# Allow-list only — never "*" — because this service reads the database.
_ALLOWED_ORIGINS = {
    "https://verumsignal.com",
    "https://www.verumsignal.com",
}

@app.after_request
def _cors(resp):
    origin = request.headers.get("Origin", "")
    if origin in _ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Headers"] = "Accept, Cache-Control"
        resp.headers["Vary"] = "Origin"
    return resp


# CORS: scoped to the known site origins, not a blanket allow-all.
# Needed because templates/debate.html's EventSource call will need to
# become a genuinely cross-origin request once this moves off
# verumsignal.com's own host (handoff doc §4.6) -- the native mobile
# client's own SSE implementation (fetch + ReadableStream) is not
# subject to CORS the same way and doesn't need this, but the browser
# client does. Widen ALLOWED_ORIGINS via an env var if a staging
# domain is ever added; do not switch this to a wildcard.
ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS",
    "https://verumsignal.com,https://www.verumsignal.com"
).split(",")
CORS(app, resources={r"/v1/debates/*": {"origins": ALLOWED_ORIGINS}})


def get_db():
    """
    Deliberately different from api.py's get_db(): NO hardcoded
    production password fallback here. api.py's fallback exists for a
    specific, already-diagnosed reason (a Railway Runtime V2 quirk
    that strips env vars from subprocesses of an *existing, already-
    always-on* service) -- it is not established that a brand-new
    service hits the same issue, and duplicating a live production
    credential into a second codebase is worth avoiding by default,
    not copying reflexively. If this service is ever observed losing
    its env vars the same way, that's the point to revisit this, with
    the actual failure in hand rather than guessing at it now.

    Set these in the Railway service's own Variables tab (same DB,
    separate service = separate env config): DB_HOST, DB_PORT,
    DB_NAME, DB_USER, DB_PASSWORD, or DATABASE_URL as a single DSN.
    """
    if os.environ.get("DATABASE_URL"):
        return psycopg2.connect(os.environ["DATABASE_URL"])
    return psycopg2.connect(
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        port=os.environ["DB_PORT"],
    )


@app.route("/health")
def health():
    # Railway uses this as the deploy gate (healthcheckPath, 120s timeout), so it
    # must NEVER return non-200 on a database problem -- a hard failure would
    # block the very deploy that fixes an outage.
    #
    # The original comment here argued against touching the DB at all: a DB-down
    # event should not flap this service's health while in-flight streams keep
    # serving claims already cached. That reasoning is preserved -- this always
    # returns HTTP 200. What changed is that it now REPORTS database state rather
    # than asserting "ok" unconditionally. It returned 200 throughout a period
    # when every real route was 500ing on a DB error (S9-031).
    #
    # "service" says veris-sse, not veris-stream: veris-stream is the capture
    # poller, a separate Railway service that binds no port. The collision cost
    # hours of debugging against a service never in the request path.
    db_state = "unknown"
    try:
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            db_state = "ok"
        finally:
            conn.close()
    except Exception as exc:
        db_state = "unreachable"
        app.logger.error("[health] database check failed: %s", exc)
    return jsonify({
        "status": "ok" if db_state == "ok" else "degraded",
        "service": "veris-sse",
        "database": db_state,
    }), 200


from flask import Blueprint
from mobile_sse import register_sse_routes

# register_sse_routes expects something with a .route() decorator and
# applies its path relative to that -- the original codebase passed a
# Blueprint with url_prefix='/mobile/v1' (mobile_routes.py's mobile_bp),
# which is where the /mobile/v1 prefix on the old endpoint actually
# came from, not anything inside mobile_sse.py itself. Reproduced the
# same mechanism here with a fresh Blueprint at /v1 -- the "mobile"
# segment meant something in the old shared codebase (one blueprint
# among many mobile-API routes); it means nothing here, since this
# service does only one thing. This IS a path change from the original
# endpoint, not just a host change -- both clients' code needs the
# full new URL, not just a new domain. Called out here so it's not a
# silent surprise buried in a client diff. Verified directly (not
# assumed from reading the code): a throwaway route-registration check
# confirmed the exact final path before this was written.
stream_bp = Blueprint("stream", __name__, url_prefix="/v1")
register_sse_routes(stream_bp, get_db)
app.register_blueprint(stream_bp)

