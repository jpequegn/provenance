"""Microsoft Teams integration via Graph API.

This module provides OAuth2 authentication and message fetching
from Microsoft Teams channels using the Microsoft Graph API.
"""

import asyncio
import json
import logging
import webbrowser
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

logger = logging.getLogger(__name__)

# Microsoft OAuth2 endpoints
AUTHORITY_URL = "https://login.microsoftonline.com"
GRAPH_API_URL = "https://graph.microsoft.com/v1.0"

# Required scopes for Teams access
DEFAULT_SCOPES = [
    "ChannelMessage.Read.All",
    "Chat.Read",
    "Team.ReadBasic.All",
    "Channel.ReadBasic.All",
    "offline_access",  # For refresh tokens
]


@dataclass
class TeamsConfig:
    """Configuration for Teams integration."""

    client_id: str
    client_secret: str | None = None  # Optional for public client flow
    tenant_id: str = "common"  # Use "common" for multi-tenant, or specific tenant ID
    redirect_uri: str = "http://localhost:8400/callback"
    scopes: list[str] = field(default_factory=lambda: DEFAULT_SCOPES.copy())

    # Token storage
    token_file: Path | None = None

    @classmethod
    def from_env(cls, token_file: Path | None = None) -> "TeamsConfig":
        """Create config from environment variables.

        Environment variables:
            TEAMS_CLIENT_ID: Azure AD application client ID
            TEAMS_CLIENT_SECRET: Azure AD application client secret (optional)
            TEAMS_TENANT_ID: Azure AD tenant ID (default: common)
        """
        import os

        client_id = os.environ.get("TEAMS_CLIENT_ID")
        if not client_id:
            raise ValueError("TEAMS_CLIENT_ID environment variable is required")

        return cls(
            client_id=client_id,
            client_secret=os.environ.get("TEAMS_CLIENT_SECRET"),
            tenant_id=os.environ.get("TEAMS_TENANT_ID", "common"),
            token_file=token_file,
        )


