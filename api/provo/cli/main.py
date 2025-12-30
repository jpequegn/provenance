"""Provenance CLI - capture the why behind your decisions."""

import logging
import os
import re
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
import typer

from provo.capture import NotesWatcher, ParsedTranscript, TranscriptWatcher

# Default API base URL
DEFAULT_API_URL = "http://localhost:8000"

# Configure logging for watch command
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

# Icons for source types
SOURCE_ICONS: dict[str, str] = {
    "quick_capture": "📍",
    "zoom": "🎥",
    "teams": "💬",
    "notes": "📝",
}

app = typer.Typer(
    name="provo",
    help="Capture the why behind your decisions.",
    add_completion=False,
)


def get_api_url() -> str:
    """Get the API base URL from environment or default."""
    return os.environ.get("PROVO_API_URL", DEFAULT_API_URL)


@app.command()
def capture(
    content: Annotated[
        str,
        typer.Argument(help="The content to capture"),
    ],
    project: Annotated[
        str | None,
        typer.Option("-p", "--project", help="Project name for organization"),
    ] = None,
    topics: Annotated[
        list[str] | None,
        typer.Option("-t", "--topic", help="Topic tags (can be used multiple times)"),
    ] = None,
    link: Annotated[
        str | None,
        typer.Option("--link", help="Reference URL or identifier"),
    ] = None,
) -> None:
    """Capture a context fragment.

    Examples:
        provo "chose Redis for sessions"
        provo -p billing -t architecture "separating payment service"
        provo --link https://github.com/... "this PR implements..."
    """
    api_url = get_api_url()

    # Build request payload
    payload: dict[str, str | list[str] | None] = {
        "content": content,
        "source_type": "quick_capture",
    }

    if project:
        payload["project"] = project
    if topics:
        payload["topics"] = topics
    if link:
        payload["source_ref"] = link

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{api_url}/api/fragments",
                json=payload,
            )

            if response.status_code == 201:
                data = response.json()
                fragment_id = data.get("id", "unknown")
                typer.echo(
                    typer.style("✓ ", fg=typer.colors.GREEN, bold=True)
                    + f"Captured! Fragment ID: {fragment_id}"
                )
                sys.exit(0)
            else:
                # Try to get error detail from response
                try:
                    error_data = response.json()
                    detail = error_data.get("detail", response.text)
                except Exception:
                    detail = response.text

                typer.echo(
                    typer.style("✗ ", fg=typer.colors.RED, bold=True)
                    + f"Failed to capture: {detail}",
                    err=True,
                )
                sys.exit(1)

    except httpx.ConnectError:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Cannot connect to API at {api_url}. Is the server running?",
            err=True,
        )
        sys.exit(1)
    except httpx.TimeoutException:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + "Request timed out. Please try again.",
            err=True,
        )
        sys.exit(1)
    except Exception as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Unexpected error: {e}",
            err=True,
        )
        sys.exit(1)


def format_source_type(source_type: str) -> str:
    """Format source type with icon and label."""
    icon = SOURCE_ICONS.get(source_type, "📄")
    label = source_type.replace("_", " ").title()
    return f"{icon} {label}"


def format_date(date_str: str) -> str:
    """Format ISO date string to readable date."""
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return date_str[:10] if date_str else "Unknown"


def format_score(score: float) -> str:
    """Format score with color based on relevance."""
    score_str = f"{score:.2f}"
    if score >= 0.8:
        return typer.style(score_str, fg=typer.colors.GREEN, bold=True)
    elif score >= 0.5:
        return typer.style(score_str, fg=typer.colors.YELLOW)
    else:
        return typer.style(score_str, fg=typer.colors.WHITE)


def truncate_content(content: str, max_length: int = 80) -> str:
    """Truncate content to max length with ellipsis."""
    content = content.replace("\n", " ").strip()
    if len(content) <= max_length:
        return content
    return content[: max_length - 3] + "..."


def format_result(result: dict[str, Any]) -> str:
    """Format a single search result for display."""
    source_type = result.get("source_type", "unknown")
    captured_at = result.get("captured_at", "")
    score = result.get("score", 0.0)
    content = result.get("content", "")

    # Build header line: icon + source type • date • Score: X.XX
    header = (
        f"{format_source_type(source_type)} • "
        f"{format_date(captured_at)} • "
        f"Score: {format_score(score)}"
    )

    # Content line with indent and quotes
    content_line = f'   "{truncate_content(content)}"'

    return f"{header}\n{content_line}"


