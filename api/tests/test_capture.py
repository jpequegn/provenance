"""Tests for the capture module (parsers and watcher)."""

import tempfile
import time
from pathlib import Path
from threading import Thread
from unittest.mock import MagicMock, patch

from provo.capture.parsers import (
    ParsedTranscript,
    TranscriptSegment,
    parse_frontmatter,
    parse_markdown,
    parse_txt,
    parse_vtt,
    parse_vtt_timestamp,
)
from provo.capture.watcher import NotesWatcher, ProcessedFileTracker, TranscriptWatcher


class TestParseVttTimestamp:
    """Tests for VTT timestamp parsing."""

    def test_parse_full_timestamp(self):
        """Test parsing HH:MM:SS.mmm format."""
        result = parse_vtt_timestamp("01:23:45.678")
        assert result == 1 * 3600 + 23 * 60 + 45.678

    def test_parse_short_timestamp(self):
        """Test parsing MM:SS.mmm format."""
        result = parse_vtt_timestamp("05:30.500")
        assert result == 5 * 60 + 30.5

    def test_parse_zero_timestamp(self):
        """Test parsing zero timestamp."""
        result = parse_vtt_timestamp("00:00:00.000")
        assert result == 0.0


class TestParseVtt:
    """Tests for VTT file parsing."""

    def test_parse_basic_vtt(self):
        """Test parsing a basic VTT file."""
        vtt_content = """WEBVTT

00:00:01.000 --> 00:00:05.000
Speaker 1: Let's discuss the architecture...

00:00:05.500 --> 00:00:10.000
Speaker 2: I think we should use microservices...
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".vtt", delete=False) as f:
            f.write(vtt_content)
            f.flush()
            file_path = Path(f.name)

        try:
            result = parse_vtt(file_path)

            assert isinstance(result, ParsedTranscript)
            assert len(result.segments) == 2
            assert result.participants == ["Speaker 1", "Speaker 2"]

            # Check first segment
            seg1 = result.segments[0]
            assert seg1.speaker == "Speaker 1"
            assert "architecture" in seg1.text
            assert seg1.start_time == 1.0
            assert seg1.end_time == 5.0

            # Check second segment
            seg2 = result.segments[1]
            assert seg2.speaker == "Speaker 2"
            assert "microservices" in seg2.text

            # Check full content
            assert "Speaker 1: Let's discuss the architecture" in result.content
            assert "Speaker 2: I think we should use microservices" in result.content

        finally:
            file_path.unlink()

    def test_parse_vtt_without_speakers(self):
        """Test parsing VTT without speaker labels."""
        vtt_content = """WEBVTT

00:00:01.000 --> 00:00:05.000
Just plain text without speaker label.

00:00:05.500 --> 00:00:10.000
More text here.
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".vtt", delete=False) as f:
            f.write(vtt_content)
            f.flush()
            file_path = Path(f.name)

        try:
            result = parse_vtt(file_path)

            assert len(result.segments) == 2
            assert result.participants == []
            assert result.segments[0].speaker is None

        finally:
            file_path.unlink()

    def test_parse_vtt_multiline_text(self):
        """Test parsing VTT with multiline text."""
        vtt_content = """WEBVTT

00:00:01.000 --> 00:00:05.000
This is line one
and this is line two.
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".vtt", delete=False) as f:
            f.write(vtt_content)
            f.flush()
            file_path = Path(f.name)

        try:
            result = parse_vtt(file_path)

            assert len(result.segments) == 1
            assert "line one" in result.segments[0].text
            assert "line two" in result.segments[0].text

        finally:
            file_path.unlink()


class TestParseTxt:
    """Tests for plain text file parsing."""

    def test_parse_basic_txt(self):
        """Test parsing a basic TXT file."""
        txt_content = """Speaker 1: Let's discuss the architecture.

Speaker 2: I think we should use microservices.