@dataclass
class TokenData:
    """OAuth2 token data."""

    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    token_type: str = "Bearer"

    @property
    def is_expired(self) -> bool:
        """Check if the token is expired."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "token_type": self.token_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TokenData":
        """Create from dictionary."""
        expires_at = None
        if data.get("expires_at"):
            expires_at = datetime.fromisoformat(data["expires_at"])
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            token_type=data.get("token_type", "Bearer"),
        )


@dataclass
class TeamsMessage:
    """A message from Teams."""

    id: str
    content: str
    sender: str
    created_at: datetime
    channel_id: str
    channel_name: str
    team_id: str
    team_name: str
    reply_to_id: str | None = None  # Thread context


@dataclass
class TeamsChannel:
    """A Teams channel."""

    id: str
    name: str
    description: str | None
    team_id: str
    team_name: str


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handle OAuth2 callback."""

    auth_code: str | None = None
    error: str | None = None

    def do_GET(self) -> None:
        """Handle GET request from OAuth callback."""
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            OAuthCallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>Authentication successful!</h1>"
                b"<p>You can close this window and return to the CLI.</p></body></html>"
            )
        elif "error" in params:
            OAuthCallbackHandler.error = params.get("error_description", params["error"])[0]
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                f"<html><body><h1>Authentication failed</h1>"
                f"<p>{OAuthCallbackHandler.error}</p></body></html>".encode()
            )
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress logging."""
        pass


class TeamsClient:
    """Client for Microsoft Teams Graph API.

    Supports OAuth2 authentication with device code flow (for CLI)
    and authorization code flow (with browser).
    """

    def __init__(self, config: TeamsConfig):
        """Initialize the Teams client.

        Args:
            config: Teams configuration with credentials.
        """
        self.config = config
        self._token: TokenData | None = None
        self._load_token()

    def _load_token(self) -> None:
        """Load token from file if available."""
        if self.config.token_file and self.config.token_file.exists():
            try:
                data = json.loads(self.config.token_file.read_text())
                self._token = TokenData.from_dict(data)
                logger.debug("Loaded token from file")
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to load token: {e}")
                self._token = None

    def _save_token(self) -> None:
        """Save token to file if configured."""
        if self.config.token_file and self._token:
            self.config.token_file.parent.mkdir(parents=True, exist_ok=True)
            self.config.token_file.write_text(
                json.dumps(self._token.to_dict(), indent=2)
            )
            logger.debug("Saved token to file")

    @property
    def is_authenticated(self) -> bool:
        """Check if client has valid authentication."""
        return self._token is not None and (
            not self._token.is_expired or self._token.refresh_token is not None
        )

    def get_auth_url(self) -> str:
        """Get the authorization URL for OAuth2 flow.

        Returns:
            URL to redirect user to for authentication.
        """
        params = {
            "client_id": self.config.client_id,
            "response_type": "code",
            "redirect_uri": self.config.redirect_uri,
            "scope": " ".join(self.config.scopes),
            "response_mode": "query",
        }
        base_url = f"{AUTHORITY_URL}/{self.config.tenant_id}/oauth2/v2.0/authorize"
        return f"{base_url}?{urlencode(params)}"

    async def authenticate_with_browser(self, timeout: int = 120) -> bool:
        """Authenticate using browser-based OAuth2 flow.

        Opens a browser for the user to authenticate and waits for callback.

        Args:
            timeout: Maximum seconds to wait for authentication.

        Returns:
            True if authentication was successful.
        """
        # Reset state
        OAuthCallbackHandler.auth_code = None
        OAuthCallbackHandler.error = None

        # Parse redirect URI for port
        parsed = urlparse(self.config.redirect_uri)
        port = parsed.port or 8400

        # Start local server for callback
        server = HTTPServer(("localhost", port), OAuthCallbackHandler)
        server.timeout = timeout

        # Start server in background thread
        server_thread = Thread(target=server.handle_request, daemon=True)
        server_thread.start()

        # Open browser
        auth_url = self.get_auth_url()
        logger.info(f"Opening browser for authentication...")
        webbrowser.open(auth_url)

        # Wait for callback
        server_thread.join(timeout=timeout)
        server.server_close()

        if OAuthCallbackHandler.error:
            logger.error(f"Authentication failed: {OAuthCallbackHandler.error}")
            return False

        if not OAuthCallbackHandler.auth_code:
            logger.error("Authentication timed out")
            return False

        # Exchange code for token
        return await self._exchange_code(OAuthCallbackHandler.auth_code)

    async def _exchange_code(self, code: str) -> bool:
        """Exchange authorization code for tokens.

        Args:
            code: Authorization code from OAuth callback.

        Returns:
            True if token exchange was successful.
        """
        token_url = f"{AUTHORITY_URL}/{self.config.tenant_id}/oauth2/v2.0/token"

        data = {
            "client_id": self.config.client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.redirect_uri,
            "scope": " ".join(self.config.scopes),
        }

        if self.config.client_secret:
            data["client_secret"] = self.config.client_secret

        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data)

            if response.status_code != 200:
                logger.error(f"Token exchange failed: {response.text}")
                return False

            token_data = response.json()
            self._token = TokenData(
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token"),
                expires_at=datetime.now(UTC) + timedelta(seconds=token_data.get("expires_in", 3600)),
                token_type=token_data.get("token_type", "Bearer"),
            )
            self._save_token()
            logger.info("Authentication successful")
            return True

    async def refresh_token(self) -> bool:
        """Refresh the access token using refresh token.

        Returns:
            True if refresh was successful.
        """
        if not self._token or not self._token.refresh_token:
            logger.error("No refresh token available")
            return False

        token_url = f"{AUTHORITY_URL}/{self.config.tenant_id}/oauth2/v2.0/token"

        data = {
            "client_id": self.config.client_id,
            "grant_type": "refresh_token",
            "refresh_token": self._token.refresh_token,
            "scope": " ".join(self.config.scopes),
        }

        if self.config.client_secret:
            data["client_secret"] = self.config.client_secret

        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data)

            if response.status_code != 200:
                logger.error(f"Token refresh failed: {response.text}")
                return False

            token_data = response.json()
            self._token = TokenData(
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token", self._token.refresh_token),
                expires_at=datetime.now(UTC) + timedelta(seconds=token_data.get("expires_in", 3600)),
                token_type=token_data.get("token_type", "Bearer"),
            )
            self._save_token()
            logger.debug("Token refreshed")
            return True

    async def _ensure_token(self) -> str:
        """Ensure we have a valid token.

        Returns:
            Valid access token.

        Raises:
            ValueError: If not authenticated.
        """
        if not self._token:
            raise ValueError("Not authenticated. Run 'provo teams login' first.")

        if self._token.is_expired:
            if self._token.refresh_token:
                success = await self.refresh_token()
                if not success:
                    raise ValueError("Token refresh failed. Run 'provo teams login' again.")
            else:
                raise ValueError("Token expired. Run 'provo teams login' again.")

        return self._token.access_token

    async def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make authenticated GET request to Graph API.

        Args:
            endpoint: API endpoint (without base URL).
            params: Query parameters.

        Returns:
            JSON response data.
        """
        token = await self._ensure_token()

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GRAPH_API_URL}{endpoint}",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                timeout=30.0,
            )

            if response.status_code == 401:
                # Try refresh and retry
                if await self.refresh_token():
                    token = await self._ensure_token()
                    response = await client.get(
                        f"{GRAPH_API_URL}{endpoint}",
                        headers={"Authorization": f"Bearer {token}"},
                        params=params,
                        timeout=30.0,
                    )

            response.raise_for_status()
            return response.json()

    async def list_teams(self) -> list[dict[str, str]]:
        """List all teams the user is a member of.

        Returns:
            List of teams with id, displayName, and description.
        """
        data = await self._get("/me/joinedTeams")
        return [
            {
                "id": team["id"],
                "name": team["displayName"],
                "description": team.get("description", ""),
            }
            for team in data.get("value", [])
        ]

    async def list_channels(self, team_id: str) -> list[TeamsChannel]:
        """List channels in a team.

        Args:
            team_id: The team ID.

        Returns:
            List of channels.
        """
        # Get team info for name
        team_data = await self._get(f"/teams/{team_id}")
        team_name = team_data.get("displayName", "Unknown Team")

        # Get channels
        data = await self._get(f"/teams/{team_id}/channels")
        return [
            TeamsChannel(
                id=channel["id"],
                name=channel["displayName"],
                description=channel.get("description"),
                team_id=team_id,
                team_name=team_name,
            )
            for channel in data.get("value", [])
        ]

    async def get_channel_messages(
        self,
        team_id: str,
        channel_id: str,
        since: datetime | None = None,
        limit: int = 50,
    ) -> list[TeamsMessage]:
        """Get messages from a channel.

        Args:
            team_id: The team ID.
            channel_id: The channel ID.
            since: Only get messages after this time.
            limit: Maximum number of messages to return.

        Returns:
            List of messages.
        """
        # Get team and channel info
        team_data = await self._get(f"/teams/{team_id}")
        team_name = team_data.get("displayName", "Unknown Team")

        channel_data = await self._get(f"/teams/{team_id}/channels/{channel_id}")
        channel_name = channel_data.get("displayName", "Unknown Channel")

        # Build endpoint with filter
        endpoint = f"/teams/{team_id}/channels/{channel_id}/messages"
        params: dict[str, Any] = {"$top": limit}

        if since:
            # Graph API uses OData filter
            since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
            params["$filter"] = f"lastModifiedDateTime gt {since_str}"

        data = await self._get(endpoint, params)

        messages = []
        for msg in data.get("value", []):
            # Skip system messages
            if msg.get("messageType") != "message":
                continue

            # Extract sender
            sender = "Unknown"
            if msg.get("from", {}).get("user"):
                sender = msg["from"]["user"].get("displayName", "Unknown")

            # Parse timestamp
            created_at = datetime.fromisoformat(
                msg["createdDateTime"].replace("Z", "+00:00")
            )

            # Extract content (strip HTML if present)
            content = msg.get("body", {}).get("content", "")
            if msg.get("body", {}).get("contentType") == "html":
                # Basic HTML stripping (for proper handling, use a library)
                import re
                content = re.sub(r"<[^>]+>", "", content)

            messages.append(
                TeamsMessage(
                    id=msg["id"],
                    content=content.strip(),
                    sender=sender,
                    created_at=created_at,
                    channel_id=channel_id,
                    channel_name=channel_name,
                    team_id=team_id,
                    team_name=team_name,
                    reply_to_id=msg.get("replyToId"),
                )
            )

        return messages

    async def get_chat_messages(
        self,
        chat_id: str,
        since: datetime | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get messages from a chat.

        Args:
            chat_id: The chat ID.
            since: Only get messages after this time.
            limit: Maximum number of messages to return.

        Returns:
            List of message data.
        """
        endpoint = f"/chats/{chat_id}/messages"
        params: dict[str, Any] = {"$top": limit}

        if since:
            since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
            params["$filter"] = f"lastModifiedDateTime gt {since_str}"

        data = await self._get(endpoint, params)
        return data.get("value", [])

    def logout(self) -> None:
        """Clear stored authentication."""
        self._token = None
        if self.config.token_file and self.config.token_file.exists():
            self.config.token_file.unlink()
            logger.info("Cleared authentication")
