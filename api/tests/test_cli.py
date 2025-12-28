"""Tests for the CLI commands."""

from unittest.mock import patch

import httpx
from typer.testing import CliRunner

from provo.cli.main import (
    app,
    format_date,
    format_result,
    format_score,
    format_source_type,
    get_api_url,
    truncate_content,
)

runner = CliRunner()


class TestGetApiUrl:
    """Tests for API URL configuration."""

    def test_default_url(self):
        """Test default API URL is used when env var not set."""
        with patch.dict("os.environ", {}, clear=True):
            url = get_api_url()
            assert url == "http://localhost:8000"

    def test_custom_url_from_env(self):
        """Test custom API URL from environment variable."""
        with patch.dict("os.environ", {"PROVO_API_URL": "http://custom:9000"}):
            url = get_api_url()
            assert url == "http://custom:9000"


class TestCaptureCommand:
    """Tests for the capture command."""

    def test_help_shows_usage(self):
        """Test that --help shows usage information."""
        result = runner.invoke(app, ["capture", "--help"])
        assert result.exit_code == 0
        assert "Capture a context fragment" in result.stdout
        assert "--project" in result.stdout
        assert "--topic" in result.stdout
        assert "--link" in result.stdout

    def test_missing_content_shows_error(self):
        """Test that missing content argument shows error."""
        result = runner.invoke(app, ["capture"])
        assert result.exit_code != 0
        assert "Missing argument" in result.stdout or "CONTENT" in result.stdout

    def test_successful_capture(self):
        """Test successful capture shows fragment ID."""
        mock_response = httpx.Response(
            status_code=201,
            json={"id": "abc-123-def", "content": "test content"},
        )

        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_response
            result = runner.invoke(app, ["capture", "test content"])

        assert result.exit_code == 0
        assert "Captured!" in result.stdout
        assert "abc-123-def" in result.stdout

    def test_capture_with_project(self):
        """Test capture with project flag."""
        mock_response = httpx.Response(
            status_code=201,
            json={"id": "abc-123", "content": "test"},
        )

        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.post.return_value = mock_response
            result = runner.invoke(app, ["capture", "-p", "billing", "test content"])

        assert result.exit_code == 0
        # Verify project was included in the request
        call_kwargs = mock_instance.post.call_args.kwargs
        assert call_kwargs["json"]["project"] == "billing"

    def test_capture_with_multiple_topics(self):
        """Test capture with multiple topic flags."""
        mock_response = httpx.Response(
            status_code=201,
            json={"id": "abc-123", "content": "test"},
        )

        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.post.return_value = mock_response
            result = runner.invoke(
                app, ["capture", "-t", "architecture", "-t", "database", "test content"]
            )

        assert result.exit_code == 0
        call_kwargs = mock_instance.post.call_args.kwargs
        assert call_kwargs["json"]["topics"] == ["architecture", "database"]

    def test_capture_with_link(self):
        """Test capture with link flag."""
        mock_response = httpx.Response(
            status_code=201,
            json={"id": "abc-123", "content": "test"},
        )

        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.post.return_value = mock_response
            result = runner.invoke(
                app, ["capture", "--link", "https://github.com/pr/123", "test content"]
            )

        assert result.exit_code == 0
        call_kwargs = mock_instance.post.call_args.kwargs
        assert call_kwargs["json"]["source_ref"] == "https://github.com/pr/123"

    def test_capture_with_all_flags(self):
        """Test capture with all flags combined."""
        mock_response = httpx.Response(
            status_code=201,
            json={"id": "full-test-123", "content": "test"},
        )

        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.post.return_value = mock_response
            result = runner.invoke(
                app,
                [
                    "capture",
                    "-p", "billing",
                    "-t", "architecture",
                    "-t", "performance",
                    "--link", "https://example.com",
                    "separating payment service",
                ],
            )

        assert result.exit_code == 0
        call_kwargs = mock_instance.post.call_args.kwargs
        payload = call_kwargs["json"]
        assert payload["content"] == "separating payment service"
        assert payload["project"] == "billing"
        assert payload["topics"] == ["architecture", "performance"]
        assert payload["source_ref"] == "https://example.com"


