import { Outlet, NavLink } from 'react-router-dom';

export default function Layout() {
  return (
    <div className="app-layout">
      <nav className="navbar">
        <div className="nav-brand">
          <NavLink to="/">
            <span className="logo">P</span>
            <span className="brand-text">Provenance</span>
          </NavLink>
        </div>
        <div className="nav-links">
          <NavLink to="/" end className={({ isActive }) => isActive ? 'active' : ''}>
            Dashboard
          </NavLink>
          <NavLink to="/search" className={({ isActive }) => isActive ? 'active' : ''}>
            Search
          </NavLink>
          <NavLink to="/timeline" className={({ isActive }) => isActive ? 'active' : ''}>
            Timeline
          </NavLink>
          <NavLink to="/graph" className={({ isActive }) => isActive ? 'active' : ''}>
            Graph
          </NavLink>
        </div>
      </nav>
      <main className="main-content">
        <Outlet />
      </main>
      <footer className="footer">
        <p>Provenance - Capture the why behind your decisions</p>
      </footer>
    </div>
  );
}
