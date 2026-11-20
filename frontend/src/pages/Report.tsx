import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  fetchLatestReport,
  generateReport,
  type ReportResponse,
  type ReportResult,
} from '../api/client';
import { readyDatasets, useLibrary } from '../api/hooks';
import RerunButton from '../components/RerunButton';
import { EmptyState, ErrorState, LoadingState, PageHeader } from '../components/StateViews';

function fmt(v: number | null | undefined, digits = 4): string {
  if (v === null || v === undefined) return '—';
  return Number(v.toFixed(digits)).toString();
}

/** 用同一份报告 JSON 在客户端生成 Markdown：数字全部取自 JSON 原值，AI 段落原样嵌入。 */
function buildReportMarkdown(r: ReportResult, analysisId: number, createdAt?: string): string {
  const L: string[] = [];
  L.push(`# AI 科研报告：${r.dataset.name}`);
  L.push('');
  L.push(`- 数据集：${r.dataset.name}（${r.dataset.filename}）`);
  L.push(`- 规模：${r.dataset.rows} 行 × ${r.dataset.cols} 列`);
  L.push(`- 文件哈希：\`${r.dataset.file_hash}\``);
  L.push(`- 列：${r.dataset.columns.map((c) => `${c.name} (${c.dtype})`).join('、')}`);
  L.push(`- 分析编号：#${analysisId}${createdAt ? `（${createdAt}）` : ''}`);
  L.push(`- 生成时间：${r.generated_at}`);
  L.push(`- 来源：${r.source === 'ai' ? 'AI 生成' : '规则版'}${r.send_manifest ? `（模型 ${r.send_manifest.model}）` : ''}`);
  if (r.tokens) {
    L.push(`- Token 用量：prompt ${r.tokens.promptTokenCount} / 生成 ${r.tokens.candidatesTokenCount} / 合计 ${r.tokens.totalTokenCount}`);
  }
  if (r.send_manifest) {
    const elapsed = r.send_manifest.elapsed_seconds;
    const elapsedText = elapsed == null ? '不适用（未调用模型）' : `${elapsed} 秒`;
    L.push(`- AI 耗时：${elapsedText}；发送原始数据行数：${r.send_manifest.raw_rows_sent}（原始数据默认不发送）`);
  }
  L.push('');
  L.push('## 数据质量审计');
  L.push('');
  L.push(`- 质量分：${r.audit.score.total} 分（满分 100），扣分合计 ${r.audit.score.total_deduction} 分`);
  L.push(`- 公式：${r.audit.score.formula}`);
  L.push(`- 缺失单元格：${r.audit.missing.total}（有效缺失 ${r.audit.missing.effective_total}）；重复行：${r.audit.duplicates.count}（${(r.audit.duplicates.rate * 100).toFixed(2)}%）`);
  for (const d of r.audit.score.deductions) {
    L.push(`- ${d.label}：扣 ${d.deduction} 分（权重 ${d.weight}，${d.rate_basis}）。${d.reason}建议：${d.suggestion}`);
    for (const ev of d.evidence) {
      L.push(`  - 证据：${ev.column} 列，${ev.count} 处（${(ev.rate * 100).toFixed(2)}%）`);
    }
  }
  L.push('');
  L.push('## 描述统计');
  L.push('');
  L.push('| 列 | 有效数 | 缺失 | 均值 | 中位数 | 标准差 | 方差 | 最小值 | 最大值 |');
  L.push('| --- | --- | --- | --- | --- | --- | --- | --- | --- |');
  for (const [name, c] of Object.entries(r.stats.columns)) {
    L.push(`| ${name} | ${c.count} | ${c.missing} | ${fmt(c.mean, 6)} | ${fmt(c.median, 6)} | ${fmt(c.std, 6)} | ${fmt(c.variance, 6)} | ${fmt(c.min, 6)} | ${fmt(c.max, 6)} |`);
  }
  L.push('');
  L.push('## 相关性（Pearson）');
  L.push('');
  const cols = Object.keys(r.correlation.matrix);
  if (cols.length === 0) {
    L.push(r.correlation.note ?? '未计算相关性。');
  } else {
    L.push(`|  | ${cols.join(' | ')} |`);
    L.push(`| --- | ${cols.map(() => '---').join(' | ')} |`);
    for (const a of cols) {
      L.push(`| ${a} | ${cols.map((b) => (r.correlation.matrix[a][b] === null ? '—' : r.correlation.matrix[a][b]!.toFixed(4))).join(' | ')} |`);
    }
  }
  L.push('');
  L.push('## 线性回归');
  L.push('');
  if (r.regression.available) {
    L.push(`- 方程：${r.regression.equation}`);
    L.push(`- R²：${r.regression.r_squared}；相关系数 r：${r.regression.r}；样本量 n：${r.regression.n}`);
    L.push(`- 自变量：${r.regression.x_column}；因变量：${r.regression.y_column}`);
  } else {
    L.push('回归不可用（数值列不足或样本不足）。');
  }
  L.push('');
  L.push('## 结论（每条均可追溯到原始分析）');
  L.push('');
  for (const c of r.conclusions) {
    const ev = c.evidence;
    L.push(`- ${c.text}`);
    L.push(`  - 证据：分析 #${ev.analysis_ids.join('、#')}（${ev.analysis}），统计量 ${ev.statistic}，方法 ${ev.method}，参数 ${JSON.stringify(ev.params)}，原始数值 ${JSON.stringify(ev.value)}`);
  }
  L.push('');
  if (r.source === 'ai' && r.ai_text) {
    L.push('## AI 解读');
    L.push('');
    L.push(r.ai_text);
    L.push('');
  } else {
    L.push('## 解读');
    L.push('');
    L.push('规则版报告：未调用 AI，结论由确定性规则生成，数字与结构与 AI 版一致。');
    L.push('');
  }
  L.push('> 相关不等于因果：相关系数与回归结果只说明变量间的统计关联，不能证明因果关系。');
  L.push('');
  return L.join('\n');
}

