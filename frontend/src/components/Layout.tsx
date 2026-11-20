import { useEffect, useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { fetchHealth } from '../api/client';
import { OFFLINE_NOTES, useOfflineMode } from '../api/offline';

const NAV = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/datasets', label: '数据集' },
  { to: '/audit', label: '数据质量审计' },
  { to: '/stats', label: '统计分析' },
  { to: '/charts', label: '数据可视化' },
  { to: '/report', label: 'AI 科研报告' },
  { to: '/archive', label: '复现档案' },
];

export default function Layout() {
  // Sidebar wave label + version both come from the live backend (/health);
  // if the backend is unreachable we fall back to the last known release label.
  const [version, setVersion] = useState<string | null>(null);
  const [wave, setWave] = useState<string | null>(null);
  const offline = useOfflineMode();
  useEffect(() => {
    fetchHealth()
      .then((h) => {
        setVersion(h.version);
        setWave(h.wave ?? null);
      })
      .catch(() => {
        setVersion(null);
        setWave(null);
      });
  }, []);

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-60 shrink-0 flex-col bg-navy-900 text-white">
        <div className="border-b border-navy-700 px-5 py-5">
          <p className="text-lg font-bold tracking-wide">LabPilot AI</p>
          <p className="mt-1 text-xs text-slate-400">科研数据智能审计与复现助手</p>
          <p className="mt-2 inline-block rounded bg-navy-700 px-2 py-0.5 text-[11px] text-slate-300">
            {wave ?? 'Wave 5'} · v{version ?? '0.6.0'}
          </p>
        </div>
        <nav className="flex-1 space-y-1 px-3 py-4">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `block rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-accent-600 text-white'
                    : 'text-slate-300 hover:bg-navy-800 hover:text-white'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-navy-700 px-5 py-4 text-xs leading-relaxed text-slate-400">
          让每一份实验数据
          <br />
          都可检查、可解释、可复现。
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        {offline && (
          <div className="border-b border-amber-300 bg-amber-50 px-8 py-3 text-sm leading-relaxed text-amber-900">
            <strong className="mr-2 rounded bg-amber-200 px-1.5 py-0.5 text-xs font-semibold">
              {OFFLINE_NOTES.banner}
            </strong>
            {OFFLINE_NOTES.detail}
            <a
              href={OFFLINE_NOTES.backendUrl}
              target="_blank"
              rel="noreferrer"
              className="ml-1 font-semibold underline decoration-amber-600 underline-offset-2"
            >
              {OFFLINE_NOTES.backendUrl}
            </a>
          </div>
        )}
        <main className="min-w-0 flex-1 px-8 py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
