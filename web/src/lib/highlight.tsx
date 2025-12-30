import { ReactNode } from 'react';

/**
 * Highlights matching text within content.
 * Returns an array of React nodes with highlighted spans.
 */
export function highlightText(content: string, query: string): ReactNode[] {
  if (!query.trim()) {
    return [content];
  }

  // Split query into words for partial matching
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) {
    return [content];
  }

  // Create a regex that matches any of the search words
  const pattern = words.map(word => escapeRegExp(word)).join('|');
  const regex = new RegExp(`(${pattern})`, 'gi');

  const parts = content.split(regex);

  return parts.map((part, index) => {
    const isMatch = words.some(word =>
      part.toLowerCase() === word.toLowerCase()
    );

    if (isMatch) {
      return (
        <mark key={index} className="highlight">
          {part}
        </mark>
      );
    }

    return part;
  });
}

/**
 * Escape special regex characters in a string.
 */
function escapeRegExp(string: string): string {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Truncate text to a maximum length with ellipsis.
 * Tries to truncate at word boundaries.
 */
export function truncateText(text: string, maxLength: number = 200): string {
  if (text.length <= maxLength) {
    return text;
  }

  // Find the last space before maxLength
  const truncated = text.slice(0, maxLength);
  const lastSpace = truncated.lastIndexOf(' ');

  if (lastSpace > maxLength * 0.7) {
    return truncated.slice(0, lastSpace) + '...';
  }

  return truncated + '...';
}
