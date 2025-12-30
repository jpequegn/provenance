import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';

export interface SearchFilterValues {
  sourceType: string;
  project: string;
  dateFrom: string;
  dateTo: string;
}

interface SearchFiltersProps {
  filters: SearchFilterValues;
  onChange: (filters: SearchFilterValues) => void;
}

const SOURCE_TYPES = [
  { value: '', label: 'All Sources' },
  { value: 'quick_capture', label: 'Quick Capture' },
  { value: 'zoom', label: 'Zoom Meeting' },
  { value: 'teams', label: 'Teams Meeting' },
  { value: 'notes', label: 'Notes' },
];

export default function SearchFilters({ filters, onChange }: SearchFiltersProps) {
  // Fetch unique projects from fragments
  const { data: fragments } = useQuery({
    queryKey: ['fragments', 'all'],
    queryFn: () => api.fragments.list({ limit: 1000 }),
  });

  const projects = fragments
    ? Array.from(new Set(fragments.map((f) => f.project).filter((p): p is string => !!p)))
    : [];

  const handleChange = (field: keyof SearchFilterValues, value: string) => {
    onChange({
      ...filters,
      [field]: value,
    });
  };

  const handleClear = () => {
    onChange({
      sourceType: '',
      project: '',
      dateFrom: '',
      dateTo: '',
    });
  };

  const hasFilters =
    filters.sourceType || filters.project || filters.dateFrom || filters.dateTo;

  return (
    <div className="search-filters">
      <div className="filter-group">
        <label htmlFor="source-type">Source Type</label>
        <select
          id="source-type"
          value={filters.sourceType}
          onChange={(e) => handleChange('sourceType', e.target.value)}
        >
          {SOURCE_TYPES.map((type) => (
            <option key={type.value} value={type.value}>
              {type.label}
            </option>
          ))}
        </select>
      </div>

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
        <label htmlFor="date-from">From Date</label>
        <input
          type="date"
          id="date-from"
          value={filters.dateFrom}
          onChange={(e) => handleChange('dateFrom', e.target.value)}
        />
      </div>

      <div className="filter-group">
        <label htmlFor="date-to">To Date</label>
        <input
          type="date"
          id="date-to"
          value={filters.dateTo}
          onChange={(e) => handleChange('dateTo', e.target.value)}
        />
      </div>

      {hasFilters && (
        <button className="clear-filters" onClick={handleClear}>
          Clear Filters
        </button>
      )}
    </div>
  );
}
