import { onScopeDispose, ref } from 'vue';

export function useConfirmation() {
  // 通用确认模态弹窗状态（替代原生 window.confirm 浏览器弹窗）
  const confirmState = ref({
    open: false,
    title: '操作确认',
    message: '',
    confirmText: '确定',
    cancelText: '取消',
    danger: true,
    resolve: null,
  });

  function confirmAction(message, options = {}) {
    handleConfirmResult(false);
    return new Promise(resolve => {
      confirmState.value = {
        open: true,
        title: options.title || '操作确认',
        message,
        confirmText: options.confirmText || '确定',
        cancelText: options.cancelText || '取消',
        danger: options.danger ?? true,
        resolve,
      };
    });
  }

  function handleConfirmResult(result) {
    if (confirmState.value.resolve) {
      confirmState.value.resolve(result);
    }
    confirmState.value.open = false;
    confirmState.value.resolve = null;
  }

  onScopeDispose(() => handleConfirmResult(false));

  return { confirmState, confirmAction, handleConfirmResult };
}
