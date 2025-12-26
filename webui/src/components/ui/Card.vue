<script setup lang="ts">
import { computed, useCssModule } from 'vue'

const $style = useCssModule()

const props = withDefaults(defineProps<{
  padding?: 'none' | 'sm' | 'md' | 'lg'
  hoverable?: boolean
  bordered?: boolean
}>(), {
  padding: 'md',
  hoverable: false,
  bordered: false
})

const classes = computed(() => [
  $style.card,
  $style[props.padding],
  props.hoverable && $style.hoverable,
  props.bordered && $style.bordered
])
</script>

<template>
  <div :class="classes">
    <slot />
  </div>
</template>

<style module>
.card {
  background-color: var(--card-bg);
  border-radius: var(--radius-xl);
  transition: all var(--transition-base);
}

.none {
  padding: 0;
}

.sm {
  padding: var(--space-3);
}

.md {
  padding: var(--space-4);
}

.lg {
  padding: var(--space-6);
}

.hoverable {
  cursor: pointer;
}

.hoverable:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
}

.bordered {
  border: 1px solid var(--border-subtle);
}
</style>

