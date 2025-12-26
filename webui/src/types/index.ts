export interface Connection {
  id: string
  name: string
  provider: string
  config: Record<string, any>
}

export type ConnectionCreate = Omit<Connection, 'id'>
export type ConnectionUpdate = Partial<ConnectionCreate>

export interface Component {
  id: string
  name: string
  type: 'camera' | 'control' | 'status'
  provider: string
  connection_id?: string
  entity_config: Record<string, any>
  connection?: Connection
}

export type ComponentCreate = Omit<Component, 'id' | 'connection'>
export type ComponentUpdate = Partial<Omit<ComponentCreate, 'type' | 'connection_id'>>

export enum PrinterStatus {
  IDLE = 'idle',
  PRINTING = 'printing',
  PAUSED = 'paused',
  ERROR = 'error',
  DISCONNECTED = 'disconnected'
}

export interface ComponentInfo {
  id: string
  name?: string
  type: string
  provider: string
  entity_config: Record<string, any>
}

export interface Printer {
  id: string
  name: string
  status: PrinterStatus
  linked_session_id?: string
  has_control: boolean
  has_camera: boolean
  components?: Record<string, ComponentInfo>
}

export interface PrinterCreate {
  name: string
  components: {
    camera: string
    status?: string | null
    control?: string | null
  }
}

export type PrinterUpdate = Partial<PrinterCreate>

export interface HealthStatus {
  healthy: boolean
  error?: string
}

export interface Entity {
  id: string
  name: string
  type: string
}

export interface ProviderField {
  name: string
  type: 'string' | 'number' | 'boolean' | 'password' | 'select' | 'device_select'
  required: boolean
  label: string
  placeholder?: string
  options?: { label: string, value: string }[]
  condition?: string
}

export interface ProviderSchema {
  connection_fields: ProviderField[]
  entity_fields: ProviderField[]
}

export interface User {
  username: string
  scopes: string
}

export interface M2MApplication {
  client_id: string
  name: string
  scopes: string
  client_secret?: string
}

