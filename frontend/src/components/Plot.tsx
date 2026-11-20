import { useEffect, useRef, useState } from 'react';

/** Thin Plotly.js wrapper: draws interactive charts (hover, zoom, pan,
 *  download) from backend-computed data. Plotly (~1 MB gzipped) is loaded
 *  lazily on first use so the rest of the app stays light. Re-renders with
 *  Plotly.react whenever the trace data or layout changes. */
type PlotlyApi = typeof import('plotly.js-dist').default;

let plotlyPromise: Promise<PlotlyApi> | null = null;
function getPlotly(): Promise<PlotlyApi> {
  if (!plotlyPromise) {
    plotlyPromise = import('plotly.js-dist').then((m) => m.default);
  }
  return plotlyPromise;
}

export default function Plot({
  data,
  layout,
  title,
  testId,
}: {
  data: unknown[];
  layout: Record<string, unknown>;
  title: string;
  testId: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const plotlyRef = useRef<PlotlyApi | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setReady(false);
    let cancelled = false;
    getPlotly()
      .then((Plotly) => {
        plotlyRef.current = Plotly;
        if (cancelled) return;
        // automargin keeps long axis tick labels (e.g. heatmap column names)
        // from being clipped by the fixed margins.
        const layoutWithMargins = {
          ...layout,
          margin: { l: 90, r: 20, t: 20, b: 70, ...((layout.margin as Record<string, unknown>) ?? {}) },
          xaxis: { automargin: true, ...((layout.xaxis as Record<string, unknown>) ?? {}) },
          yaxis: { automargin: true, ...((layout.yaxis as Record<string, unknown>) ?? {}) },
        };
        return Plotly.react(el, data, { ...layoutWithMargins, title: undefined }, {
          responsive: true,
          displaylogo: false,
          modeBarButtonsToRemove: ['lasso2d', 'select2d'],
        });
      })
      .then(() => {
        if (!cancelled) setReady(true);
      })
      .catch(() => {
        if (!cancelled) setReady(false);
      });
    return () => {
      cancelled = true;
      if (plotlyRef.current) plotlyRef.current.purge(el);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(data), JSON.stringify(layout)]);

  return (
    <div className="relative">
      <h3 className="mb-2 font-semibold text-slate-900">{title}</h3>
      <div ref={ref} data-testid={testId} data-chart-ready={ready ? 'true' : 'false'} className="h-[420px] w-full" />
      {!ready && <p className="mt-2 text-sm text-slate-400">图表渲染中…</p>}
    </div>
  );
}
