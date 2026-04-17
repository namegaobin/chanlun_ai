<template>
  <div class="multi-level-panel" v-if="multiLevelData">
    <div class="ml-header">
      <h4>🔄 多级别区间套分析</h4>
      <span class="ml-badge">{{ multiLevelData.analyzed_levels.length }} 级别</span>
    </div>

    <!-- 级别概览卡片 -->
    <div class="levels-grid">
      <div
        v-for="level in multiLevelData.analyzed_levels"
        :key="level"
        class="level-card"
        :class="{ active: expandedLevel === level, error: hasError(level), 'base-level': level === multiLevelData.base_interval }"
        @click="toggleLevel(level)"
      >
        <div class="level-name">{{ formatInterval(level) }}</div>
        <div class="level-meta">
          <span v-if="level === multiLevelData.base_interval" class="base-tag">基准</span>
          <span v-if="hasError(level)" class="error-tag">失败</span>
          <span v-else class="stat-tag">{{ getLevelData(level)?.bis_count || 0 }}笔</span>
        </div>
        <div class="level-bar">
          <div v-if="!hasError(level)" class="bar-fill" :style="{ width: getLevelFill(level) }"></div>
        </div>
      </div>
    </div>

    <!-- 展开详情 -->
    <Transition name="slide">
      <div v-if="expandedLevel && !hasError(expandedLevel)" class="level-detail">
        <div class="detail-title">
          <span>{{ formatInterval(expandedLevel) }} 级别详情</span>
          <button @click.stop="expandedLevel = null" class="close-btn">&times;</button>
        </div>

        <!-- 当前价格 -->
        <div class="price-row">
          <span class="label">价格</span>
          <span class="value">{{ formatPrice(getLevelData(expandedLevel)?.latest_price) }}</span>
        </div>

        <!-- 最近笔 -->
        <div v-if="getLevelData(expandedLevel)?.bis?.length" class="struct-block">
          <h5>笔 (最近 {{ Math.min(5, getLevelData(expandedLevel)!.bis.length) }} )</h5>
          <div class="bi-list">
            <div
              v-for="bi in getLevelData(expandedLevel)!.bis.slice(-5)"
              :key="bi.index"
              class="bi-row"
              :class="bi.type"
            >
              <span class="dir">{{ bi.type === 'up' ? '↑' : '↓' }}</span>
              <span class="price">{{ formatPrice(bi.start_price) }} → {{ formatPrice(bi.end_price) }}</span>
              <span v-if="bi.mmds.length" class="signal">{{ bi.mmds.join(',') }}</span>
            </div>
          </div>
        </div>

        <!-- 最近中枢 -->
        <div v-if="getLevelData(expandedLevel)?.bi_zss?.length" class="struct-block">
          <h5>中枢 ({{ getLevelData(expandedLevel)!.bi_zss.length }})</h5>
          <div class="zs-list">
            <div
              v-for="zs in getLevelData(expandedLevel)!.bi_zss.slice(-3)"
              :key="zs.index"
              class="zs-row"
            >
              <span class="zs-dir" :class="zs.direction">{{ zs.direction === 'up' ? '↑' : zs.direction === 'down' ? '↓' : '→' }}</span>
              <span class="zs-range">ZG {{ formatPrice(zs.zg) }} / ZD {{ formatPrice(zs.zd) }}</span>
              <span class="zs-relation" :class="zs.relation">{{ formatRelation(zs.relation) }}</span>
            </div>
          </div>
        </div>

        <!-- 最近线段 -->
        <div v-if="getLevelData(expandedLevel)?.xds?.length" class="struct-block">
          <h5>线段 ({{ getLevelData(expandedLevel)!.xds.length }})</h5>
          <div class="xd-list">
            <div
              v-for="xd in getLevelData(expandedLevel)!.xds.slice(-3)"
              :key="xd.index"
              class="xd-row"
              :class="xd.type"
            >
              <span class="dir">{{ xd.type === 'up' ? '↗' : '↘' }}</span>
              <span class="price">{{ formatPrice(xd.start_price) }} → {{ formatPrice(xd.end_price) }}</span>
              <span class="info">{{ xd.bis_count }}笔</span>
              <span v-if="xd.mmds.length" class="signal">{{ xd.mmds.join(',') }}</span>
            </div>
          </div>
        </div>
      </div>
    </Transition>

    <!-- 综合摘要 -->
    <div class="summary-section">
      <h5>综合摘要</h5>
      <div class="summary-row">
        <span class="label">级别一致性</span>
        <span class="value" :class="consistencyClass">{{ trendConsistency }}</span>
      </div>
      <div v-if="keyStructures.length" class="summary-row">
        <span class="label">关键中枢</span>
        <div class="value zs-tags">
          <span v-for="ks in keyStructures" :key="`${ks.level}-${ks.type}`" class="zs-mini-tag" :class="ks.direction">
            {{ formatInterval(ks.level) }} {{ ks.direction === 'up' ? '↑' : ks.direction === 'down' ? '↓' : '→' }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { MultiLevelAnalysisData, MultiLevelAnalysisItem } from '@/types/chanlun'

const props = defineProps<{
  multiLevelData?: MultiLevelAnalysisData
}>()

const expandedLevel = ref<string | null>(null)

const INTERVAL_LABELS: Record<string, string> = {
  '1m': '1分钟', '5m': '5分钟', '15m': '15分钟',
  '1h': '1小时', '4h': '4小时', '1d': '日线',
  '1w': '周线', '1M': '月线', '60m': '60分钟',
}

function formatInterval(iv: string): string {
  return INTERVAL_LABELS[iv] || iv
}

function formatPrice(p?: number): string {
  if (!p) return '-'
  return p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function getLevelData(level: string): MultiLevelAnalysisItem | undefined {
  return props.multiLevelData?.levels?.[level]
}

function hasError(level: string): boolean {
  return !!getLevelData(level)?.error
}

function getLevelFill(level: string): string {
  const d = getLevelData(level)
  if (!d || d.error) return '0%'
  const maxScore = Math.max(d.bis_count * 2 + d.xds_count * 5 + d.bi_zss_count * 8, 1)
  const score = Math.min(d.bis_count * 2 + d.xds_count * 5 + d.bi_zss_count * 8, maxScore)
  return `${(score / maxScore) * 100}%`
}

function toggleLevel(level: string) {
  expandedLevel.value = expandedLevel.value === level ? null : level
}

function formatRelation(r: string): string {
  const m: Record<string, string> = { new: '新', up_trend: '上升', down_trend: '下降', extend: '延伸' }
  return m[r] || r
}

const trendConsistency = computed(() => {
  const levels = props.multiLevelData?.analyzed_levels || []
  const ok = levels.filter(l => { const d = getLevelData(l); return d && !d.error && d.bi_zss_count > 0 })
  if (ok.length < 2) return '数据不足'
  const dirs = ok.map(l => { const zss = getLevelData(l)?.bi_zss; return zss?.length ? zss[zss.length - 1].direction : ''; })
  const unique = [...new Set(dirs.filter(Boolean))]
  if (unique.length === 0) return '无中枢'
  if (unique.length === 1) return unique[0] === 'up' ? '一致看涨' : unique[0] === 'down' ? '一致看跌' : '一致震荡'
  return '趋势分化'
})

const consistencyClass = computed(() => {
  const t = trendConsistency.value
  if (t.includes('涨')) return 'bullish'
  if (t.includes('跌')) return 'bearish'
  if (t.includes('分化')) return 'mixed'
  return 'neutral'
})

const keyStructures = computed(() => {
  return props.multiLevelData?.analysis_summary?.key_structures || []
})
</script>

<style scoped>
.multi-level-panel {
  background: #FFF8DC;
  border: 2px solid #D4C4A8;
  border-radius: 10px 4px 8px 5px / 5px 8px 4px 10px;
  margin: 12px 0;
  overflow: hidden;
}

.ml-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  background: rgba(41, 98, 255, 0.06);
  border-bottom: 2px solid #D4C4A8;
}

.ml-header h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: #2C2C2C;
}

