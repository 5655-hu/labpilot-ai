/* LabPilot AI API client. Base URL comes from VITE_API_URL (see .env.example). */

const API_BASE =
  (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000';

export interface DatasetColumn {
  name: string;
  dtype: string;
}

export interface Dataset {
  id: number;
  name: string;
  filename: string;
  file_hash: string;
  rows_count: number;
  cols_count: number;
  columns: DatasetColumn[];
  source: 'upload' | 'golden';
  file_path: string;
  created_at: string;
}

export interface Analysis {
  id: number;
  dataset_id: number;
  name: string;
  status: string;
  params: Record<string, unknown>;
  result: Record<string, unknown> | null;
  engine_version: string;
  created_at: string;
  finished_at: string | null;
}

export interface Preview {
  id: number;
  name: string;
  filename: string;
  rows: number;
  cols: number;
  columns: DatasetColumn[];
  preview_rows: Record<string, string>[];
  preview_limit: number;
  file_hash: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? `请求失败 (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export function fetchHealth(): Promise<{ status: string; version: string; wave?: string; db: string; datasets: number }> {
  return request('/health');
}

export async function fetchDatasets(): Promise<Dataset[]> {
  const data = await request<{ datasets: Dataset[]; total: number }>('/api/datasets');
  return data.datasets;
}

export async function fetchAnalyses(
  limit = 20,
  offset = 0,
): Promise<{ analyses: Analysis[]; total: number }> {
  return request<{ analyses: Analysis[]; total: number }>(
    `/api/analyses?limit=${limit}&offset=${offset}`,
  );
}

export function fetchPreview(id: number, limit = 100): Promise<Preview> {
  return request(`/api/datasets/${id}/preview?limit=${limit}`);
}

export async function uploadDataset(file: File): Promise<Dataset> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${API_BASE}/api/datasets/upload`, { method: 'POST', body: form });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? `上传失败 (${res.status})`);
  }
  return res.json() as Promise<Dataset>;
}

export async function deleteDataset(id: number): Promise<void> {
  await request(`/api/datasets/${id}`, { method: 'DELETE' });
}

/* ---- Audit (Wave 2) ---- */

export interface DeductionEvidence {
  column: string;
  count: number;
  rate: number;
  allowed_missing?: boolean;
  example_rows: Record<string, unknown>[];
}

export interface Deduction {
  category: string;
  label: string;
  weight: number;
  rate: number;
  rate_basis: string;
  deduction: number;
  reason: string;
  suggestion: string;
  evidence: DeductionEvidence[];
}

export interface AuditResult {
  engine: string;
  engine_version: string;
  rows: number;
  cols: number;
  total_cells: number;
  score: {
    total: number;
    formula: string;
    profile: { name: string; label: string; description: string; weights: Record<string, number> };
    total_deduction: number;
    deductions: Deduction[];
    outliers_do_not_deduct: boolean;
  };
  missing: { total: number; effective_total: number; by_column: Record<string, { count: number; rate: number; row_indices: number[]; allowed_missing: boolean }> };
  duplicates: { count: number; row_indices: number[]; rate: number };
  type_errors: Record<string, { count: number; row_indices: number[]; examples: Record<string, unknown>[] }>;
  definite_errors: Record<string, { count: number; row_indices: number[]; examples: Record<string, unknown>[] }>;
  unit_risks: { column: string; units: string[]; examples: Record<string, unknown>[]; suggestion: string }[];
  pending_outliers: {
    column: string;
    count: number;
    algorithms: string[];
    points: { row_index: number; row_number: number; value: number; algorithms: string[] }[];
    disagreement: { algorithm: string; row_indices: number[]; note: string }[];
    status: string;
    suggestion: string;
  }[];
  columns: { name: string; dtype: string; missing: number; numeric_expected: boolean; outlier_count: number }[];
  params: {
    algorithms: string[];
    iqr_k: number;
    z_threshold: number;
    profile: string;
    weights: Record<string, number>;
    allowed_missing_columns: string[];
    range_rules: Record<string, unknown>;
    per_column_algorithms: Record<string, unknown>;
  };
}