@app.command()
def search(
    query: Annotated[
        str,
        typer.Argument(help="Natural language search query"),
    ],
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Maximum number of results"),
    ] = 10,
    project: Annotated[
        str | None,
        typer.Option("-p", "--project", help="Filter by project name"),
    ] = None,
) -> None:
    """Search for context fragments by semantic similarity.

    Examples:
        provo search "why did we choose postgres"
        provo search "authentication" --limit 5
        provo search -p billing "payment decisions"
    """
    api_url = get_api_url()

    # Build query parameters
    params: dict[str, str | int] = {"q": query, "limit": limit}
    if project:
        params["project"] = project

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{api_url}/api/search",
                params=params,
            )

            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])

                if not results:
                    typer.echo(
                        typer.style("No results found", fg=typer.colors.YELLOW)
                        + f' for "{query}"'
                    )
                    sys.exit(0)

                # Header
                result_count = len(results)
                typer.echo(
                    f'\nFound {typer.style(str(result_count), bold=True)} '
                    f'result{"s" if result_count != 1 else ""} for "{query}":\n'
                )

                # Display each result
                for result in results:
                    typer.echo(format_result(result))
                    typer.echo()  # Blank line between results

                sys.exit(0)
            else:
                # Try to get error detail from response
                try:
                    error_data = response.json()
                    detail = error_data.get("detail", response.text)
                except Exception:
                    detail = response.text

                typer.echo(
                    typer.style("✗ ", fg=typer.colors.RED, bold=True)
                    + f"Search failed: {detail}",
                    err=True,
                )
                sys.exit(1)

    except httpx.ConnectError:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Cannot connect to API at {api_url}. Is the server running?",
            err=True,
        )
        sys.exit(1)
    except httpx.TimeoutException:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + "Request timed out. Please try again.",
            err=True,
        )
        sys.exit(1)
    except Exception as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Unexpected error: {e}",
            err=True,
        )
        sys.exit(1)


# Icons for link types
LINK_ICONS: dict[str, str] = {
    "relates_to": "🔗",
    "references": "📎",
    "follows": "➡️",
    "contradicts": "⚡",
    "invalidates": "❌",
}


def format_strength(strength: float) -> str:
    """Format link strength with color based on value."""
    strength_str = f"{strength:.2f}"
    if strength >= 0.9:
        return typer.style(strength_str, fg=typer.colors.GREEN, bold=True)
    elif strength >= 0.8:
        return typer.style(strength_str, fg=typer.colors.GREEN)
    elif strength >= 0.75:
        return typer.style(strength_str, fg=typer.colors.YELLOW)
    else:
        return typer.style(strength_str, fg=typer.colors.WHITE)


def format_related(result: dict[str, Any]) -> str:
    """Format a single related fragment for display."""
    source_type = result.get("source_type", "unknown")
    captured_at = result.get("captured_at", "")
    strength = result.get("strength", 0.0)
    content = result.get("content", "")
    link_type = result.get("link_type", "relates_to")

    # Build header line: link icon + source icon + source type • date • Strength: X.XX
    link_icon = LINK_ICONS.get(link_type, "🔗")
    header = (
        f"{link_icon} {format_source_type(source_type)} • "
        f"{format_date(captured_at)} • "
        f"Strength: {format_strength(strength)}"
    )

    # Content line with indent and quotes
    content_line = f'   "{truncate_content(content)}"'

    return f"{header}\n{content_line}"


@app.command()
def related(
    fragment_id: Annotated[
        str,
        typer.Argument(help="Fragment ID to find related content for"),
    ],
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Maximum number of results"),
    ] = 10,
    link_type: Annotated[
        str | None,
        typer.Option("--type", "-t", help="Filter by link type (relates_to, references, etc.)"),
    ] = None,
) -> None:
    """Show fragments related to a given fragment.

    Displays fragments that are semantically similar or otherwise linked
    to the specified fragment.

    Examples:
        provo related abc123-def456-...
        provo related abc123 --limit 5
        provo related abc123 --type relates_to
    """
    api_url = get_api_url()

    # Build query parameters
    params: dict[str, str | int] = {"limit": limit}
    if link_type:
        params["link_type"] = link_type

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{api_url}/api/fragments/{fragment_id}/related",
                params=params,
            )

            if response.status_code == 200:
                data = response.json()
                results = data.get("related", [])

                if not results:
                    typer.echo(
                        typer.style("No related fragments found", fg=typer.colors.YELLOW)
                        + f" for fragment {fragment_id[:8]}..."
                    )
                    sys.exit(0)

                # Header
                result_count = len(results)
                typer.echo(
                    f'\nFound {typer.style(str(result_count), bold=True)} '
                    f'related fragment{"s" if result_count != 1 else ""}:\n'
                )

                # Display each result
                for result in results:
                    typer.echo(format_related(result))
                    typer.echo()  # Blank line between results

                sys.exit(0)

            elif response.status_code == 404:
                typer.echo(
                    typer.style("✗ ", fg=typer.colors.RED, bold=True)
                    + f"Fragment not found: {fragment_id}",
                    err=True,
                )
                sys.exit(1)

            elif response.status_code == 400:
                try:
                    error_data = response.json()
                    detail = error_data.get("detail", response.text)
                except Exception:
                    detail = response.text
                typer.echo(
                    typer.style("✗ ", fg=typer.colors.RED, bold=True)
                    + f"Invalid request: {detail}",
                    err=True,
                )
                sys.exit(1)

            else:
                try:
                    error_data = response.json()
                    detail = error_data.get("detail", response.text)
                except Exception:
                    detail = response.text

                typer.echo(
                    typer.style("✗ ", fg=typer.colors.RED, bold=True)
                    + f"Request failed: {detail}",
                    err=True,
                )
                sys.exit(1)

    except httpx.ConnectError:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Cannot connect to API at {api_url}. Is the server running?",
            err=True,
        )
        sys.exit(1)
    except httpx.TimeoutException:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + "Request timed out. Please try again.",
            err=True,
        )
        sys.exit(1)
    except Exception as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Unexpected error: {e}",
            err=True,
        )
        sys.exit(1)


