<template>
  <div class="tradingview-widget-container">
    <div class="widget-header">
      <h3>{{ symbol }} - {{ interval }}</h3>
      <div class="widget-controls">
        <button @click="refreshChart" class="refresh-btn">🔄 刷新</button>
      </div>
    </div>
    <div ref="chartContainer" class="chart-container"></div>
    <div v-if="loading" class="loading-overlay">
      <div class="loading-spinner"></div>
      <p>加载中...</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'
import type { MarketType } from '@/api/client'

interface Props {
  symbol: string
  interval: string
  market?: MarketType
}

const props = withDefaults(defineProps<Props>(), {
  market: 'crypto'
})
const chartContainer = ref<HTMLDivElement>()
const loading = ref(true)
let chart: echarts.ECharts | null = null

const fetchKlines = async () => {
  loading.value = true
  try {
    // 使用相对路径，开发环境由 Vite 代理，生产环境由 nginx 反向代理
    let endpoint
    if (props.market === 'astock') {
      endpoint = `/api/astock/kline/${props.symbol}/${props.interval}?limit=500`
    } else if (props.market === 'gold') {
      endpoint = `/api/gold/kline/${props.interval}?limit=500`
    } else {
      endpoint = `/api/kline/${props.symbol}/${props.interval}?limit=500`
    }
    const response = await fetch(endpoint)
    const data = await response.json()
    return data
  } catch (error) {
    console.error('Failed to fetch klines:', error)
    return { klines: [], bi: [], xd: [], zs: [], fx: [] }
  } finally {
    loading.value = false
  }
}

// 计算MACD
const calculateMACD = (closes: number[], fastPeriod = 12, slowPeriod = 26, signalPeriod = 9) => {
  const emaFast = calculateEMA(closes, fastPeriod)
  const emaSlow = calculateEMA(closes, slowPeriod)
  const dif = emaFast.map((v, i) => v - emaSlow[i])
  const dea = calculateEMA(dif, signalPeriod)
  const macd = dif.map((v, i) => (v - dea[i]) * 2)
  return { dif, dea, macd }
}

// 计算EMA
const calculateEMA = (data: number[], period: number) => {
  const k = 2 / (period + 1)
  const ema: number[] = []
  let sum = 0
  
  // 第一个值用SMA
  for (let i = 0; i < period && i < data.length; i++) {
    sum += data[i]
  }
  ema[period - 1] = sum / period
  
  // 后续用EMA公式
  for (let i = period; i < data.length; i++) {
    ema[i] = data[i] * k + ema[i - 1] * (1 - k)
  }
  
  // 填充前面的值
  for (let i = 0; i < period - 1; i++) {
    ema[i] = ema[period - 1]
  }
  
  return ema
}