Speaker 1: That makes sense for our scale.
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(txt_content)
            f.flush()
            file_path = Path(f.name)

        try:
            result = parse_txt(file_path)

            assert isinstance(result, ParsedTranscript)
            assert len(result.segments) == 3
            assert result.participants == ["Speaker 1", "Speaker 2"]

            # Check segments
            assert result.segments[0].speaker == "Speaker 1"
            assert "architecture" in result.segments[0].text
            assert result.segments[1].speaker == "Speaker 2"

        finally:
            file_path.unlink()

    def test_parse_txt_without_speakers(self):
        """Test parsing TXT without speaker labels."""
        txt_content = """This is a paragraph of text without a speaker.

And this is another paragraph.
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(txt_content)
            f.flush()
            file_path = Path(f.name)

        try:
            result = parse_txt(file_path)

            assert len(result.segments) == 2
            assert result.participants == []
            assert result.segments[0].speaker is None

        finally:
            file_path.unlink()


class TestProcessedFileTracker:
    """Tests for the processed file tracker."""

    def test_tracker_marks_file_processed(self):
        """Test that tracker marks files as processed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker_path = Path(tmpdir) / "tracker.json"
            tracker = ProcessedFileTracker(tracker_path)

            # Create a test file
            test_file = Path(tmpdir) / "test.vtt"
            test_file.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nTest")

            # Should not be processed initially
            assert not tracker.is_processed(test_file)

            # Mark as processed
            tracker.mark_processed(test_file)

            # Should now be processed
            assert tracker.is_processed(test_file)

    def test_tracker_persists_across_instances(self):
        """Test that tracker data persists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker_path = Path(tmpdir) / "tracker.json"

            # Create a test file
            test_file = Path(tmpdir) / "test.vtt"
            test_file.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nTest")

            # First instance marks file
            tracker1 = ProcessedFileTracker(tracker_path)
            tracker1.mark_processed(test_file)

            # Second instance should see it
            tracker2 = ProcessedFileTracker(tracker_path)
            assert tracker2.is_processed(test_file)

    def test_tracker_clear(self):
        """Test clearing the tracker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker_path = Path(tmpdir) / "tracker.json"
            tracker = ProcessedFileTracker(tracker_path)

            # Create and mark a file
            test_file = Path(tmpdir) / "test.vtt"
            test_file.write_text("content")
            tracker.mark_processed(test_file)

            # Clear tracker
            tracker.clear()

            # Should no longer be processed
            assert not tracker.is_processed(test_file)


class TestTranscriptWatcher:
    """Tests for the transcript watcher."""

    def test_watcher_processes_existing_files(self):
        """Test that watcher processes existing files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_path = Path(tmpdir)

            # Create a VTT file before starting watcher
            vtt_file = watch_path / "meeting.vtt"
            vtt_file.write_text("""WEBVTT

