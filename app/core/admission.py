"""Bound HTTP body bytes before routing, authentication dependencies or JSON parsing."""

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import error_response

MAX_REQUEST_BODY_BYTES = 64 * 1024


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def reject():
            request = Request(scope)
            request.state.outcome_code = "REQUEST_TOO_LARGE"
            response = error_response(
                request, 413, "REQUEST_TOO_LARGE", "Request body exceeds the 65536-byte limit."
            )
            await response(scope, receive, send)

        # A large declaration can be rejected without reading. A small, missing
        # or invalid declaration never exempts actual bytes from admission.
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    if int(value) > MAX_REQUEST_BODY_BYTES:
                        await reject()
                        return
                except ValueError:
                    pass

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_REQUEST_BODY_BYTES:
                # Do not append the offending chunk or consume the remaining
                # stream. The server owns the size/allocation of each ASGI frame.
                await reject()
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        delivered = False

        async def admitted_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, admitted_receive, send)
