"""Capture mechanisms for different sources."""

from provo.capture.parsers import ParsedTranscript, parse_markdown, parse_txt, parse_vtt
from provo.capture.watcher import NotesWatcher, TranscriptWatcher

__all__ = [
    "ParsedTranscript",
    "parse_vtt",
    "parse_txt",
    "parse_markdown",
    "TranscriptWatcher",
    "NotesWatcher",
]
