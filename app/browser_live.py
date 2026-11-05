"""
Browser Live View
=================

HTTP routes that let the user watch and operate the agent's browser (`app/web_browser.py`):
the portal polls a JPEG of the page and sends back clicks and keystrokes. This is how steps
only a person can do — login, verification code, CAPTCHA — get done without the password
ever passing through the chat or the model.

Access: the routes sit behind the AgentOS auth layer like every other route, and a browser
session is only served to the `user_id` that owns the chat session it was opened in. A wrong
or missing user gets the same answer as "no browser open", so sessions cannot be probed.

Routes (prefix `/browser/sessions/{session_id}`, query `user_id`):
- GET  ``           -> {"open": bool, "url", "title", "width", "height", "waiting_for_user"}
- GET  ``/frame``   -> image/jpeg of the viewport (404 when no browser is open)
- POST ``/input``   -> one event: click {x, y} | type {text} | key {key} | scroll {dy} | back | reload | done
"""

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.web_browser import BrowserManager, get_browser_manager

LIVE_CALL_TIMEOUT = 45.0


class LiveInput(BaseModel):
    type: Literal["click", "type", "key", "scroll", "back", "reload", "done"]
    x: float | None = None
    y: float | None = None
    text: str | None = Field(default=None, max_length=500)
    key: str | None = Field(default=None, max_length=32)
    dy: float | None = None


def browser_live_router(manager: BrowserManager | None = None) -> APIRouter:
    router = APIRouter(prefix="/browser/sessions", tags=["Browser"])

    async def on_browser_thread(coro: Any) -> Any:
        active = manager or get_browser_manager()
        try:
            return await asyncio.wait_for(asyncio.wrap_future(active.submit(coro)), LIVE_CALL_TIMEOUT)
        except TimeoutError:
            raise HTTPException(status_code=504, detail="Browser did not answer in time") from None

    def active_manager() -> BrowserManager:
        return manager or get_browser_manager()

    @router.get("/{session_id}")
    async def live_status(session_id: str, user_id: str = Query(..., min_length=1)) -> dict[str, Any]:
        return await on_browser_thread(active_manager().live_status(session_id, user_id))

    @router.get("/{session_id}/frame")
    async def live_frame(session_id: str, user_id: str = Query(..., min_length=1)) -> Response:
        frame = await on_browser_thread(active_manager().live_frame(session_id, user_id))
        if frame is None:
            raise HTTPException(status_code=404, detail="No browser open for this session")
        return Response(
            content=frame,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @router.post("/{session_id}/input")
    async def live_input(session_id: str, event: LiveInput, user_id: str = Query(..., min_length=1)) -> dict[str, Any]:
        result = await on_browser_thread(
            active_manager().live_input(session_id, user_id, event.model_dump(exclude_none=True))
        )
        if result.get("error") == "closed":
            raise HTTPException(status_code=404, detail="No browser open for this session")
        return result

    return router
