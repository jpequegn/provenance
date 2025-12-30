import { createBrowserRouter } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Search from './pages/Search';
import Timeline from './pages/Timeline';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      {
        index: true,
        element: <Dashboard />,
      },
      {
        path: 'search',
        element: <Search />,
      },
      {
        path: 'timeline',
        element: <Timeline />,
      },
    ],
  },
]);