def parse_period(period: str) -> datetime | None:
    """Parse a period string like '7d', '30d', '2w' into a datetime.

    Returns the datetime representing the start of the period (now - duration).
    Returns None if the period string is invalid.

    Supported formats:
        - Nd: N days (e.g., '7d', '30d')
        - Nw: N weeks (e.g., '2w', '4w')
        - Nm: N months (approximate, 30 days each) (e.g., '1m', '3m')
    """
    pattern = r"^(\d+)([dwm])$"
    match = re.match(pattern, period.lower())
    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "d":
        delta = timedelta(days=value)
    elif unit == "w":
        delta = timedelta(weeks=value)
    elif unit == "m":
        delta = timedelta(days=value * 30)  # Approximate month
    else:
        return None

    return datetime.now() - delta


def format_confidence(confidence: float) -> str:
    """Format confidence score with color based on value."""
    confidence_str = f"{confidence:.2f}"
    if confidence >= 0.9:
        return typer.style(confidence_str, fg=typer.colors.GREEN, bold=True)
    elif confidence >= 0.7:
        return typer.style(confidence_str, fg=typer.colors.GREEN)
    elif confidence >= 0.5:
        return typer.style(confidence_str, fg=typer.colors.YELLOW)
    else:
        return typer.style(confidence_str, fg=typer.colors.WHITE)


def format_decision(decision: dict[str, Any]) -> str:
    """Format a single decision for display."""
    what = decision.get("what", "")
    why = decision.get("why", "")
    confidence = decision.get("confidence", 0.0)
    created_at = decision.get("created_at", "")

    # Header: checkmark + decision + date + confidence
    header = (
        typer.style("✓ ", fg=typer.colors.GREEN, bold=True)
        + f"{truncate_content(what, 60)} • "
        + f"{format_date(created_at)} • "
        + f"{format_confidence(confidence)} confidence"
    )

    # Reason line if available
    if why:
        reason_line = f"  Because: {truncate_content(why, 70)}"
        return f"{header}\n{reason_line}"

    return header


def format_assumption(assumption: dict[str, Any]) -> str:
    """Format a single assumption for display."""
    statement = assumption.get("statement", "")
    still_valid = assumption.get("still_valid")
    explicit = assumption.get("explicit", True)
    created_at = assumption.get("created_at", "")

    # Status icon
    if still_valid is False:
        icon = typer.style("✗ ", fg=typer.colors.RED, bold=True)
        status = typer.style("[INVALID]", fg=typer.colors.RED)
    elif still_valid is True:
        icon = typer.style("✓ ", fg=typer.colors.GREEN, bold=True)
        status = typer.style("[VALID]", fg=typer.colors.GREEN)
    else:
        icon = typer.style("? ", fg=typer.colors.YELLOW, bold=True)
        status = typer.style("[UNCHECKED]", fg=typer.colors.YELLOW)

    # Type indicator
    type_indicator = "explicit" if explicit else "implicit"

    # Header: icon + statement + date + status
    header = (
        f"{icon}{truncate_content(statement, 60)} • "
        + f"{format_date(created_at)} • "
        + f"{type_indicator} {status}"
    )

    return header


@app.command()
def decisions(
    project: Annotated[
        str | None,
        typer.Option("-p", "--project", help="Filter by project name"),
    ] = None,
    last: Annotated[
        str | None,
        typer.Option("--last", help="Filter by time period (e.g., 7d, 30d, 2w)"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Maximum number of results"),
    ] = 20,
) -> None:
    """List decisions with optional filtering.

    Examples:
        provo decisions
        provo decisions --project billing --last 7d
        provo decisions -p auth --limit 5
    """
    api_url = get_api_url()

    # Build query parameters
    params: dict[str, str | int] = {"limit": limit}
    if project:
        params["project"] = project

    # Parse --last period
    if last:
        since_dt = parse_period(last)
        if since_dt is None:
            typer.echo(
                typer.style("✗ ", fg=typer.colors.RED, bold=True)
                + f"Invalid period format: {last}. Use formats like 7d, 30d, 2w, 1m",
                err=True,
            )
            sys.exit(1)
        params["since"] = since_dt.isoformat()

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{api_url}/api/decisions",
                params=params,
            )

            if response.status_code == 200:
                results = response.json()

                if not results:
                    msg = "No decisions found"
                    if project:
                        msg += f" for project '{project}'"
                    if last:
                        msg += f" in the last {last}"
                    typer.echo(typer.style(msg, fg=typer.colors.YELLOW))
                    sys.exit(0)

                # Header
                header = "Decisions"
                if last:
                    header += f" (last {last})"
                header += ":"

                typer.echo(f"\n{typer.style(header, bold=True)}\n")

                # Display each decision
                for decision in results:
                    typer.echo(format_decision(decision))
                    typer.echo()  # Blank line between results

                sys.exit(0)
            else:
                try:
                    error_data = response.json()
                    detail = error_data.get("detail", response.text)
                except Exception:
                    detail = response.text

                typer.echo(
                    typer.style("✗ ", fg=typer.colors.RED, bold=True)
                    + f"Request failed: {detail}",
                    err=True,
                )
                sys.exit(1)

    except httpx.ConnectError:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Cannot connect to API at {api_url}. Is the server running?",
            err=True,
        )
        sys.exit(1)
    except httpx.TimeoutException:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + "Request timed out. Please try again.",
            err=True,
        )
        sys.exit(1)
    except Exception as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Unexpected error: {e}",
            err=True,
        )
        sys.exit(1)


