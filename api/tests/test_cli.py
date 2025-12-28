"""Tests for the CLI capture command."""

from unittest.mock import patch

import httpx
from typer.testing import CliRunner

from provo.cli.main import app, get_api_url

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
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Capture a context fragment" in result.stdout
        assert "--project" in result.stdout
        assert "--topic" in result.stdout
        assert "--link" in result.stdout

    def test_missing_content_shows_error(self):
        """Test that missing content argument shows error."""
        result = runner.invoke(app, [])
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
            result = runner.invoke(app, ["test content"])

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
            result = runner.invoke(app, ["-p", "billing", "test content"])

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
                app, ["-t", "architecture", "-t", "database", "test content"]
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
                app, ["--link", "https://github.com/pr/123", "test content"]
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


class TestErrorHandling:
    """Tests for error handling."""

    def test_connection_error_shows_message(self):
        """Test connection error shows helpful message."""
        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.side_effect = (
                httpx.ConnectError("Connection refused")
            )
            result = runner.invoke(app, ["test content"])

        assert result.exit_code == 1
        assert "Cannot connect to API" in result.stdout
        assert "Is the server running?" in result.stdout

    def test_timeout_error_shows_message(self):
        """Test timeout error shows helpful message."""
        with patch("provo.cli.main.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.side_effect = (
                httpx.TimeoutException("Request timed out")
            )
            result = runner.invoke(app, ["test content"])

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
            result = runner.invoke(app, ["test content"])

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
            result = runner.invoke(app, ["test content"])

        assert result.exit_code == 1
        assert "Internal Server Error" in result.stdout


class TestCustomApiUrl:
    """Tests for custom API URL configuration."""

    def test_uses_custom_api_url(self):
        """Test that custom API URL from env is used."""
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
            result = runner.invoke(app, ["test content"])

        assert result.exit_code == 0
        call_args = mock_instance.post.call_args
        assert call_args[0][0] == "http://custom:9000/api/fragments"
