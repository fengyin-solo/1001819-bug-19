<template>
  <section class="page" data-module="leak">
    <header class="page-head">
      <div>
        <h2>泄漏排查管理</h2>
        <p class="page-desc">维护排查记录，围绕排查编号、排查区域、排查方式、疑似点位做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记排查记录</button>
        <button class="btn" type="button" @click="exportRows">导出泄漏盘点清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>排查编号</span>
        <input v-model="filters.keyword" placeholder="按排查编号检索" />
      </label>
      <label class="filter-item">
        <span>排查状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
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
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ displayValue(row, column) }}</td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              :disabled="busyId === row.id"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!availableActions(row).length" class="muted-text">已结案</span>
          </td>
          <td>
            <button class="link" type="button" @click="openDetail(row)">查看详情</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无符合条件的泄漏排查数据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条泄漏排查记录（待处理 {{ pendingCount }} 条）</span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>

    <div v-if="detail" class="modal-mask" @click.self="closeDetail">
      <div class="modal-card">
        <div class="modal-head">
          <h3>排查记录详情</h3>
          <button class="link" type="button" @click="closeDetail">关闭</button>
        </div>
        <dl class="detail-grid">
          <div v-for="column in columns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ displayValue(detail, column) }}</dd>
          </div>
          <div>
            <dt>待处理标记</dt>
            <dd>{{ detail.pending ? '待处理' : '已离开待办' }}</dd>
          </div>
        </dl>
        <p v-if="detailMessage" class="detail-note">详情与列表来自同一份台账，刷新或重新打开看到的结果一致。</p>
      </div>
    </div>

    <div v-if="creating" class="modal-mask" @click.self="creating = false">
      <div class="modal-card">
        <div class="modal-head">
          <h3>登记排查记录</h3>
          <button class="link" type="button" @click="creating = false">关闭</button>
        </div>
        <form class="create-form" @submit.prevent="submitCreate">
          <label v-for="field in createFields" :key="field" class="filter-item">
            <span>{{ field }}<em v-if="requiredFields.includes(field)">*</em></span>
            <input v-model="createForm[field]" :placeholder="`请输入${field}`" />
          </label>
          <div class="modal-actions">
            <button class="btn primary" type="submit" :disabled="submitting">
              {{ submitting ? '提交中…' : '提交登记' }}
            </button>
            <button class="btn ghost" type="button" @click="creating = false">取消</button>
          </div>
        </form>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { explainFailure, requestJson } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type ActionResult = { ok: boolean; message: string; entry: Row | null }
type StatsPayload = {
  total: number
  pending: number
  by_status: Record<string, number>
}

const ENDPOINT = '/api/leak'
const columns = ['排查编号', '排查区域', '排查方式', '疑似点位', '检出数量', '排查人员', '排查日期', '排查状态']
const statuses = ['待排查', '排查中', '已处置', '已排除']
const doneStatuses = new Set(['已处置', '已排除'])
const actionByTarget: Record<string, string> = {
  排查中: '安排排查',
  已处置: '确认处置',
  已排除: '排除嫌疑',
}
const requiredFields = ['排查编号', '排查区域', '排查方式']
const createFields = columns.slice(0, 7)

const rows = ref<Row[]>([])
const total = ref(0)
const pendingCount = ref(0)
const stats = ref([
  { label: '待处理记录', value: 0 },
  { label: '排查中', value: 0 },
  { label: '已处置', value: 0 },
  { label: '已排除', value: 0 },
])
const message = ref('')
const messageOk = ref(false)
const filters = ref<{ keyword: string; status: string }>({ keyword: '', status: '' })

const detail = ref<Row | null>(null)
const detailMessage = ref(true)
const creating = ref(false)
const submitting = ref(false)
const busyId = ref<number | null>(null)
const createForm = ref<Record<string, string>>({})