@app.command()
def assumptions(
    project: Annotated[
        str | None,
        typer.Option("-p", "--project", help="Filter by project name"),
    ] = None,
    last: Annotated[
        str | None,
        typer.Option("--last", help="Filter by time period (e.g., 7d, 30d, 2w)"),
    ] = None,
    invalid: Annotated[
        bool,
        typer.Option("--invalid", help="Show only invalid assumptions"),
    ] = False,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Maximum number of results"),
    ] = 20,
) -> None:
    """List assumptions with optional filtering.

    Examples:
        provo assumptions
        provo assumptions --project auth
        provo assumptions --invalid
        provo assumptions -p billing --last 30d
    """
    api_url = get_api_url()

    # Build query parameters
    params: dict[str, str | int | bool] = {"limit": limit}
    if project:
        params["project"] = project
    if invalid:
        params["still_valid"] = False

    # Parse --last period
    if last:
        since_dt = parse_period(last)
        if since_dt is None:
            typer.echo(
                typer.style("✗ ", fg=typer.colors.RED, bold=True)
                + f"Invalid period format: {last}. Use formats like 7d, 30d, 2w, 1m",
                err=True,
            )
            sys.exit(1)
        params["since"] = since_dt.isoformat()

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{api_url}/api/assumptions",
                params=params,
            )

            if response.status_code == 200:
                results = response.json()

                if not results:
                    msg = "No assumptions found"
                    if project:
                        msg += f" for project '{project}'"
                    if last:
                        msg += f" in the last {last}"
                    if invalid:
                        msg += " (invalid only)"
                    typer.echo(typer.style(msg, fg=typer.colors.YELLOW))
                    sys.exit(0)

                # Header
                header = "Assumptions"
                if invalid:
                    header += " (invalid only)"
                elif last:
                    header += f" (last {last})"
                header += ":"

                typer.echo(f"\n{typer.style(header, bold=True)}\n")

                # Display each assumption
                for assumption in results:
                    typer.echo(format_assumption(assumption))
                    typer.echo()  # Blank line between results

                sys.exit(0)
            else:
                try:
                    error_data = response.json()
                    detail = error_data.get("detail", response.text)
                except Exception:
                    detail = response.text

                typer.echo(
                    typer.style("✗ ", fg=typer.colors.RED, bold=True)
                    + f"Request failed: {detail}",
                    err=True,
                )
                sys.exit(1)

    except httpx.ConnectError:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Cannot connect to API at {api_url}. Is the server running?",
            err=True,
        )
        sys.exit(1)
    except httpx.TimeoutException:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + "Request timed out. Please try again.",
            err=True,
        )
        sys.exit(1)
    except Exception as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Unexpected error: {e}",
            err=True,
        )
        sys.exit(1)


def send_to_api(
    transcript: ParsedTranscript,
    source_type: Literal["zoom", "teams", "notes"],
    api_url: str,
    project: str | None = None,
    topics: list[str] | None = None,
) -> str | None:
    """Send a parsed transcript to the API.

    Returns the fragment ID on success, None on failure.
    """
    payload: dict[str, Any] = {
        "content": transcript.content,
        "source_type": source_type,
        "participants": transcript.participants,
    }

    # Use project from frontmatter if available, otherwise use CLI arg
    effective_project = transcript.project or project
    if effective_project:
        payload["project"] = effective_project

    # Use topics from frontmatter if available, otherwise use CLI arg
    effective_topics = transcript.topics or topics or []
    if effective_topics:
        payload["topics"] = effective_topics

    if transcript.source_file:
        payload["source_ref"] = transcript.source_file

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{api_url}/api/fragments",
                json=payload,
            )

            if response.status_code == 201:
                data = response.json()
                return str(data.get("id", "unknown"))
            else:
                logging.error(f"API error: {response.status_code} - {response.text}")
                return None

    except Exception as e:
        logging.error(f"Failed to send to API: {e}")
        return None


