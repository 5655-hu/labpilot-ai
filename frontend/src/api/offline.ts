/* 离线回退层。
 *
 * 后端不可达（未部署 / 冷启动超时 / 网络被墙）时，用 backend/scripts/
 * capture_offline_snapshot.py 抓下来的黄金数据快照把整条链路点亮。
 * 快照内容是真实引擎的输出，不是编的假数字。
 *
 * 设计原则：
 * 1. 只做只读回退。DELETE / 上传 / 重跑一律不伪造结果。
 * 2. 快照只在真的失败时才加载（动态 import），正常连后端不下载这份体积。
 * 3. 一旦进入离线模式，UI 顶层显示明确标识，不让人误以为是实时计算。
 */

import { useEffect, useState } from 'react';

export type Dict = Record<string, unknown>;

interface Bundle {
  index: Dict;
  packs: Record<number, Dict>;
}

let bundlePromise: Promise<Bundle> | null = null;
let offlineFlag = false;
const listeners = new Set<(v: boolean) => void>();

export function markOffline(reason: string): void {
  if (!offlineFlag) {
    offlineFlag = true;
    console.info(`[LabPilot] 切到内置演示快照：${reason}`);
    listeners.forEach((fn) => fn(true));
  }
}

export function isOffline(): boolean {
  return offlineFlag;
}

export function subscribeOffline(fn: (v: boolean) => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function useOfflineMode(): boolean {
  const [value, setValue] = useState(isOffline());
  useEffect(() => subscribeOffline(setValue), []);
  return value;
}

async function loadBundle(): Promise<Bundle> {
  if (!bundlePromise) {
    bundlePromise = (async () => {
      const [index, d1, d2, d3] = await Promise.all([
        import('../data/golden/index.json'),
        import('../data/golden/d1.json'),
        import('../data/golden/d2.json'),
        import('../data/golden/d3.json'),
      ]);
      const unwrap = (m: unknown): Dict => {
        const rec = m as Dict;
        return (rec.default as Dict | undefined) ?? rec;
      };
      return {
        index: unwrap(index),
        packs: { 1: unwrap(d1), 2: unwrap(d2), 3: unwrap(d3) },
      };
    })();
  }
  return bundlePromise;
}

function dict(v: unknown): Dict | undefined {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Dict) : undefined;
}

function arrayOf(v: unknown): Dict[] {
  return Array.isArray(v) ? (v as Dict[]) : [];
}

/** 把 API 路径映射到快照里的节点；没有对应内容就返回 null。 */
export async function offlineSnapshot(path: string, reason: string): Promise<unknown | null> {
  let bundle: Bundle;
  try {
    bundle = await loadBundle();
  } catch (err) {
    console.warn('[LabPilot] 快照加载失败', err);
    return null;
  }

  const [rawPath, rawQuery = ''] = path.split('?');
  const seg = rawPath.split('/').filter(Boolean);
  const q = new URLSearchParams(rawQuery);

  if (seg[0] === 'health') {
    const health = dict(bundle.index.health) ?? {};
    return { ...health, offline: true, offline_reason: reason };
  }

  if (seg[0] !== 'api') return null;

  /* ---- /api/datasets ---- */
  if (seg[1] === 'datasets' && seg.length === 2) {
    return bundle.index.datasets ?? null;
  }

  /* ---- /api/analyses ---- */
  if (seg[1] === 'analyses') {
    if (seg.length === 2) {
      const full = arrayOf(dict(bundle.index.analyses)?.analyses);
      const slim = arrayOf(bundle.index.analyses_list);
      const source = slim.length > 0 ? slim : full;
      const total =
        typeof bundle.index.analyses_total === 'number'
          ? bundle.index.analyses_total
          : source.length;
      const limit = Number(q.get('limit') ?? 20) || 20;
      const offset = Number(q.get('offset') ?? 0) || 0;
      const page = source.slice(offset, offset + limit).map((item) => {
        const rich = full.find((f) => f.id === item.id);
        return rich ?? item;
      });
      return { analyses: page, total };
    }
    if (seg.length === 3) {
      const full = arrayOf(dict(bundle.index.analyses)?.analyses);
      const hit = full.find((a) => a.id === Number(seg[2]));
      if (hit) return hit;
      const slim = arrayOf(bundle.index.analyses_list);
      return slim.find((a) => a.id === Number(seg[2])) ?? null;
    }
    if (seg[3] === 'archive') {
      const aid = Number(seg[2]);
      for (const pack of Object.values(bundle.packs)) {
        const audit = dict(pack.audit);
        if (audit && audit.analysis_id === aid) return pack.archive ?? null;
      }
      return null;
    }
    return null;
  }

  /* ---- /api/datasets/{id}/... ---- */
  if (seg[1] !== 'datasets') return null;

  const id = Number(seg[2]);
  const pack = bundle.packs[id];
  if (!pack) return null;

  const leaf = seg[3];
  if (!leaf) return pack.dataset ?? null;
  if (leaf === 'preview') return pack.preview ?? null;
  if (leaf === 'audit') return pack.audit ?? null;
  if (leaf === 'stats') return pack.stats ?? null;
  if (leaf === 'report') return pack.report ?? null;
  if (leaf === 'compare') return pack.compare ?? null;
  if (leaf === 'archives') {
    const one = pack.archive;
    return { dataset_id: id, archives: one ? [one] : [], total: one ? 1 : 0 };
  }

  if (leaf === 'charts') {
    const charts = dict(pack.charts) ?? {};
    const kind = seg[4];
    if (kind === 'columns') return charts.columns ?? null;
    if (kind === 'boxplot') return charts.boxplot ?? null;
    if (kind === 'heatmap') return charts.heatmap ?? null;
    if (kind === 'histogram') {
      const column = q.get('column') ?? '';
      return charts[`histogram:${column}`] ?? null;
    }
    if (kind === 'scatter' || kind === 'line' || kind === 'regression') {
      const key = `${kind}:${q.get('x') ?? ''}|${q.get('y') ?? ''}`;
      return charts[key] ?? null;
    }
  }

  return null;
}

/** 离线模式下的能力边界说明，给 UI 用。 */
export const OFFLINE_NOTES = {
  banner: '演示模式 · 离线快照',
  detail:
    '当前展示的是真实计算引擎在 3 份黄金演示数据上的运行结果快照，审计 / 统计 / 图表 / 报告都能完整浏览。要上传自己的数据并实时计算，请用真后端版本：',
  backendUrl: 'http://8.163.38.73:8000',
  disabled: {
    upload: '离线演示模式下不能上传新文件。',
    rerun: '离线演示模式下不能重跑分析。',
    delete: '离线演示模式下不能删除数据集。',
  },
};
