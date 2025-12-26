<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, useCssModule } from 'vue'
import { ChevronDown, Check } from 'lucide-vue-next'

const $style = useCssModule()

const props = withDefaults(defineProps<{
  modelValue: string[]
  options: Array<{ value: string; label: string }>
  placeholder?: string
  disabled?: boolean
  error?: boolean
  fullWidth?: boolean
}>(), {
  disabled: false,
  error: false,
  fullWidth: false
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
}>()

const isOpen = ref(false)
const dropdownRef = ref<HTMLElement | null>(null)

const toggleDropdown = () => {
  if (props.disabled) return
  isOpen.value = !isOpen.value
}

const toggleOption = (value: string) => {
  const newValue = [...props.modelValue]
  const index = newValue.indexOf(value)
  if (index > -1) {
    newValue.splice(index, 1)
  } else {
    newValue.push(value)
  }
  emit('update:modelValue', newValue)
}

const handleClickOutside = (event: MouseEvent) => {
  if (dropdownRef.value && !dropdownRef.value.contains(event.target as Node)) {
    isOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('mousedown', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('mousedown', handleClickOutside)
})

const displayText = computed(() => {
  if (props.modelValue.length === 0) return props.placeholder || 'Select options...'
  if (props.modelValue.length === 1) {
    return props.options.find(o => o.value === props.modelValue[0])?.label || props.modelValue[0]
  }
  return `${props.modelValue.length} selected`
})
</script>

<template>
  <div :class="[$style.wrapper, fullWidth && $style.fullWidth]" ref="dropdownRef">
    <div 
      :class="[
        $style.selector, 
        isOpen && $style.active, 
        error && $style.error, 
        disabled && $style.disabled
      ]"
      @click="toggleDropdown"
    >
      <span :class="[$style.text, modelValue.length === 0 && $style.placeholder]">
        {{ displayText }}
      </span>
      <ChevronDown :class="[$style.icon, isOpen && $style.rotated]" />
    </div>

    <div v-if="isOpen" :class="$style.dropdown">
      <div 
        v-for="option in options" 
        :key="option.value"
        :class="[$style.option, modelValue.includes(option.value) && $style.selected]"
        @click="toggleOption(option.value)"
      >
        <div :class="$style.checkbox">
          <Check v-if="modelValue.includes(option.value)" :size="14" />
        </div>
        <span :class="$style.label">{{ option.label }}</span>
      </div>
    </div>
  </div>
</template>

<style module>
.wrapper {
  position: relative;
  display: inline-flex;
}

.wrapper.fullWidth {
  width: 100%;
}

.selector {
  width: 100%;
  min-height: 42px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-4);
  background-color: var(--bg-primary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all var(--transition-fast);
  user-select: none;
}

.selector:hover:not(.disabled) {
  border-color: var(--border-strong);
}

.selector.active {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-100);
}

.selector.disabled {
  background-color: var(--bg-secondary);
  cursor: not-allowed;
  opacity: 0.6;
}

.selector.error {
  border-color: var(--danger);
}

.text {
  font-size: var(--font-size-base);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-right: var(--space-2);
}

.placeholder {
  color: var(--text-tertiary);
}

.icon {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  color: var(--text-tertiary);
  transition: transform var(--transition-base);
}

.icon.rotated {
  transform: rotate(180deg);
}

.dropdown {
  position: absolute;
  top: calc(100% + var(--space-1));
  left: 0;
  width: 100%;
  max-height: 250px;
  overflow-y: auto;
  background-color: var(--card-bg);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  z-index: var(--z-dropdown);
  padding: var(--space-1);
}

.option {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background-color var(--transition-fast);
}

.option:hover {
  background-color: var(--bg-secondary);
}

.option.selected {
  background-color: var(--primary-50);
}

.option.selected .label {
  color: var(--primary);
  font-weight: var(--font-weight-medium);
}

.checkbox {
  width: 18px;
  height: 18px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--bg-primary);
  color: var(--primary);
}

.selected .checkbox {
  background-color: var(--primary);
  border-color: var(--primary);
  color: white;
}

.label {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}
</style>

