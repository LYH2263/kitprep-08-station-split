<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import type { BookKey, OrderRow, PrepResult } from '../types'
import ErrorBanner from '../components/ErrorBanner.vue'

const BOOK_ORDER: BookKey[] = ['hot', 'cold', 'unassigned']

const tree = ref<any[]>([])
const data = ref<PrepResult | null>(null)
const shortages = ref<any[]>([])
const orders = ref<OrderRow[]>([])
const orderId = ref<number>(1)
const running = ref(false)
const error = ref('')

async function loadLatest() {
  data.value = await api<PrepResult>(`/prep/latest?order_id=${orderId.value}`)
  try {
    const res = await api(`/prep/shortages?order_id=${orderId.value}`)
    shortages.value = res.shortages || []
  } catch { shortages.value = [] }
}

async function selectOrder(id: number) {
  if (id === orderId.value) return
  orderId.value = id
  error.value = ''
  try { await loadLatest() } catch (e) { error.value = (e as Error).message }
}

async function run() {
  error.value = ''
  running.value = true
  try {
    await api(`/prep/run?order_id=${orderId.value}`, { method: 'POST' })
    await loadLatest()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    running.value = false
  }
}

onMounted(async () => {
  try {
    tree.value = await api('/bom/tree')
    orders.value = await api<OrderRow[]>('/orders')
    if (orders.value.length) orderId.value = orders.value[0].id
    await loadLatest()
  } catch (e) { error.value = (e as Error).message }
})
</script>
<template>
  <h1>备料工作台</h1>
  <p class="sub">左 BOM 树 · 中热厨册/冷荤册/未分册 · 右缺料便利贴 · 顶栏订单芯片</p>
  <div class="kp-chips" style="margin-bottom:0.75rem" v-if="orders.length">
    <button v-for="o in orders" :key="o.id" type="button" class="kp-chip"
      :style="o.id === orderId ? 'background:var(--kp-accent);color:#1c1208;font-weight:800' : ''"
      @click="selectOrder(o.id)">
      {{ o.code }} · {{ o.outlet }}
    </button>
  </div>
  <div style="display:flex;align-items:center;gap:0.75rem">
    <button class="btn" :disabled="running" @click="run">{{ running ? '生成中…' : '生成备料单' }}</button>
    <span v-if="data?.generated" class="badge badge-ok">已生成备料单 #{{ data.id }}</span>
  </div>
  <ErrorBanner :message="error" @dismiss="error = ''" />
  <div class="kp-workbench" style="margin-top:0.85rem">
    <aside class="kp-bom-tree">
      <h2>菜品 / BOM</h2>
      <div v-for="d in tree" :key="d.code" class="kp-dish-node">
        <strong>{{ d.dish }}</strong>
        <span style="font-size:0.7rem;color:#8a8078">{{ d.code }}</span>
        <ul>
          <li v-for="(c,i) in d.children" :key="i">{{ c.ingredient }} · {{ c.qty }} {{ c.unit }}</li>
        </ul>
      </div>
    </aside>
    <section class="kp-worksheet" v-if="data">
      <h2>备料单 · {{ data.order?.code }} · {{ data.order?.outlet }}</h2>
      <p v-if="!data.generated" class="muted" style="font-size:0.82rem;margin:0 0 0.6rem">
        尚未生成备料单，点击上方「生成备料单」后热厨册、冷荤册与占用一次性同落。
      </p>
      <div class="kp-books">
        <div v-for="key in BOOK_ORDER" :key="key" class="kp-book">
          <h3>{{ data.books[key].name }}</h3>
          <table v-if="data.books[key].lines.length">
            <thead><tr><th>原料</th><th>需求</th><th>单位</th></tr></thead>
            <tbody>
              <tr v-for="l in data.books[key].lines" :key="l.ingredient_id">
                <td>{{ l.ingredient_name }}</td><td>{{ l.qty }}</td><td>{{ l.unit }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="kp-book-empty">本册无出品需求</p>
        </div>
        <div class="kp-book">
          <h3>占用汇总（热厨册 + 冷荤册 + 未分册）</h3>
          <table v-if="data.occupancy.length">
            <thead><tr><th>原料</th><th>占用</th><th>单位</th></tr></thead>
            <tbody>
              <tr v-for="l in data.occupancy" :key="l.ingredient_id">
                <td>{{ l.ingredient_name }}</td><td>{{ l.qty }}</td><td>{{ l.unit }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="kp-book-empty">暂无占用</p>
        </div>
      </div>
    </section>
    <aside class="kp-shortage-sticky">
      <h2>⚠ 缺料便利贴</h2>
      <div v-for="r in shortages" :key="r.ingredient_id" class="kp-shortage-item">
        <span>{{ r.ingredient_name }}</span>
        <span class="kp-qty">−{{ r.shortage }} {{ r.unit }}</span>
      </div>
      <p v-if="!shortages.length" style="font-size:0.8rem;margin:0.5rem 0 0">暂无缺料</p>
    </aside>
  </div>
</template>
