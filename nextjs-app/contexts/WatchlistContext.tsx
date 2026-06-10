"use client";

import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { stockApi } from "@/lib/api";

export interface WatchlistItem {
  symbol: string;
  price: number;
  change: number;
  changePercent: number;
  regime?: "bull" | "bear" | "sideways";
  lastRegime?: "bull" | "bear" | "sideways";
}

interface WatchlistContextValue {
  watchlist: WatchlistItem[];
  activeSymbol: string;
  setActiveSymbol: (symbol: string) => void;
  addStock: (item: WatchlistItem) => void;
  removeStock: (symbol: string) => void;
  isLoading: boolean;
}

const WatchlistContext = createContext<WatchlistContextValue | null>(null);

const DEFAULT_SYMBOLS = ["NVDA", "AAPL", "MSFT", "GOOGL"];

export function WatchlistProvider({ children }: { children: React.ReactNode }) {
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [activeSymbol, setActiveSymbol] = useState("NVDA");
  const [isLoading, setIsLoading] = useState(true);

  // Load watchlist from Supabase on mount; also re-fetch on window focus
  useEffect(() => {
    let cancelled = false;
    let isLoadingRef = false;
    const load = () => {
      if (isLoadingRef) return;
      isLoadingRef = true;
      stockApi
        .getWatchlist()
        .then((res) => {
          if (cancelled) return;
          const symbols: string[] = res.data ?? [];
          if (symbols.length > 0) {
            setWatchlist(symbols.map((s) => ({ symbol: s, price: 0, change: 0, changePercent: 0 })));
            setActiveSymbol(symbols[0]);
          }
        })
        .catch(() => {
          if (cancelled) return;
          setWatchlist(DEFAULT_SYMBOLS.map((s) => ({ symbol: s, price: 0, change: 0, changePercent: 0 })));
          setActiveSymbol("NVDA");
        })
        .finally(() => {
          isLoadingRef = false;
          if (!cancelled) setIsLoading(false);
        });
    };
    load();
    const onFocus = () => load();
    window.addEventListener("focus", onFocus);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", onFocus);
    };
  }, []);

  // Fetch live prices for all watchlist symbols — shared across all tabs
  const symbolsKey = watchlist.map((w) => w.symbol).sort().join(",");
  const { data: watchlistPrices } = useQuery({
    queryKey: ["watchlist-prices", symbolsKey],
    queryFn: async () => {
      const results = await Promise.allSettled(
        watchlist.map((w) => stockApi.getTicker(w.symbol).then((r) => r.data?.info))
      );
      return watchlist.map((w, i) => {
        const info = results[i]?.status === "fulfilled" ? results[i].value : null;
        return {
          symbol: w.symbol,
          price: info?.price ?? 0,
          change: info?.change ?? 0,
          changePercent: info?.changePercent ?? 0,
        };
      });
    },
    enabled: watchlist.length > 0,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  // Poll regime data for all watchlist symbols
  const { data: watchlistRegimes } = useQuery({
    queryKey: ["watchlist-regimes", symbolsKey],
    queryFn: async () => {
      const results = await Promise.allSettled(
        watchlist.map((w) => stockApi.getRegime(w.symbol).then((r) => ({ symbol: w.symbol, regime: r.data.currentRegime })))
      );
      return results.map((r, i) => {
        if (r.status === "fulfilled") return r.value;
        return { symbol: watchlist[i].symbol, regime: watchlist[i].regime as "bull" | "bear" | "sideways" | undefined };
      });
    },
    enabled: watchlist.length > 0,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  // Enriched watchlist: base symbols + live prices + live regimes — provided to all tabs
  const enrichedWatchlist = useMemo(() => {
    const baseMap = new Map(watchlist.map((w) => [w.symbol, w]));
    for (const item of watchlistPrices ?? []) {
      baseMap.set(item.symbol, item);
    }
    if (!watchlistRegimes || watchlistRegimes.length === 0) {
      return Array.from(baseMap.values());
    }
    const regimeMap = new Map(
      watchlistRegimes
        .filter((r) => r.symbol && r.regime)
        .map((r) => [r.symbol, r.regime as "bull" | "bear" | "sideways"])
    );
    if (regimeMap.size === 0) return Array.from(baseMap.values());
    return Array.from(baseMap.values()).map((item) => {
      const currentRegime = regimeMap.get(item.symbol);
      if (!currentRegime) return item;
      if (item.regime && item.regime !== currentRegime) {
        return { ...item, lastRegime: item.regime, regime: currentRegime };
      } else if (!item.regime) {
        return { ...item, regime: currentRegime };
      }
      return item;
    });
  }, [watchlistRegimes, watchlistPrices, watchlist]);

  const addStock = useCallback((item: WatchlistItem) => {
    setWatchlist((prev) => {
      if (prev.find((w) => w.symbol === item.symbol)) {
        return prev;
      }
      const updated = [...prev, item];
      // Persist to Supabase (fire-and-forget with warning on failure)
      stockApi.addToWatchlist(item.symbol).catch(() => {
        console.warn(`[WatchlistContext] Failed to persist add of ${item.symbol} to Supabase`);
      });
      return updated;
    });
    // Set active outside the updater so it fires even when already-exists path returns prev
    setActiveSymbol(item.symbol);
  }, []);

  const removeStock = useCallback((symbol: string) => {
    setWatchlist((prev) => {
      const updated = prev.filter((w) => w.symbol !== symbol);
      if (activeSymbol === symbol) {
        setActiveSymbol(updated.length > 0 ? updated[0].symbol : "NVDA");
      }
      // Persist to Supabase (fire-and-forget with warning on failure)
      stockApi.removeFromWatchlist(symbol).catch(() => {
        console.warn(`[WatchlistContext] Failed to persist removal of ${symbol} from Supabase`);
      });
      return updated;
    });
  }, [activeSymbol]);

  return (
    <WatchlistContext.Provider
      value={{
        watchlist: enrichedWatchlist,
        activeSymbol,
        setActiveSymbol,
        addStock,
        removeStock,
        isLoading,
      }}
    >
      {children}
    </WatchlistContext.Provider>
  );
}

export function useWatchlist() {
  const ctx = useContext(WatchlistContext);
  if (!ctx) throw new Error("useWatchlist must be used inside <WatchlistProvider>");
  return ctx;
}