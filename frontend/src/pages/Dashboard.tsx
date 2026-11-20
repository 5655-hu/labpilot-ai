import { Link } from 'react-router-dom';
import { useLibrary } from '../api/hooks';
import { EmptyState, ErrorState, LoadingState, PageHeader } from '../components/StateViews';

export default function Dashboard() {
  const { datasets, analyses, reload } = useLibrary();

  if (datasets.status === 'loading' || analyses.status === 'loading') {
    return (
      <>
        <PageHeader title="Dashboard" desc="科研项目与数据总览 — 所有数字来自后端真实接口" />
        <LoadingState text="正在从后端加载数据…" />
      </>
    );
  }
  if (datasets.status === 'error') {
    return (
      <>
        <PageHeader title="Dashboard" desc="科研项目与数据总览 — 所有数字来自后端真实接口" />
        <ErrorState message={datasets.message} onRetry={reload} />
      </>
    );
  }
  if (analyses.status === 'error') {
    return (
      <>
        <PageHeader title="Dashboard" desc="科研项目与数据总览 — 所有数字来自后端真实接口" />
        <ErrorState message={analyses.message} onRetry={reload} />
      </>
    );
  }

  const ds = datasets.data;
  const an = analyses.data;
  const totalRows = ds.reduce((s, d) => s + d.rows_count, 0);
  const golden = ds.filter((d) => d.source === 'golden').length;

  return (
    <>
      <PageHeader title="Dashboard" desc="科研项目与数据总览 — 所有数字来自后端真实接口" />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="数据集数量" value={String(ds.length)} sub={`${golden} 份内置演示数据`} />
        <StatCard label="数据总行数" value={String(totalRows)} sub="全部数据集行数之和" />
        <StatCard label="已完成分析次数" value={String(an.length)} sub="审计与统计分析记录" />
        <StatCard label="科研项目数量" value="1" sub="LabPilot AI（当前项目）" />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="font-semibold text-slate-900">最近分析记录</h2>
          {an.length === 0 ? (
            <EmptyState
              title="暂无分析记录"
              hint="运行一次审计或统计后，这里会显示最近的分析记录。"
            />
          ) : (
            <ul className="mt-3 space-y-2">
              {an.slice(0, 5).map((a) => (
                <li key={a.id} className="text-sm text-slate-700">
                  {a.name} · {a.status} · {a.created_at}
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="font-semibold text-slate-900">数据质量概览</h2>
          {ds.length === 0 ? (
            <EmptyState title="暂无数据集" hint="先上传一份数据，或使用内置演示数据集。" />
          ) : (
            <ul className="mt-3 space-y-2">
              {ds.map((d) => (
                <li key={d.id} className="flex justify-between text-sm">
                  <span className="text-slate-700">{d.name}</span>
                  <span className="text-slate-500">
                    {d.rows_count} 行 × {d.cols_count} 列
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <div className="mt-6 rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="font-semibold text-slate-900">快捷操作</h2>
        <div className="mt-3 flex flex-wrap gap-3">
          <Link
            to="/datasets"
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            上传数据集
          </Link>
          <Link
            to="/audit"
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            去做质量审计
          </Link>
          <Link
            to="/archive"
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            查看复现档案
          </Link>
        </div>
      </div>
    </>
  );
}

function StatCard({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-2 text-3xl font-bold text-navy-900">{value}</p>
      <p className="mt-1 text-xs text-slate-400">{sub}</p>
    </div>
  );
}
