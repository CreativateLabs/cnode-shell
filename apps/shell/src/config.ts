// Gateway base — env-driven; default local docker gateway.
const env = (import.meta as any).env?.VITE_GATEWAY_URL
export const GATEWAY: string = env !== undefined ? env : 'http://localhost:8080'
