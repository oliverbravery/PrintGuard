<script setup lang="ts">
import { computed, useCssModule } from 'vue'

type Variant = 'success' | 'warning' | 'danger' | 'neutral' | 'primary'
type Size = 'sm' | 'md' | 'lg'

const $style = useCssModule()

const props = withDefaults(defineProps<{
  variant?: Variant
  size?: Size
}>(), {
  variant: 'neutral',
  size: 'md'
})

const classes = computed(() => [
  $style.badge,
  $style[props.variant],
  $style[props.size]
])
</script>

<template>
  <span :class="classes">
    <slot />
  </span>
</template>

<style module>
.badge {
  display: inline-flex;
  align-items: center;
  font-family: var(--font-family);
  font-weight: var(--font-weight-semibold);
  border-radius: var(--radius-full);
  white-space: nowrap;
}

.sm {
  padding: var(--space-1) var(--space-2);
  font-size: var(--font-size-xs);
  letter-spacing: var(--letter-spacing-wide);
  text-transform: uppercase;
}

.md {
  padding: var(--space-1) var(--space-3);
  font-size: var(--font-size-sm);
  letter-spacing: var(--letter-spacing-wide);
  text-transform: uppercase;
}

.lg {
  padding: var(--space-2) var(--space-4);
  font-size: var(--font-size-base);
}

/* Variants */
.success {
  background-color: var(--success-bg);
  color: var(--success);
}

.warning {
  background-color: var(--warning-bg);
  color: var(--warning);
}

.danger {
  background-color: var(--danger-bg);
  color: var(--danger);
}

.neutral {
  background-color: var(--bg-tertiary);
  color: var(--text-secondary);
}

.primary {
  background-color: var(--primary-100);
  color: var(--primary-700);
}
</style>

