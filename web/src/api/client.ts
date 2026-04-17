// API Client
import axios from 'axios';
import type { ChanlunData, AIAnalysisResult } from '@/types/chanlun';

const api = axios.create({
  baseURL: '/api',
  timeout: 300000,  // 5min timeout
  headers: {
    'Content-Type': 'application/json'
  }
});

// Add retry interceptor for connection errors
api.interceptors.response.use(
  response => response,
  async error => {
    // Retry on network errors or 5xx errors
    if (!error.response && error.config) {
      // Network error - server might not be ready
      console.log('API connection error, retrying...');
      const retries = error.config._retry || 0;
      if (retries < 3) {
        error.config._retry = retries + 1;
        await new Promise(resolve => setTimeout(resolve, 1000 * (retries + 1)));
        return api.request(error.config);
      }
    }
    return Promise.reject(error);
  }
);

// Get K-line and Chanlun data
export async function getKlineData(
  symbol: string,
  interval: string,
  limit: number = 2500
): Promise<ChanlunData> {
  const response = await api.get<ChanlunData>(`/kline/${symbol}/${interval}`, {
    params: { limit }
  });
  return response.data;
}

// AI Analysis - with test mode support
export async function analyzeAI(
  symbol: string,
  interval: string,
  mode: 'structured' | 'table' = 'structured',
  test: boolean = false,  // New test parameter
  aiProvider?: string,   // New: AI provider
  aiModel?: string,      // New: AI model
  apiKey?: string,       // New: API key
  drillContext?: any,    // 区间套钻取上下文
  enableMultiLevel: boolean = true  // 新增：是否启用多级别分析
): Promise<AIAnalysisResult> {
  const response = await api.post<AIAnalysisResult>('/analyze', {
    symbol,
    interval,
    mode,
    test,
    limit: 2500,
    ai_provider: aiProvider,
    ai_model: aiModel,
    api_key: apiKey,
    drill_context: drillContext,
    enable_multi_level: enableMultiLevel,  // 新增：多级别分析参数
  });
  return response.data;
}

// AI Analysis Test Mode (mock data without actual AI call)
export async function analyzeAITest(
  symbol: string,
  interval: string,
  test: boolean = true
): Promise<AIAnalysisResult> {
  const response = await api.post<AIAnalysisResult>('/analyze', {
    symbol,
    interval,
    mode: 'structured',
    test,
    limit: 2500
  });
  return response.data;
}

// Export API instance for other uses
export default api;

// ─── A 股 API 函数 ─────────────────────────────────────────────

// Get A-stock K-line and Chanlun data
export async function getAstockKlineData(
  symbol: string,
  interval: string,
  limit: number = 500
): Promise<ChanlunData> {
  const response = await api.get<ChanlunData>(`/astock/kline/${symbol}/${interval}`, {
    params: { limit }
  });
  return response.data;
}

// A-stock AI Analysis
export async function analyzeAstockAI(
  symbol: string,
  interval: string,
  mode: 'structured' | 'table' = 'structured',
  test: boolean = false,
  aiProvider?: string,
  aiModel?: string,
  apiKey?: string,
  drillContext?: any,
  enableMultiLevel: boolean = true  // 新增：是否启用多级别分析
): Promise<AIAnalysisResult> {
  const response = await api.post<AIAnalysisResult>('/astock/analyze', {
    symbol,
    interval,
    mode,
    test,
    limit: 2500,
    ai_provider: aiProvider,
    ai_model: aiModel,
    api_key: apiKey,
    drill_context: drillContext,
    enable_multi_level: enableMultiLevel,  // 新增：多级别分析参数
  });
  return response.data;
}

// 市场类型
export type MarketType = 'crypto' | 'astock' | 'gold';

// ─── 区间套钻取：时间范围查询 ─────────────────────────────────────

// Crypto kline by time range (drill-down)
export async function getKlineDataRange(
  symbol: string,
  interval: string,
  startTime: number,
  endTime: number
): Promise<ChanlunData> {
  const response = await api.get<ChanlunData>(`/kline/${symbol}/${interval}/range`, {
    params: { start_time: startTime, end_time: endTime }
  });
  return response.data;
}

// A-stock kline by time range (drill-down)
export async function getAstockKlineDataRange(
  symbol: string,
  interval: string,
  startTime: number,
  endTime: number
): Promise<ChanlunData> {
  const response = await api.get<ChanlunData>(`/astock/kline/${symbol}/${interval}/range`, {
    params: { start_time: startTime, end_time: endTime }
  });
  return response.data;
}

// Gold kline by time range (drill-down)
export async function getGoldKlineDataRange(
  interval: string,
  startTime: number,
  endTime: number
): Promise<ChanlunData> {
  const response = await api.get<ChanlunData>(`/gold/kline/${interval}/range`, {
    params: { start_time: startTime, end_time: endTime }
  });
  return response.data;
}

// A 股预设标的
export const ASTOCK_PRESETS: Array<{ code: string; name: string }> = [
  { code: '000001', name: '上证指数' },
  { code: '600519', name: '贵州茅台' },
  { code: '601318', name: '中国平安' },
  { code: '600036', name: '招商银行' },
  { code: '300750', name: '宁德时代' },
  { code: '000858', name: '五粮液' },
  { code: '601012', name: '隆基绿能' },
];

// A 股周期选项
export const ASTOCK_INTERVALS: Array<{ value: string; label: string }> = [
  { value: '15m', label: '15分' },
  { value: '60m', label: '60分' },
  { value: '1d', label: '日线' },
  { value: '1w', label: '周线' },
  { value: '1M', label: '月线' },
];

// 黄金预设标的
export const GOLD_PRESETS: Array<{ code: string; name: string }> = [
  { code: 'XAUUSD', name: '黄金现货' },
];

// 黄金周期选项（与加密货币相同）
export const GOLD_INTERVALS: Array<{ value: string; label: string }> = [
  { value: '15m', label: '15分' },
  { value: '1h', label: '1小时' },
  { value: '4h', label: '4小时' },
  { value: '1d', label: '日线' },
  { value: '1w', label: '周线' },
  { value: '1M', label: '月线' },
];

// 黄金 AI 分析
export async function analyzeGoldAI(
  symbol: string,
  interval: string,
  mode: 'structured' | 'table' = 'structured',
  test: boolean = false,
  aiProvider?: string,
  aiModel?: string,
  apiKey?: string,
  drillContext?: any,
  enableMultiLevel: boolean = true  // 新增：是否启用多级别分析
): Promise<AIAnalysisResult> {
  const response = await api.post<AIAnalysisResult>('/gold/analyze', {
    symbol,
    interval,
    mode,
    test,
    limit: 2500,
    ai_provider: aiProvider,
    ai_model: aiModel,
    api_key: apiKey,
    drill_context: drillContext,
    enable_multi_level: enableMultiLevel,  // 新增：多级别分析参数
  });
  return response.data;
}
