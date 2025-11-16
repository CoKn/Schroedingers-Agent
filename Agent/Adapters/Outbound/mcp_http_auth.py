from urllib.parse import parse_qs, urlparse

from mcp.client.auth import TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
import httpx
import re
from typing import Optional, Dict, Any 
from dotenv import dotenv_values
from dotenv import dotenv_values, set_key
import os, json, time


config = dotenv_values(dotenv_path=".env_tokens")


class DotenvTokenStorage(TokenStorage):
    """
    Persist OAuth tokens as a JSON string in a .env-style file.
    Each server/user can use a distinct key to avoid collisions.
    """

    def __init__(self, path: str = ".env_tokens", key: str = "MCP_OAUTH_TOKEN"):
        self.path = path
        self.key = key
        self._tokens: Optional[OAuthToken] = None
        self._client_info: Optional[OAuthClientInformationFull] = None

        # Ensure the file exists
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        open(self.path, "a").close()
        try:
            os.chmod(self.path, 0o600)  # restrict perms
        except Exception:
            pass

    async def get_tokens(self) -> Optional[OAuthToken]:
        if self._tokens:
            return self._tokens

        data = dotenv_values(dotenv_path=self.path)
        raw = data.get(self.key)
        if not raw:
            return None

        try:
            payload = json.loads(raw)
            token = OAuthToken(
                access_token=payload.get("access_token"),
                token_type=payload.get("token_type", "Bearer"),
                refresh_token=payload.get("refresh_token"),
                expires_in=payload.get("expires_in"),
            )

            # Populate optional fields many providers rely on
            try:
                token.fetched_at = payload.get("fetched_at")
                token.expires_at = payload.get("expires_at")
            except Exception:
                pass

            self._tokens = token
            return token
        except Exception:
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens

        # Compute expires_at if not provided but expires_in is known
        expires_at = getattr(tokens, "expires_at", None)
        if not expires_at:
            ei = getattr(tokens, "expires_in", None)
            if ei:
                try:
                    expires_at = int(time.time()) + int(ei)
                except Exception:
                    expires_at = None

        payload = {
            "access_token": getattr(tokens, "access_token", None),
            "refresh_token": getattr(tokens, "refresh_token", None),
            "token_type": getattr(tokens, "token_type", "Bearer"),
            "expires_in": getattr(tokens, "expires_in", None),
            "fetched_at": getattr(tokens, "fetched_at", int(time.time())),
            "expires_at": expires_at,
        }

        # Write JSON to the .env-style file under the configured key
        set_key(self.path, self.key, json.dumps(payload))
        try:
            os.chmod(self.path, 0o600)
        except Exception:
            pass

    async def get_client_info(self) -> Optional[OAuthClientInformationFull]:
        return self._client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._client_info = client_info

class InMemoryTokenStorage(TokenStorage):
    """Demo In-memory token storage implementation."""

    def __init__(self):
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        """Get stored tokens."""
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        """Store tokens."""
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        """Get stored client information."""
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        """Store client information."""
        self.client_info = client_info


async def handle_redirect(auth_url: str) -> None:
    print(f"Visit: {auth_url}")


async def handle_callback() -> tuple[str, str | None]:
    callback_url = input("Paste callback URL: ")
    params = parse_qs(urlparse(callback_url).query)
    return params["code"][0], params.get("state", [None])[0]


WWW_AUTH_RE = re.compile(r'(\w+)\s+(.*)')  # crude parse


class TokenManager:
    """Minimal token manager: supports static bearer and client_credentials grant.

    - Uses provided auth_config to determine behavior.
    - Stores tokens in provided TokenStorage (defaults to InMemoryTokenStorage).
    """

    def __init__(self, auth_config: Dict[str, Any] | None = None, storage: TokenStorage | None = None):
        self.config = auth_config or {}
        self.storage = storage or InMemoryTokenStorage()
        self.http = httpx.AsyncClient(verify=True, timeout=10.0)

    async def get_token(self, resource: str) -> Optional[str]:
        # Try stored token
        tokens = await self.storage.get_tokens()
        if tokens and getattr(tokens, "access_token", None):
            expires_in = getattr(tokens, "expires_in", None)
            expires_at = getattr(tokens, "expires_at", None)
            now = time.time()
            if expires_at is not None:
                if expires_at > now + 30:
                    return tokens.access_token
            elif expires_in is not None and getattr(tokens, "fetched_at", None) is not None:
                if tokens.fetched_at + expires_in > now + 30:
                    return tokens.access_token

        # Static bearer token fallback
        if self.config.get("type") in ("bearer", "api_key"):
            return self.config.get("token")

        # Client credentials flow
        if self.config.get("type") == "oauth2_client_credentials":
            return await self._fetch_client_credentials(resource)

        return None

    async def _fetch_client_credentials(self, resource: str) -> Optional[str]:
        token_url = self.config.get("token_url")
        client_id = self.config.get("client_id")
        client_secret = self.config.get("client_secret")
        if not token_url or not client_id or not client_secret:
            return None

        data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "resource": resource,
        }
        scopes = self.config.get("scopes")
        if scopes:
            data["scope"] = " ".join(scopes) if isinstance(scopes, (list, tuple)) else str(scopes)

        resp = await self.http.post(token_url, data=data, headers={"Accept": "application/json"})
        resp.raise_for_status()
        j = resp.json()
        access = j.get("access_token")
        if not access:
            return None

        tok = OAuthToken(
            access_token=access,
            token_type=j.get("token_type", "Bearer"),
            expires_in=j.get("expires_in", 3600),
        )
        # attach fetched_at so get_token can use expires_in
        try:
            tok.fetched_at = time.time()
        except Exception:
            pass

        await self.storage.set_tokens(tok)
        return access

    async def handle_www_auth(self, www_header: str, resource: str) -> bool:
        """Parse a WWW-Authenticate header and attempt to obtain a token.

        This minimal implementation only looks for resource_metadata and will
        use configured client_credentials token_url if available.
        """
        if not www_header:
            return False

        parts: Dict[str, str] = {}
        for m in re.finditer(r'(\w+)="([^"]+)"', www_header):
            parts[m.group(1)] = m.group(2)

        resource_metadata = parts.get("resource_metadata")

        if resource_metadata and not self.config.get("token_url"):
            return False

        if self.config.get("type") == "oauth2_client_credentials" and self.config.get("token_url"):
            tok = await self._fetch_client_credentials(resource)
            return tok is not None

        return False
