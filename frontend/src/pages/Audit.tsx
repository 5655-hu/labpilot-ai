import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchLatestAudit, runAudit, type AuditRequest, type AuditResult } from '../api/client';
import { readyDatasets, useLibrary } from '../api/hooks';
import { EmptyState, ErrorState, LoadingState, PageHeader } from '../components/StateViews';

const PROFILES = [
  { name: 'measurement', label: '测量型（严格）' },
  { name: 'survey', label: '问卷型（缺失放宽）' },
  { name: 'timeseries', label: '时序型（重复从严）' },
];

const ALGO_LABEL: Record<string, string> = { iqr: 'IQR 四分位距法', zscore: 'Z-score 标准化法' };

export default function Audit() {
  const { datasets, reload } = useLibrary();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [algorithms, setAlgorithms] = useState<string[]>(['iqr']);
  const [iqrK, setIqrK] = useState(1.5);
  const [zThreshold, setZThreshold] = useState(3.0);
  const [profile, setProfile] = useState('measurement');
  const [result, setResult] = useState<AuditResult | null>(null);
  const [resultMeta, setResultMeta] = useState('');
  const [running, setRunning] = useState(false);
  const [loadingLatest, setLoadingLatest] = useState(false);
  const [error, setError] = useState('');

  const list = readyDatasets(datasets);

  useEffect(() => {
    if (selectedId === null && list.length > 0) {
      const dirty = list.find((d) => d.name.includes('脏数据'));
      setSelectedId(dirty ? dirty.id : list[0].id);
    }
  }, [list, selectedId]);

  useEffect(() => {
    if (selectedId === null) return;
    setLoadingLatest(true);
    setResult(null);
    setResultMeta('');
    setError('');
    fetchLatestAudit(selectedId)
      .then((r) => {
        setResult(r.audit);
        setResultMeta(`上次审计${r.created_at ? ` ${r.created_at}` : ''}（分析 #${r.analysis_id}）`);
      })
      .catch(() => setResult(null))
      .finally(() => setLoadingLatest(false));
  }, [selectedId]);

  function toggleAlgo(a: string) {
    setAlgorithms((prev) =>
      prev.includes(a) ? prev.filter((x) => x !== a) : [...prev, a],
    );
  }

  async function onRun() {
    if (selectedId === null || algorithms.length === 0) return;
    setRunning(true);
    setError('');
    try {
      const body: AuditRequest = { algorithms, iqr_k: iqrK, z_threshold: zThreshold, profile };
      const r = await runAudit(selectedId, body);
      setResult(r.audit);
      setResultMeta(`本次审计刚完成（分析 #${r.analysis_id}）`);
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : '审计失败');
    } finally {
      setRunning(false);
    }
  }

  const selected = list.find((d) => d.id === selectedId) ?? null;

  return (
    <>
      <PageHeader title="数据质量审计" desc="缺失、重复、异常、类型错误与评分 — 公式公开，每笔扣分带证据" />
      {datasets.status === 'loading' && <LoadingState text="正在加载数据集…" />}
      {datasets.status === 'error' && (
        <ErrorState message={datasets.message} onRetry={reload} />
      )}
      {datasets.status === 'ready' && list.length === 0 && (
        <EmptyState
          title="暂无可审计的数据集"
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
              <label className="text-sm">
                <span className="mb-1 block text-slate-500">规则画像</span>
                <select
                  value={profile}
                  onChange={(e) => setProfile(e.target.value)}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                >
                  {PROFILES.map((p) => (
                    <option key={p.name} value={p.name}>{p.label}</option>
                  ))}
                </select>
              </label>
              <fieldset className="text-sm">
                <legend className="mb-1 text-slate-500">异常值算法（可多选对比）</legend>
                <label className="mr-4">
                  <input type="checkbox" checked={algorithms.includes('iqr')} onChange={() => toggleAlgo('iqr')} /> IQR
                </label>
                <label>
                  <input type="checkbox" checked={algorithms.includes('zscore')} onChange={() => toggleAlgo('zscore')} /> Z-score
                </label>
              </fieldset>
              <label className="text-sm">
                <span className="mb-1 block text-slate-500">IQR 倍数 k</span>
                <input type="number" step="0.1" min="0.1" value={iqrK} onChange={(e) => setIqrK(Number(e.target.value))}
                  className="w-20 rounded-lg border border-slate-300 px-2 py-2 text-sm" />
              </label>
              <label className="text-sm">
                <span className="mb-1 block text-slate-500">Z-score 阈值</span>
                <input type="number" step="0.5" min="0.5" value={zThreshold} onChange={(e) => setZThreshold(Number(e.target.value))}
                  className="w-20 rounded-lg border border-slate-300 px-2 py-2 text-sm" />
              </label>
              <button
                onClick={onRun}
                disabled={running || algorithms.length === 0}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {running ? '审计中…' : '开始审计'}
              </button>
            </div>
            {error && <p className="mt-3 text-sm text-red-600">审计失败：{error}</p>}
            <p className="mt-3 text-xs text-slate-400">
              统计异常只标“待确认”，不扣分、不自动删除；类型错误、重复行与不可能的值计入扣分。
            </p>
          </section>

          {loadingLatest && <LoadingState text="正在加载审计结果…" />}
          {!loadingLatest && !result && (
            <EmptyState title="该数据集尚无审计结果" hint="调整上方参数后点“开始审计”，结果会存入复现档案。" />
          )}
          {!loadingLatest && result && selected && (
            <AuditResultView result={result} meta={resultMeta} datasetName={selected.name} />
          )}
        </div>
      )}
    </>
  );
}

