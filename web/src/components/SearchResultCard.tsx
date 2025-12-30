import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { SearchResult, Decision, Assumption, RelatedFragment } from '../lib/api';
import { api } from '../lib/api';
import { highlightText, truncateText } from '../lib/highlight';

const SOURCE_ICONS: Record<string, string> = {
  quick_capture: '📍',
  zoom: '🎥',
  teams: '💬',
  notes: '📝',
};

interface SearchResultCardProps {
  result: SearchResult;
  query: string;
  onRelatedClick?: (fragmentId: string) => void;
}

export default function SearchResultCard({
  result,
  query,
  onRelatedClick,
}: SearchResultCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const icon = SOURCE_ICONS[result.source_type] || '📄';
  const date = new Date(result.captured_at).toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });

  // Fetch decisions for this fragment when expanded
  const { data: decisions } = useQuery({
    queryKey: ['decisions', result.id],
    queryFn: () => api.decisions.list({ limit: 10 }),
    enabled: isExpanded,
    select: (data) => data.filter((d) => d.fragment_id === result.id),
  });

  // Fetch assumptions for this fragment when expanded
  const { data: assumptions } = useQuery({
    queryKey: ['assumptions', result.id],
    queryFn: () => api.assumptions.list({ limit: 10 }),
    enabled: isExpanded,
    select: (data) => data.filter((a) => a.fragment_id === result.id),
  });

  // Fetch related fragments when expanded
  const { data: related } = useQuery({
    queryKey: ['related', result.id],
    queryFn: () => api.fragments.getRelated(result.id, { limit: 5 }),
    enabled: isExpanded,
  });

  const displayContent = isExpanded
    ? result.content
    : truncateText(result.content, 200);

  return (
    <div
      className={`search-result-card ${isExpanded ? 'expanded' : ''}`}
      onClick={() => setIsExpanded(!isExpanded)}
    >
      <div className="result-header">
        <span className="source-icon" title={result.source_type.replace('_', ' ')}>
          {icon}
        </span>
        <span className="date">{date}</span>
        <span className="score" title="Similarity score">
          {(result.score * 100).toFixed(0)}%
        </span>
        {result.project && <span className="project">{result.project}</span>}
        <span className="expand-icon">{isExpanded ? '▼' : '▶'}</span>
      </div>

      <div className="result-content">
        {highlightText(displayContent, query)}
      </div>

      {result.topics.length > 0 && (
        <div className="result-topics">
          {result.topics.map((topic) => (
            <span key={topic} className="topic-tag">
              {topic}
            </span>
          ))}
        </div>
      )}

      {isExpanded && (
        <div className="result-details" onClick={(e) => e.stopPropagation()}>
          {/* Decisions Section */}
          {decisions && decisions.length > 0 && (
            <div className="decisions-section">
              <h4>Decisions</h4>
              <ul className="decisions-list">
                {decisions.map((decision) => (
                  <DecisionItem key={decision.id} decision={decision} />
                ))}
              </ul>
            </div>
          )}

          {/* Assumptions Section */}
          {assumptions && assumptions.length > 0 && (
            <div className="assumptions-section">
              <h4>Assumptions</h4>
              <ul className="assumptions-list">
                {assumptions.map((assumption) => (
                  <AssumptionItem key={assumption.id} assumption={assumption} />
                ))}
              </ul>
            </div>
          )}

          {/* Related Fragments Section */}
          {related && related.related.length > 0 && (
            <div className="related-section">
              <h4>Related Fragments</h4>
              <ul className="related-list">
                {related.related.map((fragment) => (
                  <RelatedItem
                    key={fragment.id}
                    fragment={fragment}
                    onClick={() => onRelatedClick?.(fragment.id)}
                  />
                ))}
              </ul>
            </div>
          )}

          {/* Empty State */}
          {(!decisions || decisions.length === 0) &&
            (!assumptions || assumptions.length === 0) &&
            (!related || related.related.length === 0) && (
              <div className="no-details">
                No decisions, assumptions, or related fragments found.
              </div>
            )}
        </div>
      )}
    </div>
  );
}

function DecisionItem({ decision }: { decision: Decision }) {
  const confidence = (decision.confidence * 100).toFixed(0);
  const confidenceClass =
    decision.confidence >= 0.8
      ? 'high'
      : decision.confidence >= 0.5
      ? 'medium'
      : 'low';

  return (
    <li className="decision-item">
      <div className="decision-header">
        <span className="decision-icon">✓</span>
        <span className={`confidence ${confidenceClass}`}>{confidence}%</span>
      </div>
      <div className="decision-what">{decision.what}</div>
      {decision.why && <div className="decision-why">Because: {decision.why}</div>}
    </li>
  );
}

function AssumptionItem({ assumption }: { assumption: Assumption }) {
  const statusClass =
    assumption.still_valid === true
      ? 'valid'
      : assumption.still_valid === false
      ? 'invalid'
      : 'unchecked';

  const statusIcon =
    assumption.still_valid === true
      ? '✓'
      : assumption.still_valid === false
      ? '✗'
      : '?';

  return (
    <li className={`assumption-item ${statusClass}`}>
      <span className="assumption-icon">{statusIcon}</span>
      <span className="assumption-statement">{assumption.statement}</span>
      <span className="assumption-type">
        {assumption.explicit ? 'explicit' : 'implicit'}
      </span>
    </li>
  );
}

function RelatedItem({
  fragment,
  onClick,
}: {
  fragment: RelatedFragment;
  onClick?: () => void;
}) {
  const icon = SOURCE_ICONS[fragment.source_type] || '📄';
  const strength = (fragment.strength * 100).toFixed(0);

  return (
    <li className="related-item" onClick={onClick}>
      <span className="related-icon">{icon}</span>
      <span className="related-content">{truncateText(fragment.content, 80)}</span>
      <span className="related-strength">{strength}%</span>
    </li>
  );
}
