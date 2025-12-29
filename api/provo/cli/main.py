"""Provenance CLI - capture the why behind your decisions."""

import logging
import os
import signal
import sys
from datetime import datetime
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


if __name__ == "__main__":
    app()
