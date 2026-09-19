<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue';

const props = defineProps({
  duration: { type: Number, default: 0.6 },
  ready: { type: Boolean, default: false },
});

const emit = defineEmits(['finish']);

const leaving = ref(false);
let timer = null;
let elapsed = false;

function dismiss() {
  if (leaving.value) return;
  leaving.value = true;
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  // 等 fade-out 动画结束后再触发 finish
  setTimeout(() => {
    emit('finish');
  }, 380);
}

onMounted(() => {
  timer = setTimeout(() => {
    elapsed = true;
    if (props.ready) dismiss();
  }, props.duration * 1000);
});

function onReadyChange(value) {
  if (value && elapsed) dismiss();
}

onUnmounted(() => {
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
});

watch(() => props.ready, onReadyChange, { immediate: true });
</script>

<template>
  <div
    class="splash-screen"
    :class="{ 'splash-leaving': leaving }"
    role="dialog"
    aria-label="序时 开屏封面"
    @click="dismiss"
  >
    <img class="splash-logo" src="/splash-icon.png" alt="序时" />
  </div>
</template>

<style scoped>
.splash-screen {
  position: fixed;
  inset: 0;
  width: 100vw;
  height: 100vh;
  z-index: 99999;
  overflow: hidden;
  background-color: #F6F5F2;
  display: flex;
  align-items: center;
  justify-content: center;
  user-select: none;
  -webkit-tap-highlight-color: transparent;
}

.splash-logo {
  width: min(52vw, 200px);
  display: block;
}
</style>
