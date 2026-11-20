import { HashRouter, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import Archive from './pages/Archive';
import Audit from './pages/Audit';
import Charts from './pages/Charts';
import Dashboard from './pages/Dashboard';
import Datasets from './pages/Datasets';
import Report from './pages/Report';
import Stats from './pages/Stats';

// 用 HashRouter 而不是 BrowserRouter：静态托管（Qoder Sites）不一定配置
// SPA 回退规则，换成 hash 路由后刷新任意子页面都不会 404。
export default function App() {
  return (
    <HashRouter>
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
    </HashRouter>
  );
}
