<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, useCssModule } from 'vue'
import { useComponentsStore } from '../../store/components'
import HealthBadge from './HealthBadge.vue'
import CameraFeed from './CameraFeed.vue'
import Badge from '../ui/Badge.vue'
import { ChevronDown, PlusCircle } from 'lucide-vue-next'
import type { Component } from '../../types'

const $style = useCssModule()

const props = defineProps<{
  type: 'camera' | 'control' | 'status'
  modelValue: string | null
  required?: boolean
  showAddNew?: boolean
  placeholder?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string | null): void
  (e: 'add-new'): void
}>()

const store = useComponentsStore()
const isOpen = ref(false)
const activeFilter = ref('All')
const dropdownRef = ref<HTMLElement | null>(null)

const providers = computed(() => {
  const p = new Set(store.components.filter(c => c.type === props.type).map(c => c.provider))
  return ['All', ...Array.from(p)]
})

const filteredComponents = computed(() => {
  let list = store.components.filter(c => c.type === props.type)
  if (activeFilter.value !== 'All') {
    list = list.filter(c => c.provider === activeFilter.value)
  }
  return list
})

const selectedComponent = computed(() => 
  store.components.find(c => c.id === props.modelValue) || null
)

function toggleDropdown() {
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    store.fetchAll({ type: props.type }, true)
  }
}

function selectComponent(comp: Component) {
  emit('update:modelValue', comp.id)
  isOpen.value = false
}

function handleClickOutside(event: MouseEvent) {
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
</script>

<template>
  <div :class="$style.wrapper" ref="dropdownRef">
    <!-- Camera Feed Preview Above -->
    <div v-if="type === 'camera'" :class="$style.feedPreview">
      <CameraFeed :component="selectedComponent" />
    </div>

    <div 
      :class="[$style.selector, { [$style.active]: isOpen, [$style.error]: required && !modelValue }]" 
      @click="toggleDropdown"
    >
      <div v-if="selectedComponent" :class="$style.selected">
        <span :class="$style.name">{{ selectedComponent.name }}</span>
        <Badge variant="neutral" size="sm">{{ selectedComponent.provider }}</Badge>
      </div>
      <div v-else :class="$style.placeholder">
        {{ placeholder || `Select a ${type}...` }}
      </div>
      <ChevronDown :class="[$style.arrow, { [$style.rotated]: isOpen }]" />
    </div>

    <div v-if="isOpen" :class="$style.dropdown">
      <div :class="$style.filters">
        <button 
          v-for="p in providers" 
          :key="p"
          :class="[$style.filterChip, { [$style.filterActive]: activeFilter === p }]"
          @click.stop="activeFilter = p"
        >
          {{ p }}
        </button>
      </div>

      <div :class="$style.options">
        <div 
          v-for="comp in filteredComponents" 
          :key="comp.id"
          :class="[$style.option, { [$style.optionSelected]: modelValue === comp.id }]"
          @click="selectComponent(comp)"
        >
          <div :class="$style.optionInfo">
            <span :class="$style.optionName">{{ comp.name }}</span>
            <div :class="$style.optionMeta">
              <Badge variant="neutral" size="sm">{{ comp.provider }}</Badge>
              <span v-if="comp.connection" :class="$style.connectionName">{{ comp.connection.name }}</span>
            </div>
          </div>
          <HealthBadge status="healthy" /> <!-- Mock status -->
        </div>
        
        <div v-if="filteredComponents.length === 0" :class="$style.empty">
          {{ store.loading ? 'Fetching ' + type + 's...' : 'No ' + type + 's found.' }}
        </div>
      </div>

      <button 
        v-if="showAddNew !== false" 
        :class="$style.addNew" 
        @click.stop="emit('add-new')"
      >
        <PlusCircle :size="18" />
        Add New {{ type.charAt(0).toUpperCase() + type.slice(1) }}...
      </button>
    </div>
  </div>
</template>

<style module>
.wrapper {
  position: relative;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.feedPreview {
  width: 100%;
  animation: slideDown var(--transition-base);
}

.selector {
  background-color: var(--bg-primary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: var(--space-3) var(--space-4);
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.selector:hover {
  border-color: var(--border-strong);
}

.selector.active {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-100);
}

.selector.error {
  border-color: var(--danger);
}

.selected {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.name {
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
}

.placeholder {
  color: var(--text-tertiary);
}

.arrow {
  width: 16px;
  height: 16px;
  color: var(--text-tertiary);
  transition: transform var(--transition-base);
}

.arrow.rotated {
  transform: rotate(180deg);
}

.dropdown {
  position: absolute;
  top: calc(100% + var(--space-2));
  left: 0;
  width: 100%;
  background-color: var(--card-bg);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-xl);
  z-index: var(--z-dropdown);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: fadeIn var(--transition-fast);
}

.filters {
  padding: var(--space-3);
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  border-bottom: 1px solid var(--border-subtle);
  background-color: var(--bg-secondary);
}

.filterChip {
  font-size: var(--font-size-xs);
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-full);
  background-color: var(--bg-primary);
  color: var(--text-secondary);
  border: 1px solid var(--border-default);
  transition: all var(--transition-fast);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
}

.filterChip:hover {
  background-color: var(--bg-tertiary);
  border-color: var(--border-strong);
}

.filterActive {
  background-color: var(--primary);
  color: var(--primary-on);
  border-color: var(--primary);
}

.options {
  max-height: 300px;
  overflow-y: auto;
}

.option {
  padding: var(--space-3) var(--space-4);
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  transition: background-color var(--transition-fast);
}

.option:hover {
  background-color: var(--bg-secondary);
}

.optionSelected {
  background-color: var(--primary-50);
  border-left: 3px solid var(--primary);
}

.optionInfo {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.optionName {
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
}

.optionMeta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.connectionName {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}

.empty {
  padding: var(--space-8);
  text-align: center;
  color: var(--text-tertiary);
  font-size: var(--font-size-sm);
}

.addNew {
  padding: var(--space-4);
  width: 100%;
  text-align: left;
  border: none;
  border-top: 1px solid var(--border-subtle);
  background: none;
  color: var(--primary);
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-sm);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  transition: background-color var(--transition-fast);
  cursor: pointer;
}

.addNew:hover {
  background-color: var(--primary-50);
}

.previewPanel {
  padding: var(--space-4);
  background-color: var(--bg-secondary);
  border-top: 1px solid var(--border-subtle);
}

.previewHeader {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-bold);
  color: var(--text-tertiary);
  margin-bottom: var(--space-2);
  text-transform: uppercase;
  letter-spacing: var(--letter-spacing-wide);
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>

