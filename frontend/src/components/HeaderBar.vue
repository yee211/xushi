<script setup>
defineProps({
  user: { type: Object, default: null },
  schedule: { type: Object, default: null },
  bgMode: { type: String, default: 'transparent' },
  appVersion: { type: String, default: '2.2.8' },
  isNative: { type: Boolean, default: false },
});
</script>

<template>
  <header class="top glass minimal-header">
    <div class="brand"><span class="brand-dot"></span><strong>序时</strong></div>
  </header>
</template>

