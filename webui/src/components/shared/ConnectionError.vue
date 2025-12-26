<script setup lang="ts">
defineProps<{
  title?: string
  message?: string
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'retry'): void
}>()
</script>

<template>
  <div :class="$style.error">
    <div :class="$style.icon">⚠️</div>
    <h2>{{ title || 'Connection Failed' }}</h2>
    <p>{{ message || 'Unable to reach the server. Please check your connection and try again.' }}</p>
    
    <button 
      :class="$style.retryBtn" 
      @click="emit('retry')" 
      :disabled="loading"
    >
      <div v-if="loading" :class="$style.spinner"></div>
      {{ loading ? 'Retrying...' : 'Retry Connection' }}
    </button>
  </div>
</template>

<style module>
.error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4rem 2rem;
  text-align: center;
  background-color: var(--card-bg);
  border-radius: 1rem;
  border: 1px solid var(--border);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  max-width: 500px;
  margin: 2rem auto;
}

.icon {
  font-size: 3rem;
  margin-bottom: 1rem;
}

.error h2 {
  font-size: 1.5rem;
  margin-bottom: 0.5rem;
  color: var(--text);
}

.error p {
  color: var(--text-muted);
  margin-bottom: 2rem;
  line-height: 1.5;
}

.retryBtn {
  background-color: var(--primary);
  color: white;
  padding: 0.75rem 2rem;
  border-radius: 0.5rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  transition: all 0.2s;
}

.retryBtn:hover:not(:disabled) {
  background-color: var(--primary-hover);
  transform: translateY(-1px);
}

.retryBtn:active:not(:disabled) {
  transform: translateY(0);
}

.retryBtn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.spinner {
  width: 1.25rem;
  height: 1.25rem;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
</style>