export interface AuditRequest {
  algorithms: string[];
  iqr_k: number;
  z_threshold: number;
  profile: string;
}

export async function runAudit(id: number, body: AuditRequest): Promise<{ analysis_id: number; dataset_id: number; audit: AuditResult }> {
  return request(`/api/datasets/${id}/audit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export async function fetchLatestAudit(id: number): Promise<{ analysis_id: number; dataset_id: number; created_at: string; audit: AuditResult }> {
  return request(`/api/datasets/${id}/audit`);
}

/* ---- Stats (Wave 2) ---- */

export interface ColumnStats {
  count: number;
  missing: number;
  mean: number | null;
  median: number | null;
  std: number | null;
  variance: number | null;
  min: number | null;
  max: number | null;
  constant: boolean;
  note: string | null;
  non_numeric_excluded?: number;
}

export interface StatsResult {
  engine: string;
  engine_version: string;
  rows: number;
  cols: number;
  columns: Record<string, ColumnStats>;
  skipped_columns: { column: string; reason: string }[];
  correlation: {
    method: string;
    matrix: Record<string, Record<string, number | null>>;
    unavailable: { columns: string[]; reason: string }[];
    note: string | null;
  };
  notes: string[];
  method_notes: Record<string, string>;
}

export async function runStats(id: number): Promise<{ analysis_id: number; dataset_id: number; stats: StatsResult }> {
  return request(`/api/datasets/${id}/stats`, { method: 'POST' });
}

export async function fetchLatestStats(id: number): Promise<{ analysis_id: number; dataset_id: number; created_at: string; stats: StatsResult }> {
  return request(`/api/datasets/${id}/stats`);
}

/* ---- Charts (user Wave 2) ---- */

export interface ChartColumn {
  name: string;
  dtype: string;
  numeric: boolean;
  reason: string | null;
  valid_count: number;
  missing: number;
}

export interface HistogramChart {
  type: 'histogram';
  column: string;
  bins: number;
  method: string;
  bin_edges: number[];
  counts: number[];
  n: number;
  missing: number;
  min: number;
  max: number;
}

export interface BoxplotBox {
  column: string;
  q1: number;
  median: number;
  q3: number;
  lower: number;
  upper: number;
  iqr: number;
  k: number;
  n: number;
  missing: number;
  outliers: { row_index: number; row_number: number; value: number }[];
  outlier_count: number;
}

export interface BoxplotChart {
  type: 'boxplot';
  boxes: BoxplotBox[];
  skipped_columns: { column: string; reason: string }[];
}

export interface ChartPoint {
  row_index: number;
  row_number: number;
  x: number;
  y: number;
}

export interface ScatterChartBase {
  x_column: string;
  y_column: string;
  points: ChartPoint[];
  n: number;
  excluded: number;
}

export interface ScatterChart extends ScatterChartBase {
  type: 'scatter';
}

export interface LineChart extends ScatterChartBase {
  type: 'line';
  sorted_by: string;
}

export interface HeatmapChart {
  type: 'heatmap';
  method: string;
  columns: string[];
  matrix: (number | null)[][];
  unavailable: { columns: string[]; reason: string }[];
  note: string | null;
  skipped_columns: { column: string; reason: string }[];
}

export interface RegressionChart {
  type: 'regression';
  x_column: string;
  y_column: string;
  slope: number;
  intercept: number;
  r_squared: number;
  r: number;
  n: number;
  excluded: number;
  equation: string;
  fit_line: { x: number[]; y: number[] };
  points: ChartPoint[];
}

export function fetchChartColumns(id: number): Promise<{ dataset_id: number; columns: ChartColumn[] }> {
  return request(`/api/datasets/${id}/charts/columns`);
}

export function fetchHistogram(id: number, column: string, bins?: number): Promise<{ dataset_id: number; chart: HistogramChart }> {
  const q = bins ? `&bins=${bins}` : '';
  return request(`/api/datasets/${id}/charts/histogram?column=${encodeURIComponent(column)}${q}`);
}

export function fetchBoxplot(id: number, columns?: string[]): Promise<{ dataset_id: number; chart: BoxplotChart }> {
  const q = columns && columns.length > 0 ? `?columns=${encodeURIComponent(columns.join(','))}` : '';
  return request(`/api/datasets/${id}/charts/boxplot${q}`);
}

export function fetchScatter(id: number, x: string, y: string): Promise<{ dataset_id: number; chart: ScatterChart }> {
  return request(`/api/datasets/${id}/charts/scatter?x=${encodeURIComponent(x)}&y=${encodeURIComponent(y)}`);
}

export function fetchLine(id: number, x: string, y: string): Promise<{ dataset_id: number; chart: LineChart }> {
  return request(`/api/datasets/${id}/charts/line?x=${encodeURIComponent(x)}&y=${encodeURIComponent(y)}`);
}

export function fetchHeatmap(id: number): Promise<{ dataset_id: number; chart: HeatmapChart }> {
  return request(`/api/datasets/${id}/charts/heatmap`);
}

export function fetchRegression(id: number, x: string, y: string): Promise<{ dataset_id: number; chart: RegressionChart }> {
  return request(`/api/datasets/${id}/charts/regression?x=${encodeURIComponent(x)}&y=${encodeURIComponent(y)}`);
}

/* ---- Report (Wave 3) ---- */

export interface ConclusionEvidence {
  dataset_id: number;
  analysis_ids: number[];
  analysis: string;
  statistic: string;
  method: string;
  params: Record<string, unknown>;
  value: number | string | null;
}

export interface Conclusion {
  id: string;
  text: string;
  evidence: ConclusionEvidence;
}

export interface ReportAudit {
  score: {
    total: number;
    formula: string;
    total_deduction: number;
    deductions: Deduction[];
    outliers_do_not_deduct: boolean;
  };
  missing: { total: number; effective_total: number };
  duplicates: { count: number; rate: number };
  type_errors: Record<string, { count: number }>;
}

export interface ReportRegression {
  available: boolean;
  x_column?: string;
  y_column?: string;
  slope?: number;
  intercept?: number;
  r_squared?: number;
  r?: number;
  n?: number;
  excluded?: number;
  equation?: string;
}

export interface ReportResult {
  engine: string;
  engine_version: string;
  dataset: {
    id: number;
    name: string;
    filename: string;
    rows: number;
    cols: number;
    file_hash: string;
    columns: DatasetColumn[];
  };
  audit: ReportAudit;
  stats: StatsResult;
  correlation: StatsResult['correlation'];
  regression: ReportRegression;
  conclusions: Conclusion[];
  ai_text: string | null;
  source: 'ai' | 'rule-based';
  send_manifest: {
    model: string;
    sent_fields: string[];
    raw_rows_sent: number;
    elapsed_seconds: number;
    tokens: { promptTokenCount: number; candidatesTokenCount: number; totalTokenCount: number } | null;
  } | null;
  tokens: { promptTokenCount: number; candidatesTokenCount: number; totalTokenCount: number } | null;
  generated_at: string;
  number_check: { checked: number; unmatched: string[] } | null;
  audit_analysis_id: number | null;
  stats_analysis_id: number | null;
}

export interface ReportResponse {
  analysis_id: number;
  dataset_id: number;
  created_at?: string;
  report: ReportResult;
}

export function fetchLatestReport(id: number): Promise<ReportResponse> {
  return request(`/api/datasets/${id}/report`);
}

export function generateReport(id: number, includeAi: boolean): Promise<ReportResponse> {
  return request(`/api/datasets/${id}/report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ include_ai: includeAi }),
  });
}

