<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { tunnelApi, ngrokApi, cloudflareApi } from '../../services/api'
import Button from '../ui/Button.vue'
import Input from '../ui/Input.vue'
import Select from '../ui/Select.vue'
import Badge from '../ui/Badge.vue'
import BaseModal from '../shared/BaseModal.vue'

const tunnelStatus = ref<any>(null)
const dependencies = ref<any>(null)
const loading = ref(false)
const step = ref(1)
const activeTab = ref('local')
const showModal = ref(false)

const ngrokForm = ref({ authtoken: '', domain: '' })
const cfForm = ref({ 
  api_token: '', 
  account_id: '', 
  zone_id: '', 
  tunnel_name: 'printguard-tunnel', 
  subdomain: 'camera',
  overwrite_tunnel: false,
  overwrite_dns: false
})

const cfData = ref({
  accounts: [] as any[],
  zones: [] as any[],
  existence: null as any
})

const providerOptions = [
  { value: 'local', label: 'Local (No Remote Access)' },
  { value: 'ngrok', label: 'Ngrok Tunnel' },
  { value: 'cloudflare', label: 'Cloudflare Tunnel' }
]

const accountOptions = computed(() => [
  { value: '', label: 'Select an account' },
  ...cfData.value.accounts.map(acc => ({ value: acc.id, label: acc.name }))
])

const zoneOptions = computed(() => [
  { value: '', label: 'Select a zone' },
  ...cfData.value.zones.map(zone => ({ value: zone.id, label: zone.name }))
])

async function fetchInitialData() {
  loading.value = true
  try {
    const [statusRes, depRes] = await Promise.all([
      tunnelApi.status(),
      tunnelApi.checkDependencies()
    ])
    tunnelStatus.value = statusRes.data
    dependencies.value = depRes.data
    activeTab.value = tunnelStatus.value.provider || 'local'
  } catch (e) {
    console.error('Failed to fetch initial tunnel data', e)
  } finally {
    loading.value = false
  }
}

watch(activeTab, (newVal) => {
  if (loading.value || !tunnelStatus.value) return

  if (newVal === tunnelStatus.value?.provider) return

  if (newVal === 'local') {
    disableTunnels()
  } else {
    step.value = 1
    showModal.value = true
  }
})

async function disableTunnels() {
  loading.value = true
  try {
    await tunnelApi.disable()
    await fetchInitialData()
    alert('Remote access disabled. Reverted to local mode.')
  } catch (e) {
    alert('Failed to disable tunnels')
    activeTab.value = tunnelStatus.value?.provider || 'local'
  } finally {
    loading.value = false
  }
}

function handleModalClose() {
  showModal.value = false
  activeTab.value = tunnelStatus.value?.provider || 'local'
}

// Ngrok Flow
async function setupNgrok() {
  loading.value = true
  try {
    const res = await ngrokApi.setup(ngrokForm.value)
    alert(`Ngrok tunnel started! URL: ${res.data.url}`)
    await fetchInitialData()
    showModal.value = false
  } catch (e: any) {
    alert(`Ngrok setup failed: ${e.response?.data?.detail || e.message}`)
  } finally {
    loading.value = false
  }
}

// Cloudflare Flow
async function validateCfToken() {
  loading.value = true
  try {
    const res = await cloudflareApi.validateToken(cfForm.value.api_token)
    if (res.data.valid) {
      const [accRes, zoneRes] = await Promise.all([
        cloudflareApi.accounts(cfForm.value.api_token),
        cloudflareApi.zones(cfForm.value.api_token)
      ])
      cfData.value.accounts = accRes.data
      cfData.value.zones = zoneRes.data
      step.value = 3
    } else {
      alert(`Invalid token: ${res.data.detail}`)
    }
  } catch (e: any) {
    alert(`Validation failed: ${e.response?.data?.detail || e.message}`)
  } finally {
    loading.value = false
  }
}

