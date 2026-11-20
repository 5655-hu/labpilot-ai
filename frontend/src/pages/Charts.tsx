import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  fetchBoxplot,
  fetchChartColumns,
  fetchHeatmap,
  fetchHistogram,
  fetchLine,
  fetchRegression,
  fetchScatter,
  type BoxplotChart,
  type ChartColumn,
  type HeatmapChart,
  type HistogramChart,
  type LineChart,
  type RegressionChart,
  type ScatterChart,
} from '../api/client';
import { readyDatasets, useLibrary } from '../api/hooks';
import Plot from '../components/Plot';
import { EmptyState, ErrorState, LoadingState, PageHeader } from '../components/StateViews';

type ChartType = 'histogram' | 'boxplot' | 'scatter' | 'line' | 'heatmap' | 'regression';

const CHART_TYPES: { key: ChartType; label: string }[] = [
  { key: 'histogram', label: '直方图' },
  { key: 'boxplot', label: '箱线图' },
  { key: 'scatter', label: '散点图' },
  { key: 'line', label: '折线图' },
  { key: 'heatmap', label: '相关性热力图' },
  { key: 'regression', label: '线性回归' },
];

const CAUSALITY_NOTE =
  '相关性不代表因果关系：相关系数接近 ±1 只说明两个变量的线性关系强，不能证明一个变量导致另一个变量变化。';

type ChartData =
  | HistogramChart
  | BoxplotChart
  | ScatterChart
  | LineChart
  | HeatmapChart
  | RegressionChart;

function numericOptions(cols: ChartColumn[]) {
  return cols.filter((c) => c.numeric);
}

