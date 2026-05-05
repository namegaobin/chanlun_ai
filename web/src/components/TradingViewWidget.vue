<template>
  <div class="tradingview-widget-container">
    <div class="widget-header">
      <h3>{{ symbol }} - {{ interval }}</h3>
      <div class="widget-controls">
        <span v-if="drillEnabled" class="drill-hint">点击笔/线段可钻取下一级</span>
        <button @click="refreshChart" class="refresh-btn">🔄 刷新</button>
      </div>
    </div>
    <div ref="chartContainer" class="chart-container" :class="{ 'drill-cursor': drillEnabled }"></div>
    <div v-if="loading" class="loading-overlay">
      <div class="loading-spinner"></div>
      <p>加载中...</p>
    </div>
    <!-- 缠论图层控制 -->
    <div class="chanlun-controls">
      <button 
        @click="toggleLayer('bi')" 
        class="layer-btn" 
        :class="{ active: showBi }"
        title="显示/隐藏笔">
        📈 笔
      </button>
      <button 
        @click="toggleLayer('xd')" 
        class="layer-btn" 
        :class="{ active: showXd }"
        title="显示/隐藏线段">
        📊 线段
      </button>
      <button 
        @click="toggleLayer('zs')" 
        class="layer-btn" 
        :class="{ active: showZs }"
        title="显示/隐藏中枢">
        🎯 中枢
      </button>
      <button 
        @click="toggleLayer('fx')" 
        class="layer-btn" 
        :class="{ active: showFx }"
        title="显示/隐藏买卖点">
        💰 买卖点
      </button>
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
  drillEnabled?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  market: 'crypto',
  drillEnabled: false
})

const emit = defineEmits<{
  (e: 'drill-down', payload: {
    segmentType: 'bi' | 'xd'
    segmentIndex: number
    startDate: string
    endDate: string
    startPrice: number
    endPrice: number
  }): void
}>()
const chartContainer = ref<HTMLDivElement>()
const loading = ref(true)

// 存储原始 bi/xd 数据用于钻取点击检测
const biDataStore = ref<any[]>([])
const xdDataStore = ref<any[]>([])

let chart: echarts.ECharts | null = null

// 缠论图层显示控制
const showBi = ref(true)
const showXd = ref(true)
const showZs = ref(true)
const showFx = ref(true)

// 切换图层显示
const toggleLayer = (layer: 'bi' | 'xd' | 'zs' | 'fx') => {
  switch (layer) {
    case 'bi': showBi.value = !showBi.value; break
    case 'xd': showXd.value = !showXd.value; break
    case 'zs': showZs.value = !showZs.value; break
    case 'fx': showFx.value = !showFx.value; break
  }
  // 重新渲染图表
  initChart()
}

