"""Do not expose local workspace data through tunnels or cross-origin requests."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}


class LocalAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        # The public OAuth callback must remain reachable via ngrok.
        protected = (path == '/app' or path.startswith('/app/') or
                     path == '/api/tasks' or path.startswith('/api/tasks/') or
                     path in {'/generator', '/slack/send', '/slack/send-cases', '/api/slack-status'})
        if protected:
            headers = request.headers
            host = request.url.hostname
            peer = request.client.host if request.client else None
            forwarded = any(name in headers for name in ('forwarded','x-forwarded-for','x-forwarded-host','x-forwarded-proto','x-original-host'))
            origin = headers.get('origin')
            bad_origin = origin is not None and origin != str(request.base_url).rstrip('/')
            cross_site = headers.get('sec-fetch-site') == 'cross-site'
            if host not in LOCAL_HOSTS or peer not in LOCAL_HOSTS or forwarded or bad_origin or cross_site:
                return JSONResponse({'detail': 'Local access only. Open http://127.0.0.1:8000/app directly.'}, status_code=403)
        response = await call_next(request)
        if protected:
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Frame-Options'] = 'SAMEORIGIN'
            response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
        return response
