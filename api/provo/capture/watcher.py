"""File watcher for automatic transcript processing."""

import hashlib
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from watchdog.events import (
    FileCreatedEvent,
    FileModifiedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from provo.capture.parsers import ParsedTranscript, parse_markdown, parse_txt, parse_vtt

# Default patterns to ignore when watching notes folders
DEFAULT_IGNORE_PATTERNS = [
    ".obsidian",
    ".git",
    ".trash",
    ".DS_Store",
    "node_modules",
]

logger = logging.getLogger(__name__)


SourceType = Literal["zoom", "teams", "notes"]


class ProcessedFileTracker:
    """Track processed files to avoid duplicates.

    Uses a JSON file to persist processed file hashes across restarts.
    """

    def __init__(self, tracker_path: Path | str):
        """Initialize the tracker.

        Args:
            tracker_path: Path to the JSON file for tracking processed files.
        """
        self.tracker_path = Path(tracker_path)
        self._processed: set[str] = set()
        self._load()

    def _load(self) -> None:
        """Load processed files from disk."""
        if self.tracker_path.exists():
            try:
                data = json.loads(self.tracker_path.read_text())
                self._processed = set(data.get("processed", []))
            except (json.JSONDecodeError, KeyError):
                self._processed = set()

    def _save(self) -> None:
        """Save processed files to disk."""
        self.tracker_path.parent.mkdir(parents=True, exist_ok=True)
        self.tracker_path.write_text(
            json.dumps({"processed": sorted(self._processed)}, indent=2)
        )

    def _file_hash(self, file_path: Path) -> str:
        """Generate a hash for a file based on path and content hash."""
        content = file_path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()[:16]
        return f"{file_path.name}:{content_hash}"

    def is_processed(self, file_path: Path) -> bool:
        """Check if a file has been processed."""
        return self._file_hash(file_path) in self._processed

    def mark_processed(self, file_path: Path) -> None:
        """Mark a file as processed."""
        self._processed.add(self._file_hash(file_path))
        self._save()

    def clear(self) -> None:
        """Clear all processed files."""
        self._processed.clear()
        self._save()


class TranscriptHandler(FileSystemEventHandler):
    """Handle file system events for transcript files."""

    def __init__(
        self,
        source_type: SourceType,
        callback: Callable[[ParsedTranscript, SourceType], None],
        tracker: ProcessedFileTracker,
    ):
        """Initialize the handler.

        Args:
            source_type: The type of source (zoom, teams, notes).
            callback: Function to call with parsed transcript.
            tracker: Tracker to avoid processing duplicates.
        """
        super().__init__()
        self.source_type = source_type
        self.callback = callback
        self.tracker = tracker
        self._extensions = {".vtt", ".txt"}

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        """Handle file creation events."""
        if event.is_directory:
            return

        src_path = event.src_path
        if isinstance(src_path, bytes):
            src_path = src_path.decode("utf-8")
        file_path = Path(src_path)

        # Check if it's a transcript file
        if file_path.suffix.lower() not in self._extensions:
            return

        # Wait a moment for file to be fully written
        time.sleep(0.5)

        # Check if already processed
        if self.tracker.is_processed(file_path):
            logger.info(f"Skipping already processed file: {file_path.name}")
            return

        logger.info(f"Processing new transcript: {file_path.name}")

        try:
            # Parse based on extension
            if file_path.suffix.lower() == ".vtt":
                transcript = parse_vtt(file_path)
            else:
                transcript = parse_txt(file_path)

            # Mark as processed before callback (in case callback fails)
            self.tracker.mark_processed(file_path)

            # Call the callback
            self.callback(transcript, self.source_type)

            logger.info(f"Successfully processed: {file_path.name}")

        except Exception as e:
            logger.error(f"Failed to process {file_path.name}: {e}")
            raise


class TranscriptWatcher:
    """Watch a directory for new transcript files."""

    def __init__(
        self,
        watch_path: Path | str,
        source_type: SourceType,
        callback: Callable[[ParsedTranscript, SourceType], None],
        tracker_path: Path | str | None = None,
    ):
        """Initialize the watcher.

        Args:
            watch_path: Directory to watch for new files.
            source_type: Type of source (zoom, teams, notes).
            callback: Function to call when a transcript is parsed.
            tracker_path: Path for the processed files tracker.
                         Defaults to watch_path/.provo_processed.json
        """
        self.watch_path = Path(watch_path)
        self.source_type = source_type
        self.callback = callback

        if tracker_path is None:
            tracker_path = self.watch_path / ".provo_processed.json"
        self.tracker = ProcessedFileTracker(tracker_path)

        self._handler = TranscriptHandler(
            source_type=source_type,
            callback=callback,
            tracker=self.tracker,
        )
        self._observer: BaseObserver | None = None

    def start(self) -> None:
        """Start watching the directory."""
        if self._observer is not None:
            return

        if not self.watch_path.exists():
            raise ValueError(f"Watch path does not exist: {self.watch_path}")

        if not self.watch_path.is_dir():
            raise ValueError(f"Watch path is not a directory: {self.watch_path}")

        self._observer = Observer()
        self._observer.schedule(self._handler, str(self.watch_path), recursive=False)
        self._observer.start()
        logger.info(f"Started watching: {self.watch_path}")

    def stop(self) -> None:
        """Stop watching the directory."""
        if self._observer is None:
            return

        self._observer.stop()
        self._observer.join(timeout=5)
        self._observer = None
        logger.info("Stopped watching")

    def is_running(self) -> bool:
        """Check if the watcher is running."""
        return self._observer is not None and self._observer.is_alive()

    def process_existing(self) -> int:
        """Process any existing unprocessed files in the directory.

        Returns:
            Number of files processed.
        """
        count = 0
        for ext in [".vtt", ".txt"]:
            for file_path in self.watch_path.glob(f"*{ext}"):
                if self.tracker.is_processed(file_path):
                    continue

                logger.info(f"Processing existing file: {file_path.name}")

                try:
                    if ext == ".vtt":
                        transcript = parse_vtt(file_path)
                    else:
                        transcript = parse_txt(file_path)

                    self.tracker.mark_processed(file_path)
                    self.callback(transcript, self.source_type)
                    count += 1

                except Exception as e:
                    logger.error(f"Failed to process {file_path.name}: {e}")

        return count

    def __enter__(self) -> "TranscriptWatcher":
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Context manager exit."""
        self.stop()


class NotesHandler(FileSystemEventHandler):
    """Handle file system events for markdown notes files.

    Unlike TranscriptHandler, this handles both created and modified events
    to re-process updated notes.
    """

    def __init__(
        self,
        callback: Callable[[ParsedTranscript, SourceType], None],
        tracker: ProcessedFileTracker,
        ignore_patterns: list[str] | None = None,
    ):
        """Initialize the handler.

        Args:
            callback: Function to call with parsed transcript.
            tracker: Tracker to avoid processing duplicates.
            ignore_patterns: List of path patterns to ignore.
        """
        super().__init__()
        self.callback = callback
        self.tracker = tracker
        self.ignore_patterns = ignore_patterns or DEFAULT_IGNORE_PATTERNS
        self._extensions = {".md", ".markdown"}

    def _should_ignore(self, file_path: Path) -> bool:
        """Check if a file should be ignored based on patterns."""
        path_str = str(file_path)
        for pattern in self.ignore_patterns:
            if pattern in path_str:
                return True
        return False

    def _process_file(self, file_path: Path, event_type: str) -> None:
        """Process a markdown file."""
        # Check if it's a markdown file
        if file_path.suffix.lower() not in self._extensions:
            return

        # Check if should be ignored
        if self._should_ignore(file_path):
            logger.debug(f"Ignoring file matching pattern: {file_path}")
            return

        # Wait a moment for file to be fully written
        time.sleep(0.5)

        # For modified events, we want to re-process even if previously processed
        # The tracker will use content hash, so same content = skip
        if self.tracker.is_processed(file_path):
            logger.debug(f"Skipping unchanged file: {file_path.name}")
            return

        logger.info(f"Processing {event_type} note: {file_path.name}")

        try:
            transcript = parse_markdown(file_path)

            # Mark as processed before callback
            self.tracker.mark_processed(file_path)

            # Call the callback
            self.callback(transcript, "notes")

            logger.info(f"Successfully processed: {file_path.name}")

        except Exception as e:
            logger.error(f"Failed to process {file_path.name}: {e}")
            raise

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        """Handle file creation events."""
        if event.is_directory:
            return

        src_path = event.src_path
        if isinstance(src_path, bytes):
            src_path = src_path.decode("utf-8")
        self._process_file(Path(src_path), "new")

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        """Handle file modification events."""
        if event.is_directory:
            return

        src_path = event.src_path
        if isinstance(src_path, bytes):
            src_path = src_path.decode("utf-8")
        self._process_file(Path(src_path), "modified")


class NotesWatcher:
    """Watch a directory for new and modified markdown notes files.

    Unlike TranscriptWatcher, this:
    - Watches for .md and .markdown files
    - Re-processes modified files (not just new ones)
    - Supports recursive directory watching
    - Ignores configured patterns (like .obsidian/, .git/)
    """

    def __init__(
        self,
        watch_path: Path | str,
        callback: Callable[[ParsedTranscript, SourceType], None],
        tracker_path: Path | str | None = None,
        recursive: bool = True,
        ignore_patterns: list[str] | None = None,
    ):
        """Initialize the notes watcher.

        Args:
            watch_path: Directory to watch for notes files.
            callback: Function to call when a note is parsed.
            tracker_path: Path for the processed files tracker.
                         Defaults to watch_path/.provo_notes_processed.json
            recursive: Whether to watch subdirectories.
            ignore_patterns: List of path patterns to ignore.
        """
        self.watch_path = Path(watch_path)
        self.callback = callback
        self.recursive = recursive
        self.ignore_patterns = ignore_patterns or DEFAULT_IGNORE_PATTERNS

        if tracker_path is None:
            tracker_path = self.watch_path / ".provo_notes_processed.json"
        self.tracker = ProcessedFileTracker(tracker_path)

        self._handler = NotesHandler(
            callback=callback,
            tracker=self.tracker,
            ignore_patterns=self.ignore_patterns,
        )
        self._observer: BaseObserver | None = None

    def start(self) -> None:
        """Start watching the directory."""
        if self._observer is not None:
            return

        if not self.watch_path.exists():
            raise ValueError(f"Watch path does not exist: {self.watch_path}")

        if not self.watch_path.is_dir():
            raise ValueError(f"Watch path is not a directory: {self.watch_path}")

        self._observer = Observer()
        self._observer.schedule(
            self._handler, str(self.watch_path), recursive=self.recursive
        )
        self._observer.start()
        logger.info(f"Started watching notes: {self.watch_path} (recursive={self.recursive})")

    def stop(self) -> None:
        """Stop watching the directory."""
        if self._observer is None:
            return

        self._observer.stop()
        self._observer.join(timeout=5)
        self._observer = None
        logger.info("Stopped watching notes")

    def is_running(self) -> bool:
        """Check if the watcher is running."""
        return self._observer is not None and self._observer.is_alive()

    def process_existing(self) -> int:
        """Process any existing unprocessed markdown files in the directory.

        Returns:
            Number of files processed.
        """
        count = 0
        pattern = "**/*.md" if self.recursive else "*.md"

        for file_path in self.watch_path.glob(pattern):
            # Check if should be ignored
            if self._handler._should_ignore(file_path):
                continue

            if self.tracker.is_processed(file_path):
                continue

            logger.info(f"Processing existing note: {file_path.name}")

            try:
                transcript = parse_markdown(file_path)
                self.tracker.mark_processed(file_path)
                self.callback(transcript, "notes")
                count += 1

            except Exception as e:
                logger.error(f"Failed to process {file_path.name}: {e}")

        # Also check for .markdown extension
        pattern = "**/*.markdown" if self.recursive else "*.markdown"
        for file_path in self.watch_path.glob(pattern):
            if self._handler._should_ignore(file_path):
                continue

            if self.tracker.is_processed(file_path):
                continue

            logger.info(f"Processing existing note: {file_path.name}")

            try:
                transcript = parse_markdown(file_path)
                self.tracker.mark_processed(file_path)
                self.callback(transcript, "notes")
                count += 1

            except Exception as e:
                logger.error(f"Failed to process {file_path.name}: {e}")

        return count

    def __enter__(self) -> "NotesWatcher":
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Context manager exit."""
        self.stop()