const fetchKlines = async () => {
  loading.value = true
  try {
    // 使用 Vite 代理，相对路径会自动转发到 127.0.0.1:8003
    let endpoint
    if (props.market === 'astock') {
      endpoint = `/api/astock/kline/${props.symbol}/${props.interval}?limit=2500`
    } else if (props.market === 'gold') {
      endpoint = `/api/gold/kline/${props.interval}?limit=2500`
    } else {
      endpoint = `/api/kline/${props.symbol}/${props.interval}?limit=2500`
    }
    const response = await fetch(endpoint)
    const data = await response.json()
    // 存储原始数据用于钻取
    biDataStore.value = data.bi || []
    xdDataStore.value = data.xd || []
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
    chart.getZr().off('click')
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
  if (showBi.value && data.bi && Array.isArray(data.bi) && data.bi.length > 0) {
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
  if (showXd.value && data.xd && Array.isArray(data.xd) && data.xd.length > 0) {
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
  if (showZs.value && data.zs && Array.isArray(data.zs)) {
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

  // 买卖点（分型）
  const fxMarkPoints: any[] = []
  if (showFx.value && data.fx && Array.isArray(data.fx)) {
    data.fx.forEach((fx: any) => {
      const idx = findDateIndex(fx.date)
      if (idx >= 0) {
        fxMarkPoints.push({
          name: fx.type === 'di' ? '买点' : '卖点',
          coord: [idx, fx.price],
          symbol: fx.type === 'di' ? 'triangle' : 'triangle',
          symbolSize: 12,
          symbolRotate: fx.type === 'di' ? 0 : 180,
          itemStyle: {
            color: fx.type === 'di' ? '#4CAF50' : '#F44336'
          },
          label: {
            show: true,
            position: fx.type === 'di' ? 'bottom' : 'top',
            formatter: fx.type === 'di' ? '买' : '卖',
            color: fx.type === 'di' ? '#4CAF50' : '#F44336',
            fontSize: 10,
            fontWeight: 'bold'
          }
        })
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
      data: ['K线', 'MACD'],
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
          silent: false,
          symbol: ['circle', 'circle'],
          symbolSize: 8,
          lineStyle: { type: 'solid', width: 2 },
          label: { show: false },
          animation: false,
          data: biMarkLines
        },
        markPoint: {
          data: fxMarkPoints,
          symbolSize: 12,
          label: {
            show: true,
            fontSize: 10,
            fontWeight: 'bold'
          }
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
          silent: false,
          symbol: ['diamond', 'diamond'],
          symbolSize: 10,
          lineStyle: { type: 'solid', width: 3 },
          label: { show: false },
          animation: false,
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

  // 区间套钻取：通过坐标匹配检测笔/线段点击
  if (props.drillEnabled && chart) {
    // 使用 getZr 监听画布任意位置点击（而非仅 series 数据点）
    chart.getZr().off('click')
    chart.getZr().on('click', (params: any) => {
      const pixelX = params.offsetX
      const pixelY = params.offsetY

      // 将像素坐标转为 grid 0（K线区域）的数据坐标
      let pointInGrid: number[] | undefined
      try {
        pointInGrid = chart!.convertFromPixel({ gridIndex: 0 }, [pixelX, pixelY])
      } catch {
        return
      }
      if (!pointInGrid) return

      const clickDataIndex = Math.round(pointInGrid[0])
      const clickPrice = pointInGrid[1]

      if (clickDataIndex < 0 || isNaN(clickPrice)) return

      // 在 bi 中查找包含此点击位置的线段
      const biHit = findSegmentAtPosition(biDataStore.value, dates, clickDataIndex, clickPrice)
      // 在 xd 中查找
      const xdHit = findSegmentAtPosition(xdDataStore.value, dates, clickDataIndex, clickPrice)

      // xd 优先（层级更高），否则 bi
      if (xdHit) {
        emit('drill-down', {
          segmentType: 'xd' as const,
          segmentIndex: xdHit.index,
          startDate: xdHit.start_date,
          endDate: xdHit.end_date,
          startPrice: xdHit.start_price,
          endPrice: xdHit.end_price,
        })
      } else if (biHit) {
        emit('drill-down', {
          segmentType: 'bi' as const,
          segmentIndex: biHit.index,
          startDate: biHit.start_date,
          endDate: biHit.end_date,
          startPrice: biHit.start_price,
          endPrice: biHit.end_price,
        })
      }
    })
  }
}

// 根据点击的数据索引和价格，查找对应的笔或线段
function findSegmentAtPosition(
  segments: any[],
  dates: string[],
  clickDataIndex: number,
  clickPrice: number
): any | null {
  if (!segments || segments.length === 0) return null

  for (const seg of segments) {
    const startIdx = findDateIndexInDates(dates, seg.start_date)
    const endIdx = findDateIndexInDates(dates, seg.end_date)
    if (startIdx < 0 || endIdx < 0) continue

    const minIdx = Math.min(startIdx, endIdx)
    const maxIdx = Math.max(startIdx, endIdx)
    const minPrice = Math.min(seg.start_price, seg.end_price)
    const maxPrice = Math.max(seg.start_price, seg.end_price)

    // 判断点击位置是否在笔/线段范围内（允许一定容差）
    const indexTolerance = 3 // 允许3个K线宽度的容差
    const priceRange = maxPrice - minPrice
    const priceTolerance = Math.max(priceRange * 0.3, maxPrice * 0.005) // 30%价格范围或0.5%的容差

    if (
      clickDataIndex >= minIdx - indexTolerance &&
      clickDataIndex <= maxIdx + indexTolerance &&
      clickPrice >= minPrice - priceTolerance &&
      clickPrice <= maxPrice + priceTolerance
    ) {
      return seg
    }
  }
  return null
}

function findDateIndexInDates(dates: string[], targetDate: string): number {
  if (!targetDate) return -1
  const normalizedTarget = targetDate.replace(' ', 'T')
  for (let i = 0; i < dates.length; i++) {
    const date = dates[i]
    if (date === normalizedTarget || date === targetDate) return i
    if (date.substring(0, 19) === normalizedTarget.substring(0, 19)) return i
  }
  return -1
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
    align-items: center;

    .drill-hint {
      font-size: 12px;
      color: #2962FF;
      background: rgba(41, 98, 255, 0.08);
      padding: 4px 10px;
      border-radius: 4px;
      font-weight: 500;
    }

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

.drill-cursor {
  :deep(canvas) {
    cursor: pointer !important;
  }
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

.chanlun-controls {
  display: flex;
  justify-content: center;
  gap: 8px;
  padding: 8px 16px;
  background: #f8f9fa;
  border-top: 1px solid #e0e0e0;
  flex-wrap: wrap;

  .layer-btn {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
    background: #fff;
    color: #666;
    border: 1px solid #ddd;
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.2s;

    &:hover {
      background: #f0f0f0;
      border-color: #ccc;
    }

    &.active {
      background: #4A90D9;
      color: white;
      border-color: #4A90D9;
    }
  }
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}
</style>