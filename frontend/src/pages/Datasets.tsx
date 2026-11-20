import { useRef, useState } from 'react';
import { deleteDataset, fetchPreview, uploadDataset, type Dataset, type Preview } from '../api/client';
import { useLibrary } from '../api/hooks';
import { EmptyState, ErrorState, LoadingState, PageHeader } from '../components/StateViews';

export default function Datasets() {
  const { datasets, reload } = useLibrary();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [uploadOk, setUploadOk] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  async function onUpload(file: File | undefined) {
    if (!file) return;
    setUploading(true);
    setUploadError('');
    setUploadOk('');
    try {
      const rec = await uploadDataset(file);
      setUploadOk(`已上传「${rec.name}」：${rec.rows_count} 行 × ${rec.cols_count} 列，SHA-256 已记录。`);
      reload();
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : '上传失败');
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }

  async function onPreview(ds: Dataset) {
    setPreview(null);
    setPreviewError('');
    setPreviewLoading(true);
    try {
      setPreview(await fetchPreview(ds.id, 20));
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : '预览失败');
    } finally {
      setPreviewLoading(false);
    }
  }

  async function onDelete(ds: Dataset) {
    if (!window.confirm(`确定删除数据集「${ds.name}」吗？此操作不可恢复。`)) return;
    try {
      await deleteDataset(ds.id);
      if (preview?.id === ds.id) setPreview(null);
      reload();
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : '删除失败');
    }
  }

  return (
    <>
      <PageHeader title="数据集管理" desc="上传 CSV / Excel，预览表格，查看行列与字段类型" />
      <div className="mb-4 rounded-xl border border-slate-200 bg-white p-5">
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.xlsx"
            className="text-sm"
            onChange={(e) => onUpload(e.target.files?.[0])}
            disabled={uploading}
          />
          <span className="text-xs text-slate-500">
            仅支持 CSV / XLSX，大小上限 10 MB，行数上限 100000 行。
          </span>
        </div>
        {uploading && <p className="mt-2 text-sm text-slate-500">正在上传并解析…</p>}
        {uploadError && <p className="mt-2 text-sm text-red-600">上传失败：{uploadError}</p>}
        {uploadOk && <p className="mt-2 text-sm text-green-700">{uploadOk}</p>}
      </div>

      {datasets.status === 'loading' && <LoadingState text="正在加载数据集…" />}
      {datasets.status === 'error' && (
        <ErrorState message={datasets.message} onRetry={reload} />
      )}
      {datasets.status === 'ready' && datasets.data.length === 0 && (
        <EmptyState title="暂无数据集" hint="上传一份 CSV 或 Excel，或等待启动时自动 seeding 内置演示数据。" />
      )}
      {datasets.status === 'ready' && datasets.data.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">名称</th>
                <th className="px-4 py-3 font-medium">来源</th>
                <th className="px-4 py-3 font-medium">行 × 列</th>
                <th className="px-4 py-3 font-medium">SHA-256（前 12 位）</th>
                <th className="px-4 py-3 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {datasets.data.map((d) => (
                <tr key={d.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-3 font-medium text-slate-900">{d.name}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded px-2 py-0.5 text-xs ${
                        d.source === 'golden'
                          ? 'bg-amber-100 text-amber-800'
                          : 'bg-blue-100 text-blue-800'
                      }`}
                    >
                      {d.source === 'golden' ? '内置演示' : '上传'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {d.rows_count} × {d.cols_count}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-500">
                    {d.file_hash.slice(0, 12)}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => onPreview(d)}
                      className="mr-3 text-blue-600 hover:underline"
                    >
                      预览
                    </button>
                    <button onClick={() => onDelete(d)} className="text-red-600 hover:underline">
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {previewLoading && <div className="mt-4"><LoadingState text="正在加载预览…" /></div>}
      {previewError && (
        <div className="mt-4"><ErrorState message={previewError} /></div>
      )}
      {preview && (
        <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200 bg-white p-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold text-slate-900">
              预览：{preview.name}（前 {preview.preview_rows.length} 行，共 {preview.rows} 行）
            </h2>
            <button onClick={() => setPreview(null)} className="text-sm text-slate-500 hover:underline">
              关闭
            </button>
          </div>
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50">
              <tr>
                {preview.columns.map((c) => (
                  <th key={c.name} className="px-3 py-2 font-medium text-slate-500">
                    {c.name}
                    <span className="ml-1 text-xs text-slate-400">{c.dtype}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.preview_rows.map((row, i) => (
                <tr key={i} className="border-b border-slate-100 last:border-0">
                  {preview.columns.map((c) => (
                    <td key={c.name} className="px-3 py-2 text-slate-700">
                      {row[c.name] ?? ''}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
