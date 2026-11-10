"""Do not expose local workspace data through tunnels or cross-origin requests.

Two modes:
  * local (default) - only loopback requests are served; a tunnel that forwards
    its own host or `X-Forwarded-*` headers is refused outright.
  * proxy (`QAHELPER_ACCESS_MODE=proxy`) - the app runs behind a trusted reverse
    proxy that terminates TLS and authenticates the user. Forwarded headers are
    then expected, so they no longer reject the request.
"""
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}
FORWARDING_HEADERS = ('forwarded', 'x-forwarded-for', 'x-forwarded-host',
                      'x-forwarded-proto', 'x-original-host')


def access_mode() -> str:
    """`proxy` only when explicitly configured; anything else stays local-only."""
    return 'proxy' if os.getenv('QAHELPER_ACCESS_MODE', '').strip().lower() == 'proxy' else 'local'


class LocalAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        # The public OAuth callback must remain reachable via ngrok.
        protected = (path == '/app' or path.startswith('/app/') or
                     path == '/api/tasks' or path.startswith('/api/tasks/') or
                     path.startswith('/api/slack/people') or
                     path.startswith('/api/webview') or
                     path.startswith('/api/case-images') or
                     path in {'/generator', '/slack/send', '/slack/send-cases',
                              '/api/slack-status', '/api/slack-diagnostics'})
        proxy = access_mode() == 'proxy'
        if protected:
            headers = request.headers
            host = request.url.hostname
            peer = request.client.host if request.client else None
            forwarded = any(name in headers for name in FORWARDING_HEADERS)
            origin = headers.get('origin')
            bad_origin = origin is not None and origin != str(request.base_url).rstrip('/')
            cross_site = headers.get('sec-fetch-site') == 'cross-site'
            # Behind the proxy the host and peer are the proxy's, so only the
            # browser-controlled checks remain: a foreign Origin is still a
            # cross-site request and is refused.
            if proxy:
                if bad_origin or cross_site:
                    return JSONResponse({'detail': 'Cross-site request refused.'}, status_code=403)
            elif host not in LOCAL_HOSTS or peer not in LOCAL_HOSTS or forwarded or bad_origin or cross_site:
                return JSONResponse({'detail': 'Local access only. Open http://127.0.0.1:8000/app directly.'}, status_code=403)
        response = await call_next(request)
        if protected:
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Frame-Options'] = 'SAMEORIGIN'
            response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
        return response
