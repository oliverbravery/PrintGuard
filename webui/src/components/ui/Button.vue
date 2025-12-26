<script setup lang="ts">
import { computed, useCssModule } from 'vue'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md' | 'lg'

const $style = useCssModule()

const props = withDefaults(defineProps<{
  variant?: Variant
  size?: Size
  disabled?: boolean
  loading?: boolean
  fullWidth?: boolean
  type?: 'button' | 'submit' | 'reset'
}>(), {
  variant: 'primary',
  size: 'md',
  disabled: false,
  loading: false,
  fullWidth: false,
  type: 'button'
})

const emit = defineEmits<{
  (e: 'click', event: MouseEvent): void
}>()

const classes = computed(() => [
  $style.button,
  $style[props.variant],
  $style[props.size],
  props.fullWidth && $style.fullWidth,
  props.disabled && $style.disabled,
  props.loading && $style.loading
])

function handleClick(event: MouseEvent) {
  if (!props.disabled && !props.loading) {
    emit('click', event)
  }
}
</script>

<template>
  <button
    :type="type"
    :class="classes"
    :disabled="disabled || loading"
    @click="handleClick"
  >
    <span v-if="loading" :class="$style.spinner"></span>
    <slot />
  </button>
</template>

<style module>
.button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  font-family: var(--font-family);
  font-weight: var(--font-weight-semibold);
  border-radius: var(--radius-lg);
  border: 1px solid transparent;
  cursor: pointer;
  transition: all var(--transition-fast);
  white-space: nowrap;
}

.button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.sm {
  padding: var(--space-2) var(--space-3);
  font-size: var(--font-size-sm);
}

.md {
  padding: var(--space-3) var(--space-4);
  font-size: var(--font-size-base);
}

.lg {
  padding: var(--space-4) var(--space-6);
  font-size: var(--font-size-lg);
}

.primary {
  background-color: var(--primary);
  color: var(--primary-on);
  border-color: var(--primary);
}

.primary:hover:not(:disabled) {
  background-color: var(--primary-hover);
  border-color: var(--primary-hover);
}

.primary:active:not(:disabled) {
  background-color: var(--primary-active);
  border-color: var(--primary-active);
}

.secondary {
  background-color: var(--bg-secondary);
  color: var(--text-primary);
  border-color: var(--border-default);
}

.secondary:hover:not(:disabled) {
  background-color: var(--bg-tertiary);
  border-color: var(--border-strong);
}

.ghost {
  background-color: transparent;
  color: var(--text-primary);
  border-color: transparent;
}

.ghost:hover:not(:disabled) {
  background-color: var(--bg-secondary);
}

.danger {
  background-color: var(--danger);
  color: var(--text-inverse);
  border-color: var(--danger);
}

.danger:hover:not(:disabled) {
  background-color: var(--danger-700);
  border-color: var(--danger-700);
}

.fullWidth {
  width: 100%;
}

.loading {
  pointer-events: none;
}

.spinner {
  width: 1em;
  height: 1em;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>

