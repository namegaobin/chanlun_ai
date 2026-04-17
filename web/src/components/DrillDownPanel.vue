<template>
  <Teleport to="body">
    <Transition name="drill-fade">
      <div v-if="visible" class="drill-overlay" @click.self="$emit('close')">
        <div class="drill-panel">
          <!-- Header: Breadcrumb + Close -->
          <header class="drill-header">
            <nav class="drill-breadcrumb">
              <template v-for="(crumb, idx) in breadcrumbs" :key="idx">
                <button
                  class="breadcrumb-item"
                  :class="{ active: idx === breadcrumbs.length - 1, clickable: idx < breadcrumbs.length - 1 }"
                  @click="idx < breadcrumbs.length - 1 && $emit('jump-to', idx)"
                >
                  <span class="breadcrumb-interval">{{ crumb.interval }}</span>
                  <span class="breadcrumb-segment">{{ crumb.label }}</span>
                </button>
                <span v-if="idx < breadcrumbs.length - 1" class="breadcrumb-sep">›</span>
              </template>
            </nav>
            <div class="drill-header-right">
              <span class="drill-depth">{{ depth }}/{{ maxDepth }}</span>
              <button class="drill-close" @click="$emit('close')">
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                  <path d="M15 5L5 15M5 5l10 10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                </svg>
              </button>
            </div>
          </header>

          <!-- Chart Area -->
          <div class="drill-body">
            <div v-if="loading" class="drill-loading">
              <div class="drill-spinner"></div>
              <p>正在加载 {{ currentInterval }} 缠论数据...</p>
            </div>
            <div v-else-if="error" class="drill-error">
              <p>{{ error }}</p>
              <button class="drill-retry" @click="fetchData">重试</button>
            </div>
            <div v-else ref="chartRef" class="drill-chart"></div>
          </div>

          <!-- Footer: Layer toggles -->
          <footer class="drill-footer">
            <button class="drill-layer-btn" :class="{ active: showBi }" @click="showBi = !showBi; renderChart()">
              笔
            </button>
            <button class="drill-layer-btn" :class="{ active: showXd }" @click="showXd = !showXd; renderChart()">
              线段
            </button>
            <button class="drill-layer-btn" :class="{ active: showZs }" @click="showZs = !showZs; renderChart()">
              中枢
            </button>
            <button class="drill-layer-btn" :class="{ active: showFx }" @click="showFx = !showFx; renderChart()">
              买卖点
            </button>
            <span class="drill-hint-text" v-if="canDrillDeeper">点击笔/线段可继续钻取</span>
            <button class="drill-ai-btn" @click="onAIAnalyze" :disabled="!chartData">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
              AI 区间套分析
            </button>
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import type { DrillLevel, DrillMarketType, ChanlunData } from '@/types/chanlun'
import { getNextInterval, parseDateString, getIntervalLabel, getSegmentLabel, MAX_DRILL_DEPTH } from '@/utils/drilldown'
import { getKlineDataRange, getAstockKlineDataRange, getGoldKlineDataRange } from '@/api/client'

interface BreadcrumbItem {
  interval: string
  label: string
}

const props = defineProps<{
  visible: boolean
  level: DrillLevel
  depth: number
  breadcrumbs: BreadcrumbItem[]
  drillStack: DrillLevel[]
  parentChartData?: ChanlunData | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'jump-to', index: number): void
  (e: 'drill-deeper', payload: {
    segmentType: 'bi' | 'xd'
    segmentIndex: number
    startDate: string
    endDate: string
    startPrice: number
    endPrice: number
  }): void
  (e: 'ai-analyze', payload: {
    symbol: string
    interval: string
    market: string
    drillContext: any
  }): void
  (e: 'data-loaded', levelId: string, data: ChanlunData): void
}>()

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

const loading = ref(false)
const error = ref('')
const chartData = ref<ChanlunData | null>(null)

const showBi = ref(true)
const showXd = ref(true)
const showZs = ref(true)
const showFx = ref(true)

const maxDepth = MAX_DRILL_DEPTH

const currentInterval = computed(() => props.level.interval)

const canDrillDeeper = computed(() => {
  return props.depth < maxDepth && getNextInterval(currentInterval.value, props.level.market) !== null
})

