"""Bounded verified HTTP transport; credentials cannot follow redirects or environment proxies."""
import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener
from contracts.agents_v1 import MAX_MESSAGE_BYTES


class AgentError(Exception):
    """Safe fixed messages only: never display raw credentials, responses, URLs or exceptions."""


def server_url(value):
    if not isinstance(value, str):
        raise AgentError("Configure a valid backend URL.")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise AgentError("Configure a valid backend URL.") from exc
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or parsed.path not in ("", "/") or not parsed.hostname:
        raise AgentError("Use a backend origin without credentials, path, query or fragment.")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise AgentError("HTTP is restricted to explicit loopback; other backends require verified HTTPS.")
    if any(c.isspace() for c in value) or port == 0:
        raise AgentError("Configure a valid backend URL.")
    return value.rstrip("/")


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        raise AgentError("Backend redirects are refused; verify the configured backend origin.")


class Transport:
    def post_binary(self,path,data,credential,*,identity,name):
        from contracts.evidence_v1 import OUTPUT_LIMITS, content_sha, output_name
        from contracts.runner_v1 import strict_json
        output_name(name)
        if not path.startswith('/api/v1/agents/') or not path.endswith('/output') or any(c in path for c in ('?','#','..')) or not isinstance(data,bytes) or len(data)>OUTPUT_LIMITS[name]:
            raise AgentError('Unsupported bounded evidence upload.')
        request=Request(self.base_url+path,data=data,method='POST',headers={'Content-Type':'application/octet-stream',
            'Authorization':'Bearer '+credential,'X-Execution-ID':identity['execution_id'],'X-Claim-Epoch':str(identity['epoch']),
            'X-Claim-Token':identity['claim_token'],'X-Evidence-Name':name,'X-Content-SHA256':content_sha(data)})
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                raw=response.read(MAX_MESSAGE_BYTES+1)
                if len(raw)>MAX_MESSAGE_BYTES or response.headers.get_content_type()!='application/json':
                    raise AgentError('Evidence reply exceeds protocol bounds.')
                return strict_json(raw)
        except (HTTPError,URLError,OSError,TimeoutError):
            raise AgentError('Evidence upload failed; keep the original spool for retry.') from None

    def __init__(self, base_url, timeout=5):
        self.base_url = server_url(base_url)
        if type(timeout) is not int or not 1 <= timeout <= 30:
            raise AgentError("Timeout must be 1-30 seconds.")
        self.timeout = timeout
        try:
            context = ssl.create_default_context()
        except OSError:
            raise AgentError("TLS initialization was blocked by the local environment; contact your administrator.") from None
        self.opener = build_opener(ProxyHandler({}), NoRedirects(), HTTPSHandler(context=context))

    def post(self, path, payload, credential, scheme="Bearer"):
        if not path.startswith("/api/v1/agents/") or "?" in path or "#" in path or ".." in path:
            raise AgentError("Unsupported agent route.")
        encoded = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode()
        if len(encoded) > MAX_MESSAGE_BYTES:
            raise AgentError("Agent request exceeds protocol size limit.")
        request = Request(self.base_url + path, data=encoded, method="POST",
                          headers={"Content-Type": "application/json", "Authorization": scheme + " " + credential})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                data = response.read(MAX_MESSAGE_BYTES + 1)
                if len(data) > MAX_MESSAGE_BYTES or response.headers.get_content_type() != "application/json":
                    raise AgentError("Backend response violates the bounded JSON protocol.")
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise AgentError("Agent credential or scope was rejected; contact the project administrator.") from None
            raise AgentError("Backend rejected the agent request.") from None
        except (URLError, OSError, TimeoutError):
            raise AgentError("Backend contact failed within the configured timeout.") from None
        try:
            def pairs(items):
                result = {}
                for key, value in items:
                    if key in result:
                        raise ValueError
                    result[key] = value
                return result
            result = json.loads(data, object_pairs_hook=pairs, parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (ValueError, UnicodeError):
            raise AgentError("Backend returned an invalid protocol response.") from None

    def post_bytes(self,path,payload,credential,*,maximum=1024*1024):
        if not path.startswith('/api/v1/agents/') or not path.endswith('/input') or any(c in path for c in ('?','#','..')):
            raise AgentError('Unsupported agent input route.')
        encoded=json.dumps(payload,allow_nan=False,separators=(',',':')).encode()
        if len(encoded)>MAX_MESSAGE_BYTES or type(maximum) is not int or not 0<=maximum<=1024*1024:
            raise AgentError('Input request exceeds its bound.')
        request=Request(self.base_url+path,data=encoded,method='POST',headers={'Content-Type':'application/json','Authorization':'Bearer '+credential})
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                raw=response.read(maximum+1)
                if len(raw)>maximum or response.headers.get_content_type()!='application/octet-stream':
                    raise AgentError('Backend input violates its bounded contract.')
                return raw
        except HTTPError as exc:
            if exc.code in (401,403):raise AgentError('Agent credential or scope was rejected; contact the project administrator.') from None
            raise AgentError('Backend rejected the scoped input request.') from None
        except (URLError,OSError,TimeoutError):
            raise AgentError('Backend input contact failed within its timeout.') from None
