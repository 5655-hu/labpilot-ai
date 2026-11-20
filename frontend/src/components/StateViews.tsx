export function LoadingState({ text = '正在加载…' }: { text?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-slate-500" role="status">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-300 border-t-blue-600" />
      <p className="mt-3 text-sm">{text}</p>
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white py-16 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-xl text-slate-400">
        ○
      </div>
      <p className="mt-4 font-medium text-slate-700">{title}</p>
      {hint && <p className="mt-1 max-w-md text-sm text-slate-500">{hint}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      className="flex flex-col items-center justify-center rounded-xl border border-red-200 bg-red-50 py-16 text-center"
      role="alert"
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-100 text-xl text-red-500">
        !
      </div>
      <p className="mt-4 font-medium text-red-700">加载失败</p>
      <p className="mt-1 max-w-md text-sm text-red-600">
        {message}。请确认后端服务正在运行，然后重试。
      </p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-5 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
        >
          重新加载
        </button>
      )}
    </div>
  );
}

export function PageHeader({ title, desc }: { title: string; desc: string }) {
  return (
    <div className="mb-6">
      <h1 className="text-2xl font-bold text-slate-900">{title}</h1>
      <p className="mt-1 text-sm text-slate-500">{desc}</p>
    </div>
  );
}

export function WaveNote({ wave, text }: { wave: string; text: string }) {
  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
      <span className="mr-2 rounded bg-blue-600 px-2 py-0.5 text-xs font-semibold text-white">
        {wave}
      </span>
      {text}
    </div>
  );
}