.ml-badge {
  background: #2962FF;
  color: #fff;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}

.levels-grid {
  display: flex;
  gap: 6px;
  padding: 10px 12px;
}

.level-card {
  flex: 1;
  padding: 8px;
  background: #FFFFFF;
  border: 2px solid #E0E3EB;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
  min-width: 0;
}

.level-card:hover { border-color: #2962FF; transform: translateY(-1px); }
.level-card.active { border-color: #2962FF; background: rgba(41, 98, 255, 0.06); }
.level-card.error { border-color: #F23645; opacity: 0.7; }
.level-card.base-level { border-color: #089981; }

.level-name {
  font-size: 12px;
  font-weight: 700;
  color: #2C2C2C;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.level-meta { margin-top: 4px; display: flex; gap: 4px; }

.base-tag {
  font-size: 10px;
  background: rgba(8, 153, 129, 0.15);
  color: #089981;
  padding: 1px 5px;
  border-radius: 3px;
}

.error-tag {
  font-size: 10px;
  background: rgba(242, 54, 69, 0.12);
  color: #F23645;
  padding: 1px 5px;
  border-radius: 3px;
}

.stat-tag {
  font-size: 10px;
  background: rgba(120, 123, 134, 0.12);
  color: #787B86;
  padding: 1px 5px;
  border-radius: 3px;
}

.level-bar {
  height: 3px;
  background: #E0E3EB;
  border-radius: 2px;
  margin-top: 6px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #2962FF, #089981);
  border-radius: 2px;
  transition: width 0.3s;
}

/* 详情面板 */
.level-detail {
  padding: 12px 14px;
  border-top: 2px dashed #D4C4A8;
  background: rgba(255, 255, 255, 0.5);
}

.detail-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 700;
  color: #2C2C2C;
}

.close-btn {
  background: none;
  border: none;
  font-size: 18px;
  color: #787B86;
  cursor: pointer;
  padding: 0 4px;
}

.price-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px dashed #E0E3EB;
  margin-bottom: 8px;
}

.price-row .label { color: #787B86; font-size: 12px; }
.price-row .value { font-weight: 700; font-size: 14px; color: #2C2C2C; }

.struct-block { margin-bottom: 10px; }
.struct-block h5 {
  margin: 0 0 6px 0;
  font-size: 12px;
  color: #787B86;
  font-weight: 600;
}

.bi-list, .zs-list, .xd-list { display: flex; flex-direction: column; gap: 3px; }

.bi-row, .xd-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  padding: 3px 6px;
  border-radius: 3px;
}

.bi-row.up, .xd-row.up { background: rgba(8, 153, 129, 0.06); }
.bi-row.down, .xd-row.down { background: rgba(242, 54, 69, 0.06); }

.dir { font-weight: 700; min-width: 14px; }
.bi-row.up .dir, .xd-row.up .dir { color: #089981; }
.bi-row.down .dir, .xd-row.down .dir { color: #F23645; }

.price { color: #2C2C2C; font-family: 'Consolas', monospace; }
.info { color: #787B86; font-size: 10px; }

.signal {
  margin-left: auto;
  font-size: 10px;
  color: #2962FF;
  font-weight: 600;
}

.zs-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  padding: 4px 6px;
  background: rgba(41, 98, 255, 0.04);
  border-radius: 3px;
}

.zs-dir { font-weight: 700; }
.zs-dir.up { color: #089981; }
.zs-dir.down { color: #F23645; }
.zs-dir.zd { color: #787B86; }

.zs-range { color: #2C2C2C; font-family: 'Consolas', monospace; }

.zs-relation {
  margin-left: auto;
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
}
.zs-relation.up_trend { background: rgba(8, 153, 129, 0.12); color: #089981; }
.zs-relation.down_trend { background: rgba(242, 54, 69, 0.12); color: #F23645; }
.zs-relation.extend { background: rgba(120, 123, 134, 0.12); color: #787B86; }
.zs-relation.new { background: rgba(41, 98, 255, 0.12); color: #2962FF; }

/* 摘要 */
.summary-section {
  padding: 10px 14px;
  border-top: 2px solid #D4C4A8;
}

.summary-section h5 { margin: 0 0 8px 0; font-size: 12px; color: #787B86; }

.summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
}

.summary-row .label { color: #787B86; font-size: 12px; }
.summary-row .value { font-weight: 600; font-size: 13px; }
.summary-row .value.bullish { color: #089981; }
.summary-row .value.bearish { color: #F23645; }
.summary-row .value.mixed { color: #D9A066; }
.summary-row .value.neutral { color: #787B86; }

.zs-tags { display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; }

.zs-mini-tag {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 3px;
  font-weight: 600;
}
.zs-mini-tag.up { background: rgba(8, 153, 129, 0.12); color: #089981; }
.zs-mini-tag.down { background: rgba(242, 54, 69, 0.12); color: #F23645; }
.zs-mini-tag.zd { background: rgba(120, 123, 134, 0.12); color: #787B86; }

/* 动画 */
.slide-enter-active, .slide-leave-active { transition: all 0.2s ease; }
.slide-enter-from, .slide-leave-to { opacity: 0; max-height: 0; overflow: hidden; }
.slide-enter-to, .slide-leave-from { opacity: 1; max-height: 500px; }
</style>
