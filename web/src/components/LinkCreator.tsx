import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type Fragment, type FragmentLinkData } from '../lib/api';
import { truncateText } from '../lib/highlight';

interface LinkCreatorProps {
  sourceFragment: Fragment;
  onClose: () => void;
}

const LINK_TYPES = [
  { value: 'relates_to', label: 'Relates to', description: 'General relationship' },
  { value: 'references', label: 'References', description: 'Source references target' },
  { value: 'follows', label: 'Follows', description: 'Source follows target in sequence' },
  { value: 'contradicts', label: 'Contradicts', description: 'Source contradicts target' },
  { value: 'invalidates', label: 'Invalidates', description: 'Source invalidates target' },
];

export default function LinkCreator({ sourceFragment, onClose }: LinkCreatorProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTargetId, setSelectedTargetId] = useState<string | null>(null);
  const [linkType, setLinkType] = useState('relates_to');
  const [strength, setStrength] = useState(0.8);

  const queryClient = useQueryClient();

  // Search for fragments to link to
  const { data: searchResults } = useQuery({
    queryKey: ['fragments', 'search', searchQuery],
    queryFn: () => api.fragments.list({ limit: 20 }),
    enabled: true,
  });

  // Filter results to exclude source fragment and match search query
  const filteredResults = searchResults?.filter((f) => {
    if (f.id === sourceFragment.id) return false;
    if (!searchQuery) return true;
    const query = searchQuery.toLowerCase();
    return (
      f.content.toLowerCase().includes(query) ||
      f.project?.toLowerCase().includes(query) ||
      f.topics.some((t) => t.toLowerCase().includes(query))
    );
  });

  const createLinkMutation = useMutation({
    mutationFn: (data: FragmentLinkData) =>
      api.fragments.createLink(sourceFragment.id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['related'] });
      queryClient.invalidateQueries({ queryKey: ['fragments'] });
      onClose();
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedTargetId) return;

    createLinkMutation.mutate({
      target_id: selectedTargetId,
      link_type: linkType,
      strength,
    });
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content modal-large" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Link Fragment</h3>
          <button className="modal-close" onClick={onClose}>
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Source Fragment</label>
            <div className="fragment-preview">
              {truncateText(sourceFragment.content, 100)}
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="search">Search for Target Fragment</label>
            <input
              type="text"
              id="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by content, project, or topic..."
            />
          </div>

          <div className="form-group">
            <label>Select Target</label>
            <div className="fragment-list-select">
              {filteredResults?.length === 0 ? (
                <div className="no-results">No fragments found</div>
              ) : (
                filteredResults?.map((fragment) => (
                  <div
                    key={fragment.id}
                    className={`fragment-option ${
                      selectedTargetId === fragment.id ? 'selected' : ''
                    }`}
                    onClick={() => setSelectedTargetId(fragment.id)}
                  >
                    <div className="fragment-option-content">
                      {truncateText(fragment.content, 80)}
                    </div>
                    <div className="fragment-option-meta">
                      {fragment.project && (
                        <span className="project">{fragment.project}</span>
                      )}
                      {fragment.topics.slice(0, 2).map((topic) => (
                        <span key={topic} className="topic-tag">
                          {topic}
                        </span>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label htmlFor="link-type">Link Type</label>
              <select
                id="link-type"
                value={linkType}
                onChange={(e) => setLinkType(e.target.value)}
              >
                {LINK_TYPES.map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                  </option>
                ))}
              </select>
              <span className="form-hint">
                {LINK_TYPES.find((t) => t.value === linkType)?.description}
              </span>
            </div>

            <div className="form-group">
              <label htmlFor="strength">Strength</label>
              <div className="strength-input">
                <input
                  type="range"
                  id="strength"
                  min="0"
                  max="1"
                  step="0.1"
                  value={strength}
                  onChange={(e) => setStrength(parseFloat(e.target.value))}
                />
                <span className="strength-value">{(strength * 100).toFixed(0)}%</span>
              </div>
            </div>
          </div>

          <div className="modal-actions">
            <button type="button" className="btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary"
              disabled={!selectedTargetId || createLinkMutation.isPending}
            >
              {createLinkMutation.isPending ? 'Creating...' : 'Create Link'}
            </button>
          </div>

          {createLinkMutation.isError && (
            <div className="form-error">Failed to create link. Please try again.</div>
          )}
        </form>
      </div>
    </div>
  );
}