const initChart = async () => {
  if (!chartContainer.value) return

  const data = await fetchKlines()
  const klines = data.klines || []
  
  if (!klines || klines.length === 0) {
    loading.value = false
    return
  }

  if (chart) {
    chart.dispose()
  }

  chart = echarts.init(chartContainer.value)

  const dates = klines.map((k: any) => k.date)
  const ohlc = klines.map((k: any) => [
    parseFloat(k.o),
    parseFloat(k.c),
    parseFloat(k.l),
    parseFloat(k.h)
  ])
  const volumes = klines.map((k: any) => parseFloat(k.a || 0))
  const closes = klines.map((k: any) => parseFloat(k.c))
  
  // 计算MACD
  const { dif, dea, macd } = calculateMACD(closes)
  
  // MACD柱状图颜色
  const macdColors = macd.map((v) => v >= 0 ? '#ef5350' : '#26a69a')
  
  // 计算价格范围，用于缩放成交量
  const allPrices = ohlc.flat()
  const priceMin = Math.min(...allPrices)
  const priceMax = Math.max(...allPrices)
  const priceRange = priceMax - priceMin
  
  // 成交量缩放到价格范围的20%
  const maxVolume = Math.max(...volumes)
  const volumeScale = (priceRange * 0.2) / maxVolume
  const scaledVolumes = volumes.map(v => v * volumeScale)
  // 成交量基准线（显示在价格最低点下方）
  const volumeBase = priceMin

  // ========== 缠论图形数据 ==========
  
  const findDateIndex = (targetDate: string): number => {
    if (!targetDate) return -1
    const normalizedTarget = targetDate.replace(' ', 'T')
    for (let i = 0; i < dates.length; i++) {
      const date = dates[i]
      if (date === normalizedTarget || date === targetDate) return i
      if (date.substring(0, 19) === normalizedTarget.substring(0, 19)) return i
    }
    return -1
  }
  
  // 笔
  const biMarkLines: any[] = []
  if (data.bi && Array.isArray(data.bi) && data.bi.length > 0) {
    const sortedBi = [...data.bi].sort((a, b) => a.index - b.index)
    for (let i = 0; i < sortedBi.length; i++) {
      const bi = sortedBi[i]
      const startIndex = findDateIndex(bi.start_date)
      const endIndex = findDateIndex(bi.end_date)
      if (startIndex >= 0 && endIndex >= 0) {
        biMarkLines.push([
          {
            name: `笔${bi.index}`,
            xAxis: startIndex,
            yAxis: bi.start_price,
            symbol: 'circle',
            symbolSize: 6,
            itemStyle: { color: bi.type === 'up' ? '#2196F3' : '#FF5722' }
          },
          {
            name: `笔${bi.index}`,
            xAxis: endIndex,
            yAxis: bi.end_price,
            symbol: 'circle',
            symbolSize: 6,
            itemStyle: { color: bi.type === 'up' ? '#2196F3' : '#FF5722' }
          }
        ])
      }
    }
  }

  // 线段
  const xdMarkLines: any[] = []
  if (data.xd && Array.isArray(data.xd) && data.xd.length > 0) {
    const sortedXd = [...data.xd].sort((a, b) => a.index - b.index)
    for (let i = 0; i < sortedXd.length; i++) {
      const xd = sortedXd[i]
      const startIndex = findDateIndex(xd.start_date)
      const endIndex = findDateIndex(xd.end_date)
      if (startIndex >= 0 && endIndex >= 0) {
        xdMarkLines.push([
          {
            name: `线段${xd.index}`,
            xAxis: startIndex,
            yAxis: xd.start_price,
            symbol: 'diamond',
            symbolSize: 8,
            itemStyle: { color: xd.type === 'up' ? '#1565C0' : '#D32F2F' }
          },
          {
            name: `线段${xd.index}`,
            xAxis: endIndex,
            yAxis: xd.end_price,
            symbol: 'diamond',
            symbolSize: 8,
            itemStyle: { color: xd.type === 'up' ? '#1565C0' : '#D32F2F' }
          }
        ])
      }
    }
  }

  // 中枢
  const zsRectangles: any[] = []
  if (data.zs && Array.isArray(data.zs)) {
    data.zs.forEach((zs: any) => {
      const startIndex = findDateIndex(zs.start_date)
      const endIndex = findDateIndex(zs.end_date)
      const rangeHigh = zs.zg || zs.gg
      const rangeLow = zs.zd || zs.dd
      if (startIndex >= 0 && endIndex >= 0 && rangeHigh && rangeLow) {
        zsRectangles.push([
          { coord: [startIndex, rangeLow] },
          { coord: [endIndex, rangeHigh] }
        ])
      }
    })
  }

  const option = {
    title: {
      text: `${props.symbol} ${props.interval}`,
      left: 'center'
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' }
    },
    legend: {
      data: ['K线', '成交量', 'MACD', '笔', '线段'],
      bottom: 10
    },
    // 三个grid: K线区域、MACD区域、(无成交量单独区域)
    grid: [
      {
        left: '10%',
        right: '8%',
        top: '10%',
        height: '55%'
      },
      {
        left: '10%',
        right: '8%',
        top: '70%',
        height: '20%'
      }
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        boundaryGap: true,
        axisLine: { onZero: false },
        splitLine: { show: false },
        min: 'dataMin',
        max: 'dataMax'
      },
      {
        type: 'category',
        gridIndex: 1,
        data: dates,
        boundaryGap: true,
        axisLine: { onZero: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
        min: 'dataMin',
        max: 'dataMax'
      }
    ],
    yAxis: [
      {
        scale: true,
        splitArea: { show: true },
        position: 'left'
      },
      {
        scale: true,
        gridIndex: 1,
        splitNumber: 3,
        axisLabel: { show: true },
        axisLine: { show: true },
        axisTick: { show: true },
        splitLine: { show: true, lineStyle: { type: 'dashed', color: '#eee' } }
      }
    ],
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: [0, 1],
        start: 80,
        end: 100
      },
      {
        show: true,
        xAxisIndex: [0, 1],
        type: 'slider',
        bottom: '5%',
        start: 80,
        end: 100
      }
    ],
    series: [
      // K线
      {
        name: 'K线',
        type: 'candlestick',
        data: ohlc,
        xAxisIndex: 0,
        yAxisIndex: 0,
        itemStyle: {
          color: '#ef5350',
          color0: '#26a69a',
          borderColor: '#ef5350',
          borderColor0: '#26a69a'
        },
        markArea: {
          silent: true,
          itemStyle: {
            color: 'rgba(255, 193, 7, 0.15)',
            borderColor: '#FFC107',
            borderWidth: 2
          },
          label: {
            show: true,
            position: 'insideTop',
            fontSize: 10,
            color: '#F57C00'
          },
          data: zsRectangles
        },
        markLine: {
          symbol: ['circle', 'circle'],
          symbolSize: 6,
          lineStyle: { type: 'solid', width: 2 },
          data: biMarkLines
        }
      },
      // 线段
      {
        name: '线段',
        type: 'candlestick',
        data: ohlc.map(() => ['-']),
        xAxisIndex: 0,
        yAxisIndex: 0,
        itemStyle: {
          color: 'transparent',
          color0: 'transparent',
          borderColor: 'transparent',
          borderColor0: 'transparent'
        },
        markLine: {
          symbol: ['diamond', 'diamond'],
          symbolSize: 8,
          lineStyle: { type: 'solid', width: 3 },
          data: xdMarkLines
        }
      },
      // K线区域叠加半透明成交量柱形图（占价格区域20%，显示在底部）
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 0,
        yAxisIndex: 0,  // 使用价格Y轴
        data: scaledVolumes.map((v, i) => ({
          value: [i, volumeBase + v, volumeBase],  // [x, y顶, y底]
          itemStyle: {
            color: ohlc[i][1] >= ohlc[i][0] 
              ? 'rgba(239, 83, 80, 0.3)'
              : 'rgba(38, 166, 154, 0.3)',
            borderColor: ohlc[i][1] >= ohlc[i][0] ? 'rgba(239, 83, 80, 0.5)' : 'rgba(38, 166, 154, 0.5)',
            borderWidth: 1
          }
        })),
        barWidth: '50%',
        z: 1,
        silent: true
      },
      // MACD DIF线
      {
        name: 'DIF',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: dif,
        lineStyle: { color: '#FF9800', width: 1 },
        symbol: 'none',
        z: 2
      },
      // MACD DEA线
      {
        name: 'DEA',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: dea,
        lineStyle: { color: '#2196F3', width: 1 },
        symbol: 'none',
        z: 2
      },
      // MACD柱状图
      {
        name: 'MACD',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: macd.map((v) => ({
          value: v,
          itemStyle: { color: v >= 0 ? '#ef5350' : '#26a69a' }
        })),
        barWidth: '40%',
        z: 1
      }
    ]
  }

  chart.setOption(option)
  loading.value = false
}