async function checkCfExistence() {
  loading.value = true
  try {
    const res = await cloudflareApi.checkExistence({
      api_token: cfForm.value.api_token,
      account_id: cfForm.value.account_id,
      zone_id: cfForm.value.zone_id,
      tunnel_name: cfForm.value.tunnel_name,
      subdomain: cfForm.value.subdomain
    })
    cfData.value.existence = res.data
    if (res.data.tunnel_exists || res.data.dns_exists) {
      step.value = 5 // Show overwrite confirmation
    } else {
      await finishCfSetup()
    }
  } catch (e: any) {
    alert(`Existence check failed: ${e.response?.data?.detail || e.message}`)
  } finally {
    loading.value = false
  }
}

async function finishCfSetup() {
  loading.value = true
  try {
    const res = await cloudflareApi.setup(cfForm.value.api_token, cfForm.value)
    alert(`Cloudflare tunnel started! URL: ${res.data.url}`)
    await fetchInitialData()
    showModal.value = false
    step.value = 1
  } catch (e: any) {
    alert(`Cloudflare setup failed: ${e.response?.data?.detail || e.message}`)
  } finally {
    loading.value = false
  }
}

function openUrl(url: string) {
  window.open(url, '_blank')
}

const isNgrokInstalled = computed(() => dependencies.value?.ngrok_installed)
const isCfInstalled = computed(() => dependencies.value?.cloudflared_installed)

onMounted(fetchInitialData)
</script>

