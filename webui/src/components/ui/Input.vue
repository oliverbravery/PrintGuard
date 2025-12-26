<script setup lang="ts">
import { computed, useCssModule } from 'vue'

type Size = 'sm' | 'md' | 'lg'

const $style = useCssModule()

const props = withDefaults(defineProps<{
  modelValue: string
  type?: 'text' | 'email' | 'password' | 'number' | 'url' | 'tel'
  placeholder?: string
  disabled?: boolean
  error?: boolean
  size?: Size
  fullWidth?: boolean
  id?: string
  name?: string
  required?: boolean
  autocomplete?: string
}>(), {
  type: 'text',
  disabled: false,
  error: false,
  size: 'md',
  fullWidth: false
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'focus', event: FocusEvent): void
  (e: 'blur', event: FocusEvent): void
  (e: 'keydown', event: KeyboardEvent): void
}>()

const classes = computed(() => [
  $style.input,
  $style[props.size],
  props.fullWidth && $style.fullWidth,
  props.error && $style.error,
  props.disabled && $style.disabled
])

function handleInput(event: Event) {
  const target = event.target as HTMLInputElement
  emit('update:modelValue', target.value)
}

function handleFocus(event: FocusEvent) {
  emit('focus', event)
}

function handleBlur(event: FocusEvent) {
  emit('blur', event)
}

function handleKeydown(event: KeyboardEvent) {
  emit('keydown', event)
}
</script>

<template>
  <input
    :id="id"
    :name="name"
    :type="type"
    :class="classes"
    :value="modelValue"
    :placeholder="placeholder"
    :disabled="disabled"
    :required="required"
    :autocomplete="autocomplete"
    @input="handleInput"
    @focus="handleFocus"
    @blur="handleBlur"
    @keydown="handleKeydown"
  />
</template>

<style module>
.input {
  width: 100%;
  font-family: var(--font-family);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-normal);
  line-height: var(--line-height-normal);
  color: var(--text-primary);
  background-color: var(--bg-primary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: var(--space-3) var(--space-4);
  transition: all var(--transition-fast);
  outline: none;
}

.input::placeholder {
  color: var(--text-tertiary);
}

.input:hover:not(:disabled) {
  border-color: var(--border-strong);
}

.input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-100);
}

/* Sizes */
.sm {
  padding: var(--space-2) var(--space-3);
  font-size: var(--font-size-sm);
}

.md {
  padding: var(--space-3) var(--space-4);
  font-size: var(--font-size-base);
}

.lg {
  padding: var(--space-4) var(--space-5);
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

.disabled {
  background-color: var(--bg-secondary);
  cursor: not-allowed;
  opacity: 0.6;
}
</style>

