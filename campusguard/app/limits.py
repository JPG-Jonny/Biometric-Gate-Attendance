"""Bound request bodies before FastAPI's multipart parser can spool large files."""
from starlette.responses import JSONResponse


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in {'POST','PUT','PATCH'}:
            return await self.app(scope, receive, send)
        limit = 20_000 if scope['path'] == '/api/v1/gate/verify-face' or scope['path'].startswith('/api/v1/auth/') else 5 * 1024 * 1024
        packets = []
        size = 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            size += len(message.get('body', b''))
            if size > limit:
                return await JSONResponse({'detail':'Request body too large'},status_code=413)(scope,receive,send)
            packets.append(message)
            if not message.get('more_body', False):
                break
        iterator = iter(packets)
        async def replay():
            try:
                return next(iterator)
            except StopIteration:
                return await receive()
        await self.app(scope, replay, send)
