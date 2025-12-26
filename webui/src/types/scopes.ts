export const AVAILABLE_SCOPES = [
  'admin',
  'printer:read',
  'printer:write',
  'rtc:stream',
  'tunnel:manage'
] as const;

export type Scope = typeof AVAILABLE_SCOPES[number];

