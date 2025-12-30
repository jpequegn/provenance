import { useState, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import SearchBox from '../components/SearchBox';
import SearchResultCard from '../components/SearchResultCard';
import SearchFilters, { type SearchFilterValues } from '../components/SearchFilters';
import { useDebounce } from '../hooks/useDebounce';

const DEFAULT_FILTERS: SearchFilterValues = {
  sourceType: '',
  project: '',
  dateFrom: '',
  dateTo: '',
};

export default function Search() {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get('q') || '';
  const [searchValue, setSearchValue] = useState(query);
  const [filters, setFilters] = useState<SearchFilterValues>(DEFAULT_FILTERS);
  const [searchTime, setSearchTime] = useState<number | null>(null);

  // Debounce the search value for real-time search
  const debouncedQuery = useDebounce(searchValue, 200);

  // Update URL when debounced query changes
  useEffect(() => {
    if (debouncedQuery.trim() && debouncedQuery !== query) {
      setSearchParams({ q: debouncedQuery });
    }
  }, [debouncedQuery, query, setSearchParams]);

  // Sync input with URL on navigation
  useEffect(() => {
    setSearchValue(query);
  }, [query]);

  const { data: results, isLoading, error, isFetching } = useQuery({
    queryKey: ['search', debouncedQuery],
    queryFn: async () => {
      const startTime = performance.now();
      const result = await api.search.query({ q: debouncedQuery, limit: 50 });
      const endTime = performance.now();
      setSearchTime(endTime - startTime);
      return result;
    },
    enabled: !!debouncedQuery.trim(),
  });

  // Filter results client-side based on filter values
  const filteredResults = useMemo(() => {
    if (!results?.results) return [];

    return results.results.filter((result) => {
      // Filter by source type
      if (filters.sourceType && result.source_type !== filters.sourceType) {
        return false;
      }

      // Filter by project
      if (filters.project && result.project !== filters.project) {
        return false;
      }

      // Filter by date range
      const capturedDate = new Date(result.captured_at);
      if (filters.dateFrom) {
        const fromDate = new Date(filters.dateFrom);
        if (capturedDate < fromDate) return false;
      }
      if (filters.dateTo) {
        const toDate = new Date(filters.dateTo);
        toDate.setHours(23, 59, 59, 999); // End of day
        if (capturedDate > toDate) return false;
      }

      return true;
    });
  }, [results?.results, filters]);

  const handleSearch = (newQuery: string) => {
    if (newQuery.trim()) {
      setSearchParams({ q: newQuery });
    }
  };

  const handleRelatedClick = (fragmentId: string) => {
    // Could navigate to fragment detail or highlight it
    console.log('Related fragment clicked:', fragmentId);
  };

  return (
    <div className="search-page">
      <SearchBox
        value={searchValue}
        onChange={setSearchValue}
        onSubmit={handleSearch}
        placeholder="Search your context..."
        autoFocus
      />

      <SearchFilters filters={filters} onChange={setFilters} />

      {debouncedQuery.trim() && (
        <div className="search-results">
          <h2>
            Results for "{debouncedQuery}"
            {filteredResults.length > 0 && (
              <span className="count"> ({filteredResults.length})</span>
            )}
          </h2>

          {searchTime !== null && !isFetching && filteredResults.length > 0 && (
            <div className="search-stats">
              <span>
                Found {filteredResults.length} results in{' '}
                <span className="time">{searchTime.toFixed(0)}ms</span>
              </span>
              {filteredResults.length !== results?.results.length && (
                <span>
                  ({results?.results.length} total, {filteredResults.length} after
                  filters)
                </span>
              )}
            </div>
          )}

          {isLoading || isFetching ? (
            <div className="loading">Searching...</div>
          ) : error ? (
            <div className="error">Failed to search. Is the API running?</div>
          ) : filteredResults.length === 0 ? (
            <div className="empty-state">
              <p>No results found for "{debouncedQuery}"</p>
              {results?.results.length !== filteredResults.length && (
                <p className="hint">
                  Try adjusting your filters - {results?.results.length} results
                  were filtered out.
                </p>
              )}
            </div>
          ) : (
            <div className="fragment-list">
              {filteredResults.map((result) => (
                <SearchResultCard
                  key={result.id}
                  result={result}
                  query={debouncedQuery}
                  onRelatedClick={handleRelatedClick}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