<template>
  <div :class="$style.section">
    <!-- Status Header -->
    <div :class="$style.statusCard">
      <div :class="$style.statusHeader">
        <h3>Current Remote Access Status</h3>
        <Button v-if="tunnelStatus?.provider !== 'local'" variant="danger" size="sm" @click="disableTunnels">
          Disable Remote Access
        </Button>
      </div>
      
      <div v-if="loading && !tunnelStatus" :class="$style.loading">Loading status...</div>
      <div v-else-if="tunnelStatus" :class="$style.statusInfo">
        <div :class="$style.statusRow">
          <span>Provider:</span>
          <Badge variant="neutral" size="sm">{{ tunnelStatus.provider.toUpperCase() }}</Badge>
        </div>
        <div :class="$style.statusRow">
          <span>Public URL:</span>
          <span v-if="tunnelStatus.url" :class="$style.url" @click="openUrl(tunnelStatus.url)">
            {{ tunnelStatus.url }}
          </span>
          <span v-else :class="$style.val">None (Local Access Only)</span>
        </div>
        <div :class="$style.statusRow">
          <span>Status:</span>
          <Badge :variant="tunnelStatus.is_active ? 'success' : 'neutral'" size="sm">
            {{ tunnelStatus.is_active ? 'Active' : 'Inactive' }}
          </Badge>
        </div>
      </div>
    </div>

    <!-- Provider Selection -->
    <div :class="$style.selectionCard">
      <div class="form-field">
        <label>Remote Access Provider</label>
        <Select 
          v-model="activeTab" 
          :options="providerOptions" 
          fullWidth
        />
        <p :class="$style.helpText">
          Choose how you want to access PrintGuard from outside your home network.
        </p>
      </div>
    </div>

    <!-- Configuration Modal -->
    <BaseModal 
      :show="showModal" 
      :title="activeTab === 'ngrok' ? 'Setup Ngrok Tunnel' : 'Setup Cloudflare Tunnel'"
      @close="handleModalClose"
    >
      <!-- Ngrok Flow -->
      <div v-if="activeTab === 'ngrok'">
        <div v-if="!isNgrokInstalled" :class="$style.errorBox">
          <h4>Ngrok Not Installed</h4>
          <p>The `ngrok-python` package is missing on the server.</p>
          <code>pip install ngrok-python</code>
          <p>Please install it and restart the server to use this feature.</p>
        </div>
        <div v-else :class="$style.wizard">
          <div v-if="step === 1">
            <p>Ngrok provides a secure tunnel to your local server with minimal configuration.</p>
            <div class="base-form">
              <div class="form-field">
                <label>Ngrok Auth Token</label>
                <Input v-model="ngrokForm.authtoken" type="password" required placeholder="Paste your token from ngrok dashboard" />
              </div>
              <div class="form-field">
                <label>Custom Domain (Optional)</label>
                <Input v-model="ngrokForm.domain" placeholder="e.g. my-printer.ngrok-free.app" />
              </div>
            </div>
          </div>
          <div v-if="step === 2">
            <h4>Confirm Setup</h4>
            <p>Ready to start the tunnel with provider <b>Ngrok</b>.</p>
            <div :class="$style.summary">
              <div>Auth Token: <code>********</code></div>
              <div v-if="ngrokForm.domain">Domain: <code>{{ ngrokForm.domain }}</code></div>
            </div>
          </div>
        </div>
      </div>

      <!-- Cloudflare Flow -->
      <div v-if="activeTab === 'cloudflare'">
        <div v-if="!isCfInstalled" :class="$style.errorBox">
          <h4>cloudflared Not Installed</h4>
          <p>The `cloudflared` binary was not found in the system PATH.</p>
          <a href="https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/" target="_blank">
            Download and install cloudflared from here.
          </a>
          <p>After installation, ensure it is accessible by the user running PrintGuard.</p>
        </div>
        <div v-else :class="$style.wizard">
          <!-- Step 1: Token -->
          <div v-if="step === 1">
            <p>You need an API Token with <b>Cloudflare Tunnel:Edit</b> and <b>DNS:Edit</b> permissions.</p>
            <ol :class="$style.list">
              <li>Go to <a href="https://dash.cloudflare.com/profile/api-tokens" target="_blank">Cloudflare Dashboard</a></li>
              <li>Create Token -> Use 'Cloudflare Tunnel' template</li>
              <li>Ensure 'Account' and 'Zone' resources are correctly scoped</li>
            </ol>
            <div class="base-form">
              <div class="form-field">
                <label>API Token</label>
                <Input v-model="cfForm.api_token" type="password" required />
              </div>
            </div>
          </div>

          <!-- Step 3: Account/Zone -->
          <div v-if="step === 3">
            <h4>Select Account and Zone</h4>
            <div class="base-form">
              <div class="form-field">
                <label>Cloudflare Account</label>
                <Select v-model="cfForm.account_id" :options="accountOptions" />
              </div>
              <div class="form-field">
                <label>Target DNS Zone (Domain)</label>
                <Select v-model="cfForm.zone_id" :options="zoneOptions" />
              </div>
            </div>
          </div>

          <!-- Step 4: Subdomain -->
          <div v-if="step === 4">
            <h4>Tunnel Configuration</h4>
            <div class="base-form">
              <div class="form-field">
                <label>Tunnel Name</label>
                <Input v-model="cfForm.tunnel_name" />
              </div>
              <div class="form-field">
                <label>Subdomain</label>
                <div :class="$style.subInput">
                  <Input v-model="cfForm.subdomain" placeholder="camera" />
                  <span :class="$style.domainSuffix">.{{ cfData.zones.find(z => z.id === cfForm.zone_id)?.name }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Step 5: Overwrite Confirmation -->
          <div v-if="step === 5">
            <h4>Conflict Detected</h4>
            <div v-if="cfData.existence?.tunnel_exists" :class="$style.warningBox">
              A tunnel named <b>{{ cfForm.tunnel_name }}</b> already exists in your account.
              <label :class="$style.checkbox">
                <input type="checkbox" v-model="cfForm.overwrite_tunnel" />
                Overwrite existing tunnel (recreates it)
              </label>
            </div>
            <div v-if="cfData.existence?.dns_exists" :class="$style.warningBox">
              A DNS record for <b>{{ cfForm.subdomain }}</b> already exists.
              <label :class="$style.checkbox">
                <input type="checkbox" v-model="cfForm.overwrite_dns" />
                Override existing DNS record
              </label>
            </div>
            <p v-if="!cfForm.overwrite_tunnel && cfData.existence?.tunnel_exists" :class="$style.hint">
              If you don't overwrite, we will try to reuse the existing tunnel.
            </p>
          </div>
        </div>
      </div>

      <template #footer>
        <Button variant="ghost" @click="handleModalClose">Cancel</Button>
        
        <!-- Ngrok Actions -->
        <template v-if="activeTab === 'ngrok' && isNgrokInstalled">
          <Button v-if="step === 1" variant="primary" @click="step = 2">Next</Button>
          <template v-if="step === 2">
            <Button variant="secondary" @click="step = 1">Back</Button>
            <Button variant="primary" @click="setupNgrok" :loading="loading">Start Tunnel</Button>
          </template>
        </template>

        <!-- Cloudflare Actions -->
        <template v-if="activeTab === 'cloudflare' && isCfInstalled">
          <Button v-if="step === 1" variant="primary" @click="validateCfToken" :loading="loading">Next</Button>
          <template v-if="step === 3">
            <Button variant="secondary" @click="step = 1">Back</Button>
            <Button variant="primary" @click="step = 4" :disabled="!cfForm.account_id || !cfForm.zone_id">Next</Button>
          </template>
          <template v-if="step === 4">
            <Button variant="secondary" @click="step = 3">Back</Button>
            <Button variant="primary" @click="checkCfExistence" :loading="loading">Next</Button>
          </template>
          <template v-if="step === 5">
            <Button variant="secondary" @click="step = 4">Back</Button>
            <Button variant="primary" @click="finishCfSetup" :loading="loading">Finish Setup</Button>
          </template>
        </template>
      </template>
    </BaseModal>
  </div>
</template>

<style module>
.section {
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
  max-width: 800px;
}

.statusCard, .selectionCard {
  background-color: var(--card-bg);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xl);
  padding: var(--space-6);
  box-shadow: var(--shadow-sm);
}

