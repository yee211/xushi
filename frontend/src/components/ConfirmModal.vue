<script setup>
import { nextTick, onBeforeUnmount, ref, useId, watch } from 'vue';

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '操作确认' },
  message: { type: String, default: '' },
  confirmText: { type: String, default: '确定' },
  cancelText: { type: String, default: '取消' },
  danger: { type: Boolean, default: false },
});

const emit = defineEmits(['confirm', 'cancel']);
const dialog = ref(null);
const cancelButton = ref(null);
const titleId = useId();
const messageId = useId();
let previousFocus;

function onKeydown(event) {
  if (!props.open) return;
  if (event.key === 'Escape') {
    event.preventDefault();
    event.stopImmediatePropagation();
    emit('cancel');
  } else if (event.key === 'Tab') {
    const buttons = [...(dialog.value?.querySelectorAll('button:not([disabled])') || [])];
    const index = buttons.indexOf(document.activeElement);
    if (buttons.length && (index < 0 || (!event.shiftKey && index === buttons.length - 1) || (event.shiftKey && index === 0))) {
      event.preventDefault();
      buttons[event.shiftKey ? buttons.length - 1 : 0].focus();
    }
  }
}
function cleanup() {
  document.removeEventListener('keydown', onKeydown, true);
  if (previousFocus?.isConnected) previousFocus.focus();
  previousFocus = null;
}
watch(() => props.open, async open => {
  if (!open) { cleanup(); return; }
  previousFocus = document.activeElement;
  document.addEventListener('keydown', onKeydown, true);
  await nextTick();
  if (props.open) cancelButton.value?.focus();
}, { immediate: true });
onBeforeUnmount(cleanup);
</script>

<template>
  <Teleport to="body">
  <Transition name="confirm-fade">
    <div
      v-if="open"
      class="backdrop confirm-backdrop"
      @click.self="emit('cancel')"
    >
      <Transition name="confirm-modal" appear>
        <section
          v-if="open"
          ref="dialog"
          class="modal confirm-modal"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="titleId"
          :aria-describedby="messageId"
        >
          <div class="modal-head">
            <div>
              <p>操作提示</p>
              <h2 :id="titleId">{{ title }}</h2>
            </div>
            <button
              type="button"
              class="icon"
              aria-label="关闭"
              @click="emit('cancel')"
            >×</button>
          </div>

          <div class="confirm-content">
            <p :id="messageId" class="confirm-message">{{ message }}</p>
          </div>

          <div class="modal-actions confirm-actions">
            <button
              ref="cancelButton"
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
  </Teleport>
</template>

<style scoped>
.confirm-backdrop { position: fixed; inset: 0; z-index: 2000 !important; }
.confirm-modal { width: min(420px, calc(100vw - 32px)); max-height: calc(100dvh - 32px); overflow-y: auto; }
.confirm-message { white-space: pre-line; line-height: 1.7; overflow-wrap: anywhere; }
.confirm-actions button { min-height: 44px; }
.confirm-actions button:focus-visible { outline: 3px solid #6b9ce6; outline-offset: 3px; }

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
