"""Provenance CLI - capture the why behind your decisions."""

import os
import sys
from datetime import datetime
from typing import Annotated, Any

import httpx
import typer

# Default API base URL
DEFAULT_API_URL = "http://localhost:8000"

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


if __name__ == "__main__":
    app()
