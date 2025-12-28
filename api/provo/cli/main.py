"""Provenance CLI - capture the why behind your decisions."""

import os
import sys
from typing import Annotated

import httpx
import typer

# Default API base URL
DEFAULT_API_URL = "http://localhost:8000"

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


if __name__ == "__main__":
    app()
