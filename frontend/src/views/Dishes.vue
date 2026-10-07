<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import type { DishRow, Station } from '../types'
import ErrorBanner from '../components/ErrorBanner.vue'

const rows = ref<DishRow[]>([])
const draft = ref<Record<number, string>>({})
const savedId = ref<number | null>(null)
const savingId = ref<number | null>(null)
const error = ref('')

onMounted(async () => {
  try {
    rows.value = await api<DishRow[]>('/dishes')
    for (const r of rows.value) draft.value[r.id] = r.station ?? ''
  } catch (e) { error.value = (e as Error).message }
})

async function save(r: DishRow) {
  error.value = ''
  savingId.value = r.id
  const station: Station = (draft.value[r.id] || null) as Station
  try {
    const updated = await api<DishRow>(`/dishes/${r.id}`, {
      method: 'PATCH', body: JSON.stringify({ station }),
    })
    r.station = updated.station
    draft.value[r.id] = updated.station ?? ''
    savedId.value = r.id
    window.setTimeout(() => { if (savedId.value === r.id) savedId.value = null }, 2000)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    savingId.value = null
  }
}
</script>
<template>
  <h1>菜品</h1>
  <p class="sub">中央厨房出品菜品 · 标记热厨 / 冷荤工位后保存</p>
  <ErrorBanner :message="error" @dismiss="error = ''" />
  <div class="card">
    <table>
      <thead><tr><th>编码</th><th>名称</th><th>单位</th><th>工位</th><th></th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>{{ r.code }}</td><td>{{ r.name }}</td><td>{{ r.portion_unit }}</td>
          <td>
            <select v-model="draft[r.id]" class="kp-station-select">
              <option value="">未分册</option>
              <option value="hot">热厨</option>
              <option value="cold">冷荤</option>
            </select>
            <span v-if="savedId === r.id" class="kp-saved-ok">已保存</span>
          </td>
          <td>
            <button class="btn" :disabled="savingId === r.id" @click="save(r)">
              {{ savingId === r.id ? '保存中…' : '保存' }}
            </button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
