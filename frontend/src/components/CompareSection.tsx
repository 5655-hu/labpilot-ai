import { useEffect, useState } from 'react';
import {
  fetchLatestCompare,
  runCompare,
  type CompareResponse,
  type Dataset,
} from '../api/client';

function fmtP(p: number): string {
  if (p < 0.000001) return '<0.000001';
  return p.toFixed(6);
}

function isNumeric(dtype: string): boolean {
  return dtype.includes('int') || dtype.includes('float');
}

/** 分组比较区块：分组列与数值列下拉来自所选数据集的真实列名，结果全部来自真实接口。 */
export default function CompareSection({ dataset }: { dataset: Dataset }) {
  const allCols = dataset.columns.map((c) => c.name);
  const numericCols = dataset.columns.filter((c) => isNumeric(c.dtype)).map((c) => c.name);
  const catCols = dataset.columns.filter((c) => !isNumeric(c.dtype)).map((c) => c.name);

  const defaultGroup = allCols.includes('group') ? 'group' : (catCols[0] ?? allCols[0] ?? '');
  const defaultValue = allCols.includes('response') ? 'response' : (numericCols[0] ?? '');

  const [groupCol, setGroupCol] = useState(defaultGroup);
  const [valueCol, setValueCol] = useState(defaultValue);
  const [resp, setResp] = useState<CompareResponse | null>(null);
  const [meta, setMeta] = useState('');
  const [running, setRunning] = useState(false);
  const [loadingLatest, setLoadingLatest] = useState(false);
  const [error, setError] = useState('');

  // 切换数据集时：重置列选择，并加载该数据集最近一次比较结果（无则空态）。
  useEffect(() => {
    setGroupCol(defaultGroup);
    setValueCol(defaultValue);
    setResp(null);
    setMeta('');
    setError('');
    setLoadingLatest(true);
    fetchLatestCompare(dataset.id)
      .then((r) => {
        setResp(r);
        setMeta(`上次比较 ${r.created_at ?? ''}（分析 #${r.analysis_id}）`);
        setGroupCol(r.compare.group_col);
        setValueCol(r.compare.value_col);
      })
      .catch(() => setResp(null))
      .finally(() => setLoadingLatest(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataset.id]);

  async function onRun() {
    if (!groupCol || !valueCol) return;
    setRunning(true);
    setError('');
    try {
      const r = await runCompare(dataset.id, { group_col: groupCol, value_col: valueCol });
      setResp(r);
      setMeta(`本次比较刚完成（分析 #${r.analysis_id}）`);
    } catch (e) {
      setError(e instanceof Error ? e.message : '比较失败');
    } finally {
      setRunning(false);
    }
  }

  const c = resp?.compare ?? null;
  const groupNames = c ? Object.keys(c.descriptive) : [];

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5" data-testid="compare-section">
      <h2 className="font-semibold text-slate-900">分组比较</h2>
      <p className="mt-1 text-sm text-slate-500">
        按分组列把样本分成两组，比较数值列的组间差异；检验方法由正态性与方差齐性前提自动选择。
      </p>
      <div className="mt-4 flex flex-wrap items-end gap-4 text-sm">
        <label>
          <span className="mb-1 block text-slate-500">分组列</span>
          <select
            value={groupCol}
            onChange={(e) => setGroupCol(e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2"
          >
            {allCols.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
        <label>
          <span className="mb-1 block text-slate-500">数值列</span>
          <select
            value={valueCol}
            onChange={(e) => setValueCol(e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2"
          >
            {numericCols.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
        <button
          onClick={onRun}
          disabled={running || !groupCol || !valueCol}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {running ? '比较中…' : '运行比较'}
        </button>
      </div>
      {numericCols.length === 0 && (
        <p className="mt-3 text-sm text-amber-700">该数据集没有数值列，无法做分组比较。</p>
      )}
      {error && <p className="mt-3 text-sm text-red-600">比较失败：{error}</p>}
      {loadingLatest && <p className="mt-3 text-sm text-slate-400">正在加载最近一次比较结果…</p>}

      {!loadingLatest && !c && !error && (
        <p className="mt-4 text-sm text-slate-500">该数据集尚无分组比较结果，选择分组列与数值列后点“运行比较”。</p>
      )}

      {!loadingLatest && c && (
        <div className="mt-5 space-y-4" data-testid="compare-result">
          <p className="text-xs text-slate-400">{meta}</p>

          {/* 两组描述统计 */}
          <div>
            <h3 className="text-sm font-semibold text-slate-900">两组描述统计（{c.group_col} × {c.value_col}）</h3>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-slate-200 bg-slate-50 text-slate-500">
                  <tr>
                    <th className="px-3 py-2 font-medium">组</th>
                    <th className="px-3 py-2 font-medium">样本量 n</th>
                    <th className="px-3 py-2 font-medium">均值</th>
                    <th className="px-3 py-2 font-medium">中位数</th>
                    <th className="px-3 py-2 font-medium">标准差</th>
                    <th className="px-3 py-2 font-medium">最小值</th>
                    <th className="px-3 py-2 font-medium">最大值</th>
                  </tr>
                </thead>
                <tbody>
                  {groupNames.map((g) => {
                    const d = c.descriptive[g];
                    return (
                      <tr key={g} className="border-b border-slate-100 last:border-0">
                        <td className="px-3 py-2 font-medium text-slate-900">{g}</td>
                        <td className="px-3 py-2 text-slate-600">{d.n}</td>
                        <td className="px-3 py-2 text-slate-700">{d.mean.toFixed(4)}</td>
                        <td className="px-3 py-2 text-slate-700">{d.median.toFixed(4)}</td>
                        <td className="px-3 py-2 text-slate-700">{d.std.toFixed(4)}</td>
                        <td className="px-3 py-2 text-slate-700">{d.min.toFixed(4)}</td>
                        <td className="px-3 py-2 text-slate-700">{d.max.toFixed(4)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="mt-1 text-xs text-slate-400">总样本 {c.n_total} 个；各组剔除缺失 {Object.entries(c.missing_excluded).map(([g, n]) => `${g} ${n}`).join('、')} 个。</p>
          </div>

          {/* 前提检查 */}
          <div>
            <h3 className="text-sm font-semibold text-slate-900">前提检查</h3>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
              {Object.entries(c.assumptions.shapiro).map(([g, s]) => (
                <li key={g}>
                  Shapiro-Wilk 正态性（{g} 组）：{s.judgement}
                </li>
              ))}
              <li>
                Levene 方差齐性：{c.assumptions.levene.judgement}
              </li>
            </ul>
            <p className="mt-1 text-sm text-slate-500">{c.assumptions.judgement}</p>
          </div>

          {/* 检验与效应量 */}
          <div className="grid gap-3 rounded-lg bg-slate-50 p-4 text-sm sm:grid-cols-2">
            <div>
              <p className="text-slate-500">所选检验</p>
              <p className="mt-1 font-semibold text-slate-900">{c.selected_test_name}{c.overridden ? '（手动指定）' : ''}</p>
              <p className="mt-1 text-slate-600">{c.selection_reason}</p>
            </div>
            <div>
              <p className="text-slate-500">检验结果（α={c.alpha}）</p>
              <p className="mt-1 font-semibold text-slate-900">
                统计量 {c.test_result.statistic.toFixed(4)}，p={fmtP(c.test_result.p_value)}，
                {c.test_result.significant ? '差异显著' : '差异不显著'}
              </p>
              {c.effect_size && (
                <p className="mt-1 text-slate-600">
                  效应量 {c.effect_size.name} = {c.effect_size.value.toFixed(4)}（{c.effect_size.interpretation}）；{c.effect_size.note}
                </p>
              )}
            </div>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-slate-900">结论</h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-700">{c.conclusion}</p>
          </div>

          {c.warnings.length > 0 && (
            <ul className="list-disc space-y-1 rounded-lg border border-amber-200 bg-amber-50 p-4 pl-8 text-sm text-amber-800">
              {c.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}

          <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            组间差异不等于因果：本比较仅说明两组观测值存在或不存在统计学差异，不能据此推断分组导致了该差异。
          </p>
        </div>
      )}
    </section>
  );
}
