import type { TickRecord } from "../types/api";

/**
 * IndexedDB persistence for the time-and-sales (成交明細) panel.
 * One record per (date, symbol); records from previous days are purged on
 * first access after the date rolls over.
 */

const DB_NAME = "yuanta-trading";
const STORE = "dailyTicks";
// 成交明細保留筆數上限（前端 state / IndexedDB 共用，與後端 deque 一致）。
// 注意：此為「訂閱後累積」的上限，無法回補訂閱前（開盤段）的明細。
export const MAX_TICKS = 8000;

function todayText() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function recordKey(symbol: string) {
  return `${todayText()}|${symbol}`;
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) {
        request.result.createObjectStore(STORE, { keyPath: "key" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function purgeOldDates(db: IDBDatabase): Promise<void> {
  const today = todayText();
  await new Promise<void>((resolve) => {
    const tx = db.transaction(STORE, "readwrite");
    const store = tx.objectStore(STORE);
    const request = store.getAllKeys();
    request.onsuccess = () => {
      for (const key of request.result) {
        if (typeof key === "string" && !key.startsWith(today)) {
          store.delete(key);
        }
      }
    };
    tx.oncomplete = () => resolve();
    tx.onerror = () => resolve();
  });
}

export async function loadDailyTicks(symbol: string): Promise<TickRecord[]> {
  try {
    const db = await openDb();
    await purgeOldDates(db);
    return await new Promise((resolve) => {
      const tx = db.transaction(STORE, "readonly");
      const request = tx.objectStore(STORE).get(recordKey(symbol));
      request.onsuccess = () => resolve(Array.isArray(request.result?.ticks) ? request.result.ticks : []);
      request.onerror = () => resolve([]);
    });
  } catch {
    return [];
  }
}

export async function saveDailyTicks(symbol: string, ticks: TickRecord[]): Promise<void> {
  try {
    const db = await openDb();
    await new Promise<void>((resolve) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).put({
        key: recordKey(symbol),
        date: todayText(),
        symbol,
        ticks: ticks.slice(-MAX_TICKS)
      });
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
    });
  } catch {
    // IndexedDB unavailable (private mode etc.) — degrade to in-memory only.
  }
}