function displayValue(row: Row, column: string): string {
  const value = row[column]
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

/** 终态不再给任何动作按钮；排查中只能走向两个终态，避免“改回去”。 */
function availableActions(row: Row): string[] {
  const current = String(row['排查状态'] ?? '')
  if (doneStatuses.has(current)) {
    return []
  }
  return statuses
    .filter((target) => statuses.indexOf(target) > statuses.indexOf(current))
    .map((target) => actionByTarget[target])
    .filter(Boolean)
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function exportRows() {
  const params = new URLSearchParams()
  if (filters.value.keyword) params.set('keyword', filters.value.keyword)
  if (filters.value.status) params.set('status', filters.value.status)
  const query = params.toString()
  // 盘点清单与列表、详情同一数据源，处置结果刷新后立即反映。
  window.open(`${ENDPOINT}/export${query ? `?${query}` : ''}`, '_blank')
}

function openCreate() {
  createForm.value = Object.fromEntries(createFields.map((field) => [field, '']))
  creating.value = true
}

async function submitCreate() {
  message.value = ''
  submitting.value = true
  try {
    const { response, body } = await requestJson<ActionResult>(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
      retries: 3,
    })
    if (!response.ok) {
      messageOk.value = false
      message.value = await explainFailure(response, '排查记录登记失败')
      return
    }
    if (!body.ok) {
      messageOk.value = false
      message.value = body.message
      return
    }
    creating.value = false
    messageOk.value = true
    message.value = body.message
    await reload()
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '排查记录登记失败，请检查网络后重试'
  } finally {
    submitting.value = false
  }
}

function openDetail(row: Row) {
  detail.value = row
}

function closeDetail() {
  detail.value = null
}

async function runAction(action: string, row: Row) {
  message.value = ''
  busyId.value = Number(row.id)
  try {
    // 动作在后端是状态机 + 幂等，断线重试不会把结果改回去，可以安全重试。
    const { response, body } = await requestJson<ActionResult>(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
      retries: 3,
    })
    if (!response.ok) {
      messageOk.value = false
      message.value = await explainFailure(response, `「${action}」未生效`)
      return
    }
    messageOk.value = body.ok
    message.value = body.ok
      ? body.message
      : `${body.message}（记录保持原状态：${String(row['排查状态'] ?? '')}）`
    // 已处置/已排除后，列表与概览待办同时少一条。
    await reload()
    if (detail.value && String(detail.value.id) === String(row.id) && body.entry) {
      detail.value = body.entry
    }
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error
      ? `网络中断，已自动重试仍失败：${error.message}。结果未被改写，请稍后再试`
      : '泄漏排查操作失败，请检查网络后重试'
  } finally {
    busyId.value = null
  }
}

async function loadStats() {
  try {
    const { body } = await requestJson<StatsPayload>(`${ENDPOINT}/stats`)
    pendingCount.value = body.pending
    stats.value = [
      { label: '待处理记录', value: body.pending },
      { label: '排查中', value: body.by_status['排查中'] ?? 0 },
      { label: '已处置', value: body.by_status['已处置'] ?? 0 },
      { label: '已排除', value: body.by_status['已排除'] ?? 0 },
    ]
  } catch {
    // 统计失败不影响主列表，保留上一次的数字。
  }
}

async function reload() {
  message.value = ''
  const params = new URLSearchParams()
  if (filters.value.keyword.trim()) params.set('keyword', filters.value.keyword.trim())
  if (filters.value.status) params.set('status', filters.value.status)
  const query = params.toString()
  try {
    const { response, body } = await requestJson<{ items: Row[]; total: number }>(
      `${ENDPOINT}?${query}`,
      { retries: 3 },
    )
    if (!response.ok) {
      messageOk.value = false
      message.value = await explainFailure(response, '排查记录列表读取失败')
      return
    }
    rows.value = body.items ?? []
    total.value = body.total ?? rows.value.length
    await loadStats()
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '泄漏排查列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.muted-text {
  color: var(--muted);
  font-size: 12px;
}
.ok-text {
  color: #067647;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(16, 24, 40, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal-card {
  background: #fff;
  border-radius: 10px;
  width: 640px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 64px);
  overflow: auto;
  padding: 16px 20px;
}
.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.modal-head h3 {
  margin: 0;
  font-size: 16px;
}
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 16px;
  margin: 0;
}
.detail-grid dt {
  font-size: 12px;
  color: var(--muted);
}
.detail-grid dd {
  margin: 2px 0 0;
  font-size: 13px;
}
.detail-note {
  color: var(--muted);
  font-size: 12px;
  margin-top: 12px;
}
.create-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 16px;
}
.create-form em {
  color: #b42318;
  font-style: normal;
  margin-left: 2px;
}
.modal-actions {
  grid-column: 1 / -1;
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 4px;
}
.link:disabled {
  color: #94a3b8;
  cursor: not-allowed;
}
</style>
