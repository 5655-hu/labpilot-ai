import { useState } from 'react';
import { Link } from 'react-router-dom';
import { archiveExportUrl, fetchArchive, type Archive } from '../api/client';
import { useLibrary, useAnalysesPage } from '../api/hooks';
import RerunButton from '../components/RerunButton';
import { EmptyState, ErrorState, LoadingState, PageHeader, WaveNote } from '../components/StateViews';

const TYPE_LABEL: Record<string, string> = {
  audit: '质量审计',
  stats: '统计分析',
  report: 'AI 报告',
  compare: '分组比较',
};

/** 复现档案（第四波）：每次分析的完整档案——数据集 SHA-256、运行环境、
 *  清洗规则、全部参数、引擎与代码版本、随机种子说明与结果快照；点开看
 *  详情、可下载一键重跑包、可一键重跑（audit / stats / report / compare
 *  四类均支持，compare 重跑在第四波补齐）。档案按需从分析记录现场组装，
 *  与分析记录永远一致，无单独档案表。 */
export default function Archive() {
  const { datasets, reload } = useLibrary();
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 20;
  const { items: analyses, total: analysesTotal, reload: reloadAnalyses } = useAnalysesPage(page, PAGE_SIZE);
  const pageCount = Math.max(1, Math.ceil(analysesTotal / PAGE_SIZE));
  const reloadAll = () => {
    reload();
    reloadAnalyses();
  };
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [archive, setArchive] = useState<Archive | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');

  const loading = analyses.status === 'loading' || datasets.status === 'loading';
  const error =
    analyses.status === 'error' ? analyses.message : datasets.status === 'error' ? datasets.message : null;

  const dsName = (id: number) =>
    datasets.status === 'ready'
      ? (datasets.data.find((d) => d.id === id)?.name ?? `数据集 #${id}`)
      : `数据集 #${id}`;

  async function openArchive(id: number) {
    setSelectedId(id);
    setDetailLoading(true);
    setDetailError('');
    setArchive(null);
    try {
      setArchive(await fetchArchive(id));
    } catch (e) {
      setDetailError(e instanceof Error ? e.message : '档案加载失败');
    } finally {
      setDetailLoading(false);
    }
  }

  const selected = analyses.status === 'ready' ? analyses.data.find((a) => a.id === selectedId) : undefined;

  return (
    <>
      <PageHeader title="复现档案" desc="每次分析自动封存：文件哈希、方法、参数、环境版本与结果 — 支持历史查看与一键复现导出" />
      <div className="mb-4">
        <WaveNote
          wave="第五波"
          text="完整档案已交付：点开任意一条分析可看 SHA-256、Python 与依赖版本、清洗规则、全部参数与随机种子说明；可下载一键重跑包（JSON），也可直接重跑——审计、统计、报告、分组比较四类均支持重跑。列表已分页，每页 20 条。"
        />
      </div>
      {loading && <LoadingState text="正在加载档案…" />}
      {error && <ErrorState message={error} onRetry={reloadAll} />}
      {!loading && !error && analyses.status === 'ready' && analysesTotal === 0 && (
        <EmptyState
          title="暂无分析档案"
          hint="完成一次分析后，档案会自动生成并保存在这里；当前库中有数据集但尚未产生分析记录。"
          action={
            <Link to="/datasets" className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">
              去数据集管理
            </Link>
          }
        />
      )}
      {!loading && !error && analyses.status === 'ready' && analysesTotal > 0 && (
        <div className="grid min-w-0 gap-5 lg:grid-cols-2">
          <section className="min-w-0 rounded-xl border border-slate-200 bg-white p-5" data-testid="archive-list">
            <h2 className="font-semibold text-slate-900">分析记录（共 {analysesTotal} 条）</h2>
            <p className="mt-1 text-sm text-slate-500">
              点一条查看完整档案；重跑用原参数重新执行同一分析并与原结果逐项比对，四类分析均可重跑。
            </p>
            <ul className="mt-4 space-y-3">
              {analyses.data.map((a) => (
                <li
                  key={a.id}
                  className={`rounded-lg border p-4 ${selectedId === a.id ? 'border-blue-400 bg-blue-50/40' : 'border-slate-200'}`}
                  data-testid={`analysis-${a.id}`}
                >
                  <button onClick={() => openArchive(a.id)} className="block w-full text-left text-sm">
                    <p className="font-medium text-slate-900">
                      #{a.id} · {TYPE_LABEL[a.name] ?? a.name} · {dsName(a.dataset_id)}
                    </p>
                    <p className="mt-1 text-slate-500">
                      状态 {a.status} · 引擎 {a.engine_version} · {a.created_at}
                      {a.finished_at ? ` → ${a.finished_at}` : ''}
                    </p>
                  </button>
                  <div className="mt-2">
                    <RerunButton analysisId={a.id} analysisName={a.name} onRerun={reloadAll} />
                  </div>
                </li>
              ))}
            </ul>
            <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 text-sm">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
              >
                上一页
              </button>
              <span className="text-slate-500">
                第 {page} / {pageCount} 页 · 每页 {PAGE_SIZE} 条
              </span>
              <button
                onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
                disabled={page >= pageCount}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
              >
                下一页
              </button>
            </div>
          </section>

          <section className="min-w-0 rounded-xl border border-slate-200 bg-white p-5" data-testid="archive-detail">
            {!selected && <p className="text-sm text-slate-500">点左侧任意一条分析，查看它的完整复现档案。</p>}
            {selected && detailLoading && <LoadingState text="正在加载档案详情…" />}
            {selected && detailError && <ErrorState message={detailError} onRetry={() => openArchive(selected.id)} />}
            {selected && archive && (
              <div className="space-y-4 text-sm">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="font-semibold text-slate-900">
                      #{archive.analysis_id} · {TYPE_LABEL[archive.analysis_type] ?? archive.analysis_type} 档案
                    </h2>
                    <p className="mt-1 text-slate-500">
                      {archive.dataset.name} · 档案版本 {archive.archive_version} · 归档于 {archive.archived_at}
                    </p>
                  </div>
                  {archiveExportUrl(archive.analysis_id) ? (
                    <a
                      href={archiveExportUrl(archive.analysis_id)}
                      download
                      data-testid="archive-export"
                      className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
                    >
                      下载重跑包（JSON）
                    </a>
                  ) : (
                    <span className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-500">
                      重跑包需后端在线
                    </span>
                  )}
                </div>

                <div>
                  <h3 className="font-medium text-slate-900">数据指纹</h3>
                  <p className="mt-1 break-all font-mono text-xs text-slate-600" data-testid="archive-hash">
                    SHA-256：{archive.data_fingerprint.file_hash}
                  </p>
                  <p className="mt-1 text-slate-500">
                    {archive.dataset.rows} 行 × {archive.dataset.cols} 列 · {archive.dataset.filename} ·
                    与上传时记录的哈希一致
                  </p>
                </div>

                <div>
                  <h3 className="font-medium text-slate-900">运行环境</h3>
                  <p className="mt-1 text-slate-600">
                    Python {archive.environment.python_version}（{archive.environment.python_implementation}）·{' '}
                    {archive.environment.platform}
                  </p>
                  <ul className="mt-1 grid grid-cols-2 gap-1 font-mono text-xs text-slate-600">
                    {Object.entries(archive.environment.dependencies).map(([k, v]) => (
                      <li key={k}>
                        {k} {v ?? '未安装'}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-1 text-slate-500">
                    代码版本 v{archive.code_version} · {archive.engine} 引擎 {archive.engine_version}
                  </p>
                </div>

                <div>
                  <h3 className="font-medium text-slate-900">清洗规则（{archive.cleaning_rules.source}）</h3>
                  <p className="mt-1 text-slate-600">
                    画像 {archive.cleaning_rules.profile}
                    {archive.cleaning_rules.profile_label ? `（${archive.cleaning_rules.profile_label}）` : ''} ·
                    算法 {archive.cleaning_rules.algorithms.join('、')} · IQR k={archive.cleaning_rules.iqr_k} ·
                    Z-score 阈值 {archive.cleaning_rules.z_threshold}
                  </p>
                  <p className="mt-1 text-slate-500">{archive.cleaning_rules.score_formula}</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-5 text-slate-500">
                    {archive.cleaning_rules.policy.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                </div>

                <div>
                  <h3 className="font-medium text-slate-900">分析参数</h3>
                  <pre className="mt-1 overflow-auto rounded-lg bg-slate-50 p-3 font-mono text-xs text-slate-600">
                    {JSON.stringify(archive.params, null, 2)}
                  </pre>
                </div>

                <div>
                  <h3 className="font-medium text-slate-900">随机种子</h3>
                  <p className="mt-1 text-slate-600">{archive.random_seed.note}</p>
                </div>

                <div>
                  <h3 className="font-medium text-slate-900">结果快照</h3>
                  <pre className="mt-1 max-h-64 overflow-auto rounded-lg bg-slate-50 p-3 font-mono text-xs text-slate-600">
                    {JSON.stringify(archive.result_snapshot, null, 2)}
                  </pre>
                </div>

                <p className="text-xs text-slate-500">{archive.rerun.note}</p>
              </div>
            )}
          </section>
        </div>
      )}
    </>
  );
}
