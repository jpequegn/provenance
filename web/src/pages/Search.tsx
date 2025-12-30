import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import FragmentCard from '../components/FragmentCard';
import SearchBox from '../components/SearchBox';

export default function Search() {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get('q') || '';
  const [searchValue, setSearchValue] = useState(query);

  const { data: results, isLoading, error } = useQuery({
    queryKey: ['search', query],
    queryFn: () => api.search.query({ q: query, limit: 20 }),
    enabled: !!query,
  });

  useEffect(() => {
    setSearchValue(query);
  }, [query]);

  const handleSearch = (newQuery: string) => {
    if (newQuery.trim()) {
      setSearchParams({ q: newQuery });
    }
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

      {query && (
        <div className="search-results">
          <h2>
            Results for "{query}"
            {results && <span className="count"> ({results.results.length})</span>}
          </h2>

          {isLoading ? (
            <div className="loading">Searching...</div>
          ) : error ? (
            <div className="error">
              Failed to search. Is the API running?
            </div>
          ) : results?.results.length === 0 ? (
            <div className="empty-state">
              <p>No results found for "{query}"</p>
            </div>
          ) : (
            <div className="fragment-list">
              {results?.results.map((result) => (
                <FragmentCard
                  key={result.id}
                  fragment={result}
                  score={result.score}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
