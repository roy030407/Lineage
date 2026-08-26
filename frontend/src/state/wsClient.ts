// WebSocket subscription manager: connects /ws/line, dispatches incoming
// LineState ticks into the store. Reconnects with a short fixed backoff if
// the connection drops -- a live mirror shouldn't need a page refresh to
// recover from a transient disconnect.

import { useLineageStore } from "./store";
import type { LineState } from "./types";

const RECONNECT_DELAY_MS = 2000;

// VITE_WS_URL is the full ws(s):// URL for a split deployment (frontend on
// Vercel, backend on Render, different origins -- same-origin construction
// below would otherwise point back at Vercel, where there's no WebSocket).
// Left unset, same-origin still works for local dev via the vite proxy.
function lineWebSocketUrl(): string {
  const configured = import.meta.env.VITE_WS_URL;
  if (configured) return configured;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/line`;
}

export function connectLineWebSocket(): () => void {
  let socket: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let closedByCaller = false;

  function connect() {
    socket = new WebSocket(lineWebSocketUrl());

    socket.onmessage = (event) => {
      const state = JSON.parse(event.data) as LineState;
      useLineageStore.getState().applyLineState(state);
    };

    socket.onclose = () => {
      if (!closedByCaller) {
        reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
      }
    };

    socket.onerror = () => {
      socket?.close();
    };
  }

  connect();

  return () => {
    closedByCaller = true;
    if (reconnectTimer !== null) clearTimeout(reconnectTimer);
    socket?.close();
  };
}