00:00:01.000 --> 00:00:05.000
Speaker: Hello world
""")

            # Track callback calls
            callback_calls: list[tuple] = []

            def callback(transcript: ParsedTranscript, source_type: str) -> None:
                callback_calls.append((transcript, source_type))

            watcher = TranscriptWatcher(
                watch_path=watch_path,
                source_type="zoom",
                callback=callback,
            )

            # Process existing
            count = watcher.process_existing()

            assert count == 1
            assert len(callback_calls) == 1
            assert callback_calls[0][0].content is not None
            assert callback_calls[0][1] == "zoom"

    def test_watcher_skips_already_processed(self):
        """Test that watcher skips already processed files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_path = Path(tmpdir)

            # Create a VTT file
            vtt_file = watch_path / "meeting.vtt"
            vtt_file.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nTest")

            callback_calls: list[tuple] = []

            def callback(transcript: ParsedTranscript, source_type: str) -> None:
                callback_calls.append((transcript, source_type))

            watcher = TranscriptWatcher(
                watch_path=watch_path,
                source_type="zoom",
                callback=callback,
            )

            # Process twice
            count1 = watcher.process_existing()
            count2 = watcher.process_existing()

            assert count1 == 1
            assert count2 == 0  # Should skip already processed
            assert len(callback_calls) == 1

    def test_watcher_detects_new_files(self):
        """Test that watcher detects new files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_path = Path(tmpdir)

            callback_calls: list[tuple] = []

            def callback(transcript: ParsedTranscript, source_type: str) -> None:
                callback_calls.append((transcript, source_type))

            watcher = TranscriptWatcher(
                watch_path=watch_path,
                source_type="teams",
                callback=callback,
            )

            # Start watcher
            watcher.start()

            try:
                # Give watcher time to start
                time.sleep(0.5)

                # Create a new file
                new_file = watch_path / "new_meeting.txt"
                new_file.write_text("Meeting notes: We decided to use Redis.")

                # Wait for detection
                time.sleep(1.5)

            finally:
                watcher.stop()

            assert len(callback_calls) == 1
            assert "Redis" in callback_calls[0][0].content
            assert callback_calls[0][1] == "teams"

    def test_watcher_context_manager(self):
        """Test watcher as context manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_path = Path(tmpdir)

            with TranscriptWatcher(
                watch_path=watch_path,
                source_type="zoom",
                callback=lambda t, s: None,
            ) as watcher:
                assert watcher.is_running()

            assert not watcher.is_running()

    def test_watcher_validates_path(self):
        """Test watcher validates the watch path."""
        callback = lambda t, s: None

        # Non-existent path
        watcher = TranscriptWatcher(
            watch_path="/nonexistent/path",
            source_type="zoom",
            callback=callback,
        )

        try:
            watcher.start()
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "does not exist" in str(e)

    def test_watcher_ignores_non_transcript_files(self):
        """Test that watcher ignores non-transcript files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_path = Path(tmpdir)

            callback_calls: list[tuple] = []

            def callback(transcript: ParsedTranscript, source_type: str) -> None:
                callback_calls.append((transcript, source_type))

            watcher = TranscriptWatcher(
                watch_path=watch_path,
                source_type="zoom",
                callback=callback,
            )

            watcher.start()

            try:
                time.sleep(0.5)

                # Create non-transcript files
                (watch_path / "readme.md").write_text("# Readme")
                (watch_path / "image.png").write_bytes(b"fake image")
                (watch_path / "data.json").write_text("{}")

                time.sleep(1.0)

            finally:
                watcher.stop()

            # Should not have processed any files
            assert len(callback_calls) == 0


class TestParseFrontmatter:
    """Tests for YAML frontmatter parsing."""

    def test_parse_frontmatter_with_project_and_topics(self):
        """Test parsing frontmatter with project and topics."""
        content = """---
project: billing
topics: [architecture, decisions]
---

# Meeting Notes

Content here.
"""
        frontmatter, body = parse_frontmatter(content)

        assert frontmatter["project"] == "billing"
        assert frontmatter["topics"] == ["architecture", "decisions"]
        assert "# Meeting Notes" in body
        assert "---" not in body

    def test_parse_frontmatter_empty_when_missing(self):
        """Test parsing content without frontmatter."""
        content = """# Just a Regular Document

No frontmatter here.
"""
        frontmatter, body = parse_frontmatter(content)

        assert frontmatter == {}
        assert body == content

    def test_parse_frontmatter_with_quoted_values(self):
        """Test parsing frontmatter with quoted values."""
        content = """---
project: "my-project"
title: 'Some Title'
---

Body content.
"""
        frontmatter, body = parse_frontmatter(content)

        assert frontmatter["project"] == "my-project"
        assert frontmatter["title"] == "Some Title"

    def test_parse_frontmatter_unclosed_returns_original(self):
        """Test parsing unclosed frontmatter returns original content."""
        content = """---
project: billing

No closing delimiter here.
"""
        frontmatter, body = parse_frontmatter(content)

        assert frontmatter == {}
        assert body == content


class TestParseMarkdown:
    """Tests for markdown file parsing."""

    def test_parse_markdown_with_frontmatter(self):
        """Test parsing markdown with frontmatter."""
        md_content = """---
