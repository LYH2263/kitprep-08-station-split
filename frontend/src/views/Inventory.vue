<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
onMounted(async () => { rows.value = await api('/inventory') })
</script>
<template>
  <h1>库存</h1>
  <p class="sub">中央厨房原料库存 · 占用列按热厨册 + 冷荤册 + 未分册加总；结存数字不因生成备料单改变</p>
  <div class="card">
    <table>
      <thead><tr><th>编码</th><th>名称</th><th>结存</th><th>占用（两册加总）</th><th>可用</th><th>单位</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>{{ r.code }}</td><td>{{ r.name }}</td>
          <td>{{ r.stock_qty }}</td>
          <td>{{ r.occupied_qty }}</td>
          <td>{{ r.available_qty }}</td>
          <td>{{ r.unit }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
