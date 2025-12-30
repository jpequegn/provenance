import { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import ForceGraph2D, { ForceGraphMethods } from 'react-force-graph-2d';
import { api, type GraphNode } from '../lib/api';

// Color mapping for source types
const SOURCE_COLORS: Record<string, string> = {
  quick_capture: '#1F4E8C', // Primary blue
  zoom: '#28A745', // Green
  teams: '#6F42C1', // Purple
  notes: '#FFC107', // Yellow
};

// Color mapping for link types
const LINK_COLORS: Record<string, string> = {
  relates_to: '#666666', // Gray
  references: '#1F4E8C', // Blue
  follows: '#28A745', // Green
  contradicts: '#DC3545', // Red
  invalidates: '#FD7E14', // Orange
};

// Format date for display
function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

interface GraphFilters {
  project: string;
  sourceType: string;
  since: string;
  until: string;
}

export default function Graph() {
  const [filters, setFilters] = useState<GraphFilters>({
    project: '',
    sourceType: '',
    since: '',
    until: '',
  });
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const graphRef = useRef<ForceGraphMethods<any, any>>();

  // Fetch graph data
  const { data: graphData, isLoading, error } = useQuery({
    queryKey: ['graph', filters],
    queryFn: () =>
      api.graph.getData({
        project: filters.project || undefined,
        source_type: filters.sourceType || undefined,
        since: filters.since || undefined,
        until: filters.until || undefined,
        limit: 500,
      }),
    staleTime: 60000, // 1 minute
  });

  // Fetch list of projects for filter dropdown
  const { data: fragments } = useQuery({
    queryKey: ['fragments', 'all'],
    queryFn: () => api.fragments.list({ limit: 500 }),
    staleTime: 60000,
  });

  // Extract unique projects from fragments
  const projects = useMemo(() => {
    if (!fragments) return [];
    const projectSet = new Set(fragments.map((f) => f.project).filter(Boolean) as string[]);
    return Array.from(projectSet).sort();
  }, [fragments]);

  // Transform data for force-graph
  const graphDataForViz = useMemo(() => {
    if (!graphData) return { nodes: [], links: [] };

    return {
      nodes: graphData.nodes.map((node) => ({
        ...node,
        // Size nodes by number of connections (min 5, max 15)
        val: Math.min(15, Math.max(5, 5 + node.connections * 2)),
        color: SOURCE_COLORS[node.source_type] || SOURCE_COLORS.quick_capture,
      })),
      links: graphData.edges.map((edge) => ({
        ...edge,
        color: LINK_COLORS[edge.link_type] || LINK_COLORS.relates_to,
        // Width based on strength (1-5)
        width: 1 + edge.strength * 4,
      })),
    };
  }, [graphData]);

  // Handle node click
  const handleNodeClick = useCallback((node: GraphNode) => {
    setSelectedNode(node);
    // Center on the clicked node
    if (graphRef.current) {
      graphRef.current.centerAt(
        (node as unknown as { x: number }).x,
        (node as unknown as { y: number }).y,
        1000
      );
      graphRef.current.zoom(2, 1000);
    }
  }, []);

  // Handle background click to deselect
  const handleBackgroundClick = useCallback(() => {
    setSelectedNode(null);
  }, []);

  // Handle filter changes
  const handleFilterChange = (key: keyof GraphFilters, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  // Zoom controls
  const handleZoomIn = () => {
    if (graphRef.current) {
      const currentZoom = graphRef.current.zoom();
      graphRef.current.zoom(currentZoom * 1.5, 300);
    }
  };

  const handleZoomOut = () => {
    if (graphRef.current) {
      const currentZoom = graphRef.current.zoom();
      graphRef.current.zoom(currentZoom / 1.5, 300);
    }
  };

  const handleReset = () => {
    if (graphRef.current) {
      graphRef.current.zoomToFit(400, 50);
    }
  };

  // Zoom to fit on initial load
  useEffect(() => {
    if (graphData && graphData.nodes.length > 0 && graphRef.current) {
      setTimeout(() => {
        graphRef.current?.zoomToFit(400, 50);
      }, 500);
    }
  }, [graphData?.nodes.length]);

  if (error) {
    return (
      <div className="graph-page">
        <div className="graph-error">
          <h2>Error Loading Graph</h2>
          <p>Failed to load graph data. Please try again.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="graph-page">
      {/* Filters */}
      <div className="graph-filters">
        <div className="filter-group">
          <label htmlFor="project-filter">Project</label>
          <select
            id="project-filter"
            value={filters.project}
            onChange={(e) => handleFilterChange('project', e.target.value)}
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
          <label htmlFor="source-filter">Source Type</label>
          <select
            id="source-filter"
            value={filters.sourceType}
            onChange={(e) => handleFilterChange('sourceType', e.target.value)}
          >
            <option value="">All Sources</option>
            <option value="quick_capture">Quick Capture</option>
            <option value="zoom">Zoom</option>
            <option value="teams">Teams</option>
            <option value="notes">Notes</option>
          </select>
        </div>

        <div className="filter-group">
          <label htmlFor="since-filter">From</label>
          <input
            type="date"
            id="since-filter"
            value={filters.since}
            onChange={(e) => handleFilterChange('since', e.target.value)}
          />
        </div>

        <div className="filter-group">
          <label htmlFor="until-filter">To</label>
          <input
            type="date"
            id="until-filter"
            value={filters.until}
            onChange={(e) => handleFilterChange('until', e.target.value)}
          />
        </div>
      </div>

      {/* Graph stats */}
      <div className="graph-stats">
        <span>
          {graphData?.nodes.length || 0} nodes, {graphData?.edges.length || 0} edges
        </span>
      </div>

      {/* Graph container */}
      <div className="graph-container">
        {isLoading ? (
          <div className="graph-loading">
            <div className="spinner" />
            <p>Loading graph...</p>
          </div>
        ) : graphDataForViz.nodes.length === 0 ? (
          <div className="graph-empty">
            <h3>No fragments to display</h3>
            <p>Capture some context to see the relationship graph.</p>
          </div>
        ) : (
          <ForceGraph2D
            ref={graphRef}
            graphData={graphDataForViz}
            nodeLabel="label"
            nodeColor="color"
            nodeVal="val"
            linkColor="color"
            linkWidth="width"
            linkDirectionalParticles={2}
            linkDirectionalParticleWidth={(link) =>
              (link as unknown as { width: number }).width
            }
            onNodeClick={handleNodeClick}
            onBackgroundClick={handleBackgroundClick}
            backgroundColor="#121317"
            nodeCanvasObject={(node, ctx, globalScale) => {
              // Draw node circle
              const size = (node as unknown as { val: number }).val || 5;
              const color = (node as unknown as { color: string }).color || '#1F4E8C';
              const isSelected = selectedNode?.id === node.id;

              ctx.beginPath();
              ctx.arc(
                (node as unknown as { x: number }).x || 0,
                (node as unknown as { y: number }).y || 0,
                size,
                0,
                2 * Math.PI
              );
              ctx.fillStyle = color;
              ctx.fill();

              // Draw selection ring
              if (isSelected) {
                ctx.strokeStyle = '#E0E6F0';
                ctx.lineWidth = 2;
                ctx.stroke();
              }

              // Draw label on hover or when zoomed in
              if (globalScale > 1.5 || isSelected) {
                const label = (node as unknown as { label: string }).label || '';
                const truncatedLabel = label.length > 30 ? label.slice(0, 30) + '...' : label;
                const fontSize = 10 / globalScale;
                ctx.font = `${fontSize}px Inter, sans-serif`;
                ctx.textAlign = 'center';
                ctx.textBaseline = 'top';
                ctx.fillStyle = '#E0E6F0';
                ctx.fillText(
                  truncatedLabel,
                  (node as unknown as { x: number }).x || 0,
                  ((node as unknown as { y: number }).y || 0) + size + 2
                );
              }
            }}
            cooldownTicks={100}
            warmupTicks={50}
          />
        )}

        {/* Zoom controls */}
        <div className="graph-controls">
          <button onClick={handleZoomIn} title="Zoom in">
            +
          </button>
          <button onClick={handleZoomOut} title="Zoom out">
            -
          </button>
          <button onClick={handleReset} title="Reset view">
            ⟲
          </button>
        </div>

        {/* Legend */}
        <div className="graph-legend">
          <h4>Source Types</h4>
          <div className="legend-items">
            <div className="legend-item">
              <span className="legend-dot" style={{ backgroundColor: SOURCE_COLORS.quick_capture }} />
              Quick Capture
            </div>
            <div className="legend-item">
              <span className="legend-dot" style={{ backgroundColor: SOURCE_COLORS.zoom }} />
              Zoom
            </div>
            <div className="legend-item">
              <span className="legend-dot" style={{ backgroundColor: SOURCE_COLORS.teams }} />
              Teams
            </div>
            <div className="legend-item">
              <span className="legend-dot" style={{ backgroundColor: SOURCE_COLORS.notes }} />
              Notes
            </div>
          </div>
          <h4>Link Types</h4>
          <div className="legend-items">
            <div className="legend-item">
              <span className="legend-line" style={{ backgroundColor: LINK_COLORS.relates_to }} />
              Relates to
            </div>
            <div className="legend-item">
              <span className="legend-line" style={{ backgroundColor: LINK_COLORS.references }} />
              References
            </div>
            <div className="legend-item">
              <span className="legend-line" style={{ backgroundColor: LINK_COLORS.contradicts }} />
              Contradicts
            </div>
            <div className="legend-item">
              <span className="legend-line" style={{ backgroundColor: LINK_COLORS.invalidates }} />
              Invalidates
            </div>
          </div>
        </div>
      </div>

      {/* Selected node details panel */}
      {selectedNode && (
        <div className="node-details-panel">
          <div className="panel-header">
            <h3>Fragment Details</h3>
            <button className="close-btn" onClick={() => setSelectedNode(null)}>
              ✕
            </button>
          </div>
          <div className="panel-content">
            <div className="detail-row">
              <span className="detail-label">Source</span>
              <span className="detail-value">
                {selectedNode.source_type.replace('_', ' ')}
              </span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Date</span>
              <span className="detail-value">{formatDate(selectedNode.captured_at)}</span>
            </div>
            {selectedNode.project && (
              <div className="detail-row">
                <span className="detail-label">Project</span>
                <span className="detail-value">{selectedNode.project}</span>
              </div>
            )}
            {selectedNode.topics.length > 0 && (
              <div className="detail-row">
                <span className="detail-label">Topics</span>
                <div className="topic-tags">
                  {selectedNode.topics.map((topic) => (
                    <span key={topic} className="topic-tag">
                      {topic}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div className="detail-row">
              <span className="detail-label">Connections</span>
              <span className="detail-value">{selectedNode.connections}</span>
            </div>
            <div className="detail-content">
              <span className="detail-label">Content</span>
              <p className="content-text">{selectedNode.label}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
