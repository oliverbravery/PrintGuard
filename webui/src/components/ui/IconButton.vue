<script setup lang="ts">
import { computed, useCssModule } from 'vue'

type Variant = 'default' | 'primary' | 'danger' | 'ghost'
type Size = 'sm' | 'md' | 'lg'

const $style = useCssModule()

const props = withDefaults(defineProps<{
  variant?: Variant
  size?: Size
  disabled?: boolean
  loading?: boolean
  title?: string
}>(), {
  variant: 'default',
  size: 'md',
  disabled: false,
  loading: false
})

const emit = defineEmits<{
  (e: 'click', event: MouseEvent): void
}>()

const classes = computed(() => [
  $style.iconButton,
  $style[props.variant],
  $style[props.size],
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
    :class="classes"
    :disabled="disabled || loading"
    :title="title"
    @click="handleClick"
  >
    <span v-if="loading" :class="$style.spinner"></span>
    <slot v-else />
  </button>
</template>

<style module>
.iconButton {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-family);
  border-radius: var(--radius-lg);
  border: 1px solid transparent;
  cursor: pointer;
  transition: all var(--transition-fast);
  color: var(--text-primary);
}

.iconButton:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.sm {
  width: 2rem;
  height: 2rem;
}

.sm :deep(svg) {
  width: 14px;
  height: 14px;
}

.md {
  width: 2.25rem;
  height: 2.25rem;
}

.md :deep(svg) {
  width: 16px;
  height: 16px;
}

.lg {
  width: 2.5rem;
  height: 2.5rem;
}

.lg :deep(svg) {
  width: 18px;
  height: 18px;
}

.default {
  background-color: var(--bg-secondary);
  border-color: var(--border-default);
}

.default:hover:not(:disabled) {
  background-color: var(--bg-tertiary);
  border-color: var(--border-strong);
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

.danger {
  background-color: var(--danger-bg);
  color: var(--danger);
  border-color: var(--danger);
}

.danger:hover:not(:disabled) {
  background-color: var(--danger);
  color: var(--text-inverse);
}

.ghost {
  background-color: transparent;
  border-color: transparent;
}

.ghost:hover:not(:disabled) {
  background-color: var(--bg-secondary);
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