project: billing
topics: [architecture, decisions]
---

# Meeting Notes 2025-12-27

Decided to use Redis for session caching because of its speed.

## Next Steps

- Implement Redis client
- Add cache invalidation
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(md_content)
            f.flush()
            file_path = Path(f.name)

        try:
            result = parse_markdown(file_path)

            assert isinstance(result, ParsedTranscript)
            assert result.project == "billing"
            assert result.topics == ["architecture", "decisions"]
            assert "Redis" in result.content
            assert "---" not in result.content  # Frontmatter stripped
            assert len(result.segments) > 0

        finally:
            file_path.unlink()

    def test_parse_markdown_without_frontmatter(self):
        """Test parsing markdown without frontmatter."""
        md_content = """# Regular Notes

Just some notes without frontmatter.

Another paragraph.
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(md_content)
            f.flush()
            file_path = Path(f.name)

        try:
            result = parse_markdown(file_path)

            assert result.project is None
            assert result.topics == []
            assert "Regular Notes" in result.content
            # 3 segments: heading, first paragraph, second paragraph
            assert len(result.segments) == 3

        finally:
            file_path.unlink()

    def test_parse_markdown_single_topic_string(self):
        """Test parsing frontmatter with single topic as string."""
        md_content = """---
project: api
topics: architecture
---

Content here.
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(md_content)
            f.flush()
            file_path = Path(f.name)

        try:
            result = parse_markdown(file_path)

            assert result.topics == ["architecture"]

        finally:
            file_path.unlink()


class TestNotesWatcher:
    """Tests for the notes folder watcher."""

    def test_notes_watcher_processes_existing_markdown(self):
        """Test that notes watcher processes existing markdown files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_path = Path(tmpdir)

            # Create a markdown file
            md_file = watch_path / "notes.md"
            md_file.write_text("""---
project: test-project
topics: [testing]
---

# Test Notes

