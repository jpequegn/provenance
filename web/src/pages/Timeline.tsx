import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, type Fragment } from '../lib/api';
import TimelineCard from '../components/TimelineCard';
import TimelineFilters, {
  type TimelineFilterValues,
} from '../components/TimelineFilters';

const DEFAULT_FILTERS: TimelineFilterValues = {
  project: '',
  dateFrom: '',
  dateTo: '',
};

export default function Timeline() {
  const [filters, setFilters] = useState<TimelineFilterValues>(DEFAULT_FILTERS);

  const { data: fragments, isLoading, error } = useQuery({
    queryKey: ['fragments', 'timeline'],
    queryFn: () => api.fragments.list({ limit: 500 }),
  });

  // Filter fragments based on filter values
  const filteredFragments = useMemo(() => {
    if (!fragments) return [];

    return fragments.filter((fragment) => {
      // Filter by project
      if (filters.project && fragment.project !== filters.project) {
        return false;
      }

      // Filter by date range
      const capturedDate = new Date(fragment.captured_at);
      if (filters.dateFrom) {
        const fromDate = new Date(filters.dateFrom);
        if (capturedDate < fromDate) return false;
      }
      if (filters.dateTo) {
        const toDate = new Date(filters.dateTo);
        toDate.setHours(23, 59, 59, 999);
        if (capturedDate > toDate) return false;
      }

      return true;
    });
  }, [fragments, filters]);

  // Group fragments by date, sorted newest first
  const groupedByDate = useMemo(() => {
    const groups: Record<string, Fragment[]> = {};

    // Sort fragments by date (newest first)
    const sorted = [...filteredFragments].sort(
      (a, b) =>
        new Date(b.captured_at).getTime() - new Date(a.captured_at).getTime()
    );

    for (const fragment of sorted) {
      const date = new Date(fragment.captured_at).toLocaleDateString('en-US', {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      });
      if (!groups[date]) {
        groups[date] = [];
      }
      groups[date].push(fragment);
    }

    // Sort fragments within each day by time (newest first)
    for (const date in groups) {
      groups[date].sort(
        (a, b) =>
          new Date(b.captured_at).getTime() - new Date(a.captured_at).getTime()
      );
    }

    return groups;
  }, [filteredFragments]);

  const dateCount = Object.keys(groupedByDate).length;
  const fragmentCount = filteredFragments.length;

  return (
    <div className="timeline-page">
      <div className="timeline-header-section">
        <h1>Timeline</h1>
        <p className="subtitle">Chronological view of your captured context</p>
      </div>

      <TimelineFilters filters={filters} onChange={setFilters} />

      {isLoading ? (
        <div className="loading">Loading timeline...</div>
      ) : error ? (
        <div className="error">Failed to load timeline. Is the API running?</div>
      ) : !fragments?.length ? (
        <div className="empty-state">
          <p>No fragments captured yet.</p>
          <p className="hint">
            Start capturing context with the CLI:
            <code>provo capture "Your context here"</code>
          </p>
        </div>
      ) : filteredFragments.length === 0 ? (
        <div className="empty-state">
          <p>No fragments match your filters.</p>
          <p className="hint">
            {fragments.length} fragments available. Try adjusting your filters.
          </p>
        </div>
      ) : (
        <>
          <div className="timeline-stats">
            <span>
              Showing {fragmentCount} fragment{fragmentCount !== 1 ? 's' : ''}{' '}
              across {dateCount} day{dateCount !== 1 ? 's' : ''}
            </span>
            {fragments.length !== filteredFragments.length && (
              <span className="filtered-note">
                ({fragments.length - filteredFragments.length} filtered out)
              </span>
            )}
          </div>

          <div className="timeline">
            {Object.entries(groupedByDate).map(([date, dateFragments]) => (
              <div key={date} className="timeline-day-group">
                <div className="timeline-date-header">
                  <h2>{date}</h2>
                  <span className="day-count">
                    {dateFragments.length} fragment
                    {dateFragments.length !== 1 ? 's' : ''}
                  </span>
                </div>
                <div className="timeline-day-content">
                  {dateFragments.map((fragment) => (
                    <TimelineCard key={fragment.id} fragment={fragment} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
