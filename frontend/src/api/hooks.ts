import { useCallback, useEffect, useState } from 'react';
import { fetchAnalyses, fetchDatasets, type Analysis, type Dataset } from './client';

export type LoadState<T> =
  | { status: 'loading' }
  | { status: 'error'; message: string; retry: () => void }
  | { status: 'ready'; data: T };

/** Shared empty array: a stable identity so effects depending on the dataset
 * list don't re-run on every render while the library is still loading. */
const NO_DATASETS: Dataset[] = [];

/** Dataset array for rendering. Returns the loaded array (stable identity) or
 * the shared empty array — never a fresh `[]` per render. */
export function readyDatasets(state: LoadState<Dataset[]>): Dataset[] {
  return state.status === 'ready' ? state.data : NO_DATASETS;
}

/** Loads datasets + analyses from the real backend. No fake data anywhere. */
export function useLibrary(): {
  datasets: LoadState<Dataset[]>;
  analyses: LoadState<Analysis[]>;
  reload: () => void;
} {
  const [datasets, setDatasets] = useState<LoadState<Dataset[]>>({ status: 'loading' });
  const [analyses, setAnalyses] = useState<LoadState<Analysis[]>>({ status: 'loading' });

  // Named function expression: the retry callback can reference the loader
  // itself without reading the outer `load` binding while it is initialising.
  const load = useCallback(function loadLibrary() {
    setDatasets({ status: 'loading' });
    setAnalyses({ status: 'loading' });
    fetchDatasets()
      .then((d) => setDatasets({ status: 'ready', data: d }))
      .catch((e: Error) =>
        setDatasets({ status: 'error', message: e.message, retry: loadLibrary }),
      );
    fetchAnalyses()
      .then((a) => setAnalyses({ status: 'ready', data: a.analyses }))
      .catch((e: Error) =>
        setAnalyses({ status: 'error', message: e.message, retry: loadLibrary }),
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

  const load = useCallback(function loadPage() {
    setItems({ status: 'loading' });
    fetchAnalyses(pageSize, (page - 1) * pageSize)
      .then((r) => {
        setTotal(r.total);
        setItems({ status: 'ready', data: r.analyses });
      })
      .catch((e: Error) => setItems({ status: 'error', message: e.message, retry: loadPage }));
  }, [page, pageSize]);

  useEffect(() => {
    load();
  }, [load]);

  return { items, total, reload: load };
}
