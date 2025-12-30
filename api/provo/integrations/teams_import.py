"""Teams export import functionality.

Alternative to Graph API: import Teams chat exports directly.
Teams allows exporting chat history which can be imported as fragments.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class TeamsExportMessage:
    """A message parsed from Teams export."""

    sender: str
    content: str
    timestamp: datetime
    thread_id: str | None = None


def parse_teams_export(export_path: Path) -> list[TeamsExportMessage]:
    """Parse a Teams export file.

    Teams exports can come in various formats:
    - JSON export from compliance/eDiscovery
    - HTML export from chat history

    Args:
        export_path: Path to the export file.

    Returns:
        List of parsed messages.
    """
    if not export_path.exists():
        raise FileNotFoundError(f"Export file not found: {export_path}")

    suffix = export_path.suffix.lower()

    if suffix == ".json":
        return _parse_json_export(export_path)
    elif suffix in (".html", ".htm"):
        return _parse_html_export(export_path)
    else:
        raise ValueError(f"Unsupported export format: {suffix}")


def _parse_json_export(export_path: Path) -> list[TeamsExportMessage]:
    """Parse JSON format Teams export."""
    data = json.loads(export_path.read_text(encoding="utf-8"))

    messages = []

    # Handle common JSON export formats
    if isinstance(data, list):
        # Array of messages
        for item in data:
            msg = _parse_json_message(item)
            if msg:
                messages.append(msg)
    elif isinstance(data, dict):
        # Object with messages array
        msg_array = data.get("messages", data.get("value", []))
        for item in msg_array:
            msg = _parse_json_message(item)
            if msg:
                messages.append(msg)

    return messages


def _parse_json_message(item: dict[str, Any]) -> TeamsExportMessage | None:
    """Parse a single JSON message object."""
    try:
        # Try different field names for sender
        sender = (
            item.get("from", {}).get("user", {}).get("displayName")
            or item.get("sender", {}).get("displayName")
            or item.get("sender")
            or item.get("from")
            or "Unknown"
        )

        # Try different field names for content
        content = (
            item.get("body", {}).get("content")
            or item.get("content")
            or item.get("message")
            or ""
        )

        # Strip HTML if present
        if "<" in content:
            import re
            content = re.sub(r"<[^>]+>", "", content)

        if not content.strip():
            return None

        # Try different timestamp fields
        timestamp_str = (
            item.get("createdDateTime")
            or item.get("timestamp")
            or item.get("sentDateTime")
            or item.get("date")
        )

        if timestamp_str:
            # Handle various timestamp formats
            if isinstance(timestamp_str, str):
                timestamp_str = timestamp_str.replace("Z", "+00:00")
                timestamp = datetime.fromisoformat(timestamp_str)
            else:
                timestamp = datetime.fromtimestamp(timestamp_str / 1000)
        else:
            timestamp = datetime.now()

        return TeamsExportMessage(
            sender=str(sender),
            content=content.strip(),
            timestamp=timestamp,
            thread_id=item.get("replyToId") or item.get("threadId"),
        )

    except Exception as e:
        logger.warning(f"Failed to parse message: {e}")
        return None


def _parse_html_export(export_path: Path) -> list[TeamsExportMessage]:
    """Parse HTML format Teams export.

    Note: This is a basic parser. Real HTML exports may vary.
    """
    content = export_path.read_text(encoding="utf-8")

    # Very basic HTML message extraction
    # Real implementation would use BeautifulSoup or similar
    import re

    messages = []

    # Pattern for common Teams HTML export format
    # This is simplified and may need adjustment for actual exports
    message_pattern = r'<div class="message"[^>]*>.*?<span class="sender">([^<]+)</span>.*?<span class="time">([^<]+)</span>.*?<div class="content">([^<]+)</div>'

    for match in re.finditer(message_pattern, content, re.DOTALL):
        sender, time_str, msg_content = match.groups()

        try:
            timestamp = datetime.fromisoformat(time_str.strip())
        except ValueError:
            timestamp = datetime.now()

        messages.append(
            TeamsExportMessage(
                sender=sender.strip(),
                content=msg_content.strip(),
                timestamp=timestamp,
            )
        )

    return messages


async def import_teams_export(
    export_path: Path,
    api_url: str = "http://localhost:8000",
    project: str | None = None,
    topics: list[str] | None = None,
    source_ref: str | None = None,
) -> list[str]:
    """Import a Teams export file as fragments.

    Args:
        export_path: Path to the export file.
        api_url: URL of the Provenance API.
        project: Optional project name for fragments.
        topics: Optional topics for fragments.
        source_ref: Optional source reference (defaults to filename).

    Returns:
        List of created fragment IDs.
    """
    messages = parse_teams_export(export_path)

    if not messages:
        logger.warning("No messages found in export")
        return []

    logger.info(f"Parsed {len(messages)} messages from export")

    # Group messages by thread or create individual fragments
    fragment_ids = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for msg in messages:
            payload: dict[str, Any] = {
                "content": f"[{msg.sender}]: {msg.content}",
                "source_type": "teams",
                "source_ref": source_ref or export_path.name,
                "participants": [msg.sender],
                "captured_at": msg.timestamp.isoformat(),
            }

            if project:
                payload["project"] = project
            if topics:
                payload["topics"] = topics

            try:
                response = await client.post(
                    f"{api_url}/api/fragments",
                    json=payload,
                )

                if response.status_code == 201:
                    data = response.json()
                    fragment_id = str(data.get("id", "unknown"))
                    fragment_ids.append(fragment_id)
                    logger.debug(f"Created fragment {fragment_id}")
                else:
                    logger.error(f"API error: {response.status_code}")

            except Exception as e:
                logger.error(f"Failed to create fragment: {e}")

    logger.info(f"Created {len(fragment_ids)} fragments from export")
    return fragment_ids
