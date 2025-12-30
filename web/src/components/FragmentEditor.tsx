import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api, type Fragment, type FragmentUpdateData } from '../lib/api';

interface FragmentEditorProps {
  fragment: Fragment;
  onClose: () => void;
}

export default function FragmentEditor({ fragment, onClose }: FragmentEditorProps) {
  const [project, setProject] = useState(fragment.project || '');
  const [topics, setTopics] = useState(fragment.topics.join(', '));
  const [summary, setSummary] = useState(fragment.summary || '');

  const queryClient = useQueryClient();

  const updateMutation = useMutation({
    mutationFn: (data: FragmentUpdateData) => api.fragments.update(fragment.id, data),
    onSuccess: () => {
      // Invalidate queries to refresh data
      queryClient.invalidateQueries({ queryKey: ['fragments'] });
      queryClient.invalidateQueries({ queryKey: ['search'] });
      onClose();
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    const data: FragmentUpdateData = {};

    // Only include changed fields
    if (project !== (fragment.project || '')) {
      data.project = project || undefined;
    }

    const newTopics = topics
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);
    if (JSON.stringify(newTopics) !== JSON.stringify(fragment.topics)) {
      data.topics = newTopics;
    }

    if (summary !== (fragment.summary || '')) {
      data.summary = summary || undefined;
    }

    // Only update if there are changes
    if (Object.keys(data).length > 0) {
      updateMutation.mutate(data);
    } else {
      onClose();
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Edit Fragment</h3>
          <button className="modal-close" onClick={onClose}>
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="project">Project</label>
            <input
              type="text"
              id="project"
              value={project}
              onChange={(e) => setProject(e.target.value)}
              placeholder="Enter project name"
            />
          </div>

          <div className="form-group">
            <label htmlFor="topics">Topics</label>
            <input
              type="text"
              id="topics"
              value={topics}
              onChange={(e) => setTopics(e.target.value)}
              placeholder="Enter topics, separated by commas"
            />
            <span className="form-hint">Separate multiple topics with commas</span>
          </div>

          <div className="form-group">
            <label htmlFor="summary">Summary</label>
            <textarea
              id="summary"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="Enter a summary of this fragment"
              rows={3}
            />
          </div>

          <div className="modal-actions">
            <button type="button" className="btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary"
              disabled={updateMutation.isPending}
            >
              {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
            </button>
          </div>

          {updateMutation.isError && (
            <div className="form-error">
              Failed to update fragment. Please try again.
            </div>
          )}
        </form>
      </div>
    </div>
  );
}
