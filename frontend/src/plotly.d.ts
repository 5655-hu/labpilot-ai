/* Minimal typing for plotly.js-dist (the package ships no TS types).
   The Plot component only uses newPlot/react/purge with plain data. */
declare module 'plotly.js-dist' {
  const Plotly: {
    newPlot(
      el: HTMLElement,
      data: unknown[],
      layout?: Record<string, unknown>,
      config?: Record<string, unknown>,
    ): Promise<void>;
    react(
      el: HTMLElement,
      data: unknown[],
      layout?: Record<string, unknown>,
      config?: Record<string, unknown>,
    ): Promise<void>;
    purge(el: HTMLElement): void;
  };
  export default Plotly;
}