@app.command()
def watch(
    path: Annotated[
        Path,
        typer.Argument(help="Directory to watch for transcript files"),
    ],
    source_type: Annotated[
        str,
        typer.Option(
            "--type",
            "-t",
            help="Type of transcripts (zoom, teams, notes)",
        ),
    ] = "zoom",
    project: Annotated[
        str | None,
        typer.Option("-p", "--project", help="Project name for all captured fragments"),
    ] = None,
    process_existing: Annotated[
        bool,
        typer.Option(
            "--process-existing",
            help="Process existing unprocessed files on startup",
        ),
    ] = True,
    recursive: Annotated[
        bool,
        typer.Option(
            "--recursive",
            "-r",
            help="Watch subdirectories recursively (only for notes type)",
        ),
    ] = True,
) -> None:
    """Watch a directory for new transcript files.

    For zoom/teams: processes VTT and TXT files.
    For notes: processes markdown files with frontmatter support.

    Examples:
        provo watch ~/Zoom --type zoom
        provo watch ~/Meetings -t teams -p billing
        provo watch ~/Notes -t notes --recursive
        provo watch ./transcripts --process-existing
    """
    # Validate source type
    valid_types = {"zoom", "teams", "notes"}
    if source_type not in valid_types:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Invalid source type: {source_type}. Must be one of: {', '.join(valid_types)}",
            err=True,
        )
        sys.exit(1)

    # Validate path
    if not path.exists():
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Path does not exist: {path}",
            err=True,
        )
        sys.exit(1)

    if not path.is_dir():
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Path is not a directory: {path}",
            err=True,
        )
        sys.exit(1)

    api_url = get_api_url()

    # Track statistics
    stats = {"processed": 0, "failed": 0}

    def on_transcript(
        transcript: ParsedTranscript,
        src_type: Literal["zoom", "teams", "notes"],
    ) -> None:
        """Handle a new transcript."""
        file_name = Path(transcript.source_file or "unknown").name
        typer.echo(
            typer.style("📄 ", bold=True)
            + f"Processing: {file_name}"
        )

        fragment_id = send_to_api(transcript, src_type, api_url, project)

        if fragment_id:
            stats["processed"] += 1
            typer.echo(
                typer.style("✓ ", fg=typer.colors.GREEN, bold=True)
                + f"Captured! Fragment ID: {fragment_id}"
            )
        else:
            stats["failed"] += 1
            typer.echo(
                typer.style("✗ ", fg=typer.colors.RED, bold=True)
                + "Failed to capture. Check API connection.",
                err=True,
            )

    # Create appropriate watcher based on source type
    source_type_literal: Literal["zoom", "teams", "notes"] = source_type  # type: ignore[assignment]

    if source_type == "notes":
        watcher: TranscriptWatcher | NotesWatcher = NotesWatcher(
            watch_path=path,
            callback=on_transcript,
            recursive=recursive,
        )
        file_types = "markdown notes"
    else:
        watcher = TranscriptWatcher(
            watch_path=path,
            source_type=source_type_literal,
            callback=on_transcript,
        )
        file_types = "VTT/TXT transcripts"

    # Handle Ctrl+C gracefully
    stop_requested = False

    def signal_handler(signum: int, frame: object) -> None:
        nonlocal stop_requested
        if stop_requested:
            # Force exit on second Ctrl+C
            sys.exit(1)
        stop_requested = True
        typer.echo("\n" + typer.style("Stopping watcher...", fg=typer.colors.YELLOW))
        watcher.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start watching
    typer.echo(
        typer.style("👁️  ", bold=True)
        + f"Watching {path} for {file_types}"
    )
    if source_type == "notes":
        typer.echo(f"   Recursive: {recursive}")
    if project:
        typer.echo(f"   Project: {project}")
    typer.echo(f"   API: {api_url}")
    typer.echo("   Press Ctrl+C to stop\n")

    try:
        watcher.start()

        # Process existing files if requested
        if process_existing:
            existing_count = watcher.process_existing()
            if existing_count > 0:
                typer.echo(
                    typer.style("ℹ️  ", bold=True)
                    + f"Processed {existing_count} existing file(s)\n"
                )

        # Keep running until stopped
        while watcher.is_running() and not stop_requested:
            signal.pause()

    except Exception as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Watcher error: {e}",
            err=True,
        )
        sys.exit(1)

    finally:
        watcher.stop()

    # Print summary
    typer.echo(
        f"\n{typer.style('Summary:', bold=True)} "
        f"Processed {stats['processed']}, Failed {stats['failed']}"
    )


@app.command()
def serve(
    api_port: Annotated[
        int,
        typer.Option("--api-port", help="Port for the API server"),
    ] = 8000,
    ui_port: Annotated[
        int,
        typer.Option("--ui-port", help="Port for the web UI"),
    ] = 3000,
    api_only: Annotated[
        bool,
        typer.Option("--api-only", help="Only start the API server"),
    ] = False,
    ui_only: Annotated[
        bool,
        typer.Option("--ui-only", help="Only start the web UI (requires API running)"),
    ] = False,
) -> None:
    """Start the Provenance servers.

    By default, starts both the API server and the web UI.
    The web UI proxies API requests to the API server.

    Examples:
        provo serve                    # Start both API and UI
        provo serve --api-only         # Start only the API
        provo serve --ui-only          # Start only the UI (requires API)
        provo serve --api-port 9000    # Use custom API port
    """
    import subprocess
    import time

    # Find the web directory relative to this file
    # The structure is: api/provo/cli/main.py -> web/
    api_dir = Path(__file__).parent.parent.parent.parent
    web_dir = api_dir.parent / "web"

    if not web_dir.exists():
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Web directory not found at {web_dir}",
            err=True,
        )
        sys.exit(1)

    processes: list[subprocess.Popen] = []
    stop_requested = False

    def signal_handler(signum: int, frame: object) -> None:
        nonlocal stop_requested
        if stop_requested:
            sys.exit(1)
        stop_requested = True
        typer.echo("\n" + typer.style("Stopping servers...", fg=typer.colors.YELLOW))
        for proc in processes:
            proc.terminate()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start API server
    if not ui_only:
        typer.echo(
            typer.style("🚀 ", bold=True)
            + f"Starting API server on http://localhost:{api_port}"
        )
        api_proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                "provo.api.main:app",
                "--host", "0.0.0.0",
                "--port", str(api_port),
                "--reload",
            ],
            cwd=str(api_dir),
        )
        processes.append(api_proc)

        # Wait a bit for API to start
        time.sleep(2)

    # Start web UI
    if not api_only:
        # Check if npm/node is available
        try:
            subprocess.run(["npm", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            typer.echo(
                typer.style("✗ ", fg=typer.colors.RED, bold=True)
                + "npm not found. Please install Node.js to use the web UI.",
                err=True,
            )
            if processes:
                processes[0].terminate()
            sys.exit(1)

        # Check if dependencies are installed
        node_modules = web_dir / "node_modules"
        if not node_modules.exists():
            typer.echo(
                typer.style("📦 ", bold=True)
                + "Installing web UI dependencies..."
            )
            result = subprocess.run(
                ["npm", "install"],
                cwd=str(web_dir),
                capture_output=True,
            )
            if result.returncode != 0:
                typer.echo(
                    typer.style("✗ ", fg=typer.colors.RED, bold=True)
                    + "Failed to install dependencies",
                    err=True,
                )
                if processes:
                    processes[0].terminate()
                sys.exit(1)

        typer.echo(
            typer.style("🌐 ", bold=True)
            + f"Starting web UI on http://localhost:{ui_port}"
        )

        # Set environment variable for API URL if using non-default port
        env = os.environ.copy()
        if api_port != 8000:
            env["VITE_API_URL"] = f"http://localhost:{api_port}"

        ui_proc = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(ui_port)],
            cwd=str(web_dir),
            env=env,
        )
        processes.append(ui_proc)

    typer.echo(
        "\n" + typer.style("Ready! ", fg=typer.colors.GREEN, bold=True)
        + "Press Ctrl+C to stop\n"
    )

    # Wait for processes
    try:
        while not stop_requested:
            for proc in processes:
                if proc.poll() is not None:
                    typer.echo(
                        typer.style("⚠️  ", fg=typer.colors.YELLOW)
                        + "A server process exited unexpectedly"
                    )
                    stop_requested = True
                    break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for proc in processes:
            proc.terminate()
            proc.wait(timeout=5)


