<template>
  <section class="page" data-module="leak">
    <header class="page-head">
      <div>
        <h2>泄漏排查管理</h2>
        <p class="page-desc">维护排查记录，围绕排查编号、排查区域、排查方式、疑似点位做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记排查记录</button>
        <button class="btn" type="button" @click="exportRows">导出泄漏排查清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="scope-bar">
      <button
        v-for="tab in scopeTabs"
        :key="tab.value"
        class="btn"
        :class="{ primary: scope === tab.value }"
        type="button"
        @click="switchScope(tab.value)"
      >
        {{ tab.label }}<span v-if="tab.value === 'pending'">（{{ statsMap['待处理'] }}）</span>
      </button>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>排查编号</span>
        <input v-model="keyword" placeholder="按排查编号检索" />
      </label>
      <label v-if="scope === 'all'" class="filter-item">
        <span>排查状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(String(row['排查状态']))"
              :key="action"
              class="link"
              type="button"
              :disabled="busyId === String(row.id)"
              @click="runAction(action, row)"
            >
              {{ busyId === String(row.id) && lastAction === action ? '提交中…' : action }}
            </button>
            <span v-if="!availableActions(String(row['排查状态'])).length" class="muted-text">已办结</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">
            {{ scope === 'pending' ? '待处理范围已清空：已处置与已排除的记录不再显示在这里' : '暂无泄漏排查数据，可先登记排查记录' }}
          </td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条泄漏排查记录</span>
      <span v-if="successMessage" class="success-text">{{ successMessage }}</span>
      <span v-else-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/leak'
const columns = ["排查编号", "排查区域", "排查方式", "疑似点位", "检出数量", "排查人员", "排查日期", "排查状态"]
const statuses = ["待排查", "排查中", "已处置", "已排除"]

// 状态机在前端镜像一份：只给当前状态亮可执行的动作，避免排查人员误点重复处置。
const NEXT_ACTIONS: Record<string, string[]> = {
  "待排查": ["安排排查"],
  "排查中": ["确认处置", "排除嫌疑"],
  "已处置": [],
  "已排除": [],
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const successMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const scope = ref<'pending' | 'all'>('pending')
const scopeTabs = [
  { label: '待处理', value: 'pending' as const },
  { label: '全部记录', value: 'all' as const },
]
const busyId = ref<string | null>(null)
const lastAction = ref('')

const statsMap = ref<Record<string, number>>({
  "待排查": 0, "排查中": 0, "已处置": 0, "已排除": 0, "待处理": 0, "本月检出点": 0,
})
const stats = ref([
  { label: '待处理记录', value: 0 },
  { label: '已处置', value: 0 },
  { label: '已排除', value: 0 },
  { label: '检出点合计', value: 0 },
])

function availableActions(status: string): string[] {
  return NEXT_ACTIONS[status] ?? []
}

function switchScope(next: 'pending' | 'all') {
  scope.value = next
  if (next === 'pending') statusFilter.value = ''
  void reload()
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '排查记录登记入口尚未接入审批流'
  successMessage.value = ''
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) return
    const data = (await response.json()) as Record<string, number>
    statsMap.value = data
    stats.value = [
      { label: '待处理记录', value: data['待处理'] ?? 0 },
      { label: '已处置', value: data['已处置'] ?? 0 },
      { label: '已排除', value: data['已排除'] ?? 0 },
      { label: '检出点合计', value: data['本月检出点'] ?? 0 },
    ]
  } catch {
    // 统计读取失败不阻断列表，页脚会在列表请求失败时给出说明。
  }
}

// 动作接口幂等：网络中断导致响应丢失时，重发同一动作不会把结果改回去。
async function postAction(id: string, action: string, attempt: number): Promise<Response> {
  try {
    return await request(`${ENDPOINT}/${id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
  } catch (error) {
    if (attempt >= 2) throw error
    await new Promise((resolve) => setTimeout(resolve, 600))
    return postAction(id, action, attempt + 1)
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  successMessage.value = ''
  busyId.value = String(row.id)
  lastAction.value = action
  try {
    const response = await postAction(String(row.id), action, 0)
    // HTTP 层失败也要把后端的原因透出来，而不是含糊地说「未生效」。
    let message = ''
    try {
      message = String((await response.json())?.message ?? '')
    } catch {
      message = ''
    }
    if (!response.ok) {
      throw new Error(message || `服务暂不可用（HTTP ${response.status}），请稍后重试；本次处置未被修改`)
    }
    if (message) successMessage.value = message
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error
      ? `「${action}」失败：${error.message.replace(/^接口请求失败：/, '')}。请求未确认成功，请检查网络后重试，重试不会覆盖已有处置结果`
      : '泄漏排查操作失败，请稍后重试'
  } finally {
    busyId.value = null
    lastAction.value = ''
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  params.set('scope', scope.value)
  if (scope.value === 'all' && statusFilter.value) params.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      let detail = ''
      try {
        detail = String((await response.json())?.detail ?? '')
      } catch {
        detail = ''
      }
      throw new Error(detail || `服务返回 ${response.status}`)
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? `排查记录列表读取失败：${error.message.replace(/^接口请求失败：/, '')}` : '泄漏排查列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadStats()
})
</script>