const refreshChart = () => {
  initChart()
}

onMounted(() => {
  initChart()
  window.addEventListener('resize', () => {
    chart?.resize()
  })
})

onUnmounted(() => {
  if (chart) {
    chart.dispose()
    chart = null
  }
  window.removeEventListener('resize', () => {})
})

watch([() => props.symbol, () => props.interval, () => props.market], () => {
  initChart()
})
</script>

<style scoped lang="scss">
.tradingview-widget-container {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 8px;
  overflow: hidden;
}

.widget-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: #f5f5f5;
  border-bottom: 1px solid #e0e0e0;

  h3 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
    color: #333;
  }

  .widget-controls {
    display: flex;
    gap: 8px;

    .refresh-btn {
      padding: 4px 12px;
      background: #4A90D9;
      color: white;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 14px;
      transition: background 0.3s;

      &:hover {
        background: #357ABD;
      }
    }
  }
}

.chart-container {
  flex: 1;
  min-height: 500px;
}

.loading-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(255, 255, 255, 0.9);
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  z-index: 1000;

  .loading-spinner {
    width: 40px;
    height: 40px;
    border: 3px solid #f3f3f3;
    border-top: 3px solid #4A90D9;
    border-radius: 50%;
    animation: spin 1s linear infinite;
  }

  p {
    margin-top: 12px;
    color: #666;
  }
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}
</style>