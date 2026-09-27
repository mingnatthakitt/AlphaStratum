"use client";

import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { stockApi, type WatchlistItem } from "@/lib/api";
import { useToast } from "@/components/ui/toast";

export type { WatchlistItem };

interface WatchlistContextValue {
  watchlist: WatchlistItem[];
  activeSymbol: string;
  setActiveSymbol: (symbol: string) => void;
  addStock: (item: WatchlistItem) => void;
  removeStock: (symbol: string) => void;
  isLoading: boolean;
  /** True when the latest quotes poll failed — rows show stale/blank prices. */
  quotesError: boolean;
}

const WatchlistContext = createContext<WatchlistContextValue | null>(null);

const DEFAULT_SYMBOLS = ["NVDA", "AAPL", "MSFT", "GOOGL"];

export function WatchlistProvider({ children }: { children: React.ReactNode }) {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [activeSymbol, setActiveSymbol] = useState("NVDA");
  const [isLoading, setIsLoading] = useState(true);
  const { toast } = useToast();
  // Previous regime per symbol — persists across polls so flips are detectable.
  const prevRegimesRef = useRef<Map<string, WatchlistItem["regime"]>>(new Map());

  // Load watchlist once on mount. Prices/regimes poll below; re-fetching the
  // symbol list on window focus raced with optimistic adds and reset the
  // user's active symbol.
  useEffect(() => {
    let cancelled = false;
    stockApi
      .getWatchlist()
      .then((res) => {
        if (cancelled) return;
        const loaded: string[] = res.data ?? [];
        setSymbols(loaded.length > 0 ? loaded : DEFAULT_SYMBOLS);
      })
      .catch(() => {
        if (cancelled) return;
        setSymbols(DEFAULT_SYMBOLS);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Keep the active symbol valid when the list changes.
  useEffect(() => {
    if (symbols.length > 0 && !symbols.includes(activeSymbol)) {
      setActiveSymbol(symbols[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbols]);

  const symbolsKey = symbols.slice().sort().join(",");

  // Lightweight quotes poll: one batched call per minute instead of a full
  // year of OHLCV per symbol. Candles are fetched by pages that need them.
  // Errors are allowed to propagate: swallowing them here made react-query
  // cache a SUCCESSFUL empty map, so one backend hiccup rendered every row as
  // $0.00 / +0.0% with no error and no retry for a full minute.
  const { data: watchlistQuotes, isError: quotesError } = useQuery({
    queryKey: ["watchlist-quotes", symbolsKey],
    queryFn: async () => {
      const res = await stockApi.getQuotes(symbols);
      return new Map(res.data.quotes.map((q) => [q.symbol, q]));
    },
    enabled: symbols.length > 0,
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: 2,
  });

  const { data: watchlistRegimes } = useQuery({
    queryKey: ["watchlist-regimes", symbolsKey],
    queryFn: async () => {
      const results = await Promise.allSettled(
        symbols.map((s) =>
          stockApi.getRegime(s).then((r) => ({ symbol: s, regime: r.data.currentRegime })),
        ),
      );
      return results.map((r, i) =>
        r.status === "fulfilled" ? r.value : { symbol: symbols[i], regime: undefined },
      );
    },
    enabled: symbols.length > 0,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  // Flip detection compares each poll's regime against the last one we
  // COMMITTED. It lives in an effect, not in the memo below: useMemo is a
  // render-phase function, and under StrictMode (and on any render React
  // discards) a ref written there is mutated by a render that never commits,
  // which silently kills the flip marker.
  const [regimeFlips, setRegimeFlips] = useState<Map<string, WatchlistItem["regime"]>>(new Map());

  useEffect(() => {
    const updates = new Map<string, WatchlistItem["regime"]>();
    for (const row of watchlistRegimes ?? []) {
      if (!row.regime) continue;
      const previous = prevRegimesRef.current.get(row.symbol);
      if (previous && previous !== row.regime) {
        updates.set(row.symbol, previous);
      }
      prevRegimesRef.current.set(row.symbol, row.regime);
    }
    if (updates.size > 0) {
      setRegimeFlips((prev) => new Map([...prev, ...updates]));
    }
  }, [watchlistRegimes]);

  const enrichedWatchlist = useMemo<WatchlistItem[]>(() => {
    const regimeMap = new Map(
      (watchlistRegimes ?? [])
        .filter((r) => r.regime)
        .map((r) => [r.symbol, r.regime as NonNullable<WatchlistItem["regime"]>]),
    );

    return symbols.map((symbol) => {
      const quote = watchlistQuotes?.get(symbol);
      const item: WatchlistItem = {
        symbol,
        price: quote?.price ?? 0,
        change: quote?.change ?? 0,
        changePercent: quote?.changePercent ?? 0,
        hasQuote: quote !== undefined,
        regime: regimeMap.get(symbol) ?? prevRegimesRef.current.get(symbol),
      };
      const flippedFrom = regimeFlips.get(symbol);
      if (flippedFrom) {
        item.lastRegime = flippedFrom;
      }
      return item;
    });
    // regimeFlips is intentionally a dependency: a flip is state, not a
    // render-time side effect, so the memo stays pure.
  }, [symbols, watchlistQuotes, watchlistRegimes, regimeFlips]);

  const addStock = useCallback(
    (item: WatchlistItem) => {
      setSymbols((prev) => {
        if (prev.includes(item.symbol)) return prev;
        return [...prev, item.symbol];
      });
      setActiveSymbol(item.symbol);
      stockApi.addToWatchlist(item.symbol).catch(() => {
        toast({
          title: `Couldn't save ${item.symbol}`,
          description: "It will disappear on reload — check your connection.",
          variant: "error",
        });
      });
    },
    [toast],
  );

  const removeStock = useCallback(
    (symbol: string) => {
      setSymbols((prev) => prev.filter((s) => s !== symbol));
      // If the removed symbol was active, the effect above re-pins
      // activeSymbol to the first remaining one.
      prevRegimesRef.current.delete(symbol);
      stockApi.removeFromWatchlist(symbol).catch(() => {
        toast({
          title: `Couldn't remove ${symbol}`,
          description: "It may reappear on reload — check your connection.",
          variant: "error",
        });
      });
    },
    [toast],
  );

  return (
    <WatchlistContext.Provider
      value={{
        watchlist: enrichedWatchlist,
        activeSymbol,
        setActiveSymbol,
        addStock,
        removeStock,
        isLoading,
        quotesError,
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
