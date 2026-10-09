import { onBeforeUnmount, onMounted } from 'vue'

/**
 * 统一的 Esc 关闭行为。
 *
 * 右侧抽屉与弹层都应支持按 Esc 关闭，与 Ant Design Pro / Linear 的键盘约定一致；
 * 回调里按"最上层先关"的顺序处理多个浮层。
 *
 * @param close 关闭回调
 */
export function useEscapeClose(close: () => void) {
  function onKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') close()
  }
  onMounted(() => window.addEventListener('keydown', onKeydown))
  onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
}