# Teams subcommand group
teams_app = typer.Typer(
    name="teams",
    help="Microsoft Teams integration commands.",
)
app.add_typer(teams_app, name="teams")


def get_teams_config():
    """Get Teams configuration from environment."""
    from provo.integrations import TeamsConfig

    # Default token and state files
    config_dir = Path.home() / ".provo"
    token_file = config_dir / "teams_token.json"

    return TeamsConfig.from_env(token_file=token_file)


def get_teams_state_file() -> Path:
    """Get path to Teams poller state file."""
    return Path.home() / ".provo" / "teams_state.json"


@teams_app.command("login")
def teams_login() -> None:
    """Authenticate with Microsoft Teams.

    Opens a browser for OAuth2 authentication. Requires environment variables:
        TEAMS_CLIENT_ID: Azure AD application client ID
        TEAMS_CLIENT_SECRET: Azure AD application client secret (optional)
        TEAMS_TENANT_ID: Azure AD tenant ID (default: common)

    Example:
        export TEAMS_CLIENT_ID=your-app-id
        provo teams login
    """
    import asyncio
    from provo.integrations import TeamsClient

    try:
        config = get_teams_config()
    except ValueError as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + str(e),
            err=True,
        )
        typer.echo(
            "\nSet the required environment variables:\n"
            "  export TEAMS_CLIENT_ID=your-app-id\n"
            "  export TEAMS_CLIENT_SECRET=your-secret  # optional\n"
            "  export TEAMS_TENANT_ID=your-tenant-id   # optional, default: common"
        )
        sys.exit(1)

    client = TeamsClient(config)

    if client.is_authenticated:
        typer.echo(
            typer.style("✓ ", fg=typer.colors.GREEN, bold=True)
            + "Already authenticated with Teams"
        )
        if typer.confirm("Re-authenticate?", default=False):
            client.logout()
        else:
            sys.exit(0)

    typer.echo("Opening browser for Teams authentication...")
    typer.echo(
        typer.style("ℹ ", fg=typer.colors.BLUE, bold=True)
        + "Sign in with your Microsoft account and grant permissions."
    )

    async def do_auth() -> bool:
        return await client.authenticate_with_browser(timeout=120)

    try:
        success = asyncio.run(do_auth())
    except Exception as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Authentication failed: {e}",
            err=True,
        )
        sys.exit(1)

    if success:
        typer.echo(
            typer.style("✓ ", fg=typer.colors.GREEN, bold=True)
            + "Successfully authenticated with Microsoft Teams!"
        )
        sys.exit(0)
    else:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + "Authentication failed or timed out",
            err=True,
        )
        sys.exit(1)


@teams_app.command("logout")
def teams_logout() -> None:
    """Clear Teams authentication."""
    from provo.integrations import TeamsClient

    try:
        config = get_teams_config()
        client = TeamsClient(config)
        client.logout()
        typer.echo(
            typer.style("✓ ", fg=typer.colors.GREEN, bold=True)
            + "Logged out of Microsoft Teams"
        )
    except ValueError:
        typer.echo(
            typer.style("ℹ ", fg=typer.colors.BLUE)
            + "No Teams authentication to clear"
        )


@teams_app.command("status")
def teams_status() -> None:
    """Check Teams authentication status."""
    from provo.integrations import TeamsClient

    try:
        config = get_teams_config()
    except ValueError as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.YELLOW)
            + f"Teams not configured: {e}"
        )
        sys.exit(1)

    client = TeamsClient(config)

    if client.is_authenticated:
        typer.echo(
            typer.style("✓ ", fg=typer.colors.GREEN, bold=True)
            + "Authenticated with Microsoft Teams"
        )
    else:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED)
            + "Not authenticated. Run 'provo teams login' to authenticate."
        )