Some test content here.
""")

            callback_calls: list[tuple] = []

            def callback(transcript: ParsedTranscript, source_type: str) -> None:
                callback_calls.append((transcript, source_type))

            watcher = NotesWatcher(
                watch_path=watch_path,
                callback=callback,
            )

            count = watcher.process_existing()

            assert count == 1
            assert len(callback_calls) == 1
            assert callback_calls[0][0].project == "test-project"
            assert callback_calls[0][0].topics == ["testing"]
            assert callback_calls[0][1] == "notes"

    def test_notes_watcher_ignores_obsidian_folder(self):
        """Test that notes watcher ignores .obsidian folder."""
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_path = Path(tmpdir)

            # Create .obsidian directory with a file
            obsidian_dir = watch_path / ".obsidian"
            obsidian_dir.mkdir()
            (obsidian_dir / "config.md").write_text("# Config")

            # Create a regular markdown file
            (watch_path / "notes.md").write_text("# Notes")

            callback_calls: list[tuple] = []

            def callback(transcript: ParsedTranscript, source_type: str) -> None:
                callback_calls.append((transcript, source_type))

            watcher = NotesWatcher(
                watch_path=watch_path,
                callback=callback,
                recursive=True,
            )

            count = watcher.process_existing()

            # Should only process notes.md, not .obsidian/config.md
            assert count == 1
            assert len(callback_calls) == 1
            assert "Notes" in callback_calls[0][0].content

    def test_notes_watcher_ignores_git_folder(self):
        """Test that notes watcher ignores .git folder."""
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_path = Path(tmpdir)

            # Create .git directory with a file
            git_dir = watch_path / ".git"
            git_dir.mkdir()
            (git_dir / "readme.md").write_text("# Git Readme")

            callback_calls: list[tuple] = []

            def callback(transcript: ParsedTranscript, source_type: str) -> None:
                callback_calls.append((transcript, source_type))

            watcher = NotesWatcher(
                watch_path=watch_path,
                callback=callback,
            )

            count = watcher.process_existing()

            # Should not process any files
            assert count == 0
            assert len(callback_calls) == 0

    def test_notes_watcher_detects_new_files(self):
        """Test that notes watcher detects new markdown files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_path = Path(tmpdir)

            callback_calls: list[tuple] = []

            def callback(transcript: ParsedTranscript, source_type: str) -> None:
                callback_calls.append((transcript, source_type))

            watcher = NotesWatcher(
                watch_path=watch_path,
                callback=callback,
            )

            watcher.start()

            try:
                time.sleep(0.5)

                # Create a new markdown file
                new_file = watch_path / "new_note.md"
                new_file.write_text("# New Note\n\nSome content.")

                time.sleep(1.5)

            finally:
                watcher.stop()

            assert len(callback_calls) == 1
            assert "New Note" in callback_calls[0][0].content

    def test_notes_watcher_detects_modified_files(self):
        """Test that notes watcher detects modified files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_path = Path(tmpdir)

            # Create a file first
            note_file = watch_path / "note.md"
            note_file.write_text("# Original Content")

            callback_calls: list[tuple] = []

            def callback(transcript: ParsedTranscript, source_type: str) -> None:
                callback_calls.append((transcript, source_type))

            watcher = NotesWatcher(
                watch_path=watch_path,
                callback=callback,
            )

            # Process existing first
            watcher.process_existing()
            initial_count = len(callback_calls)

            watcher.start()

            try:
                time.sleep(0.5)

                # Modify the file
                note_file.write_text("# Modified Content\n\nNew stuff here.")

                time.sleep(1.5)

            finally:
                watcher.stop()

            # Should have processed the modified file
            assert len(callback_calls) > initial_count
            # Find the modified callback
            modified_call = [c for c in callback_calls if "Modified" in c[0].content]
            assert len(modified_call) == 1

    def test_notes_watcher_recursive(self):
        """Test that notes watcher works recursively."""
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_path = Path(tmpdir)

            # Create nested directory structure
            subdir = watch_path / "subfolder" / "deeper"
            subdir.mkdir(parents=True)
            (subdir / "nested.md").write_text("# Nested Note")

            callback_calls: list[tuple] = []

            def callback(transcript: ParsedTranscript, source_type: str) -> None:
                callback_calls.append((transcript, source_type))

            watcher = NotesWatcher(
                watch_path=watch_path,
                callback=callback,
                recursive=True,
            )

            count = watcher.process_existing()

            assert count == 1
            assert "Nested" in callback_calls[0][0].content

    def test_notes_watcher_non_recursive(self):
        """Test that notes watcher respects non-recursive setting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_path = Path(tmpdir)

            # Create files in root and subdirectory
            (watch_path / "root.md").write_text("# Root Note")
            subdir = watch_path / "subfolder"
            subdir.mkdir()
            (subdir / "nested.md").write_text("# Nested Note")

            callback_calls: list[tuple] = []

            def callback(transcript: ParsedTranscript, source_type: str) -> None:
                callback_calls.append((transcript, source_type))

            watcher = NotesWatcher(
                watch_path=watch_path,
                callback=callback,
                recursive=False,
            )

            count = watcher.process_existing()

            # Should only process root file
            assert count == 1
            assert "Root" in callback_calls[0][0].content

    def test_notes_watcher_context_manager(self):
        """Test notes watcher as context manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            watch_path = Path(tmpdir)

            with NotesWatcher(
                watch_path=watch_path,
                callback=lambda t, s: None,
            ) as watcher:
                assert watcher.is_running()

            assert not watcher.is_running()

    def test_notes_watcher_validates_path(self):
        """Test notes watcher validates the watch path."""
        watcher = NotesWatcher(
            watch_path="/nonexistent/path",
            callback=lambda t, s: None,
        )

        try:
            watcher.start()
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "does not exist" in str(e)