export default function Charts() {
  const { datasets, reload } = useLibrary();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [columns, setColumns] = useState<ChartColumn[]>([]);
  const [chartType, setChartType] = useState<ChartType>('histogram');
  const [histColumn, setHistColumn] = useState('');
  const [histBins, setHistBins] = useState('');
  const [boxCols, setBoxCols] = useState<string[]>([]);
  const [independentScale, setIndependentScale] = useState(true);
  const [xy, setXy] = useState<{ x: string; y: string }>({ x: '', y: '' });
  const [chart, setChart] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const list = readyDatasets(datasets);
  const selected = list.find((d) => d.id === selectedId) ?? null;
  const numeric = useMemo(() => numericOptions(columns), [columns]);

  useEffect(() => {
    if (selectedId === null && list.length > 0) {
      const corr = list.find((d) => d.name.includes('相关性'));
      setSelectedId(corr ? corr.id : list[0].id);
    }
  }, [list, selectedId]);

  // Load per-column chart usability whenever the dataset changes, and set
  // sensible field defaults (first numeric column(s)).
  useEffect(() => {
    if (selectedId === null) return;
    setColumns([]);
    setChart(null);
    setError('');
    fetchChartColumns(selectedId)
      .then((r) => {
        setColumns(r.columns);
        const nums = numericOptions(r.columns);
        setHistColumn(nums[0]?.name ?? '');
        setBoxCols(nums.map((c) => c.name));
        setXy({ x: nums[0]?.name ?? '', y: nums[1]?.name ?? nums[0]?.name ?? '' });
      })
      .catch((e) => setError(e instanceof Error ? e.message : '加载字段失败'));
  }, [selectedId]);

  // Fetch chart data whenever dataset, type or fields change.
  useEffect(() => {
    if (selectedId === null || columns.length === 0) return;
    setLoading(true);
    setError('');
    let cancelled = false;
    const done = (c: ChartData) => {
      if (!cancelled) {
        setChart(c);
        setLoading(false);
      }
    };
    const fail = (e: unknown) => {
      if (!cancelled) {
        setError(e instanceof Error ? e.message : '绘图失败');
        setChart(null);
        setLoading(false);
      }
    };
    if (chartType === 'histogram' && histColumn) {
      const bins = histBins.trim() === '' ? undefined : Number(histBins);
      fetchHistogram(selectedId, histColumn, bins).then((r) => done(r.chart)).catch(fail);
    } else if (chartType === 'boxplot') {
      fetchBoxplot(selectedId, boxCols).then((r) => done(r.chart)).catch(fail);
    } else if (chartType === 'scatter' && xy.x && xy.y) {
      fetchScatter(selectedId, xy.x, xy.y).then((r) => done(r.chart)).catch(fail);
    } else if (chartType === 'line' && xy.x && xy.y) {
      fetchLine(selectedId, xy.x, xy.y).then((r) => done(r.chart)).catch(fail);
    } else if (chartType === 'heatmap') {
      fetchHeatmap(selectedId).then((r) => done(r.chart)).catch(fail);
    } else if (chartType === 'regression' && xy.x && xy.y) {
      fetchRegression(selectedId, xy.x, xy.y).then((r) => done(r.chart)).catch(fail);
    } else {
      setLoading(false);
    }
    return () => {
      cancelled = true;
    };
  }, [selectedId, columns, chartType, histColumn, histBins, boxCols, xy]);

  const plot = useMemo(() => {
    if (!chart || !selected) return null;
    const base = { margin: { l: 60, r: 20, t: 20, b: 60 } };
    if (chart.type === 'histogram') {
      const centers = chart.bin_edges.slice(0, -1).map((e, i) => (e + chart.bin_edges[i + 1]) / 2);
      const width = chart.bin_edges.length > 1 ? chart.bin_edges[1] - chart.bin_edges[0] : 1;
      return {
        title: `直方图：${chart.column}`,
        data: [{ type: 'bar', x: centers, y: chart.counts, width: width * 0.9, marker: { color: '#2563eb' } }],
        layout: { ...base, xaxis: { title: { text: chart.column } }, yaxis: { title: { text: '频数' } } },
        note: `分箱 ${chart.bins} 个（${chart.method === 'freedman-diaconis' ? 'Freedman-Diaconis 自动分箱' : chart.method === 'sturges' ? 'Sturges 自动分箱' : '手动分箱'}）；有效样本 ${chart.n} 个，缺失/非数值剔除 ${chart.missing} 个；取值范围 ${chart.min} ~ ${chart.max}。`,
      };
    }
    if (chart.type === 'boxplot') {
      const traces: unknown[] = chart.boxes.map((b) => ({
        type: 'box',
        name: b.column,
        q1: [b.q1],
        median: [b.median],
        q3: [b.q3],
        lowerfence: [b.lower],
        upperfence: [b.upper],
        boxpoints: false,
        marker: { color: '#2563eb' },
      }));
      const outX: string[] = [];
      const outY: number[] = [];
      const outText: string[] = [];
      chart.boxes.forEach((b) => {
        b.outliers.forEach((o) => {
          outX.push(b.column);
          outY.push(o.value);
          outText.push(`第 ${o.row_number} 行：${o.value}`);
        });
      });
      if (outX.length > 0) {
        traces.push({
          type: 'scatter',
          mode: 'markers',
          name: '异常点（IQR，待确认）',
          x: outX,
          y: outY,
          text: outText,
          marker: { color: '#dc2626', size: 8, symbol: 'circle-open' },
        });
      }
      const totalOut = chart.boxes.reduce((s, b) => s + b.outlier_count, 0);
      return {
        title: '箱线图（IQR 异常点）',
        data: traces,
        layout: { ...base, xaxis: { title: { text: '字段' } }, yaxis: { title: { text: '数值' } }, showlegend: true },
        note: `箱体为 Q1~Q3，中线为中位数，须线为 1.5×IQR 边界；红圈为 IQR 异常点，共 ${totalOut} 个，与审计页的“待确认”清单一致（统计异常不一定是错误，不自动删除）。${chart.skipped_columns.length > 0 ? '跳过：' + chart.skipped_columns.map((s) => `${s.column}（${s.reason}）`).join('；') : ''}`,
      };
    }
    if (chart.type === 'scatter' || chart.type === 'line') {
      const isLine = chart.type === 'line';
      return {
        title: isLine ? `折线图：${chart.y_column} 随 ${chart.x_column} 变化` : `散点图：${chart.x_column} × ${chart.y_column}`,
        data: [
          {
            type: 'scatter',
            mode: isLine ? 'lines+markers' : 'markers',
            x: chart.points.map((p) => p.x),
            y: chart.points.map((p) => p.y),
            text: chart.points.map((p) => `第 ${p.row_number} 行`),
            marker: { color: '#2563eb', size: 6 },
          },
        ],
        layout: {
          ...base,
          xaxis: { title: { text: chart.x_column } },
          yaxis: { title: { text: chart.y_column } },
        },
        note: isLine
          ? `按 ${chart.sorted_by} 升序排列；成对有效样本 ${chart.n} 个，剔除缺失/非数值 ${chart.excluded} 行。`
          : `成对有效样本 ${chart.n} 个，剔除缺失/非数值 ${chart.excluded} 行。`,
      };
    }
    if (chart.type === 'heatmap') {
      const text = chart.matrix.map((row) =>
        row.map((v) => (v === null ? '—' : Math.abs(v) < 0.005 ? '0.00' : v.toFixed(2))),
      );
      return {
        title: '相关性热力图（Pearson）',
        data: [
          {
            type: 'heatmap',
            z: chart.matrix,
            x: chart.columns,
            y: chart.columns,
            text,
            texttemplate: '%{text}',
            colorscale: 'RdBu',
            zmin: -1,
            zmax: 1,
            colorbar: { title: { text: 'r' } },
          },
        ],
        layout: { ...base, xaxis: { title: { text: '字段' } }, yaxis: { title: { text: '字段' } } },
        note: `Pearson 相关系数，成对删除缺失值，每对至少 3 个有效样本。${chart.skipped_columns.length > 0 ? '跳过：' + chart.skipped_columns.map((s) => `${s.column}（${s.reason}）`).join('；') : ''}${chart.unavailable.length > 0 ? '无法计算：' + chart.unavailable.map((u) => `${u.columns.join(' × ')}（${u.reason}）`).join('；') : ''}`,
      };
    }
    // regression
    return {
      title: `线性回归：${chart.y_column} ~ ${chart.x_column}`,
      data: [
        {
          type: 'scatter',
          mode: 'markers',
          name: '观测点',
          x: chart.points.map((p) => p.x),
          y: chart.points.map((p) => p.y),
          text: chart.points.map((p) => `第 ${p.row_number} 行`),
          marker: { color: '#2563eb', size: 6 },
        },
        {
          type: 'scatter',
          mode: 'lines',
          name: '拟合直线',
          x: chart.fit_line.x,
          y: chart.fit_line.y,
          line: { color: '#dc2626', width: 2 },
        },
      ],
      layout: {
        ...base,
        xaxis: { title: { text: chart.x_column } },
        yaxis: { title: { text: chart.y_column } },
        showlegend: true,
      },
      note: `普通最小二乘（OLS），成对删除缺失值；有效样本 ${chart.n} 个，剔除 ${chart.excluded} 行。`,
    };
  }, [chart, selected]);

  const reg = chart && chart.type === 'regression' ? chart : null;

  // Independent-scale boxplots (Wave 3 fix): one subplot per column, each with
  // its own Y axis, so a small-scale column (e.g. concentration ~0.5) is not
  // flattened by a large-scale column (e.g. sample_id 0–125) sharing one axis.
  const boxplotPlots = useMemo(() => {
    if (!chart || chart.type !== 'boxplot') return null;
    return chart.boxes.map((b) => {
      const traces: unknown[] = [
        {
          type: 'box',
          name: b.column,
          q1: [b.q1],
          median: [b.median],
          q3: [b.q3],
          lowerfence: [b.lower],
          upperfence: [b.upper],
          boxpoints: false,
          marker: { color: '#2563eb' },
        },
      ];
      if (b.outliers.length > 0) {
        traces.push({
          type: 'scatter',
          mode: 'markers',
          name: '异常点（IQR，待确认）',
          x: b.outliers.map(() => b.column),
          y: b.outliers.map((o) => o.value),
          text: b.outliers.map((o) => `第 ${o.row_number} 行：${o.value}`),
          marker: { color: '#dc2626', size: 8, symbol: 'circle-open' },
        });
      }
      return {
        column: b.column,
        title: `箱线图：${b.column}`,
        data: traces,
        layout: {
          margin: { l: 60, r: 20, t: 20, b: 60 },
          xaxis: { title: { text: '字段' } },
          yaxis: { title: { text: b.column } },
          showlegend: true,
        },
        note: `Q1 ${b.q1} · 中位数 ${b.median} · Q3 ${b.q3} · 须线 ${b.lower} ~ ${b.upper}；有效样本 ${b.n} 个，IQR 异常点 ${b.outlier_count} 个（待确认，不自动删除）。`,
      };
    });
  }, [chart]);

  const boxTotalOut =
    chart && chart.type === 'boxplot' ? chart.boxes.reduce((s, b) => s + b.outlier_count, 0) : 0;

  return (
    <>
      <PageHeader title="数据可视化" desc="六类交互图表 — 全部由后端真实计算后下发，支持悬停读数、缩放与下载" />
      {datasets.status === 'loading' && <LoadingState text="正在加载数据集…" />}
      {datasets.status === 'error' && <ErrorState message={datasets.message} onRetry={reload} />}
      {datasets.status === 'ready' && list.length === 0 && (
        <EmptyState
          title="暂无可绘图的数据集"
          hint="先上传一份数据，或使用内置演示数据。"
          action={
            <Link to="/datasets" className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">
              去数据集管理
            </Link>
          }
        />
      )}
      {datasets.status === 'ready' && list.length > 0 && selected && (
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
              <div className="flex flex-wrap gap-2" role="tablist" aria-label="图表类型">
                {CHART_TYPES.map((t) => (
                  <button
                    key={t.key}
                    role="tab"
                    aria-selected={chartType === t.key}
                    onClick={() => setChartType(t.key)}
                    className={`rounded-lg px-3 py-2 text-sm font-medium ${
                      chartType === t.key ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>

            {/* field selectors per chart type */}
            <div className="mt-4 flex flex-wrap items-end gap-4 text-sm">
              {chartType === 'histogram' && (
                <>
                  <label>
                    <span className="mb-1 block text-slate-500">字段（数值列）</span>
                    <select value={histColumn} onChange={(e) => setHistColumn(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-2">
                      {columns.map((c) => (
                        <option key={c.name} value={c.name} disabled={!c.numeric}>
                          {c.name}
                          {c.numeric ? '' : `（非数值列：${c.reason}）`}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span className="mb-1 block text-slate-500">分箱数（留空自动）</span>
                    <input
                      value={histBins}
                      onChange={(e) => setHistBins(e.target.value.replace(/[^0-9]/g, ''))}
                      placeholder="自动"
                      className="w-24 rounded-lg border border-slate-300 px-3 py-2"
                    />
                  </label>
                </>
              )}
              {chartType === 'boxplot' && (
                <>
                  <fieldset>
                    <legend className="mb-1 text-slate-500">字段（数值列，可多选）</legend>
                    <div className="flex flex-wrap gap-3">
                      {columns.map((c) => (
                        <label key={c.name} className={`flex items-center gap-1 ${c.numeric ? '' : 'text-slate-400'}`}>
                          <input
                            type="checkbox"
                            disabled={!c.numeric}
                            checked={boxCols.includes(c.name)}
                            onChange={(e) =>
                              setBoxCols(e.target.checked ? [...boxCols, c.name] : boxCols.filter((x) => x !== c.name))
                            }
                          />
                          {c.name}
                          {!c.numeric && `（${c.reason}）`}
                        </label>
                      ))}
                    </div>
                  </fieldset>
                  <label className="flex items-center gap-2 text-slate-700">
                    <input
                      type="checkbox"
                      checked={independentScale}
                      onChange={(e) => setIndependentScale(e.target.checked)}
                    />
                    每列独立量纲
                    <span className="text-xs text-slate-400">
                      （开启：每列单独成图、各用各的 Y 轴，小量纲列不再被压扁；关闭：多列共用一轴）
                    </span>
                  </label>
                </>
              )}
              {(chartType === 'scatter' || chartType === 'line' || chartType === 'regression') && (
                <>
                  <label>
                    <span className="mb-1 block text-slate-500">X 轴（数值列）</span>
                    <select value={xy.x} onChange={(e) => setXy({ ...xy, x: e.target.value })} className="rounded-lg border border-slate-300 px-3 py-2">
                      {columns.map((c) => (
                        <option key={c.name} value={c.name} disabled={!c.numeric}>
                          {c.name}
                          {c.numeric ? '' : `（非数值列：${c.reason}）`}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span className="mb-1 block text-slate-500">Y 轴（数值列）</span>
                    <select value={xy.y} onChange={(e) => setXy({ ...xy, y: e.target.value })} className="rounded-lg border border-slate-300 px-3 py-2">
                      {columns.map((c) => (
                        <option key={c.name} value={c.name} disabled={!c.numeric}>
                          {c.name}
                          {c.numeric ? '' : `（非数值列：${c.reason}）`}
                        </option>
                      ))}
                    </select>
                  </label>
                </>
              )}
              {chartType === 'heatmap' && <p className="text-slate-500">全部数值列自动参与，成对删除缺失值。</p>}
            </div>
            {numeric.length < 1 && <p className="mt-3 text-sm text-amber-700">该数据集没有数值列，无法绘图。</p>}
            {numeric.length === 1 && (chartType === 'scatter' || chartType === 'line' || chartType === 'regression' || chartType === 'heatmap') && (
              <p className="mt-3 text-sm text-amber-700">该数据集只有 1 个数值列，此图表至少需要 2 个数值列。</p>
            )}
          </section>

          {(chartType === 'heatmap' || chartType === 'regression') && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">{CAUSALITY_NOTE}</div>
          )}

          {loading && <LoadingState text="正在计算图表数据…" />}
          {!loading && error && <ErrorState message={error} onRetry={() => setChartType(chartType)} />}
          {!loading && !error && chartType === 'boxplot' && independentScale && boxplotPlots && (
            <section className="rounded-xl border border-slate-200 bg-white p-5" data-testid="boxplot-independent">
              <h2 className="font-semibold text-slate-900">箱线图（IQR 异常点，每列独立量纲）</h2>
              <p className="mt-1 text-sm text-slate-500">
                每列单独成图、各用各的 Y 轴；箱体为 Q1~Q3，中线为中位数，须线为 1.5×IQR 边界；红圈为 IQR 异常点，共 {boxTotalOut} 个，与审计页的“待确认”清单一致（统计异常不一定是错误，不自动删除）。
              </p>
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                {boxplotPlots.map((bp) => (
                  <div key={bp.column} className="rounded-lg border border-slate-100 p-3">
                    <Plot data={bp.data} layout={bp.layout} title={bp.title} testId={`boxplot-col-${bp.column}`} />
                    <p className="mt-3 text-sm text-slate-500">{bp.note}</p>
                  </div>
                ))}
              </div>
            </section>
          )}
          {!loading && !error && !(chartType === 'boxplot' && independentScale && boxplotPlots) && plot && (
            <section className="rounded-xl border border-slate-200 bg-white p-5">
              <Plot data={plot.data} layout={plot.layout} title={plot.title} testId="chart-plot" />
              <p className="mt-3 text-sm text-slate-500">{plot.note}</p>
              {reg && (
                <div className="mt-4 grid gap-3 rounded-lg bg-slate-50 p-4 text-sm sm:grid-cols-4">
                  <div>
                    <p className="text-slate-500">回归方程</p>
                    <p className="mt-1 font-mono font-semibold text-slate-900">{reg.equation}</p>
                  </div>
                  <div>
                    <p className="text-slate-500">R²（决定系数）</p>
                    <p className="mt-1 font-mono font-semibold text-slate-900">{reg.r_squared.toFixed(4)}</p>
                  </div>
                  <div>
                    <p className="text-slate-500">相关系数 r</p>
                    <p className="mt-1 font-mono font-semibold text-slate-900">{reg.r.toFixed(4)}</p>
                  </div>
                  <div>
                    <p className="text-slate-500">样本量 n</p>
                    <p className="mt-1 font-mono font-semibold text-slate-900">{reg.n}</p>
                  </div>
                </div>
              )}
              {chartType === 'heatmap' && <p className="mt-3 text-sm text-amber-700">{CAUSALITY_NOTE}</p>}
            </section>
          )}
        </div>
      )}
    </>
  );
}