/* ---- Group comparison (Wave 3) ---- */

export interface GroupDescriptive {
  n: number;
  mean: number;
  median: number;
  std: number;
  min: number;
  max: number;
}

export interface CompareResult {
  engine: string;
  engine_version: string;
  group_col: string;
  value_col: string;
  groups: string[];
  alpha: number;
  descriptive: Record<string, GroupDescriptive>;
  assumptions: {
    shapiro: Record<string, { statistic: number; p_value: number; normal: boolean; reliable: boolean; judgement: string }>;
    levene: { statistic: number; p_value: number; equal_variance: boolean; judgement: string };
    judgement: string;
    auto_suggestion: string;
    auto_suggestion_name: string;
  };
  selected_test: string;
  selected_test_name: string;
  selection_reason: string;
  overridden: boolean;
  test_result: { test: string; test_name: string; statistic: number; p_value: number; significant: boolean; alpha: number };
  effect_size: { method: string; name: string; value: number; interpretation: string; note: string } | null;
  conclusion: string;
  warnings: string[];
  missing_excluded: Record<string, number>;
  n_total: number;
}

export interface CompareResponse {
  analysis_id: number;
  dataset_id: number;
  created_at?: string;
  compare: CompareResult;
}

export function fetchLatestCompare(id: number): Promise<CompareResponse> {
  return request(`/api/datasets/${id}/compare`);
}

