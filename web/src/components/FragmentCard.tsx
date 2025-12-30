import type { Fragment } from '../lib/api';

const SOURCE_ICONS: Record<string, string> = {
  quick_capture: '📍',
  zoom: '🎥',
  teams: '💬',
  notes: '📝',
};

interface FragmentCardProps {
  fragment: Fragment;
  score?: number;
}

export default function FragmentCard({ fragment, score }: FragmentCardProps) {
  const icon = SOURCE_ICONS[fragment.source_type] || '📄';
  const date = new Date(fragment.captured_at).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });

  return (
    <div className="fragment-card">
      <div className="fragment-header">
        <span className="source-icon" title={fragment.source_type.replace('_', ' ')}>
          {icon}
        </span>
        <span className="date">{date}</span>
        {score !== undefined && (
          <span className="score" title="Similarity score">
            {(score * 100).toFixed(0)}%
          </span>
        )}
        {fragment.project && (
          <span className="project">{fragment.project}</span>
        )}
      </div>
      <div className="fragment-content">
        {fragment.content}
      </div>
      {fragment.topics.length > 0 && (
        <div className="fragment-topics">
          {fragment.topics.map((topic) => (
            <span key={topic} className="topic-tag">
              {topic}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
