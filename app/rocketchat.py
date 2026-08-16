"""
Rocket.Chat Interface
=====================

Small Rocket.Chat outgoing-webhook bridge for AgentOS agents.
"""

from os import getenv
from typing import Any
from urllib.parse import parse_qsl

from fastapi import APIRouter, HTTPException, Request

from agents.chief import chief
from agents.general_chat import general_chat
from agents.jira_ticket_responder import jira_ticket_responder

ROCKETCHAT_AGENT_MAP = {
    "chief": chief,
    "general-chat": general_chat,
    "jira-ticket-responder": jira_ticket_responder,
}


def _rocketchat_agent() -> Any:
    agent_id = getenv("ROCKETCHAT_AGENT_ID", "jira-ticket-responder")
    return ROCKETCHAT_AGENT_MAP.get(agent_id, jira_ticket_responder)


async def _rocketchat_payload(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
        return payload if isinstance(payload, dict) else {}

    body = (await request.body()).decode("utf-8")
    return dict(parse_qsl(body, keep_blank_values=True))


def _payload_value(payload: dict[str, Any], *names: str) -> str:
    for name in names:
        value = payload.get(name)
        if value is not None:
            return str(value)
    return ""


def _validate_rocketchat_token(payload: dict[str, Any], request: Request) -> None:
    expected_token = getenv("ROCKETCHAT_WEBHOOK_TOKEN", "")
    if not expected_token:
        raise HTTPException(status_code=503, detail="Rocket.Chat webhook is not configured.")

    received_token = (
        _payload_value(payload, "token")
        or request.headers.get("X-RocketChat-Token", "")
        or request.headers.get("X-Rocket-Token", "")
    )
    if received_token != expected_token:
        raise HTTPException(status_code=401, detail="Invalid Rocket.Chat webhook token.")


def _clean_rocketchat_text(text: str) -> str:
    bot_username = getenv("ROCKETCHAT_BOT_USERNAME", "").strip()
    cleaned = text.strip()
    if bot_username:
        cleaned = cleaned.replace(f"@{bot_username}", "").strip()
    return cleaned


def _rocketchat_session_id(payload: dict[str, Any]) -> str:
    room_id = (
        _payload_value(payload, "channel_id", "room_id", "rid", "channel_name")
        or "unknown-room"
    )
    thread_id = _payload_value(payload, "thread_id", "tmid", "message_id", "_id")
    return f"rocketchat:{room_id}:{thread_id or 'main'}"


def _rocketchat_user_id(payload: dict[str, Any]) -> str:
    user_id = _payload_value(payload, "user_id", "userId", "user_name", "username")
    return f"rocketchat:{user_id or 'unknown-user'}"


def rocketchat_router() -> APIRouter:
    router = APIRouter(prefix="/rocketchat", tags=["Rocket.Chat"])

    @router.post("/webhook")
    async def rocket_chat_webhook(request: Request) -> dict[str, str]:
        payload = await _rocketchat_payload(request)
        _validate_rocketchat_token(payload, request)

        text = _clean_rocketchat_text(_payload_value(payload, "text", "message", "msg"))
        if not text:
            return {"text": ""}

        agent = _rocketchat_agent()
        response = await agent.arun(
            text,
            user_id=_rocketchat_user_id(payload),
            session_id=_rocketchat_session_id(payload),
        )
        return {"text": str(getattr(response, "content", response) or "")}

    return router
