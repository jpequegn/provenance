"""Teams message poller for automatic fragment creation.

This module provides background polling of Teams channels
and automatic creation of fragments from messages.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import httpx

from provo.integrations.teams import TeamsClient, TeamsConfig, TeamsMessage

logger = logging.getLogger(__name__)


@dataclass
class MonitoredChannel:
    """A channel being monitored for messages."""

    team_id: str
    team_name: str
    channel_id: str
    channel_name: str
    project: str | None = None  # Optional project to assign to fragments
    topics: list[str] = field(default_factory=list)  # Default topics


@dataclass
class PollerState:
    """Persistent state for the poller."""

    channels: list[MonitoredChannel] = field(default_factory=list)
    last_poll: dict[str, str] = field(default_factory=dict)  # channel_id -> ISO timestamp

    def get_last_poll(self, channel_id: str) -> datetime | None:
        """Get last poll time for a channel."""
        ts = self.last_poll.get(channel_id)
        if ts:
            return datetime.fromisoformat(ts)
        return None

    def set_last_poll(self, channel_id: str, timestamp: datetime) -> None:
        """Set last poll time for a channel."""
        self.last_poll[channel_id] = timestamp.isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "channels": [
                {
                    "team_id": ch.team_id,
                    "team_name": ch.team_name,
                    "channel_id": ch.channel_id,
                    "channel_name": ch.channel_name,
                    "project": ch.project,
                    "topics": ch.topics,
                }
                for ch in self.channels
            ],
            "last_poll": self.last_poll,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PollerState":
        """Create from dictionary."""
        channels = [
            MonitoredChannel(
                team_id=ch["team_id"],
                team_name=ch["team_name"],
                channel_id=ch["channel_id"],
                channel_name=ch["channel_name"],
                project=ch.get("project"),
                topics=ch.get("topics", []),
            )
            for ch in data.get("channels", [])
        ]
        return cls(
            channels=channels,
            last_poll=data.get("last_poll", {}),
        )


class TeamsPoller:
    """Polls Teams channels for new messages and creates fragments.

    The poller runs in the background, periodically checking monitored
    channels for new messages and sending them to the API as fragments.
    """

    def __init__(
        self,
        client: TeamsClient,
        api_url: str = "http://localhost:8000",
        state_file: Path | None = None,
        poll_interval: int = 60,  # seconds
    ):
        """Initialize the poller.

        Args:
            client: Authenticated Teams client.
            api_url: URL of the Provenance API.
            state_file: Path for persistent state (channels, last poll times).
            poll_interval: Seconds between polls.
        """
        self.client = client
        self.api_url = api_url
        self.poll_interval = poll_interval
        self.state_file = state_file

        self._state: PollerState = PollerState()
        self._running = False
        self._task: asyncio.Task | None = None

        self._load_state()

    def _load_state(self) -> None:
        """Load state from file if available."""
        if self.state_file and self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                self._state = PollerState.from_dict(data)
                logger.debug(f"Loaded state: {len(self._state.channels)} channels")
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to load state: {e}")

    def _save_state(self) -> None:
        """Save state to file."""
        if self.state_file:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps(self._state.to_dict(), indent=2)
            )

    @property
    def monitored_channels(self) -> list[MonitoredChannel]:
        """Get list of monitored channels."""
        return self._state.channels.copy()

    def add_channel(
        self,
        team_id: str,
        team_name: str,
        channel_id: str,
        channel_name: str,
        project: str | None = None,
        topics: list[str] | None = None,
    ) -> None:
        """Add a channel to monitor.

        Args:
            team_id: The team ID.
            team_name: The team display name.
            channel_id: The channel ID.
            channel_name: The channel display name.
            project: Optional project to assign to fragments.
            topics: Optional default topics for fragments.
        """
        # Check if already monitored
        for ch in self._state.channels:
            if ch.channel_id == channel_id:
                logger.info(f"Channel {channel_name} already monitored")
                return

        self._state.channels.append(
            MonitoredChannel(
                team_id=team_id,
                team_name=team_name,
                channel_id=channel_id,
                channel_name=channel_name,
                project=project,
                topics=topics or [],
            )
        )
        self._save_state()
        logger.info(f"Added channel to monitor: {team_name}/{channel_name}")

    def remove_channel(self, channel_id: str) -> bool:
        """Remove a channel from monitoring.

        Args:
            channel_id: The channel ID to remove.

        Returns:
            True if channel was removed.
        """
        for i, ch in enumerate(self._state.channels):
            if ch.channel_id == channel_id:
                removed = self._state.channels.pop(i)
                self._save_state()
                logger.info(f"Removed channel: {removed.team_name}/{removed.channel_name}")
                return True
        return False

    async def _create_fragment(
        self,
        message: TeamsMessage,
        channel: MonitoredChannel,
    ) -> str | None:
        """Create a fragment from a Teams message.

        Args:
            message: The Teams message.
            channel: The monitored channel config.

        Returns:
            Fragment ID on success, None on failure.
        """
        # Build source reference
        source_ref = f"teams://{channel.team_name}/{channel.channel_name}/{message.id}"

        # Build content with context
        content_parts = [f"[{message.sender}]: {message.content}"]
        if message.reply_to_id:
            content_parts.insert(0, f"(Reply in thread)")

        payload = {
            "content": "\n".join(content_parts),
            "source_type": "teams",
            "source_ref": source_ref,
            "participants": [message.sender],
            "captured_at": message.created_at.isoformat(),
        }

        if channel.project:
            payload["project"] = channel.project

        if channel.topics:
            payload["topics"] = channel.topics

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.api_url}/api/fragments",
                    json=payload,
                )

                if response.status_code == 201:
                    data = response.json()
                    return str(data.get("id", "unknown"))
                else:
                    logger.error(f"API error: {response.status_code} - {response.text}")
                    return None

        except Exception as e:
            logger.error(f"Failed to create fragment: {e}")
            return None

    async def _poll_channel(self, channel: MonitoredChannel) -> int:
        """Poll a single channel for new messages.

        Args:
            channel: The channel to poll.

        Returns:
            Number of messages processed.
        """
        # Get last poll time, default to 24 hours ago
        last_poll = self._state.get_last_poll(channel.channel_id)
        if not last_poll:
            last_poll = datetime.now(UTC) - timedelta(hours=24)

        try:
            messages = await self.client.get_channel_messages(
                team_id=channel.team_id,
                channel_id=channel.channel_id,
                since=last_poll,
                limit=100,
            )

            count = 0
            latest_time = last_poll

            for message in messages:
                # Skip empty messages
                if not message.content.strip():
                    continue

                # Create fragment
                fragment_id = await self._create_fragment(message, channel)
                if fragment_id:
                    count += 1
                    logger.info(
                        f"Created fragment {fragment_id} from "
                        f"{channel.channel_name}: {message.content[:50]}..."
                    )

                # Track latest message time
                if message.created_at > latest_time:
                    latest_time = message.created_at

            # Update last poll time
            self._state.set_last_poll(channel.channel_id, latest_time)
            self._save_state()

            return count

        except Exception as e:
            logger.error(f"Failed to poll {channel.channel_name}: {e}")
            return 0

    async def poll_once(self) -> dict[str, int]:
        """Poll all channels once.

        Returns:
            Dictionary of channel_name -> messages processed.
        """
        results: dict[str, int] = {}

        for channel in self._state.channels:
            count = await self._poll_channel(channel)
            results[f"{channel.team_name}/{channel.channel_name}"] = count

        return results

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                results = await self.poll_once()
                total = sum(results.values())
                if total > 0:
                    logger.info(f"Poll complete: {total} new messages processed")
            except Exception as e:
                logger.error(f"Poll error: {e}")

            # Wait for next poll
            await asyncio.sleep(self.poll_interval)

    def start(self) -> None:
        """Start the polling loop."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            f"Started polling {len(self._state.channels)} channels "
            f"every {self.poll_interval}s"
        )

    def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Stopped polling")

    @property
    def is_running(self) -> bool:
        """Check if poller is running."""
        return self._running


async def poll_teams_interactive(
    client: TeamsClient,
    api_url: str = "http://localhost:8000",
    state_file: Path | None = None,
    poll_interval: int = 60,
    on_message: Callable[[TeamsMessage, str | None], None] | None = None,
) -> None:
    """Run interactive Teams polling.

    Args:
        client: Authenticated Teams client.
        api_url: URL of the Provenance API.
        state_file: Path for persistent state.
        poll_interval: Seconds between polls.
        on_message: Optional callback for each message processed.
    """
    poller = TeamsPoller(
        client=client,
        api_url=api_url,
        state_file=state_file,
        poll_interval=poll_interval,
    )

    if not poller.monitored_channels:
        logger.warning("No channels configured for monitoring")
        return

    poller.start()

    try:
        while poller.is_running:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        poller.stop()