@teams_app.command("teams")
def teams_list_teams() -> None:
    """List all Teams you are a member of."""
    import asyncio
    from provo.integrations import TeamsClient

    try:
        config = get_teams_config()
    except ValueError as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True) + str(e),
            err=True,
        )
        sys.exit(1)

    client = TeamsClient(config)

    if not client.is_authenticated:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED)
            + "Not authenticated. Run 'provo teams login' first.",
            err=True,
        )
        sys.exit(1)

    async def list_teams() -> list[dict[str, str]]:
        return await client.list_teams()

    try:
        teams = asyncio.run(list_teams())
    except Exception as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Failed to list teams: {e}",
            err=True,
        )
        sys.exit(1)

    if not teams:
        typer.echo(typer.style("No teams found", fg=typer.colors.YELLOW))
        sys.exit(0)

    typer.echo(f"\n{typer.style('Your Teams:', bold=True)}\n")

    for team in teams:
        typer.echo(
            f"  💬 {typer.style(team['name'], bold=True)}"
        )
        if team.get("description"):
            typer.echo(f"     {team['description'][:60]}...")
        typer.echo(f"     ID: {team['id']}")
        typer.echo()


@teams_app.command("channels")
def teams_list_channels(
    team_id: Annotated[
        str,
        typer.Argument(help="Team ID (from 'provo teams teams')"),
    ],
) -> None:
    """List channels in a Team."""
    import asyncio
    from provo.integrations import TeamsClient

    try:
        config = get_teams_config()
    except ValueError as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True) + str(e),
            err=True,
        )
        sys.exit(1)

    client = TeamsClient(config)

    if not client.is_authenticated:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED)
            + "Not authenticated. Run 'provo teams login' first.",
            err=True,
        )
        sys.exit(1)

    async def list_channels() -> list:
        return await client.list_channels(team_id)

    try:
        channels = asyncio.run(list_channels())
    except Exception as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Failed to list channels: {e}",
            err=True,
        )
        sys.exit(1)

    if not channels:
        typer.echo(typer.style("No channels found", fg=typer.colors.YELLOW))
        sys.exit(0)

    typer.echo(f"\n{typer.style(f'Channels in {channels[0].team_name}:', bold=True)}\n")

    for channel in channels:
        typer.echo(
            f"  📢 {typer.style(channel.name, bold=True)}"
        )
        if channel.description:
            typer.echo(f"     {channel.description[:60]}...")
        typer.echo(f"     ID: {channel.id}")
        typer.echo()


@teams_app.command("add")
def teams_add_channel(
    team_id: Annotated[
        str,
        typer.Argument(help="Team ID"),
    ],
    channel_id: Annotated[
        str,
        typer.Argument(help="Channel ID"),
    ],
    project: Annotated[
        str | None,
        typer.Option("-p", "--project", help="Project name for fragments"),
    ] = None,
    topics: Annotated[
        list[str] | None,
        typer.Option("-t", "--topic", help="Default topics for fragments"),
    ] = None,
) -> None:
    """Add a channel to monitor for messages.

    Example:
        provo teams add TEAM_ID CHANNEL_ID -p my-project -t meetings
    """
    import asyncio
    from provo.integrations import TeamsClient, TeamsPoller

    try:
        config = get_teams_config()
    except ValueError as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True) + str(e),
            err=True,
        )
        sys.exit(1)

    client = TeamsClient(config)

    if not client.is_authenticated:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED)
            + "Not authenticated. Run 'provo teams login' first.",
            err=True,
        )
        sys.exit(1)

    # Get team and channel info
    async def get_info() -> tuple:
        channels = await client.list_channels(team_id)
        for ch in channels:
            if ch.id == channel_id:
                return ch.team_name, ch.name
        raise ValueError(f"Channel {channel_id} not found in team")

    try:
        team_name, channel_name = asyncio.run(get_info())
    except Exception as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Failed to get channel info: {e}",
            err=True,
        )
        sys.exit(1)

    # Add to poller
    poller = TeamsPoller(
        client=client,
        state_file=get_teams_state_file(),
    )

    poller.add_channel(
        team_id=team_id,
        team_name=team_name,
        channel_id=channel_id,
        channel_name=channel_name,
        project=project,
        topics=topics or [],
    )

    typer.echo(
        typer.style("✓ ", fg=typer.colors.GREEN, bold=True)
        + f"Added channel: {team_name}/{channel_name}"
    )
    if project:
        typer.echo(f"  Project: {project}")
    if topics:
        typer.echo(f"  Topics: {', '.join(topics)}")


@teams_app.command("remove")
def teams_remove_channel(
    channel_id: Annotated[
        str,
        typer.Argument(help="Channel ID to remove"),
    ],
) -> None:
    """Remove a channel from monitoring."""
    from provo.integrations import TeamsClient, TeamsPoller

    try:
        config = get_teams_config()
    except ValueError as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True) + str(e),
            err=True,
        )
        sys.exit(1)

    client = TeamsClient(config)
    poller = TeamsPoller(
        client=client,
        state_file=get_teams_state_file(),
    )

    if poller.remove_channel(channel_id):
        typer.echo(
            typer.style("✓ ", fg=typer.colors.GREEN, bold=True)
            + "Channel removed from monitoring"
        )
    else:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.YELLOW)
            + "Channel not found in monitored list"
        )