.statusHeader {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-6);
}

.statusHeader h3 {
  margin: 0;
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: var(--letter-spacing-wide);
}

.statusInfo {
  display: flex;
  gap: var(--space-12);
}

.statusRow {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.statusRow span:first-child {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  font-weight: var(--font-weight-semibold);
  text-transform: uppercase;
  letter-spacing: var(--letter-spacing-wide);
}

.val {
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.url {
  font-family: monospace;
  color: var(--primary);
  font-weight: var(--font-weight-semibold);
  cursor: pointer;
  text-decoration: underline;
  transition: color var(--transition-fast);
}

.url:hover {
  color: var(--primary-hover);
}

.selectionCard {
  background-color: var(--card-bg);
}

.helpText {
  margin-top: var(--space-3);
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
}

.wizard h4 {
  margin-bottom: var(--space-4);
  font-size: var(--font-size-xl);
  color: var(--text-primary);
}

.wizard p {
  margin-bottom: var(--space-6);
  color: var(--text-secondary);
}

.subInput {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.domainSuffix {
  color: var(--text-tertiary);
  font-weight: var(--font-weight-medium);
  font-family: monospace;
}

.errorBox, .warningBox {
  padding: var(--space-4);
  border-radius: var(--radius-lg);
  margin-bottom: var(--space-6);
  font-size: var(--font-size-sm);
}

.errorBox { background: var(--danger-bg); border: 1px solid var(--danger-200); color: var(--danger); }
.warningBox { background: var(--warning-bg); border: 1px solid var(--warning-200); color: var(--warning); }

.checkbox {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-2);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  color: var(--text-primary);
}

.list {
  padding-left: var(--space-6);
  margin-bottom: var(--space-6);
  color: var(--text-secondary);
}

.list li {
  margin-bottom: var(--space-2);
}

.summary {
  background: var(--bg-secondary);
  padding: var(--space-4);
  border-radius: var(--radius-lg);
  margin-bottom: var(--space-6);
  border: 1px solid var(--border-subtle);
}

.summary code {
  background-color: var(--bg-primary);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-default);
}

.hint {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  font-style: italic;
  margin-top: var(--space-2);
}

.loading {
  padding: var(--space-12);
  text-align: center;
  color: var(--text-tertiary);
}
</style>