async function fetchData() {
  loading.value = true
  error.value = ''
  chartData.value = null

  try {
    const startTime = parseDateString(props.level.startDate)
    const endTime = parseDateString(props.level.endDate)
    let data: ChanlunData

    if (props.level.market === 'astock') {
      data = await getAstockKlineDataRange(props.level.symbol, currentInterval.value, startTime, endTime)
    } else if (props.level.market === 'gold') {
      data = await getGoldKlineDataRange(currentInterval.value, startTime, endTime)
    } else {
      data = await getKlineDataRange(props.level.symbol, currentInterval.value, startTime, endTime)
    }

    if ((data as any).error) {
      error.value = (data as any).error
      return
    }

    chartData.value = data
    loading.value = false
    emit('data-loaded', props.level.id, data)
    await nextTick()
    renderChart()
  } catch (e: any) {
    loading.value = false
    error.value = e.message || '加载数据失败'
  }
}

function renderChart() {
  if (!chartRef.value || !chartData.value) return

  if (!chart) {
    chart = echarts.init(chartRef.value)
  }

  const { klines, bi, xd, zs, fx } = chartData.value
  if (!klines || !Array.isArray(klines)) return

  const dates = klines.map((k: any) => k.date)
  const ohlc = klines.map((k: any) => [parseFloat(k.o), parseFloat(k.c), parseFloat(k.l), parseFloat(k.h)])
  const closes = klines.map((k: any) => parseFloat(k.c))

  // EMA / MACD
  const calcEMA = (data: number[], period: number) => {
    const k = 2 / (period + 1)
    const ema: number[] = []
    let sum = 0
    for (let i = 0; i < period && i < data.length; i++) sum += data[i]
    ema[period - 1] = sum / period
    for (let i = period; i < data.length; i++) ema[i] = data[i] * k + ema[i - 1] * (1 - k)
    for (let i = 0; i < period - 1; i++) ema[i] = ema[period - 1]
    return ema
  }
  const dif = calcEMA(closes, 12).map((v, i) => v - calcEMA(closes, 26)[i])
  const dea = calcEMA(dif, 9)
  const macd = dif.map((v, i) => (v - dea[i]) * 2)

  const findIdx = (d: string) => {
    if (!d) return -1
    const norm = d.replace(' ', 'T')
    for (let i = 0; i < dates.length; i++) {
      if (dates[i] === norm || dates[i] === d || dates[i].substring(0, 19) === norm.substring(0, 19)) return i
    }
    return -1
  }

  // Bi markLines
  const biML: any[] = []
  if (showBi.value && bi?.length) {
    for (const b of [...bi].sort((a: any, b: any) => a.index - b.index)) {
      const si = findIdx(b.start_date), ei = findIdx(b.end_date)
      if (si >= 0 && ei >= 0) {
        biML.push([
          { name: `笔${b.index}`, xAxis: si, yAxis: b.start_price, symbol: 'circle', symbolSize: 6, itemStyle: { color: b.type === 'up' ? '#2196F3' : '#FF5722' } },
          { name: `笔${b.index}`, xAxis: ei, yAxis: b.end_price, symbol: 'circle', symbolSize: 6, itemStyle: { color: b.type === 'up' ? '#2196F3' : '#FF5722' } }
        ])
      }
    }
  }

  // Xd markLines
  const xdML: any[] = []
  if (showXd.value && xd?.length) {
    for (const x of [...xd].sort((a: any, b: any) => a.index - b.index)) {
      const si = findIdx(x.start_date), ei = findIdx(x.end_date)
      if (si >= 0 && ei >= 0) {
        xdML.push([
          { name: `线段${x.index}`, xAxis: si, yAxis: x.start_price, symbol: 'diamond', symbolSize: 8, itemStyle: { color: x.type === 'up' ? '#1565C0' : '#D32F2F' } },
          { name: `线段${x.index}`, xAxis: ei, yAxis: x.end_price, symbol: 'diamond', symbolSize: 8, itemStyle: { color: x.type === 'up' ? '#1565C0' : '#D32F2F' } }
        ])
      }
    }
  }

  // ZS markAreas
  const zsMA: any[] = []
  if (showZs.value && zs?.length) {
    for (const z of zs) {
      const si = findIdx((z as any).start_date), ei = findIdx((z as any).end_date)
      if (si >= 0 && ei >= 0) {
        zsMA.push([{ coord: [si, z.zd] }, { coord: [ei, z.zg] }])
      }
    }
  }

  // FX markPoints
  const fxMP: any[] = []
  if (showFx.value && fx?.length) {
    for (const f of fx) {
      const idx = findIdx((f as any).date)
      if (idx >= 0) {
        const isDi = (f as any).type === 'di'
        fxMP.push({
          coord: [idx, (f as any).price],
          symbol: 'triangle',
          symbolSize: 12,
          symbolRotate: isDi ? 0 : 180,
          itemStyle: { color: isDi ? '#4CAF50' : '#F44336' },
          label: { show: true, position: isDi ? 'bottom' : 'top', formatter: isDi ? '买' : '卖', color: isDi ? '#4CAF50' : '#F44336', fontSize: 10, fontWeight: 'bold' }
        })
      }
    }
  }

  // Depth-based accent color
  const depthColors = ['#2962FF', '#9C27B0', '#089981', '#FF6D00']
  const accentColor = depthColors[(props.depth - 1) % depthColors.length]

  const option = {
    backgroundColor: '#FFFFFF',
    title: {
      text: `${props.level.symbol} ${getIntervalLabel(currentInterval.value)} (${getSegmentLabel(props.level.segmentType, props.level.segmentIndex)})`,
      left: 'center',
      textStyle: { fontSize: 14, fontWeight: 600, color: accentColor }
    },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    grid: [
      { left: '8%', right: '6%', top: '12%', height: '52%' },
      { left: '8%', right: '6%', top: '70%', height: '20%' }
    ],
    xAxis: [
      { type: 'category', data: dates, boundaryGap: true, axisLine: { onZero: false }, splitLine: { show: false } },
      { type: 'category', gridIndex: 1, data: dates, boundaryGap: true, axisLine: { onZero: false }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false } }
    ],
    yAxis: [
      { scale: true, splitArea: { show: true } },
      { scale: true, gridIndex: 1, splitNumber: 3, axisLabel: { show: true }, axisLine: { show: true }, splitLine: { show: true, lineStyle: { type: 'dashed', color: '#eee' } } }
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
      { show: true, xAxisIndex: [0, 1], type: 'slider', bottom: '3%', start: 0, end: 100 }
    ],
    series: [
      {
        name: 'K线', type: 'candlestick', data: ohlc, xAxisIndex: 0, yAxisIndex: 0,
        itemStyle: { color: '#ef5350', color0: '#26a69a', borderColor: '#ef5350', borderColor0: '#26a69a' },
        markArea: { silent: true, itemStyle: { color: 'rgba(255,193,7,0.12)', borderColor: '#FFC107', borderWidth: 1 }, data: zsMA },
        markLine: { symbol: ['circle', 'circle'], symbolSize: 6, lineStyle: { type: 'solid', width: 2 }, data: biML },
        markPoint: { data: fxMP, symbolSize: 12 }
      },
      {
        name: '线段', type: 'candlestick', data: ohlc.map(() => ['-']), xAxisIndex: 0, yAxisIndex: 0,
        itemStyle: { color: 'transparent', color0: 'transparent', borderColor: 'transparent', borderColor0: 'transparent' },
        markLine: { symbol: ['diamond', 'diamond'], symbolSize: 8, lineStyle: { type: 'solid', width: 3 }, data: xdML }
      },
      { name: 'DIF', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: dif, lineStyle: { color: '#FF9800', width: 1 }, symbol: 'none', z: 2 },
      { name: 'DEA', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: dea, lineStyle: { color: '#2196F3', width: 1 }, symbol: 'none', z: 2 },
      { name: 'MACD', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: macd.map((v) => ({ value: v, itemStyle: { color: v >= 0 ? '#ef5350' : '#26a69a' } })), barWidth: '40%', z: 1 }
    ]
  }

  chart.setOption(option, true)

  // Click handler for deeper drill
  if (canDrillDeeper.value && chart) {
    chart.off('click')
    chart.on('click', 'markLine', (params: any) => {
      const name = params.name || ''
      let segmentType: 'bi' | 'xd' | null = null
      let segmentIndex = -1
      const biMatch = name.match(/^笔(\d+)$/)
      const xdMatch = name.match(/^线段(\d+)$/)
      if (biMatch) { segmentType = 'bi'; segmentIndex = parseInt(biMatch[1], 10) }
      else if (xdMatch) { segmentType = 'xd'; segmentIndex = parseInt(xdMatch[1], 10) }
      if (!segmentType || segmentIndex < 0) return

      const store = segmentType === 'bi' ? (bi || []) : (xd || [])
      const seg = store.find((s: any) => s.index === segmentIndex)
      if (!seg) return

      emit('drill-deeper', {
        segmentType,
        segmentIndex,
        startDate: seg.start_date,
        endDate: seg.end_date,
        startPrice: seg.start_price,
        endPrice: seg.end_price,
      })
    })
  }
}

