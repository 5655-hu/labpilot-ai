import { useCallback, useEffect, useState } from 'react';
import { fetchAnalyses, fetchDatasets, type Analysis, type Dataset } from './client';

export type LoadState<T> =
  | { status: 'loading' }
  | { status: 'error'; message: string; retry: () => void }
  | { status: 'ready'; data: T };

/** Loads datasets + analyses from the real backend. No fake data anywhere. */
export function useLibrary(): {
  datasets: LoadState<Dataset[]>;
  analyses: LoadState<Analysis[]>;
  reload: () => void;
} {
  const [datasets, setDatasets] = useState<LoadState<Dataset[]>>({ status: 'loading' });
  const [analyses, setAnalyses] = useState<LoadState<Analysis[]>>({ status: 'loading' });

  const load = useCallback(() => {
    setDatasets({ status: 'loading' });
    setAnalyses({ status: 'loading' });
    fetchDatasets()
      .then((d) => setDatasets({ status: 'ready', data: d }))
      .catch((e: Error) =>
        setDatasets({ status: 'error', message: e.message, retry: load }),
      );
    fetchAnalyses()
      .then((a) => setAnalyses({ status: 'ready', data: a.analyses }))
      .catch((e: Error) =>
        setAnalyses({ status: 'error', message: e.message, retry: load }),
      );
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return { datasets, analyses, reload: load };
}

/** Paged analysis history for the Archive page (Wave 5): 20 per page. */
export function useAnalysesPage(
  page: number,
  pageSize = 20,
): {
  items: LoadState<Analysis[]>;
  total: number;
  reload: () => void;
} {
  const [items, setItems] = useState<LoadState<Analysis[]>>({ status: 'loading' });
  const [total, setTotal] = useState(0);

  const load = useCallback(() => {
    setItems({ status: 'loading' });
    fetchAnalyses(pageSize, (page - 1) * pageSize)
      .then((r) => {
        setTotal(r.total);
        setItems({ status: 'ready', data: r.analyses });
      })
      .catch((e: Error) => setItems({ status: 'error', message: e.message, retry: load }));
  }, [page, pageSize]);

  useEffect(() => {
    load();
  }, [load]);

  return { items, total, reload: load };
}
