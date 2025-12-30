import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';

export interface TimelineFilterValues {
  project: string;
  dateFrom: string;
  dateTo: string;
}

interface TimelineFiltersProps {
  filters: TimelineFilterValues;
  onChange: (filters: TimelineFilterValues) => void;
}

export default function TimelineFilters({
  filters,
  onChange,
}: TimelineFiltersProps) {
  // Fetch unique projects from fragments
  const { data: fragments } = useQuery({
    queryKey: ['fragments', 'all'],
    queryFn: () => api.fragments.list({ limit: 1000 }),
  });

  const projects = fragments
    ? Array.from(
        new Set(fragments.map((f) => f.project).filter((p): p is string => !!p))
      )
    : [];

  const handleChange = (field: keyof TimelineFilterValues, value: string) => {
    onChange({
      ...filters,
      [field]: value,
    });
  };

  const handleClear = () => {
    onChange({
      project: '',
      dateFrom: '',
      dateTo: '',
    });
  };

  const hasFilters = filters.project || filters.dateFrom || filters.dateTo;

  // Quick date presets
  const setDatePreset = (days: number) => {
    const today = new Date();
    const fromDate = new Date();
    fromDate.setDate(today.getDate() - days);

    onChange({
      ...filters,
      dateFrom: fromDate.toISOString().split('T')[0],
      dateTo: today.toISOString().split('T')[0],
    });
  };

  return (
    <div className="timeline-filters">
      <div className="filter-row">
        <div className="filter-group">
          <label htmlFor="project">Project</label>
          <select
            id="project"
            value={filters.project}
            onChange={(e) => handleChange('project', e.target.value)}
          >
            <option value="">All Projects</option>
            {projects.map((project) => (
              <option key={project} value={project}>
                {project}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label htmlFor="date-from">From</label>
          <input
            type="date"
            id="date-from"
            value={filters.dateFrom}
            onChange={(e) => handleChange('dateFrom', e.target.value)}
          />
        </div>

        <div className="filter-group">
          <label htmlFor="date-to">To</label>
          <input
            type="date"
            id="date-to"
            value={filters.dateTo}
            onChange={(e) => handleChange('dateTo', e.target.value)}
          />
        </div>

        {hasFilters && (
          <button className="clear-filters" onClick={handleClear}>
            Clear
          </button>
        )}
      </div>

      <div className="date-presets">
        <span className="presets-label">Quick:</span>
        <button
          className="preset-button"
          onClick={() => setDatePreset(7)}
          title="Last 7 days"
        >
          Week
        </button>
        <button
          className="preset-button"
          onClick={() => setDatePreset(30)}
          title="Last 30 days"
        >
          Month
        </button>
        <button
          className="preset-button"
          onClick={() => setDatePreset(90)}
          title="Last 90 days"
        >
          Quarter
        </button>
      </div>
    </div>
  );
}
