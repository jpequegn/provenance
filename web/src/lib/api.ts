// API types
export interface Fragment {
  id: string;
  content: string;
  summary: string | null;
  source_type: 'quick_capture' | 'zoom' | 'teams' | 'notes';
  source_ref: string | null;
  captured_at: string;
  participants: string[];
  topics: string[];
  project: string | null;
}

export interface SearchResult extends Fragment {
  score: number;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
}

export interface Decision {
  id: string;
  fragment_id: string;
  what: string;
  why: string;
  confidence: number;
  created_at: string;
}

export interface Assumption {
  id: string;
  fragment_id: string;
  statement: string;
  explicit: boolean;
  still_valid: boolean | null;
  invalidated_by: string | null;
  created_at: string;
}

export interface RelatedFragment extends Fragment {
  strength: number;
  link_type: string;
}

export interface RelatedResponse {
  fragment_id: string;
  related: RelatedFragment[];
}

export interface FragmentLink {
  id: string;
  source_id: string;
  target_id: string;
  link_type: string;
  strength: number;
  created_at: string;
}

export interface FragmentUpdateData {
  project?: string;
  topics?: string[];
  summary?: string;
}

export interface FragmentLinkData {
  target_id: string;
  link_type?: string;
  strength?: number;
}

export interface AssumptionUpdateData {
  still_valid?: boolean;
  invalidated_by?: string;
}

// Graph visualization types
export interface GraphNode {
  id: string;
  label: string;
  source_type: 'quick_capture' | 'zoom' | 'teams' | 'notes';
  project: string | null;
  captured_at: string;
  topics: string[];
  connections: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  link_type: string;
  strength: number;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// API base URL - uses proxy in development
const API_BASE = '/api';

// Generic fetch wrapper with error handling
async function fetchApi<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'API request failed');
  }

  return response.json();
}

// API methods
export const api = {
  fragments: {
    list: (params?: { project?: string; limit?: number; offset?: number }) => {
      const searchParams = new URLSearchParams();
      if (params?.project) searchParams.set('project', params.project);
      if (params?.limit) searchParams.set('limit', String(params.limit));
      if (params?.offset) searchParams.set('offset', String(params.offset));
      const query = searchParams.toString();
      return fetchApi<Fragment[]>(`/fragments${query ? `?${query}` : ''}`);
    },

    get: (id: string) => {
      return fetchApi<Fragment>(`/fragments/${id}`);
    },

    create: (data: { content: string; project?: string; topics?: string[] }) => {
      return fetchApi<Fragment>('/fragments', {
        method: 'POST',
        body: JSON.stringify(data),
      });
    },

    getRelated: (id: string, params?: { link_type?: string; limit?: number }) => {
      const searchParams = new URLSearchParams();
      if (params?.link_type) searchParams.set('link_type', params.link_type);
      if (params?.limit) searchParams.set('limit', String(params.limit));
      const query = searchParams.toString();
      return fetchApi<RelatedResponse>(`/fragments/${id}/related${query ? `?${query}` : ''}`);
    },

    update: (id: string, data: FragmentUpdateData) => {
      return fetchApi<Fragment>(`/fragments/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      });
    },

    createLink: (id: string, data: FragmentLinkData) => {
      return fetchApi<FragmentLink>(`/fragments/${id}/links`, {
        method: 'POST',
        body: JSON.stringify(data),
      });
    },
  },

  search: {
    query: (params: { q: string; limit?: number; project?: string }) => {
      const searchParams = new URLSearchParams();
      searchParams.set('q', params.q);
      if (params.limit) searchParams.set('limit', String(params.limit));
      if (params.project) searchParams.set('project', params.project);
      return fetchApi<SearchResponse>(`/search?${searchParams.toString()}`);
    },
  },

  decisions: {
    list: (params?: { project?: string; since?: string; limit?: number }) => {
      const searchParams = new URLSearchParams();
      if (params?.project) searchParams.set('project', params.project);
      if (params?.since) searchParams.set('since', params.since);
      if (params?.limit) searchParams.set('limit', String(params.limit));
      const query = searchParams.toString();
      return fetchApi<Decision[]>(`/decisions${query ? `?${query}` : ''}`);
    },
  },

  assumptions: {
    list: (params?: { project?: string; since?: string; still_valid?: boolean; limit?: number }) => {
      const searchParams = new URLSearchParams();
      if (params?.project) searchParams.set('project', params.project);
      if (params?.since) searchParams.set('since', params.since);
      if (params?.still_valid !== undefined) searchParams.set('still_valid', String(params.still_valid));
      if (params?.limit) searchParams.set('limit', String(params.limit));
      const query = searchParams.toString();
      return fetchApi<Assumption[]>(`/assumptions${query ? `?${query}` : ''}`);
    },

    update: (id: string, data: AssumptionUpdateData) => {
      return fetchApi<Assumption>(`/assumptions/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      });
    },
  },

  graph: {
    getData: (params?: {
      project?: string;
      source_type?: string;
      since?: string;
      until?: string;
      limit?: number;
    }) => {
      const searchParams = new URLSearchParams();
      if (params?.project) searchParams.set('project', params.project);
      if (params?.source_type) searchParams.set('source_type', params.source_type);
      if (params?.since) searchParams.set('since', params.since);
      if (params?.until) searchParams.set('until', params.until);
      if (params?.limit) searchParams.set('limit', String(params.limit));
      const query = searchParams.toString();
      return fetchApi<GraphData>(`/graph${query ? `?${query}` : ''}`);
    },
  },
};
