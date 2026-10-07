<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import type { OrderLineRow, OrderRow } from '../types'
import ErrorBanner from '../components/ErrorBanner.vue'

const orders = ref<OrderRow[]>([])
const lines = ref<OrderLineRow[]>([])
const orderId = ref<number | null>(null)
const runId = ref<number | null>(null)
const running = ref(false)
const error = ref('')

async function loadLines(id: number) {
  lines.value = await api<OrderLineRow[]>('/orders/' + id + '/lines')
  const latest = await api<{ id: number | null; generated?: boolean }>(`/prep/latest?order_id=${id}`)
  runId.value = latest.generated ? latest.id : null
}

async function selectOrder(o: OrderRow) {
  if (o.id === orderId.value) return
  orderId.value = o.id
  error.value = ''
  try { await loadLines(o.id) } catch (e) { error.value = (e as Error).message }
}

async function run() {
  if (orderId.value == null) return
  error.value = ''
  running.value = true
  try {
    const res = await api<{ id: number }>(`/prep/run?order_id=${orderId.value}`, { method: 'POST' })
    runId.value = res.id
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    running.value = false
  }
}

onMounted(async () => {
  try {
    orders.value = await api<OrderRow[]>('/orders')
    if (orders.value.length) { orderId.value = orders.value[0].id; await loadLines(orderId.value) }
  } catch (e) { error.value = (e as Error).message }
})
</script>
<template>
  <h1>订单芯片</h1>
  <p class="sub">门店要货 · 选择订单后生成备料单（热厨册 / 冷荤册同成同败）</p>
  <div class="kp-chips" style="margin-bottom:1rem">
    <button v-for="o in orders" :key="o.id" type="button" class="kp-chip"
      :style="o.id === orderId ? 'background:var(--kp-accent);color:#1c1208;font-weight:800' : ''"
      @click="selectOrder(o)">{{ o.code }} · {{ o.outlet }} · {{ o.status }}</button>
  </div>
  <div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.85rem">
    <button class="btn" :disabled="running || orderId == null" @click="run">
      {{ running ? '生成中…' : '生成备料单' }}
    </button>
    <span v-if="runId != null" class="badge badge-ok">已生成备料单 #{{ runId }}</span>
    <span v-else class="muted" style="font-size:0.8rem">同一订单重复生成返回同一套两册</span>
  </div>
  <ErrorBanner :message="error" @dismiss="error = ''" />
  <div class="kp-worksheet">
    <h2>订单行</h2>
    <table>
      <thead><tr><th>菜品</th><th>份数</th></tr></thead>
      <tbody>
        <tr v-for="l in lines" :key="l.id"><td>{{ l.dish_name }}</td><td>{{ l.portions }}</td></tr>
      </tbody>
    </table>
  </div>
</template>
