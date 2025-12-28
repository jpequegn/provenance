"""Parsers for different transcript formats."""

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TranscriptSegment:
    """A segment of a transcript with optional timing and speaker info."""

    text: str
    start_time: float | None = None  # seconds
    end_time: float | None = None  # seconds
    speaker: str | None = None


@dataclass
class ParsedTranscript:
    """A parsed transcript with metadata and segments."""

    content: str  # Full text content
    segments: list[TranscriptSegment] = field(default_factory=list)
    participants: list[str] = field(default_factory=list)
    source_file: str | None = None


def parse_vtt_timestamp(timestamp: str) -> float:
    """Parse a VTT timestamp (HH:MM:SS.mmm) to seconds.

    Supports formats:
    - HH:MM:SS.mmm
    - MM:SS.mmm
    """
    parts = timestamp.strip().split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
    elif len(parts) == 2:
        minutes, seconds = parts
        return float(minutes) * 60 + float(seconds)
    else:
        return float(timestamp)


def parse_vtt(file_path: Path | str) -> ParsedTranscript:
    """Parse a WebVTT transcript file.

    VTT format example:
    ```
    WEBVTT

    00:00:01.000 --> 00:00:05.000
    Speaker 1: Let's discuss the architecture...

    00:00:05.500 --> 00:00:10.000
    Speaker 2: I think we should use microservices...
    ```
    """
    file_path = Path(file_path)
    content = file_path.read_text(encoding="utf-8")

    segments: list[TranscriptSegment] = []
    participants: set[str] = set()
    full_text_parts: list[str] = []

    # Pattern to match timestamp lines: 00:00:01.000 --> 00:00:05.000
    timestamp_pattern = re.compile(
        r"(\d{1,2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})\s*-->\s*"
        r"(\d{1,2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})"
    )

    # Pattern to match speaker label: "Speaker Name:" at start of text
    speaker_pattern = re.compile(r"^([^:]+):\s*(.*)$")

    lines = content.split("\n")
    i = 0

    # Skip WEBVTT header
    while i < len(lines) and not lines[i].strip().startswith("WEBVTT"):
        i += 1
    if i < len(lines):
        i += 1  # Skip the WEBVTT line

    while i < len(lines):
        line = lines[i].strip()

        # Look for timestamp line
        timestamp_match = timestamp_pattern.match(line)
        if timestamp_match:
            start_time = parse_vtt_timestamp(timestamp_match.group(1))
            end_time = parse_vtt_timestamp(timestamp_match.group(2))

            # Collect text lines until empty line or next timestamp
            i += 1
            text_parts: list[str] = []
            while i < len(lines) and lines[i].strip():
                text_line = lines[i].strip()
                # Check for next timestamp
                if timestamp_pattern.match(text_line):
                    break
                text_parts.append(text_line)
                i += 1

            text = " ".join(text_parts)
            if text:
                speaker = None
                # Check for speaker label
                speaker_match = speaker_pattern.match(text)
                if speaker_match:
                    speaker = speaker_match.group(1).strip()
                    text = speaker_match.group(2).strip()
                    participants.add(speaker)

                segments.append(
                    TranscriptSegment(
                        text=text,
                        start_time=start_time,
                        end_time=end_time,
                        speaker=speaker,
                    )
                )

                # Build full text with speaker prefix if present
                if speaker:
                    full_text_parts.append(f"{speaker}: {text}")
                else:
                    full_text_parts.append(text)
        else:
            i += 1

    full_content = "\n\n".join(full_text_parts)

    return ParsedTranscript(
        content=full_content,
        segments=segments,
        participants=sorted(participants),
        source_file=str(file_path),
    )


def parse_txt(file_path: Path | str) -> ParsedTranscript:
    """Parse a plain text transcript file.

    Plain text format assumes:
    - Each paragraph is a separate segment
    - Optional speaker labels in format "Speaker: text"
    """
    file_path = Path(file_path)
    content = file_path.read_text(encoding="utf-8")

    segments: list[TranscriptSegment] = []
    participants: set[str] = set()

    # Pattern to match speaker label: "Speaker Name:" at start of line
    speaker_pattern = re.compile(r"^([^:]+):\s*(.*)$")

    # Split into paragraphs (double newline separated)
    paragraphs = re.split(r"\n\s*\n", content.strip())

    for paragraph in paragraphs:
        text = paragraph.strip()
        if not text:
            continue

        speaker = None
        # Check for speaker label
        speaker_match = speaker_pattern.match(text)
        if speaker_match:
            potential_speaker = speaker_match.group(1).strip()
            # Only treat as speaker if it looks like a name (not too long)
            if len(potential_speaker) < 50 and not potential_speaker.count(" ") > 3:
                speaker = potential_speaker
                text = speaker_match.group(2).strip()
                participants.add(speaker)

        if text:
            segments.append(
                TranscriptSegment(
                    text=text,
                    speaker=speaker,
                )
            )

    return ParsedTranscript(
        content=content.strip(),
        segments=segments,
        participants=sorted(participants),
        source_file=str(file_path),
    )
