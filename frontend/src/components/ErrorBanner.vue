<script setup lang="ts">
defineProps<{ message: string }>()
defineEmits<{ dismiss: [] }>()
</script>
<template>
  <div v-if="message" class="kp-error-banner" role="alert">
    <span>⚠ {{ message }}</span>
    <button type="button" class="kp-error-x" aria-label="关闭" @click="$emit('dismiss')">×</button>
  </div>
</template>
