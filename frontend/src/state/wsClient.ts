// WebSocket subscription manager: connects /ws/line, dispatches incoming
// LineState ticks into the store. Reconnects with a short fixed backoff if
// the connection drops -- a live mirror shouldn't need a page refresh to
// recover from a transient disconnect.

import { useLineageStore } from "./store";
import type { LineState } from "./types";

const RECONNECT_DELAY_MS = 2000;

export function connectLineWebSocket(): () => void {
  let socket: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let closedByCaller = false;

  function connect() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    socket = new WebSocket(`${protocol}//${window.location.host}/ws/line`);

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