export function runCompare(
  id: number,
  body: { group_col: string; value_col: string; groups?: string[]; override_test?: string },
): Promise<CompareResponse> {
  return request(`/api/datasets/${id}/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/* ---- Rerun (Wave 3) ---- */

export interface RerunDifference {
  key: string;
  old: unknown;
  new: unknown;
}

export interface RerunResult {
  original_id: number;
  rerun_id: number;
  name: string;
  consistent: boolean;
  differences: RerunDifference[];
  original_engine_version: string;
  engine_version: string;
  engine_version_changed: boolean;
}

export function rerunAnalysis(id: number): Promise<RerunResult> {
  return request(`/api/analyses/${id}/rerun`, { method: 'POST' });
}

export function fetchAnalysis(id: number): Promise<Analysis> {
  return request(`/api/analyses/${id}`);
}

/* ---- Archive (Wave 4) ---- */

export interface Archive {
  archive_version: string;
  analysis_id: number;
  analysis_type: string;
  dataset_id: number;
  dataset: {
    id: number;
    name: string;
    filename: string;
    source: string;
    rows: number;
    cols: number;
    columns: DatasetColumn[];
    created_at: string;
  };
  data_fingerprint: { algorithm: string; file_hash: string; note: string };
  environment: {
    python_version: string;
    python_implementation: string;
    platform: string;
    dependencies: Record<string, string | null>;
  };
  code_version: string;
  engine: string;
  engine_version: string;
  cleaning_rules: {
    source: string;
    policy: string[];
    profile: string;
    profile_label?: string;
    weights: Record<string, number>;
    score_formula: string;
    algorithms: string[];
    iqr_k: number;
    z_threshold: number;
    allowed_missing_columns: string[];
    range_rules: Record<string, unknown>;
    per_column_algorithms: Record<string, string[]>;
    sentinel_missing_values: number[];
  };
  params: Record<string, unknown>;
  random_seed: { seed: number | null; note: string };
  result_snapshot: Record<string, unknown> | null;
  analysis_created_at: string;
  analysis_finished_at: string | null;
  archived_at: string;
  rerun: { supported: boolean; endpoint: string; note: string };
}

export function fetchArchive(analysisId: number): Promise<Archive> {
  return request(`/api/analyses/${analysisId}/archive`);
}

export async function fetchDatasetArchives(
  datasetId: number,
): Promise<{ dataset_id: number; archives: Archive[]; total: number }> {
  return request(`/api/datasets/${datasetId}/archives`);
}

/** Direct download URL for the one-click rerun package (JSON attachment). */
export function archiveExportUrl(analysisId: number): string {
  return `${API_BASE}/api/analyses/${analysisId}/archive/export`;
}
