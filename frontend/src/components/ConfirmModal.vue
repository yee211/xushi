<script setup>
defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '操作确认' },
  message: { type: String, default: '' },
  confirmText: { type: String, default: '确定' },
  cancelText: { type: String, default: '取消' },
  danger: { type: Boolean, default: false },
});

const emit = defineEmits(['confirm', 'cancel']);
</script>

<template>
  <Transition name="confirm-fade">
    <div
      v-if="open"
      class="backdrop confirm-backdrop"
      @click.self="emit('cancel')"
    >
      <Transition name="confirm-modal" appear>
        <section
          v-if="open"
          class="modal confirm-modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-title"
        >
          <div class="modal-head">
            <div>
              <p>操作提示</p>
              <h2 id="confirm-title">{{ title }}</h2>
            </div>
            <button
              type="button"
              class="icon"
              aria-label="关闭"
              @click="emit('cancel')"
            >×</button>
          </div>

          <div class="confirm-content">
            <p class="confirm-message">{{ message }}</p>
          </div>

          <div class="modal-actions confirm-actions">
            <button
              class="uiverse-button"
              type="button"
              @click="emit('cancel')"
            >
              {{ cancelText }}
            </button>
            <button
              class="uiverse-button"
              :class="danger ? 'danger' : 'primary'"
              type="button"
              @click="emit('confirm')"
            >
              {{ confirmText }}
            </button>
          </div>
        </section>
      </Transition>
    </div>
  </Transition>
</template>

<style scoped>
/* Backdrop fade */
.confirm-fade-enter-active,
.confirm-fade-leave-active {
  transition: opacity 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}
.confirm-fade-enter-from,
.confirm-fade-leave-to {
  opacity: 0;
}

/* Modal slide-up spring */
.confirm-modal-enter-active {
  transition: opacity 0.32s cubic-bezier(0.16, 1, 0.3, 1),
              transform 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.confirm-modal-leave-active {
  transition: opacity 0.2s ease,
              transform 0.2s ease;
}
.confirm-modal-enter-from {
  opacity: 0;
  transform: translateY(28px) scale(0.94);
}
.confirm-modal-leave-to {
  opacity: 0;
  transform: translateY(12px) scale(0.96);
}
</style>
