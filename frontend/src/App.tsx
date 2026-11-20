import { BrowserRouter, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import Archive from './pages/Archive';
import Audit from './pages/Audit';
import Charts from './pages/Charts';
import Dashboard from './pages/Dashboard';
import Datasets from './pages/Datasets';
import Report from './pages/Report';
import Stats from './pages/Stats';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/datasets" element={<Datasets />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="/stats" element={<Stats />} />
          <Route path="/charts" element={<Charts />} />
          <Route path="/report" element={<Report />} />
          <Route path="/archive" element={<Archive />} />
          <Route path="*" element={<Dashboard />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
