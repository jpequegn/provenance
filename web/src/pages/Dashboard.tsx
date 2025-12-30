import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import FragmentCard from '../components/FragmentCard';
import SearchBox from '../components/SearchBox';

export default function Dashboard() {
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState('');

  const { data: fragments, isLoading } = useQuery({
    queryKey: ['fragments', 'recent'],
    queryFn: () => api.fragments.list({ limit: 10 }),
  });

  const handleSearch = (query: string) => {
    if (query.trim()) {
      navigate(`/search?q=${encodeURIComponent(query)}`);
    }
  };

  return (
    <div className="dashboard">
      <section className="hero">
        <h1>Provenance</h1>
        <p className="subtitle">Capture the why behind your decisions</p>
        <SearchBox
          value={searchQuery}
          onChange={setSearchQuery}
          onSubmit={handleSearch}
          placeholder="Search your context..."
        />
      </section>

      <section className="recent">
        <h2>Recent Fragments</h2>
        {isLoading ? (
          <div className="loading">Loading...</div>
        ) : fragments?.length === 0 ? (
          <div className="empty-state">
            <p>No fragments captured yet.</p>
            <p className="hint">Use the CLI to capture your first fragment:</p>
            <code>provo "chose Redis for sessions"</code>
          </div>
        ) : (
          <div className="fragment-list">
            {fragments?.map((fragment) => (
              <FragmentCard key={fragment.id} fragment={fragment} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
