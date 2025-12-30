import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api, type Assumption, type AssumptionUpdateData } from '../lib/api';

interface AssumptionToggleProps {
  assumption: Assumption;
  onUpdate?: (assumption: Assumption) => void;
}

export default function AssumptionToggle({ assumption, onUpdate }: AssumptionToggleProps) {
  const queryClient = useQueryClient();

  const updateMutation = useMutation({
    mutationFn: (data: AssumptionUpdateData) => api.assumptions.update(assumption.id, data),
    onSuccess: (updated) => {
      // Invalidate queries to refresh data
      queryClient.invalidateQueries({ queryKey: ['assumptions'] });
      onUpdate?.(updated);
    },
  });

  const handleToggle = (newValue: boolean | null) => {
    // If clicking the same value, set to null (unchecked)
    const value = assumption.still_valid === newValue ? null : newValue;
    updateMutation.mutate({ still_valid: value ?? undefined });
  };

  const statusClass =
    assumption.still_valid === true
      ? 'valid'
      : assumption.still_valid === false
      ? 'invalid'
      : 'unchecked';

  return (
    <div className={`assumption-toggle ${statusClass}`}>
      <div className="toggle-buttons">
        <button
          className={`toggle-btn valid ${assumption.still_valid === true ? 'active' : ''}`}
          onClick={() => handleToggle(true)}
          disabled={updateMutation.isPending}
          title="Mark as valid"
        >
          ✓
        </button>
        <button
          className={`toggle-btn invalid ${assumption.still_valid === false ? 'active' : ''}`}
          onClick={() => handleToggle(false)}
          disabled={updateMutation.isPending}
          title="Mark as invalid"
        >
          ✗
        </button>
      </div>
      <span className="assumption-statement">{assumption.statement}</span>
      <span className="assumption-type">
        {assumption.explicit ? 'explicit' : 'implicit'}
      </span>
      {assumption.still_valid === false && assumption.invalidated_by && (
        <span className="invalidated-note" title="Invalidated by another fragment">
          invalidated
        </span>
      )}
    </div>
  );
}