function AuditResultView({ result, meta, datasetName }: { result: AuditResult; meta: string; datasetName: string }) {
  const s = result.score;
  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <div className="flex flex-wrap items-baseline gap-3">
          <h2 className="font-semibold text-slate-900">审计结果：{datasetName}</h2>
          <span className="text-xs text-slate-400">{meta}</span>
        </div>
        <div className="mt-4 flex flex-wrap items-end gap-6">
          <div>
            <p className="text-sm text-slate-500">数据质量评分</p>
            <p className="text-5xl font-bold text-navy-900">{s.total}<span className="text-xl text-slate-400"> / 100</span></p>
          </div>
          <div className="text-sm text-slate-600">
            <p>{result.rows} 行 × {result.cols} 列，共 {result.total_cells} 个单元格</p>
            <p>缺失 {result.missing.total} 个 · 重复 {result.duplicates.count} 行 · 待确认异常 {result.pending_outliers.reduce((n, p) => n + p.count, 0)} 个点</p>
          </div>
        </div>
        <p className="mt-3 font-mono text-xs text-slate-500">{s.formula}</p>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="font-semibold text-slate-900">评分详细解释</h2>
        <p className="mt-1 text-xs text-slate-400">每一笔扣分都有来源与依据；统计异常不扣分，原因见下方“待确认异常清单”。</p>

        <h3 className="mt-4 font-medium text-slate-800">一、总分构成</h3>
        <table className="mt-2 w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-slate-500">
            <tr><th className="px-3 py-2 font-medium">扣分项</th><th className="px-3 py-2 font-medium">权重</th><th className="px-3 py-2 font-medium">发生率</th><th className="px-3 py-2 font-medium">扣分</th></tr>
          </thead>
          <tbody>
            {s.deductions.map((d) => (
              <tr key={d.category} className="border-b border-slate-100 last:border-0">
                <td className="px-3 py-2 font-medium text-slate-900">{d.label}</td>
                <td className="px-3 py-2 text-slate-600">{d.weight}</td>
                <td className="px-3 py-2 text-slate-600">{(d.rate * 100).toFixed(2)}%</td>
                <td className="px-3 py-2 font-medium text-red-600">−{d.deduction.toFixed(2)}</td>
              </tr>
            ))}
            <tr className="font-medium">
              <td className="px-3 py-2">合计扣分</td><td className="px-3 py-2" colSpan={2}></td>
              <td className="px-3 py-2 text-red-600">−{s.total_deduction.toFixed(2)}</td>
            </tr>
          </tbody>
        </table>

        <h3 className="mt-5 font-medium text-slate-800">二、每笔扣分的来源与计算过程</h3>
        <div className="mt-2 space-y-3">
          {s.deductions.map((d) => (
            <div key={d.category} className="rounded-lg bg-slate-50 p-3 text-sm">
              <p className="font-medium text-slate-900">{d.label}：扣 {d.deduction.toFixed(2)} 分</p>
              <p className="mt-1 text-slate-600">{d.rate_basis}</p>
              <p className="mt-1 text-slate-600">原因：{d.reason}</p>
              <p className="mt-1 text-slate-600">建议：{d.suggestion}</p>
              {d.evidence.length === 0 && <p className="mt-1 text-slate-400">本项未检出问题。</p>}
              {d.evidence.map((ev, i) => (
                <div key={i} className="mt-2 border-t border-slate-200 pt-2">
                  <p className="text-slate-700">列 {ev.column}：{ev.count} 处，占比 {(ev.rate * 100).toFixed(2)}%</p>
                  {ev.example_rows.length > 0 && (
                    <ul className="mt-1 list-disc pl-5 text-slate-500">
                      {ev.example_rows.map((ex, j) => (
                        <li key={j}>
                          第 {(ex as { row_number?: number }).row_number ?? '?'} 行：
                          <code className="ml-1 rounded bg-white px-1 font-mono text-xs">{JSON.stringify((ex as { value?: unknown }).value)}</code>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>

        <h3 className="mt-5 font-medium text-slate-800">三、待确认异常清单（未扣分）</h3>
        {result.pending_outliers.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">未检出统计异常。</p>
        ) : (
          <div className="mt-2 space-y-3">
            {result.pending_outliers.map((p) => (
              <div key={p.column} className="rounded-lg bg-amber-50 p-3 text-sm">
                <p className="font-medium text-slate-900">
                  {p.column}：{p.count} 个异常点（{p.algorithms.map((a) => ALGO_LABEL[a] ?? a).join(' / ')}）· {p.status}
                </p>
                <p className="mt-1 text-slate-600">{p.suggestion}</p>
                <ul className="mt-1 list-disc pl-5 text-slate-600">
                  {p.points.slice(0, 6).map((pt) => (
                    <li key={`${pt.row_index}-${pt.algorithms.join('+')}`}>
                      第 {pt.row_number} 行：值 {pt.value}（{pt.algorithms.map((a) => ALGO_LABEL[a] ?? a).join('、')}检出）
                    </li>
                  ))}
                  {p.points.length > 6 && <li>…共 {p.points.length} 个点</li>}
                </ul>
                {p.disagreement.length > 0 && p.disagreement.some((d) => d.row_indices.length > 0) && (
                  <p className="mt-2 text-slate-500">
                    算法分歧：{p.disagreement.filter((d) => d.row_indices.length > 0).map((d) => `${ALGO_LABEL[d.algorithm] ?? d.algorithm}独有 ${d.row_indices.length} 个点`).join('；')}，系统不替用户裁决。
                  </p>
                )}
              </div>
            ))}
          </div>
        )}

        <h3 className="mt-5 font-medium text-slate-800">四、豁免说明</h3>
        <p className="mt-2 text-sm text-slate-600">
          本次审计{result.params.allowed_missing_columns.length > 0
            ? `将以下列设为允许缺失，不计入有效缺失率：${result.params.allowed_missing_columns.join('、')}。`
            : '未设置允许缺失列，全部缺失均计入评分。'}
          统计异常一律不扣分，只列入待确认清单。
        </p>

        <h3 className="mt-5 font-medium text-slate-800">五、规则快照</h3>
        <div className="mt-2 rounded-lg bg-slate-50 p-3 text-sm text-slate-600">
          <p>画像：{s.profile.label}（{s.profile.name}）— {s.profile.description}</p>
          <p>权重：缺失 {s.profile.weights.missing} · 重复 {s.profile.weights.duplicate} · 类型错误 {s.profile.weights.type_error} · 确定错误 {s.profile.weights.definite_error}</p>
          <p>算法：{result.params.algorithms.map((a) => ALGO_LABEL[a] ?? a).join('、')}；IQR 倍数 k={result.params.iqr_k}；Z-score 阈值 |z|&gt;{result.params.z_threshold}</p>
          <p>引擎版本：{result.engine_version}</p>
        </div>
      </section>

      {result.unit_risks.length > 0 && (
        <section className="rounded-xl border border-amber-200 bg-amber-50 p-5">
          <h2 className="font-semibold text-slate-900">单位不一致风险提示</h2>
          {result.unit_risks.map((u) => (
            <div key={u.column} className="mt-2 text-sm text-slate-700">
              <p>{u.column} 列混有单位 {u.units.join('、')}，与纯数值混用。</p>
              <p className="mt-1 text-slate-600">{u.suggestion}</p>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
