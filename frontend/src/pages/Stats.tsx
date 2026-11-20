import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchLatestStats, runStats, type StatsResult } from '../api/client';
import { readyDatasets, useLibrary } from '../api/hooks';
import CompareSection from '../components/CompareSection';
import { EmptyState, ErrorState, LoadingState, PageHeader } from '../components/StateViews';

function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  return String(v);
}

export default function Stats() {
  const { datasets, reload } = useLibrary();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [result, setResult] = useState<StatsResult | null>(null);
  const [resultMeta, setResultMeta] = useState('');
  const [running, setRunning] = useState(false);
  const [loadingLatest, setLoadingLatest] = useState(false);
  const [error, setError] = useState('');

  const list = readyDatasets(datasets);

  useEffect(() => {
    if (selectedId === null && list.length > 0) {
      const corr = list.find((d) => d.name.includes('相关性'));
      setSelectedId(corr ? corr.id : list[0].id);
    }
  }, [list, selectedId]);

  useEffect(() => {
    if (selectedId === null) return;
    setLoadingLatest(true);
    setResult(null);
    setResultMeta('');
    setError('');
    fetchLatestStats(selectedId)
      .then((r) => {
        setResult(r.stats);
        setResultMeta(`上次统计 ${r.created_at}（分析 #${r.analysis_id}）`);
      })
      .catch(() => setResult(null))
      .finally(() => setLoadingLatest(false));
  }, [selectedId]);

  async function onRun() {
    if (selectedId === null) return;
    setRunning(true);
    setError('');
    try {
      const r = await runStats(selectedId);
      setResult(r.stats);
      setResultMeta(`本次统计刚完成（分析 #${r.analysis_id}）`);
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : '统计失败');
    } finally {
      setRunning(false);
    }
  }

  const selected = list.find((d) => d.id === selectedId) ?? null;
  const corrCols = result ? Object.keys(result.correlation.matrix) : [];

  return (
    <>
      <PageHeader title="统计分析" desc="描述统计、分布、相关性与线性回归 — 全部由 Python 科学计算库真实计算" />
      {datasets.status === 'loading' && <LoadingState text="正在加载数据集…" />}
      {datasets.status === 'error' && (
        <ErrorState message={datasets.message} onRetry={reload} />
      )}
      {datasets.status === 'ready' && list.length === 0 && (
        <EmptyState
          title="暂无可分析的数据集"
          hint="先上传一份数据，或使用内置演示数据。"
          action={
            <Link to="/datasets" className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">
              去数据集管理
            </Link>
          }
        />
      )}
      {datasets.status === 'ready' && list.length > 0 && (
        <div className="space-y-4">
          <section className="rounded-xl border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-end gap-4">
              <label className="text-sm">
                <span className="mb-1 block text-slate-500">数据集</span>
                <select
                  value={selectedId ?? ''}
                  onChange={(e) => setSelectedId(Number(e.target.value))}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                >
                  {list.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}（{d.rows_count} 行 × {d.cols_count} 列）
                    </option>
                  ))}
                </select>
              </label>
              <button
                onClick={onRun}
                disabled={running}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {running ? '计算中…' : '开始统计'}
              </button>
            </div>
            {error && <p className="mt-3 text-sm text-red-600">统计失败：{error}</p>}
            <p className="mt-3 text-xs text-slate-400">
              样本标准差（ddof=1）；相关性为 Pearson 系数，成对删除缺失值，每对至少 3 个有效样本。常量列与非数值列不参与相关性，原因见下方。
            </p>
          </section>

          {loadingLatest && <LoadingState text="正在加载统计结果…" />}
          {!loadingLatest && !result && (
            <EmptyState title="该数据集尚无统计结果" hint="点“开始统计”，结果会存入复现档案。" />
          )}
          {!loadingLatest && result && selected && (
            <div className="space-y-4">
              <section className="rounded-xl border border-slate-200 bg-white p-5">
                <div className="flex flex-wrap items-baseline gap-3">
                  <h2 className="font-semibold text-slate-900">统计结果：{selected.name}</h2>
                  <span className="text-xs text-slate-400">{resultMeta}</span>
                </div>
                <p className="mt-1 text-sm text-slate-500">{result.rows} 行 × {result.cols} 列 · 引擎 {result.engine_version}</p>
                <div className="mt-4 overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="border-b border-slate-200 bg-slate-50 text-slate-500">
                      <tr>
                        <th className="px-3 py-2 font-medium">列</th>
                        <th className="px-3 py-2 font-medium">有效数</th>
                        <th className="px-3 py-2 font-medium">缺失</th>
                        <th className="px-3 py-2 font-medium">均值</th>
                        <th className="px-3 py-2 font-medium">中位数</th>
                        <th className="px-3 py-2 font-medium">标准差</th>
                        <th className="px-3 py-2 font-medium">方差</th>
                        <th className="px-3 py-2 font-medium">最小值</th>
                        <th className="px-3 py-2 font-medium">最大值</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(result.columns).map(([name, c]) => (
                        <tr key={name} className="border-b border-slate-100 last:border-0">
                          <td className="px-3 py-2 font-medium text-slate-900">
                            {name}
                            {c.constant && <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800">常量列</span>}
                          </td>
                          <td className="px-3 py-2 text-slate-600">{c.count}</td>
                          <td className="px-3 py-2 text-slate-600">{c.missing}</td>
                          <td className="px-3 py-2 text-slate-700">{fmt(c.mean)}</td>
                          <td className="px-3 py-2 text-slate-700">{fmt(c.median)}</td>
                          <td className="px-3 py-2 text-slate-700">{fmt(c.std)}</td>
                          <td className="px-3 py-2 text-slate-700">{fmt(c.variance)}</td>
                          <td className="px-3 py-2 text-slate-700">{fmt(c.min)}</td>
                          <td className="px-3 py-2 text-slate-700">{fmt(c.max)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {result.notes.length > 0 && (
                  <ul className="mt-3 list-disc pl-5 text-sm text-slate-500">
                    {result.notes.map((n, i) => <li key={i}>{n}</li>)}
                  </ul>
                )}
                {result.skipped_columns.length > 0 && (
                  <div className="mt-3 text-sm text-slate-500">
                    <p className="font-medium text-slate-700">跳过的列：</p>
                    <ul className="list-disc pl-5">
                      {result.skipped_columns.map((sk) => (
                        <li key={sk.column}>{sk.column}：{sk.reason}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </section>

              <section className="rounded-xl border border-slate-200 bg-white p-5">
                <h2 className="font-semibold text-slate-900">相关性分析（Pearson）</h2>
                {corrCols.length === 0 ? (
                  <p className="mt-2 text-sm text-slate-500">
                    {result.correlation.note ?? '未计算相关性。'}
                  </p>
                ) : (
                  <>
                    <div className="mt-4 overflow-x-auto">
                      <table className="w-full text-left text-sm">
                        <thead className="border-b border-slate-200 bg-slate-50 text-slate-500">
                          <tr>
                            <th className="px-3 py-2 font-medium"></th>
                            {corrCols.map((c) => (
                              <th key={c} className="px-3 py-2 font-medium">{c}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {corrCols.map((a) => (
                            <tr key={a} className="border-b border-slate-100 last:border-0">
                              <td className="px-3 py-2 font-medium text-slate-900">{a}</td>
                              {corrCols.map((b) => (
                                <td key={b} className="px-3 py-2 text-slate-700">
                                  {result.correlation.matrix[a][b] === null ? '—' : result.correlation.matrix[a][b]?.toFixed(4)}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <p className="mt-3 text-xs text-slate-400">相关不等于因果；相关系数接近 ±1 只说明线性关系强。</p>
                  </>
                )}
                {result.correlation.unavailable.length > 0 && (
                  <ul className="mt-3 list-disc pl-5 text-sm text-slate-500">
                    {result.correlation.unavailable.map((u, i) => (
                      <li key={i}>{u.columns.join(' × ')}：{u.reason}</li>
                    ))}
                  </ul>
                )}
                {result.correlation.note && corrCols.length > 0 && (
                  <p className="mt-3 text-sm text-slate-500">{result.correlation.note}</p>
                )}
              </section>

              <CompareSection dataset={selected} />
            </div>
          )}
        </div>
      )}
    </>
  );
}
