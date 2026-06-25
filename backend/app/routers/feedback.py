"""
Feedback & feature-voting board.

Powers the in-app widget (no separate page): a single-answer list of candidate
features. Users cast ONE vote per release ("round"), all votes weigh the same,
and the board is returned sorted by votes so the most-wanted bubble to the top.

Design notes (kept intentionally simple / maintainable):
  - No dependency on backend Clerk verification (the app runs Clerk keyless): the
    frontend passes the Clerk user_id, which we use only to de-duplicate votes.
    Feature polling is low-stakes, so trusting the caller's id is acceptable.
  - "One vote per release" = PRIMARY KEY (round_id, user_id); changing your vote
    is an upsert. Bump FEATURE_VOTE_ROUND each release to reset the board.
  - Reads/writes go through users.duckdb (same pattern as saved_queries) so they
    survive restarts via the existing GCS sync cycle.
"""
import os
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database import get_user_db_connection, get_user_db_lock

router = APIRouter(prefix="/api/feedback", tags=["Feedback"])


def current_round() -> str:
    """The active voting round. Bump FEATURE_VOTE_ROUND per release so every user
    gets one fresh vote each time you ship something new."""
    return (os.getenv("FEATURE_VOTE_ROUND", "r1").strip() or "r1")


def _clean_id(user_id: Optional[str]) -> Optional[str]:
    return (user_id or "").strip() or None


class VoteIn(BaseModel):
    option_id: str
    user_id: Optional[str] = None


class SuggestionIn(BaseModel):
    text: str
    user_id: Optional[str] = None


def _read_board(user_id: Optional[str]) -> dict:
    rnd = current_round()
    lock = get_user_db_lock()
    with lock:
        con = get_user_db_connection(read_only=True)
        try:
            rows = con.execute(
                """
                SELECT o.id, o.label, o.description, COUNT(v.user_id) AS votes
                FROM feature_options o
                LEFT JOIN feature_votes v
                  ON v.option_id = o.id AND v.round_id = ?
                WHERE o.archived = FALSE
                GROUP BY o.id, o.label, o.description, o.sort_order
                ORDER BY votes DESC, o.sort_order ASC
                """,
                [rnd],
            ).fetchall()
            my_vote = None
            uid = _clean_id(user_id)
            if uid:
                r = con.execute(
                    "SELECT option_id FROM feature_votes WHERE round_id = ? AND user_id = ?",
                    [rnd, uid],
                ).fetchone()
                my_vote = r[0] if r else None
        finally:
            con.close()

    options = [
        {"id": a, "label": b, "description": c, "votes": int(d or 0)}
        for (a, b, c, d) in rows
    ]
    return {
        "round": rnd,
        "options": options,
        "my_vote": my_vote,
        "total_votes": sum(o["votes"] for o in options),
    }


@router.get("/board")
def get_board(user_id: Optional[str] = None):
    """Return the options sorted by votes (desc) for the current round, plus the
    caller's current pick (my_vote) when a user_id is supplied."""
    return _read_board(user_id)


@router.post("/vote")
def vote(payload: VoteIn):
    """Cast / change the caller's single vote for the current round."""
    uid = _clean_id(payload.user_id)
    if not uid:
        raise HTTPException(status_code=401, detail="Inicia sesión para votar")

    rnd = current_round()
    lock = get_user_db_lock()
    with lock:
        con = get_user_db_connection()
        try:
            exists = con.execute(
                "SELECT 1 FROM feature_options WHERE id = ? AND archived = FALSE",
                [payload.option_id],
            ).fetchone()
            if not exists:
                raise HTTPException(status_code=404, detail="Opción no encontrada")
            # PK (round_id, user_id) => one active vote per release; revoting upserts.
            con.execute(
                "INSERT OR REPLACE INTO feature_votes (round_id, user_id, option_id, created_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                [rnd, uid, payload.option_id],
            )
        finally:
            con.close()
    return _read_board(uid)


@router.post("/suggestion")
def suggestion(payload: SuggestionIn):
    """Free-text "¿Qué echas de menos en Edgecute?" — the escape hatch from the
    voting list when none of the options fit."""
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="El texto no puede estar vacío")
    text = text[:2000]

    lock = get_user_db_lock()
    with lock:
        con = get_user_db_connection()
        try:
            con.execute(
                "INSERT INTO feature_suggestions (id, user_id, message, round_id, created_at) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                [str(uuid4()), _clean_id(payload.user_id), text, current_round()],
            )
        finally:
            con.close()
    return {"ok": True}


@router.get("/suggestions")
def list_suggestions(limit: int = 200):
    """Read recent free-text suggestions (for the team to review)."""
    lock = get_user_db_lock()
    with lock:
        con = get_user_db_connection(read_only=True)
        try:
            rows = con.execute(
                "SELECT id, user_id, message, round_id, created_at "
                "FROM feature_suggestions ORDER BY created_at DESC LIMIT ?",
                [max(1, min(limit, 1000))],
            ).fetchall()
        finally:
            con.close()
    return {
        "suggestions": [
            {
                "id": a,
                "user_id": b,
                "message": c,
                "round": d,
                "created_at": str(e),
            }
            for (a, b, c, d, e) in rows
        ]
    }