// 构造区间套分析上下文并 emit 给父组件
function onAIAnalyze() {
  if (!chartData.value) return

  // 取父级（当前级的上一级）的缠论数据
  const drillChain = props.drillStack.map((level) => ({
    interval: level.interval,
    label: getSegmentLabel(level.segmentType, level.segmentIndex),
    segmentType: level.segmentType,
    segmentIndex: level.segmentIndex,
  }))

  const drillContext: any = {
    parent_interval: props.level.parentInterval,
    segment_type: props.level.segmentType,
    segment_index: props.level.segmentIndex,
    drill_depth: props.depth,
    drill_chain: drillChain,
  }

  if (props.parentChartData) {
    drillContext.parent_bi = props.parentChartData.bi || []
    drillContext.parent_xd = props.parentChartData.xd || []
    drillContext.parent_zs = props.parentChartData.zs || []
    drillContext.parent_fx = props.parentChartData.fx || []
  }

  emit('ai-analyze', {
    symbol: props.level.symbol,
    interval: props.level.interval,
    market: props.level.market,
    drillContext,
  })
}

// Watch visibility
watch(() => props.visible, (val) => {
  if (val) {
    fetchData()
  } else {
    if (chart) { chart.dispose(); chart = null }
  }
})

// ESC key handler
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.visible) {
    emit('close')
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  // 组件首次挂载时 visible 已经是 true（由 v-if 控制），需要主动加载数据
  fetchData()
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  if (chart) { chart.dispose(); chart = null }
})
</script>