class TestCaptureErrorHandling:
    """Tests for capture error handling."""

    def test_connection_error_shows_message(self):
        """Test connection error shows helpful message."""
        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.side_effect = (
                httpx.ConnectError("Connection refused")
            )
            result = runner.invoke(app, ["capture", "test content"])

        assert result.exit_code == 1
        assert "Cannot connect to API" in result.stdout
        assert "Is the server running?" in result.stdout

    def test_timeout_error_shows_message(self):
        """Test timeout error shows helpful message."""
        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.side_effect = (
                httpx.TimeoutException("Request timed out")
            )
            result = runner.invoke(app, ["capture", "test content"])

        assert result.exit_code == 1
        assert "timed out" in result.stdout

    def test_api_error_shows_detail(self):
        """Test API error response shows detail message."""
        mock_response = httpx.Response(
            status_code=400,
            json={"detail": "Content too short"},
        )

        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_response
            result = runner.invoke(app, ["capture", "test content"])

        assert result.exit_code == 1
        assert "Content too short" in result.stdout

    def test_api_error_without_json_shows_text(self):
        """Test API error without JSON shows response text."""
        mock_response = httpx.Response(
            status_code=500,
            text="Internal Server Error",
        )

        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_response
            result = runner.invoke(app, ["capture", "test content"])

        assert result.exit_code == 1
        assert "Internal Server Error" in result.stdout


class TestCustomApiUrl:
    """Tests for custom API URL configuration."""

    def test_capture_uses_custom_api_url(self):
        """Test that capture uses custom API URL from env."""
        mock_response = httpx.Response(
            status_code=201,
            json={"id": "test-id", "content": "test"},
        )

        with (
            patch.dict("os.environ", {"PROVO_API_URL": "http://custom:9000"}),
            patch("provo.cli.main.httpx.Client") as mock_client,
        ):
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.post.return_value = mock_response
            result = runner.invoke(app, ["capture", "test content"])

        assert result.exit_code == 0
        call_args = mock_instance.post.call_args
        assert call_args[0][0] == "http://custom:9000/api/fragments"


class TestFormatHelpers:
    """Tests for formatting helper functions."""

    def test_format_source_type_quick_capture(self):
        """Test quick_capture gets the right icon."""
        result = format_source_type("quick_capture")
        assert "📍" in result
        assert "Quick Capture" in result

    def test_format_source_type_zoom(self):
        """Test zoom gets the right icon."""
        result = format_source_type("zoom")
        assert "🎥" in result
        assert "Zoom" in result

    def test_format_source_type_unknown(self):
        """Test unknown source type gets fallback icon."""
        result = format_source_type("unknown_type")
        assert "📄" in result
        assert "Unknown Type" in result

    def test_format_date_iso_format(self):
        """Test ISO date formatting."""
        result = format_date("2025-12-15T10:30:00+00:00")
        assert result == "2025-12-15"

    def test_format_date_with_z_suffix(self):
        """Test ISO date with Z suffix."""
        result = format_date("2025-12-15T10:30:00Z")
        assert result == "2025-12-15"

    def test_format_date_invalid(self):
        """Test invalid date returns first 10 chars."""
        result = format_date("not-a-date")
        assert result == "not-a-date"

    def test_format_date_empty(self):
        """Test empty date returns Unknown."""
        result = format_date("")
        assert result == "Unknown"

    def test_format_score_high(self):
        """Test high score formatting."""
        result = format_score(0.9)
        assert "0.90" in result

    def test_format_score_medium(self):
        """Test medium score formatting."""
        result = format_score(0.6)
        assert "0.60" in result

    def test_format_score_low(self):
        """Test low score formatting."""
        result = format_score(0.3)
        assert "0.30" in result

    def test_truncate_content_short(self):
        """Test short content is not truncated."""
        result = truncate_content("Short content")
        assert result == "Short content"

    def test_truncate_content_long(self):
        """Test long content is truncated with ellipsis."""
        long_content = "A" * 100
        result = truncate_content(long_content, max_length=80)
        assert len(result) == 80
        assert result.endswith("...")

    def test_truncate_content_newlines_removed(self):
        """Test newlines are replaced with spaces."""
        result = truncate_content("Line 1\nLine 2\nLine 3")
        assert "\n" not in result
        assert "Line 1 Line 2 Line 3" == result


class TestFormatResult:
    """Tests for the format_result function."""

    def test_format_result_complete(self):
        """Test formatting a complete result."""
        result_data = {
            "source_type": "quick_capture",
            "captured_at": "2025-12-15T10:30:00Z",
            "score": 0.89,
            "content": "Chose Postgres for ACID compliance",
        }
        formatted = format_result(result_data)
        assert "📍" in formatted
        assert "Quick Capture" in formatted
        assert "2025-12-15" in formatted
        assert "0.89" in formatted
        assert "Chose Postgres for ACID compliance" in formatted

    def test_format_result_with_zoom_source(self):
        """Test formatting a zoom meeting result."""
        result_data = {
            "source_type": "zoom",
            "captured_at": "2025-12-10T14:00:00Z",
            "score": 0.76,
            "content": "Sarah mentioned we should stick with relational",
        }
        formatted = format_result(result_data)
        assert "🎥" in formatted
        assert "Zoom" in formatted


