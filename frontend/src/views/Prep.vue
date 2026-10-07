<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const tree = ref<any[]>([])
const data = ref<any>(null)
const shortages = ref<any[]>([])
const orders = ref<any[]>([])
const loading = ref(false)
const splitError = ref('')
const note = ref('')

function occMap() {
  const m: Record<number, any> = {}
  for (const r of (data.value?.occupancy || [])) m[r.ingredient_id] = r
  return m
}

async function loadShortages() {
  try {
    const res = await api('/prep/shortages?order_id=1')
    shortages.value = res.shortages || []
  } catch { shortages.value = [] }
}

async function run() {
  loading.value = true; splitError.value = ''; note.value = ''
  try {
    // 一次提交：热厨册、冷荤册与占用列同成同败；同标记重复生成返回同一套两册
    data.value = await api('/prep/run?order_id=1', { method: 'POST' })
    note.value = data.value.reused ? '与既有备料单为同一套两册（未重复落单）' : ''
    await loadShortages()
  } catch (e: any) {
    let msg = String(e?.message || e)
    // 分册失败：两册与占用全部退回，绝不能显示成“结存不够”
    if (msg.includes('split_mismatch')) splitError.value = '分册失败：热厨册、冷荤册与占用列对不上，两册与占用已全部退回。'
    else splitError.value = '生成失败，两册与占用已全部退回：' + msg
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  tree.value = await api('/bom/tree')
  orders.value = await api('/orders')
  try {
    data.value = await api('/prep/latest?order_id=1')
    await loadShortages()
  } catch { data.value = null }
})
</script>
<template>
  <h1>备料工作台</h1>
  <p class="sub">左 BOM 树 · 中热厨册 / 冷荤册（未标记出品进同一册）· 右缺料便利贴 · 占用列按两册加总</p>
  <div class="kp-chips" style="margin-bottom:0.75rem" v-if="orders.length">
    <span v-for="o in orders" :key="o.id" class="kp-chip" style="cursor:default">
      {{ o.code }} · {{ o.outlet }}
    </span>
  </div>
  <button class="btn" :disabled="loading" @click="run">
    {{ loading ? '两册一起落单中…' : '生成备料单（两册一起落）' }}
  </button>
  <span v-if="data?.generation" class="badge badge-ok" style="margin-left:0.6rem">第 {{ data.generation }} 版</span>
  <span v-if="note" style="margin-left:0.6rem;color:#a8b0b8;font-size:0.78rem">{{ note }}</span>
  <p v-if="splitError" class="badge badge-bad" style="display:block;margin-top:0.6rem;font-size:0.85rem">{{ splitError }}</p>
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
      <h2>
        备料单 · {{ data.order?.code }} · {{ data.order?.outlet }}
        <span class="muted" style="font-size:0.72rem">占用 = 各册加总</span>
      </h2>
      <p v-if="!data.books?.length" class="muted" style="font-size:0.8rem">尚未生成备料单。</p>
      <div v-for="b in data.books" :key="b.book" class="kp-book">
        <h3 class="kp-book-title" :class="'kp-book-' + b.book">{{ b.label }}</h3>
        <table>
          <thead><tr><th>原料</th><th>本册需求</th><th>占用合计</th><th>单位</th></tr></thead>
          <tbody>
            <tr v-for="l in b.lines" :key="b.book + '-' + l.ingredient_id">
              <td>{{ l.ingredient_name }}</td>
              <td>{{ l.need_qty }}</td>
              <td>{{ occMap()[l.ingredient_id]?.qty ?? '—' }}</td>
              <td>{{ l.unit }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="muted" style="font-size:0.74rem;margin:0.6rem 0 0">
        占用合计列：热厨册 + 冷荤册 + 未分册，逐原料加总。
      </p>
    </section>
    <aside class="kp-shortage-sticky">
      <h2>⚠ 缺料便利贴</h2>
      <div v-for="r in shortages" :key="r.ingredient_id" class="kp-shortage-item">
        <span>{{ r.ingredient_name }}</span>
        <span class="kp-qty">−{{ r.shortage }} {{ r.unit }}</span>
      </div>
      <p v-if="!shortages.length" style="font-size:0.8rem;margin:0.5rem 0 0">暂无缺料</p>
      <p style="font-size:0.68rem;margin:0.45rem 0 0;color:#7a6a30">缺料仅供参考，不等于分册失败。</p>
    </aside>
  </div>
</template>
