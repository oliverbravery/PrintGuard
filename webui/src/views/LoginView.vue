<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../store/auth'
import Button from '../components/ui/Button.vue'
import Input from '../components/ui/Input.vue'

const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref<string | null>(null)

async function handleLogin() {
  loading.value = true
  error.value = null
  try {
    await auth.login(username.value, password.value)
    router.push('/')
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Invalid username or password'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div :class="$style.container">
    <div :class="$style.card">
      <div :class="$style.header">
        <h1>PrintGuard</h1>
        <p>Sign in to manage your printers</p>
      </div>

      <form @submit.prevent="handleLogin" class="base-form">
        <div class="form-field">
          <label for="username">Username</label>
          <Input
            id="username"
            v-model="username"
            type="text"
            required
            placeholder="Enter username"
            :error="!!error"
          />
        </div>

        <div class="form-field">
          <label for="password">Password</label>
          <Input
            id="password"
            v-model="password"
            type="password"
            required
            placeholder="Enter password"
            :error="!!error"
          />
        </div>

        <div v-if="error" class="form-error">{{ error }}</div>

        <Button
          type="submit"
          variant="primary"
          size="lg"
          :loading="loading"
          full-width
        >
          {{ loading ? 'Signing in...' : 'Sign In' }}
        </Button>
      </form>
    </div>
  </div>
</template>

<style module>
.container {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: var(--space-4);
}

.card {
  background: var(--card-bg);
  padding: var(--space-8);
  border-radius: var(--radius-2xl);
  width: 100%;
  max-width: 400px;
  box-shadow: var(--shadow-xl);
  border: 1px solid var(--border-subtle);
}

.header {
  text-align: center;
  margin-bottom: var(--space-8);
}

.header h1 {
  font-size: var(--font-size-3xl);
  color: var(--primary);
  margin-bottom: var(--space-2);
  letter-spacing: var(--letter-spacing-tight);
}

.header p {
  color: var(--text-secondary);
  font-size: var(--font-size-base);
}
</style>