@teams_app.command("list")
def teams_list_monitored() -> None:
    """List channels being monitored."""
    from provo.integrations import TeamsClient, TeamsPoller

    try:
        config = get_teams_config()
    except ValueError as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True) + str(e),
            err=True,
        )
        sys.exit(1)

    client = TeamsClient(config)
    poller = TeamsPoller(
        client=client,
        state_file=get_teams_state_file(),
    )

    channels = poller.monitored_channels

    if not channels:
        typer.echo(
            typer.style("No channels being monitored", fg=typer.colors.YELLOW)
        )
        typer.echo("\nAdd channels with: provo teams add TEAM_ID CHANNEL_ID")
        sys.exit(0)

    typer.echo(f"\n{typer.style('Monitored Channels:', bold=True)}\n")

    for channel in channels:
        typer.echo(
            f"  📢 {typer.style(channel.team_name, bold=True)}/{channel.channel_name}"
        )
        if channel.project:
            typer.echo(f"     Project: {channel.project}")
        if channel.topics:
            typer.echo(f"     Topics: {', '.join(channel.topics)}")
        typer.echo(f"     Channel ID: {channel.channel_id}")
        typer.echo()


@teams_app.command("import")
def teams_import(
    export_file: Annotated[
        Path,
        typer.Argument(help="Path to Teams export file (JSON or HTML)"),
    ],
    project: Annotated[
        str | None,
        typer.Option("-p", "--project", help="Project name for fragments"),
    ] = None,
    topics: Annotated[
        list[str] | None,
        typer.Option("-t", "--topic", help="Topics for fragments"),
    ] = None,
) -> None:
    """Import a Teams export file as fragments.

    Alternative to Graph API integration. Export your Teams chat history
    and import it directly.

    Example:
        provo teams import chat_export.json -p my-project
    """
    import asyncio
    from provo.integrations.teams_import import import_teams_export

    if not export_file.exists():
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"File not found: {export_file}",
            err=True,
        )
        sys.exit(1)

    api_url = get_api_url()

    typer.echo(f"Importing Teams export from {export_file}...")

    async def do_import() -> list[str]:
        return await import_teams_export(
            export_path=export_file,
            api_url=api_url,
            project=project,
            topics=topics or [],
        )

    try:
        fragment_ids = asyncio.run(do_import())
    except Exception as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True)
            + f"Import failed: {e}",
            err=True,
        )
        sys.exit(1)

    if fragment_ids:
        typer.echo(
            typer.style("✓ ", fg=typer.colors.GREEN, bold=True)
            + f"Imported {len(fragment_ids)} message(s) as fragments"
        )
    else:
        typer.echo(
            typer.style("⚠ ", fg=typer.colors.YELLOW)
            + "No messages found in export file"
        )


@teams_app.command("poll")
def teams_poll(
    interval: Annotated[
        int,
        typer.Option("--interval", "-i", help="Poll interval in seconds"),
    ] = 60,
    once: Annotated[
        bool,
        typer.Option("--once", help="Poll once and exit"),
    ] = False,
) -> None:
    """Poll Teams channels for new messages.

    Fetches messages from monitored channels and creates fragments.

    Examples:
        provo teams poll              # Poll continuously every 60s
        provo teams poll --once       # Poll once and exit
        provo teams poll -i 30        # Poll every 30 seconds
    """
    import asyncio
    from provo.integrations import TeamsClient, TeamsPoller

    try:
        config = get_teams_config()
    except ValueError as e:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED, bold=True) + str(e),
            err=True,
        )
        sys.exit(1)

    client = TeamsClient(config)

    if not client.is_authenticated:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.RED)
            + "Not authenticated. Run 'provo teams login' first.",
            err=True,
        )
        sys.exit(1)

    api_url = get_api_url()
    poller = TeamsPoller(
        client=client,
        api_url=api_url,
        state_file=get_teams_state_file(),
        poll_interval=interval,
    )

    if not poller.monitored_channels:
        typer.echo(
            typer.style("✗ ", fg=typer.colors.YELLOW)
            + "No channels configured for monitoring"
        )
        typer.echo("\nAdd channels with: provo teams add TEAM_ID CHANNEL_ID")
        sys.exit(1)

    if once:
        typer.echo("Polling Teams channels once...")

        async def do_poll() -> dict[str, int]:
            return await poller.poll_once()

        try:
            results = asyncio.run(do_poll())
            total = sum(results.values())
            typer.echo(
                typer.style("✓ ", fg=typer.colors.GREEN, bold=True)
                + f"Processed {total} message(s)"
            )
            for channel, count in results.items():
                if count > 0:
                    typer.echo(f"  {channel}: {count}")
        except Exception as e:
            typer.echo(
                typer.style("✗ ", fg=typer.colors.RED, bold=True)
                + f"Poll failed: {e}",
                err=True,
            )
            sys.exit(1)
    else:
        # Continuous polling
        typer.echo(
            typer.style("👁️  ", bold=True)
            + f"Polling {len(poller.monitored_channels)} channel(s) every {interval}s"
        )
        typer.echo(f"   API: {api_url}")
        typer.echo("   Press Ctrl+C to stop\n")

        stop_requested = False

        def signal_handler(signum: int, frame: object) -> None:
            nonlocal stop_requested
            if stop_requested:
                sys.exit(1)
            stop_requested = True
            typer.echo("\n" + typer.style("Stopping...", fg=typer.colors.YELLOW))
            poller.stop()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        async def run_poller() -> None:
            poller.start()
            while poller.is_running and not stop_requested:
                await asyncio.sleep(1)

        try:
            asyncio.run(run_poller())
        except Exception as e:
            typer.echo(
                typer.style("✗ ", fg=typer.colors.RED, bold=True)
                + f"Poller error: {e}",
                err=True,
            )
            sys.exit(1)


if __name__ == "__main__":
    app()
