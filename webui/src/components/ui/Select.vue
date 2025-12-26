<script setup lang="ts">
import { computed, useCssModule } from 'vue'
import { ChevronDown } from 'lucide-vue-next'

type Size = 'sm' | 'md' | 'lg'

const $style = useCssModule()

const props = withDefaults(defineProps<{
  modelValue: string | number
  options: Array<{ value: string | number; label: string }>
  placeholder?: string
  disabled?: boolean
  error?: boolean
  size?: Size
  fullWidth?: boolean
  id?: string
  name?: string
  required?: boolean
}>(), {
  disabled: false,
  error: false,
  size: 'md',
  fullWidth: false
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string | number): void
  (e: 'change', value: string | number): void
}>()

const classes = computed(() => [
  $style.select,
  $style[props.size],
  props.fullWidth && $style.fullWidth,
  props.error && $style.error,
  props.disabled && $style.disabled
])

function handleChange(event: Event) {
  const target = event.target as HTMLSelectElement
  const value = target.value
  emit('update:modelValue', value)
  emit('change', value)
}
</script>

<template>
  <div :class="[$style.wrapper, fullWidth && $style.fullWidth]">
    <select
      :id="id"
      :name="name"
      :class="classes"
      :value="modelValue"
      :disabled="disabled"
      :required="required"
      @change="handleChange"
    >
      <option v-if="placeholder" value="" disabled selected>{{ placeholder }}</option>
      <option
        v-for="option in options"
        :key="option.value"
        :value="option.value"
      >
        {{ option.label }}
      </option>
    </select>
    <ChevronDown :class="$style.icon" />
  </div>
</template>

<style module>
.wrapper {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.wrapper.fullWidth {
  width: 100%;
}

.select {
  width: 100%;
  font-family: var(--font-family);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-normal);
  line-height: var(--line-height-normal);
  color: var(--text-primary);
  background-color: var(--bg-primary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: var(--space-3) var(--space-10) var(--space-3) var(--space-4);
  transition: all var(--transition-fast);
  outline: none;
  appearance: none;
  cursor: pointer;
}

.select:hover:not(:disabled) {
  border-color: var(--border-strong);
}

.select:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-100);
}

.select:disabled {
  background-color: var(--bg-secondary);
  cursor: not-allowed;
  opacity: 0.6;
}

.sm {
  padding: var(--space-2) var(--space-8) var(--space-2) var(--space-3);
  font-size: var(--font-size-sm);
}

.md {
  padding: var(--space-3) var(--space-10) var(--space-3) var(--space-4);
  font-size: var(--font-size-base);
}

.lg {
  padding: var(--space-4) var(--space-12) var(--space-4) var(--space-5);
  font-size: var(--font-size-lg);
}

.fullWidth {
  width: 100%;
}

.error {
  border-color: var(--danger);
}

.error:focus {
  box-shadow: 0 0 0 3px var(--danger-100);
}

.icon {
  position: absolute;
  right: var(--space-3);
  pointer-events: none;
  color: var(--text-tertiary);
  transition: color var(--transition-fast);
}

.sm .icon {
  right: var(--space-2);
  width: 14px;
  height: 14px;
}

.md .icon {
  right: var(--space-3);
  width: 16px;
  height: 16px;
}

.lg .icon {
  right: var(--space-4);
  width: 18px;
  height: 18px;
}

.select:focus ~ .icon {
  color: var(--primary);
}
</style>