export default function Report() {
  const { datasets, reload } = useLibrary();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [includeAi, setIncludeAi] = useState(true);
  const [resp, setResp] = useState<ReportResponse | null>(null);
  const [meta, setMeta] = useState('');
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
    setResp(null);
    setMeta('');
    setError('');
    fetchLatestReport(selectedId)
      .then((r) => {
        setResp(r);
        setMeta(`上次报告 ${r.created_at ?? ''}（分析 #${r.analysis_id}）`);
      })
      .catch(() => setResp(null))
      .finally(() => setLoadingLatest(false));
  }, [selectedId]);

  async function onGenerate() {
    if (selectedId === null) return;
    setRunning(true);
    setError('');
    try {
      const r = await generateReport(selectedId, includeAi);
      setResp(r);
      setMeta(`本次报告刚完成（分析 #${r.analysis_id}）`);
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : '生成报告失败');
    } finally {
      setRunning(false);
    }
  }

  function onExportMarkdown() {
    if (!resp) return;
    const md = buildReportMarkdown(resp.report, resp.analysis_id, resp.created_at);
    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `labpilot-report-${resp.report.dataset.filename.replace(/\.[^.]+$/, '')}-analysis-${resp.analysis_id}.md`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  const selected = list.find((d) => d.id === selectedId) ?? null;
  const report = resp?.report ?? null;
  const corrCols = report ? Object.keys(report.correlation.matrix) : [];

  return (
    <>
      <PageHeader title="AI 科研报告" desc="审计、统计、图表与 AI 解释整合为一份报告 — 数字由后端 JSON 填槽，AI 只写文字" />
      {datasets.status === 'loading' && <LoadingState text="正在加载数据集…" />}
      {datasets.status === 'error' && <ErrorState message={datasets.message} onRetry={reload} />}
      {datasets.status === 'ready' && list.length === 0 && (
        <EmptyState
          title="暂无可生成报告的数据集"
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
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={includeAi}
                  onChange={(e) => setIncludeAi(e.target.checked)}
                />
                使用 AI 生成解读（关闭则生成规则版）
              </label>
              <button
                onClick={onGenerate}
                disabled={running}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {running ? '生成中…' : '生成报告'}
              </button>
              {resp && (
                <button
                  onClick={onExportMarkdown}
                  className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  导出 Markdown
                </button>
              )}
            </div>
            {error && <p className="mt-3 text-sm text-red-600">生成失败：{error}</p>}
            <p className="mt-3 text-xs text-slate-400">
              报告数字全部来自后端结构化 JSON（审计、统计、回归先行计算）；AI 只写解释段落，且默认不接收原始数据行，只接收统计摘要。
            </p>
          </section>

          {loadingLatest && <LoadingState text="正在加载报告…" />}
          {!loadingLatest && !report && (
            <EmptyState title="该数据集尚无报告" hint="点“生成报告”，报告会存入复现档案。" />
          )}
          {!loadingLatest && report && resp && selected && (
            <div className="space-y-4" data-testid="report-content">
              {/* 来源标识 */}
              <section className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-5">
                <span
                  className={`rounded-full px-3 py-1 text-sm font-medium ${
                    report.source === 'ai' ? 'bg-violet-100 text-violet-800' : 'bg-slate-100 text-slate-700'
                  }`}
                >
                  {report.source === 'ai' ? 'AI 生成' : '规则版'}
                </span>
                <span className="text-sm text-slate-500">{meta}</span>
                {report.tokens && (
                  <span className="text-sm text-slate-500">
                    Token：prompt {report.tokens.promptTokenCount} / 生成 {report.tokens.candidatesTokenCount} / 合计 {report.tokens.totalTokenCount}
                  </span>
                )}
                {report.send_manifest && (
                  <span className="text-sm text-slate-500">
                    模型 {report.send_manifest.model}
                    {report.send_manifest.elapsed_seconds != null &&
                      ` · 耗时 ${report.send_manifest.elapsed_seconds} 秒`}
                    {' · '}原始数据行发送 {report.send_manifest.raw_rows_sent} 行
                  </span>
                )}
                <span className="ml-auto">
                  <RerunButton analysisId={resp.analysis_id} analysisName="report" onRerun={reload} />
                </span>
              </section>

              {/* 数据集概览 */}
              <section className="rounded-xl border border-slate-200 bg-white p-5">
                <h2 className="font-semibold text-slate-900">数据集概览</h2>
                <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                  <div className="min-w-0"><dt className="text-slate-500">名称</dt><dd className="font-medium text-slate-900 break-words">{report.dataset.name}（{report.dataset.filename}）</dd></div>
                  <div className="min-w-0"><dt className="text-slate-500">规模</dt><dd className="font-medium text-slate-900">{report.dataset.rows} 行 × {report.dataset.cols} 列</dd></div>
                  <div className="min-w-0"><dt className="text-slate-500">文件哈希</dt><dd className="font-mono text-xs text-slate-700 break-all">{report.dataset.file_hash}</dd></div>
                  <div className="min-w-0"><dt className="text-slate-500">生成时间</dt><dd className="font-medium text-slate-900 break-words">{report.generated_at}</dd></div>
                </dl>
                <p className="mt-2 text-sm text-slate-500">
                  列：{report.dataset.columns.map((c) => `${c.name} (${c.dtype})`).join('、')}
                </p>
              </section>

              {/* 审计评分与扣分证据 */}
              <section className="rounded-xl border border-slate-200 bg-white p-5">
                <h2 className="font-semibold text-slate-900">数据质量审计</h2>
                <p className="mt-2 text-sm text-slate-700">
                  质量分 <span className="text-2xl font-bold text-slate-900">{report.audit.score.total}</span> 分（满分 100），扣分合计 {report.audit.score.total_deduction} 分
                </p>
                <p className="mt-1 text-xs text-slate-400">{report.audit.score.formula}</p>
                <p className="mt-1 text-sm text-slate-500">
                  缺失单元格 {report.audit.missing.total}（有效缺失 {report.audit.missing.effective_total}）· 重复行 {report.audit.duplicates.count}（{(report.audit.duplicates.rate * 100).toFixed(2)}%）
                </p>
                <ul className="mt-3 space-y-3">
                  {report.audit.score.deductions.map((d) => (
                    <li key={d.category} className="rounded-lg bg-slate-50 p-3 text-sm">
                      <p className="font-medium text-slate-900">
                        {d.label}：扣 {d.deduction} 分 <span className="font-normal text-slate-500">（权重 {d.weight}，{d.rate_basis}）</span>
                      </p>
                      <p className="mt-1 text-slate-600">{d.reason}</p>
                      <p className="mt-1 text-slate-600">建议：{d.suggestion}</p>
                      {d.evidence.length > 0 && (
                        <details className="mt-2">
                          <summary className="cursor-pointer text-blue-700">扣分证据（{d.evidence.length} 项）</summary>
                          <ul className="mt-1 list-disc pl-5 text-slate-600">
                            {d.evidence.map((ev, i) => (
                              <li key={i}>
                                {ev.column} 列：{ev.count} 处（{(ev.rate * 100).toFixed(2)}%）
                                {ev.example_rows.length > 0 && `，示例 ${JSON.stringify(ev.example_rows.slice(0, 2))}`}
                              </li>
                            ))}
                          </ul>
                        </details>
                      )}
                    </li>
                  ))}
                </ul>
              </section>

              {/* 描述统计表 */}
              <section className="rounded-xl border border-slate-200 bg-white p-5">
                <h2 className="font-semibold text-slate-900">描述统计</h2>
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
                      {Object.entries(report.stats.columns).map(([name, c]) => (
                        <tr key={name} className="border-b border-slate-100 last:border-0">
                          <td className="px-3 py-2 font-medium text-slate-900">{name}</td>
                          <td className="px-3 py-2 text-slate-600">{c.count}</td>
                          <td className="px-3 py-2 text-slate-600">{c.missing}</td>
                          <td className="px-3 py-2 text-slate-700">{fmt(c.mean, 6)}</td>
                          <td className="px-3 py-2 text-slate-700">{fmt(c.median, 6)}</td>
                          <td className="px-3 py-2 text-slate-700">{fmt(c.std, 6)}</td>
                          <td className="px-3 py-2 text-slate-700">{fmt(c.variance, 6)}</td>
                          <td className="px-3 py-2 text-slate-700">{fmt(c.min, 6)}</td>
                          <td className="px-3 py-2 text-slate-700">{fmt(c.max, 6)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              {/* 相关性 */}
              <section className="rounded-xl border border-slate-200 bg-white p-5">
                <h2 className="font-semibold text-slate-900">相关性（Pearson）</h2>
                {corrCols.length === 0 ? (
                  <p className="mt-2 text-sm text-slate-500">{report.correlation.note ?? '未计算相关性。'}</p>
                ) : (
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
                                {report.correlation.matrix[a][b] === null ? '—' : report.correlation.matrix[a][b]?.toFixed(4)}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <p className="mt-3 text-xs text-slate-400">相关不等于因果；相关系数接近 ±1 只说明线性关系强。</p>
              </section>

              {/* 回归 */}
              <section className="rounded-xl border border-slate-200 bg-white p-5">
                <h2 className="font-semibold text-slate-900">线性回归</h2>
                {report.regression.available ? (
                  <div className="mt-3 grid gap-3 text-sm sm:grid-cols-4">
                    <div><p className="text-slate-500">回归方程</p><p className="mt-1 font-mono font-semibold text-slate-900">{report.regression.equation}</p></div>
                    <div><p className="text-slate-500">R²（决定系数）</p><p className="mt-1 font-mono font-semibold text-slate-900">{report.regression.r_squared}</p></div>
                    <div><p className="text-slate-500">相关系数 r</p><p className="mt-1 font-mono font-semibold text-slate-900">{report.regression.r}</p></div>
                    <div><p className="text-slate-500">样本量 n</p><p className="mt-1 font-mono font-semibold text-slate-900">{report.regression.n}</p></div>
                  </div>
                ) : (
                  <p className="mt-2 text-sm text-slate-500">回归不可用（数值列不足或样本不足）。</p>
                )}
              </section>

              {/* 结论与证据链 */}
              <section className="rounded-xl border border-slate-200 bg-white p-5">
                <h2 className="font-semibold text-slate-900">结论与证据链</h2>
                <ul className="mt-3 space-y-3">
                  {report.conclusions.map((c) => (
                    <li key={c.id} className="rounded-lg bg-slate-50 p-3 text-sm">
                      <p className="text-slate-900">{c.text}</p>
                      <details className="mt-2">
                        <summary className="cursor-pointer text-blue-700">证据</summary>
                        <dl className="mt-1 grid gap-1 text-slate-600 sm:grid-cols-2">
                          <div><dt className="text-slate-500">来自分析</dt><dd>#{c.evidence.analysis_ids.join('、#')}（{c.evidence.analysis}，数据集 #{c.evidence.dataset_id}）</dd></div>
                          <div><dt className="text-slate-500">统计量</dt><dd>{c.evidence.statistic}</dd></div>
                          <div><dt className="text-slate-500">方法</dt><dd>{c.evidence.method}</dd></div>
                          <div><dt className="text-slate-500">原始数值</dt><dd className="font-mono">{JSON.stringify(c.evidence.value)}</dd></div>
                          <div className="sm:col-span-2"><dt className="text-slate-500">参数</dt><dd className="font-mono text-xs">{JSON.stringify(c.evidence.params)}</dd></div>
                        </dl>
                      </details>
                    </li>
                  ))}
                </ul>
              </section>

              {/* AI 解读 */}
              <section className="rounded-xl border border-slate-200 bg-white p-5">
                <h2 className="font-semibold text-slate-900">{report.source === 'ai' ? 'AI 解读' : '规则版解读'}</h2>
                {report.source === 'ai' && report.ai_text ? (
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-slate-700">{report.ai_text}</p>
                ) : (
                  <p className="mt-2 text-sm text-slate-500">
                    规则版报告：未调用 AI，结论由确定性规则生成，数字与结构与 AI 版一致。
                  </p>
                )}
                <p className="mt-3 text-xs text-slate-400">
                  本报告的数字全部来自后端结构化 JSON，AI 不参与数字计算；相关与回归结果不构成因果推断。
                </p>
              </section>
            </div>
          )}
        </div>
      )}
    </>
  );
}
