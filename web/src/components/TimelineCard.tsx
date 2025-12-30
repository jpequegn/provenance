import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { Fragment, Decision } from '../lib/api';
import { api } from '../lib/api';
import { truncateText } from '../lib/highlight';
import FragmentEditor from './FragmentEditor';
import LinkCreator from './LinkCreator';
import AssumptionToggle from './AssumptionToggle';

const SOURCE_ICONS: Record<string, string> = {
  quick_capture: '📍',
  zoom: '🎥',
  teams: '💬',
  notes: '📝',
};

const SOURCE_LABELS: Record<string, string> = {
  quick_capture: 'Quick Capture',
  zoom: 'Zoom',
  teams: 'Teams',
  notes: 'Notes',
};

interface TimelineCardProps {
  fragment: Fragment;
}

export default function TimelineCard({ fragment }: TimelineCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [showEditor, setShowEditor] = useState(false);
  const [showLinkCreator, setShowLinkCreator] = useState(false);

  const icon = SOURCE_ICONS[fragment.source_type] || '📄';
  const sourceLabel = SOURCE_LABELS[fragment.source_type] || fragment.source_type;
  const time = new Date(fragment.captured_at).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });

  // Fetch decisions for this fragment when expanded
  const { data: decisions } = useQuery({
    queryKey: ['decisions', fragment.id],
    queryFn: () => api.decisions.list({ limit: 20 }),
    enabled: isExpanded,
    select: (data) => data.filter((d) => d.fragment_id === fragment.id),
  });

  // Fetch assumptions for this fragment when expanded
  const { data: assumptions, refetch: refetchAssumptions } = useQuery({
    queryKey: ['assumptions', fragment.id],
    queryFn: () => api.assumptions.list({ limit: 20 }),
    enabled: isExpanded,
    select: (data) => data.filter((a) => a.fragment_id === fragment.id),
  });

  const decisionsCount = decisions?.length || 0;
  const assumptionsCount = assumptions?.length || 0;

  const displayContent = isExpanded
    ? fragment.content
    : truncateText(fragment.content, 150);

  const handleActionClick = (e: React.MouseEvent, action: () => void) => {
    e.stopPropagation();
    action();
  };

  return (
    <>
      <div
        className={`timeline-card ${isExpanded ? 'expanded' : ''}`}
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="timeline-connector">
          <div className="timeline-dot" />
          <div className="timeline-line" />
        </div>

        <div className="timeline-content">
          <div className="timeline-header">
            <span className="source-icon" title={sourceLabel}>
              {icon}
            </span>
            <span className="source-label">
              {sourceLabel}
              {fragment.source_ref && `: ${fragment.source_ref}`}
            </span>
            <span className="time">{time}</span>
            <span className="expand-icon">{isExpanded ? '▼' : '▶'}</span>
          </div>

          <div className="timeline-body">
            <p className="fragment-text">{displayContent}</p>

            {fragment.topics.length > 0 && (
              <div className="topics">
                {fragment.topics.map((topic) => (
                  <span key={topic} className="topic-tag">
                    {topic}
                  </span>
                ))}
              </div>
            )}

            {/* Inline summary of decisions/assumptions when collapsed */}
            {!isExpanded && (decisionsCount > 0 || assumptionsCount > 0) && (
              <div className="inline-summary">
                {decisionsCount > 0 && (
                  <span className="summary-badge decisions">
                    {decisionsCount} decision{decisionsCount !== 1 ? 's' : ''}
                  </span>
                )}
                {assumptionsCount > 0 && (
                  <span className="summary-badge assumptions">
                    {assumptionsCount} assumption{assumptionsCount !== 1 ? 's' : ''}
                  </span>
                )}
              </div>
            )}
          </div>

          {isExpanded && (
            <div className="timeline-details" onClick={(e) => e.stopPropagation()}>
              {/* Action Buttons */}
              <div className="annotation-actions">
                <button
                  className="action-btn"
                  onClick={(e) => handleActionClick(e, () => setShowEditor(true))}
                  title="Edit fragment metadata"
                >
                  ✏️ Edit
                </button>
                <button
                  className="action-btn"
                  onClick={(e) => handleActionClick(e, () => setShowLinkCreator(true))}
                  title="Link to another fragment"
                >
                  🔗 Link
                </button>
              </div>

              {/* Decisions Section */}
              {decisions && decisions.length > 0 && (
                <div className="detail-section">
                  <h4>Decisions</h4>
                  <ul className="detail-list">
                    {decisions.map((decision) => (
                      <DecisionItem key={decision.id} decision={decision} />
                    ))}
                  </ul>
                </div>
              )}

              {/* Assumptions Section with Toggle */}
              {assumptions && assumptions.length > 0 && (
                <div className="detail-section">
                  <h4>Assumptions</h4>
                  <ul className="detail-list assumptions-toggleable">
                    {assumptions.map((assumption) => (
                      <li key={assumption.id}>
                        <AssumptionToggle
                          assumption={assumption}
                          onUpdate={() => refetchAssumptions()}
                        />
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Empty state when expanded but no details */}
              {(!decisions || decisions.length === 0) &&
                (!assumptions || assumptions.length === 0) && (
                  <div className="no-details">
                    No decisions or assumptions found for this fragment.
                  </div>
                )}
            </div>
          )}
        </div>
      </div>

      {/* Modals */}
      {showEditor && (
        <FragmentEditor
          fragment={fragment}
          onClose={() => setShowEditor(false)}
        />
      )}
      {showLinkCreator && (
        <LinkCreator
          sourceFragment={fragment}
          onClose={() => setShowLinkCreator(false)}
        />
      )}
    </>
  );
}

function DecisionItem({ decision }: { decision: Decision }) {
  const confidenceClass =
    decision.confidence >= 0.8
      ? 'high'
      : decision.confidence >= 0.5
      ? 'medium'
      : 'low';

  return (
    <li className="decision-item">
      <span className="decision-icon">✓</span>
      <div className="decision-content">
        <span className="decision-what">{decision.what}</span>
        {decision.why && (
          <span className="decision-why">Because: {decision.why}</span>
        )}
      </div>
      <span className={`confidence ${confidenceClass}`}>
        {(decision.confidence * 100).toFixed(0)}%
      </span>
    </li>
  );
}
