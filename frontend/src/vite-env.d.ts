/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** REST API base URL for a split deployment (frontend on Vercel, backend
   * on Render). Unset locally -- paths stay relative, proxied by Vite. */
  readonly VITE_API_BASE_URL?: string;
  /** Full ws(s):// URL for the line WebSocket, same reasoning as above. */
  readonly VITE_WS_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