<style scoped>
.drill-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.drill-panel {
  width: 100%;
  max-width: 1200px;
  height: 90vh;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.drill-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: #F8F9FD;
  border-bottom: 1px solid #E0E3EB;
  flex-shrink: 0;
}

.drill-breadcrumb {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.breadcrumb-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  cursor: default;
  font-size: 13px;
  font-weight: 500;
  color: #787B86;
  transition: all 0.15s;
}

.breadcrumb-item.clickable {
  cursor: pointer;
}

.breadcrumb-item.clickable:hover {
  background: rgba(41, 98, 255, 0.08);
  color: #2962FF;
}

.breadcrumb-item.active {
  background: rgba(41, 98, 255, 0.12);
  color: #2962FF;
  font-weight: 600;
}

.breadcrumb-interval {
  font-weight: 600;
}

.breadcrumb-segment {
  color: #A0A4A8;
  font-size: 12px;
}

.breadcrumb-item.active .breadcrumb-segment {
  color: #2962FF;
}

.breadcrumb-sep {
  color: #C0C4CC;
  font-size: 16px;
  margin: 0 2px;
}

.drill-header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.drill-depth {
  font-size: 12px;
  font-weight: 600;
  color: #787B86;
  background: #E0E3EB;
  padding: 2px 8px;
  border-radius: 10px;
}

.drill-close {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #787B86;
  cursor: pointer;
  transition: all 0.15s;
}

.drill-close:hover {
  background: rgba(242, 54, 69, 0.1);
  color: #F23645;
}

.drill-body {
  flex: 1;
  position: relative;
  min-height: 0;
}

.drill-chart {
  width: 100%;
  height: 100%;
}

.drill-loading,
.drill-error {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #787B86;
}

.drill-spinner {
  width: 36px;
  height: 36px;
  border: 3px solid #E0E3EB;
  border-top-color: #2962FF;
  border-radius: 50%;
  animation: drillspin 0.8s linear infinite;
}

.drill-retry {
  padding: 6px 16px;
  border: 1px solid #2962FF;
  border-radius: 6px;
  background: transparent;
  color: #2962FF;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.drill-retry:hover {
  background: rgba(41, 98, 255, 0.08);
}

.drill-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 20px;
  background: #F8F9FD;
  border-top: 1px solid #E0E3EB;
  flex-shrink: 0;
}

.drill-layer-btn {
  padding: 5px 14px;
  border: 1px solid #E0E3EB;
  border-radius: 6px;
  background: #fff;
  color: #787B86;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.drill-layer-btn:hover {
  border-color: #C0C4CC;
}

.drill-layer-btn.active {
  background: #2962FF;
  color: #fff;
  border-color: #2962FF;
}

.drill-hint-text {
  margin-left: auto;
  font-size: 12px;
  color: #2962FF;
  opacity: 0.7;
}

.drill-ai-btn {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 14px;
  border: 1px solid #2962FF;
  border-radius: 6px;
  background: transparent;
  color: #2962FF;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.drill-ai-btn:hover:not(:disabled) {
  background: rgba(41, 98, 255, 0.08);
}

.drill-ai-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

@keyframes drillspin {
  to { transform: rotate(360deg); }
}

/* Transition */
.drill-fade-enter-active,
.drill-fade-leave-active {
  transition: all 0.25s ease;
}

.drill-fade-enter-from,
.drill-fade-leave-to {
  opacity: 0;
}

.drill-fade-enter-from .drill-panel,
.drill-fade-leave-to .drill-panel {
  transform: scale(0.95);
  opacity: 0;
}
</style>
