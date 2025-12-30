import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import FragmentCard from '../components/FragmentCard';

export default function Timeline() {
  const { data: fragments, isLoading, error } = useQuery({
    queryKey: ['fragments', 'timeline'],
    queryFn: () => api.fragments.list({ limit: 50 }),
  });

  // Group fragments by date
  const groupedByDate = fragments?.reduce((acc, fragment) => {
    const date = new Date(fragment.captured_at).toLocaleDateString('en-US', {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
    if (!acc[date]) {
      acc[date] = [];
    }
    acc[date].push(fragment);
    return acc;
  }, {} as Record<string, typeof fragments>);

  return (
    <div className="timeline-page">
      <h1>Timeline</h1>
      <p className="subtitle">Chronological view of your captured context</p>

      {isLoading ? (
        <div className="loading">Loading timeline...</div>
      ) : error ? (
        <div className="error">
          Failed to load timeline. Is the API running?
        </div>
      ) : !fragments?.length ? (
        <div className="empty-state">
          <p>No fragments captured yet.</p>
        </div>
      ) : (
        <div className="timeline">
          {Object.entries(groupedByDate || {}).map(([date, dateFragments]) => (
            <div key={date} className="timeline-group">
              <h2 className="timeline-date">{date}</h2>
              <div className="fragment-list">
                {dateFragments?.map((fragment) => (
                  <FragmentCard key={fragment.id} fragment={fragment} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
