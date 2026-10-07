<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const orders = ref<any[]>([])
const lines = ref<any[]>([])
const data = ref<any>(null)
const loading = ref(false)
const splitError = ref('')
const note = ref('')

async function loadLines(id: number) {
  lines.value = await api('/orders/' + id + '/lines')
  try { data.value = await api('/prep/latest?order_id=' + id) } catch { data.value = null }
}

async function generate(id = 1) {
  loading.value = true; splitError.value = ''; note.value = ''
  try {
    // 与备料台同一接口：同一次标记下，这里生成一次、备料台再生成，只拿到同一套两册
    data.value = await api('/prep/run?order_id=' + id, { method: 'POST' })
    note.value = data.value.reused ? '已存在同标记备料单，返回的是同一套两册。' : '两册与占用已一起落下。'
  } catch (e: any) {
    const msg = String(e?.message || e)
    splitError.value = msg.includes('split_mismatch')
      ? '分册失败：热厨册、冷荤册与占用列对不上，两册与占用已全部退回（非结存不够）。'
      : '生成失败，两册与占用已全部退回：' + msg
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  orders.value = await api('/orders')
  if (orders.value.length) await loadLines(orders.value[0].id)
})
</script>
<template>
  <h1>订单芯片</h1>
  <p class="sub">门店要货 · 顶栏芯片对应订单 · 在此生成与备料台为同一套热厨册 / 冷荤册</p>
  <div class="kp-chips" style="margin-bottom:1rem">
    <span v-for="o in orders" :key="o.id" class="kp-chip">{{ o.code }} · {{ o.outlet }} · {{ o.status }}</span>
  </div>
  <button class="btn" :disabled="loading" @click="generate(orders[0]?.id ?? 1)">
    {{ loading ? '两册一起落单中…' : '生成备料单' }}
  </button>
  <span v-if="data?.generation" class="badge badge-ok" style="margin-left:0.6rem">第 {{ data.generation }} 版 · {{ data.books?.length || 0 }} 册</span>
  <p v-if="note" style="margin:0.5rem 0 0;color:#a8b0b8;font-size:0.8rem">{{ note }}</p>
  <p v-if="splitError" class="badge badge-bad" style="display:block;margin-top:0.6rem;font-size:0.85rem">{{ splitError }}</p>
  <div class="kp-worksheet" style="margin-top:0.85rem">
    <h2>订单行</h2>
    <table>
      <thead><tr><th>菜品</th><th>份数</th></tr></thead>
      <tbody>
        <tr v-for="l in lines" :key="l.id"><td>{{ l.dish_name }}</td><td>{{ l.portions }}</td></tr>
      </tbody>
    </table>
  </div>
</template>
