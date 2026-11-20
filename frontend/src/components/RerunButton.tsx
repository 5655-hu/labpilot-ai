import { useState } from 'react';
import { rerunAnalysis, type RerunResult } from '../api/client';

/** 跨重挂载缓存：父页重跑后常会 reload 列表（useLibrary 会先回到 loading，
 *  列表短暂卸载再挂载），结果若只放在组件 state 里会被清空；放模块级缓存则重挂载后仍能显示。 */
const resultCache = new Map<number, RerunResult>();
const errorCache = new Map<number, string>();

/** “重跑”按钮：调 POST /api/analyses/{id}/rerun，展示是否一致与差异项。
 *  后端支持 audit / stats / report / compare 四类重跑（compare 在第四波补齐）。 */
export default function RerunButton({
  analysisId,
  analysisName,
  onRerun,
}: {
  analysisId: number;
  analysisName: string;
  onRerun?: () => void;
}) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RerunResult | null>(() => resultCache.get(analysisId) ?? null);
  const [error, setError] = useState(() => errorCache.get(analysisId) ?? '');

  async function onClick() {
    setRunning(true);
    setError('');
    setResult(null);
    try {
      const r = await rerunAnalysis(analysisId);
      resultCache.set(analysisId, r);
      errorCache.delete(analysisId);
      setResult(r);
      onRerun?.();
    } catch (e) {
      const msg = e instanceof Error ? e.message : '重跑失败';
      errorCache.set(analysisId, msg);
      resultCache.delete(analysisId);
      setError(msg);
    } finally {
      setRunning(false);
    }
  }

  return (
    <span className="inline-flex flex-col items-start gap-1" data-testid={`rerun-${analysisId}`}>
      <button
        onClick={onClick}
        disabled={running}
        title={`重跑分析 #${analysisId}（${analysisName}）`}
        className="rounded-lg border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
      >
        {running ? '重跑中…' : '重跑'}
      </button>
      {error && <span className="max-w-xs text-xs text-red-600">重跑失败：{error}</span>}
      {result && (
        <span
          className={`max-w-xs rounded-lg border px-2 py-1 text-xs ${
            result.consistent ? 'border-green-200 bg-green-50 text-green-800' : 'border-amber-200 bg-amber-50 text-amber-800'
          }`}
          data-testid={`rerun-result-${analysisId}`}
        >
          重跑完成：新分析 #{result.rerun_id}，
          {result.consistent ? '结果一致' : `结果不一致（${result.differences.length} 处差异）`}
          {result.engine_version_changed && `；引擎版本 ${result.original_engine_version} → ${result.engine_version}`}
          {!result.consistent &&
            result.differences.map((d, i) => (
              <span key={i} className="mt-1 block">
                {d.key}：{JSON.stringify(d.old)} → {JSON.stringify(d.new)}
              </span>
            ))}
        </span>
      )}
    </span>
  );
}
