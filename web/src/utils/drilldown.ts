import type { DrillMarketType } from '@/types/chanlun';
import { INTERVAL_HIERARCHY } from '@/types/chanlun';

/**
 * 根据当前周期和市场类型，返回下一级更小的周期
 * 返回 null 表示已到达最小周期
 */
export function getNextInterval(currentInterval: string, market: DrillMarketType): string | null {
  const hierarchy = INTERVAL_HIERARCHY[market];
  if (!hierarchy) return null;
  const idx = hierarchy.indexOf(currentInterval);
  if (idx === -1 || idx >= hierarchy.length - 1) return null;
  return hierarchy[idx + 1];
}

/**
 * 将日期字符串解析为毫秒时间戳
 * 支持格式：2024-01-15 08:00:00+00:00, 2024-01-15T08:00:00, 2024-01-15 08:00:00
 */
export function parseDateString(dateStr: string): number {
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) {
    throw new Error(`Invalid date string: ${dateStr}`);
  }
  return date.getTime();
}

/**
 * 获取周期的中文标签
 */
export function getIntervalLabel(interval: string): string {
  const map: Record<string, string> = {
    '1m': '1分', '5m': '5分', '15m': '15分', '30m': '30分',
    '60m': '60分', '1h': '1小时', '4h': '4小时',
    '1d': '日线', '1w': '周线', '1M': '月线',
  };
  return map[interval] || interval;
}

/**
 * 获取段类型的中文标签
 */
export function getSegmentLabel(type: 'bi' | 'xd', index: number): string {
  const prefix = type === 'bi' ? '笔' : '线段';
  return `${prefix}${index}`;
}

/**
 * 生成唯一 ID
 */
export function generateDrillId(): string {
  return `drill_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

/** 最大钻取深度 */
export const MAX_DRILL_DEPTH = 4;
