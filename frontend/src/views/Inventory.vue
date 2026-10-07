<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import type { InventoryRow } from '../types'
import ErrorBanner from '../components/ErrorBanner.vue'

const rows = ref<InventoryRow[]>([])
const error = ref('')
onMounted(async () => {
  try { rows.value = await api<InventoryRow[]>('/inventory') }
  catch (e) { error.value = (e as Error).message }
})
</script>
<template>
  <h1>库存</h1>
  <p class="sub">中央厨房原料库存 · 结存不随备料扣减，占用为各订单最新备料单加总</p>
  <ErrorBanner :message="error" @dismiss="error = ''" />
  <div class="card">
    <table>
      <thead><tr><th>编码</th><th>名称</th><th>结存</th><th>占用</th><th>可用</th><th>单位</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>{{ r.code }}</td><td>{{ r.name }}</td>
          <td>{{ r.stock_qty }}</td><td>{{ r.occupied_qty }}</td>
          <td>
            {{ r.available_qty }}
            <span v-if="r.available_qty < 0" class="badge badge-bad">缺料</span>
          </td>
          <td>{{ r.unit }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
