import { useEffect, useRef, useState } from "react";
import type { FiveTickBook, Quote, TickRecord } from "../types/api";

export type QuoteStreamStatus = "off" | "connecting" | "live";

type Options = {
  enabled: boolean;
  symbols: string[];
  tickSymbol?: string;
  onQuotes: (quotes: Quote[]) => void;
  onTicks?: (symbol: string, ticks: TickRecord[]) => void;
  onFiveTick?: (symbol: string, book: FiveTickBook) => void;
  onError?: (message: string) => void;
};

// 報價 WebSocket 也要認證：金鑰以 subprotocol 夾帶（避免寫進 URL 被 log），須與後端 API_KEY 相同。
const API_KEY = (import.meta.env.VITE_API_KEY as string | undefined) ?? "";

function streamUrl() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}/api/ws/quotes`;
}

/**
 * Push-based quote subscription with auto-reconnect (exponential backoff,
 * 1s → 10s). The caller's REST polling remains as the fallback transport
 * whenever the returned status is not "live".
 */
export function useQuoteStream({ enabled, symbols, tickSymbol = "", onQuotes, onTicks, onFiveTick, onError }: Options): QuoteStreamStatus {
  const [status, setStatus] = useState<QuoteStreamStatus>("off");
  const socketRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(1000);
  const callbacksRef = useRef({ onQuotes, onTicks, onFiveTick, onError });
  callbacksRef.current = { onQuotes, onTicks, onFiveTick, onError };
  const symbolsKey = `${symbols.join(",")}|${tickSymbol}`;
  const subscriptionRef = useRef({ symbols, tickSymbol });
  subscriptionRef.current = { symbols, tickSymbol };

  useEffect(() => {
    if (!enabled) {
      setStatus("off");
      return;
    }

    let disposed = false;
    let reconnectTimer = 0;

    function connect() {
      if (disposed) {
        return;
      }
      setStatus("connecting");
      const socket = new WebSocket(streamUrl(), API_KEY ? [API_KEY] : undefined);
      socketRef.current = socket;

      socket.onopen = () => {
        retryRef.current = 1000;
        setStatus("live");
        socket.send(JSON.stringify({ symbols: subscriptionRef.current.symbols, tick_symbol: subscriptionRef.current.tickSymbol }));
      };

      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === "quotes" && Array.isArray(payload.data)) {
            callbacksRef.current.onQuotes(payload.data as Quote[]);
          } else if (payload.type === "ticks" && Array.isArray(payload.data)) {
            callbacksRef.current.onTicks?.(String(payload.symbol ?? ""), payload.data as TickRecord[]);
          } else if (payload.type === "fivetick" && payload.data) {
            callbacksRef.current.onFiveTick?.(String(payload.symbol ?? ""), payload.data as FiveTickBook);
          } else if (payload.type === "error" && payload.message) {
            callbacksRef.current.onError?.(String(payload.message));
          }
        } catch {
          // Ignore malformed frames.
        }
      };

      socket.onclose = () => {
        if (disposed) {
          return;
        }
        setStatus("connecting");
        reconnectTimer = window.setTimeout(connect, retryRef.current);
        retryRef.current = Math.min(retryRef.current * 2, 10000);
      };

      socket.onerror = () => {
        socket.close();
      };
    }

    connect();

    return () => {
      disposed = true;
      window.clearTimeout(reconnectTimer);
      socketRef.current?.close();
      socketRef.current = null;
      setStatus("off");
    };
  }, [enabled]);

  useEffect(() => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ symbols: subscriptionRef.current.symbols, tick_symbol: subscriptionRef.current.tickSymbol }));
    }
  }, [symbolsKey]);

  return status;
}
