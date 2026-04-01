/// <reference types="vite/client" />

declare module '*.wasm?url' {
  const url: string
  export default url
}

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
