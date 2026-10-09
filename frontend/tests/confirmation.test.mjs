import { test } from 'node:test';
import assert from 'node:assert/strict';
import { effectScope } from 'vue';
import { useConfirmation } from '../src/composables/useConfirmation.js';

function harness() {
  const scope = effectScope();
  const confirmation = scope.run(() => useConfirmation());
  return { scope, ...confirmation };
}

test('cancelled confirmation resolves false and clears pending state', async () => {
  const ui = harness();
  const result = ui.confirmAction('替换课表', { confirmText: '同步课表' });
  assert.equal(ui.confirmState.value.confirmText, '同步课表');
  ui.handleConfirmResult(false);
  assert.equal(await result, false);
  assert.equal(ui.confirmState.value.open, false);
  ui.scope.stop();
});

test('replaced confirmation releases previous caller and accepts current action', async () => {
  const ui = harness();
  const previous = ui.confirmAction('first');
  const current = ui.confirmAction('second');
  assert.equal(await previous, false);
  ui.handleConfirmResult(true);
  assert.equal(await current, true);
  ui.scope.stop();
});

test('unmount cancels an outstanding confirmation', async () => {
  const ui = harness();
  const result = ui.confirmAction('pending');
  ui.scope.stop();
  assert.equal(await result, false);
});
