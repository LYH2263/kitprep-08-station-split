<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const savingId = ref<number | null>(null)
const savedId = ref<number | null>(null)
const error = ref('')

const STATION_OPTIONS = [
  { value: 'none', label: '未标记' },
  { value: 'hot', label: '热厨' },
  { value: 'cold', label: '冷荤' },
]

async function load() { rows.value = await api('/dishes') }

async function saveStation(r: any) {
  savingId.value = r.id; error.value = ''; savedId.value = null
  try {
    const updated = await api('/dishes/' + r.id, {
      method: 'PATCH', body: JSON.stringify({ station: r.station }),
    })
    r.station = updated.station
    savedId.value = r.id
  } catch (e: any) {
    error.value = '工位标记保存失败：' + (e?.message || e)
  } finally {
    savingId.value = null
  }
}

onMounted(load)
</script>
<template>
  <h1>出品</h1>
  <p class="sub">中央厨房出品 · 标记热厨 / 冷荤工位（保存后，下次生成备料单两册一起按新标记重生）</p>
  <div class="card">
    <table>
      <thead><tr><th>编码</th><th>名称</th><th>单位</th><th>工位标记</th><th></th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>{{ r.code }}</td><td>{{ r.name }}</td><td>{{ r.portion_unit }}</td>
          <td>
            <select v-model="r.station" :disabled="savingId === r.id">
              <option v-for="o in STATION_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
          </td>
          <td>
            <button class="btn" :disabled="savingId === r.id" @click="saveStation(r)">
              {{ savingId === r.id ? '保存中…' : '保存标记' }}
            </button>
            <span v-if="savedId === r.id" class="badge badge-ok" style="margin-left:0.5rem">已保存</span>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="error" class="badge badge-bad" style="margin-top:0.6rem">{{ error }}</p>
  </div>
</template>