class TestSearchCommand:
    """Tests for the search command."""

    def test_search_help_shows_usage(self):
        """Test that search --help shows usage information."""
        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0
        assert "Search for context fragments" in result.stdout
        assert "--limit" in result.stdout
        assert "--project" in result.stdout

    def test_search_missing_query_shows_error(self):
        """Test that missing query argument shows error."""
        result = runner.invoke(app, ["search"])
        assert result.exit_code != 0
        assert "Missing argument" in result.stdout or "QUERY" in result.stdout

    def test_search_with_results(self):
        """Test search displays results correctly."""
        mock_response = httpx.Response(
            status_code=200,
            json={
                "query": "postgres",
                "results": [
                    {
                        "id": "abc-123",
                        "content": "Chose Postgres for ACID compliance",
                        "source_type": "quick_capture",
                        "captured_at": "2025-12-15T10:30:00Z",
                        "score": 0.89,
                    },
                    {
                        "id": "def-456",
                        "content": "Sarah mentioned relational databases",
                        "source_type": "zoom",
                        "captured_at": "2025-12-10T14:00:00Z",
                        "score": 0.76,
                    },
                ],
            },
        )

        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response
            result = runner.invoke(app, ["search", "postgres"])

        assert result.exit_code == 0
        assert "Found 2 results" in result.stdout
        assert "postgres" in result.stdout
        assert "Chose Postgres for ACID compliance" in result.stdout
        assert "📍" in result.stdout
        assert "🎥" in result.stdout

    def test_search_no_results(self):
        """Test search with no results shows message."""
        mock_response = httpx.Response(
            status_code=200,
            json={"query": "nonexistent", "results": []},
        )

        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response
            result = runner.invoke(app, ["search", "nonexistent"])

        assert result.exit_code == 0
        assert "No results found" in result.stdout

    def test_search_with_limit(self):
        """Test search with limit flag."""
        mock_response = httpx.Response(
            status_code=200,
            json={"query": "test", "results": []},
        )

        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value = mock_response
            result = runner.invoke(app, ["search", "--limit", "5", "test"])

        assert result.exit_code == 0
        call_kwargs = mock_instance.get.call_args.kwargs
        assert call_kwargs["params"]["limit"] == 5

    def test_search_with_project_filter(self):
        """Test search with project filter."""
        mock_response = httpx.Response(
            status_code=200,
            json={"query": "test", "results": []},
        )

        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value = mock_response
            result = runner.invoke(app, ["search", "-p", "billing", "test"])

        assert result.exit_code == 0
        call_kwargs = mock_instance.get.call_args.kwargs
        assert call_kwargs["params"]["project"] == "billing"

    def test_search_single_result_grammar(self):
        """Test search with single result uses correct grammar."""
        mock_response = httpx.Response(
            status_code=200,
            json={
                "query": "unique",
                "results": [
                    {
                        "id": "abc-123",
                        "content": "Unique finding",
                        "source_type": "notes",
                        "captured_at": "2025-12-15T10:30:00Z",
                        "score": 0.95,
                    },
                ],
            },
        )

        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response
            result = runner.invoke(app, ["search", "unique"])

        assert result.exit_code == 0
        assert "Found 1 result" in result.stdout
        assert "results" not in result.stdout.replace("results", "")  # No plural

    def test_search_connection_error(self):
        """Test search connection error shows helpful message."""
        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = (
                httpx.ConnectError("Connection refused")
            )
            result = runner.invoke(app, ["search", "test"])

        assert result.exit_code == 1
        assert "Cannot connect to API" in result.stdout

    def test_search_timeout_error(self):
        """Test search timeout error shows message."""
        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = (
                httpx.TimeoutException("Request timed out")
            )
            result = runner.invoke(app, ["search", "test"])

        assert result.exit_code == 1
        assert "timed out" in result.stdout

    def test_search_api_error(self):
        """Test search API error shows detail."""
        mock_response = httpx.Response(
            status_code=500,
            json={"detail": "Internal server error"},
        )

        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response
            result = runner.invoke(app, ["search", "test"])

        assert result.exit_code == 1
        assert "Internal server error" in result.stdout

    def test_search_uses_custom_api_url(self):
        """Test search uses custom API URL from env."""
        mock_response = httpx.Response(
            status_code=200,
            json={"query": "test", "results": []},
        )

        with (
            patch.dict("os.environ", {"PROVO_API_URL": "http://custom:9000"}),
            patch("provo.cli.main.httpx.Client") as mock_client,
        ):
            mock_instance = mock_client.return_value.__enter__.return_value
            mock_instance.get.return_value = mock_response
            result = runner.invoke(app, ["search", "test"])

        assert result.exit_code == 0
        call_args = mock_instance.get.call_args
        assert call_args[0][0] == "http://custom:9000/api/search"
