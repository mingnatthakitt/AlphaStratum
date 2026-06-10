"use client";

import React, { useState, useEffect, useRef } from "react";
import { stockApi } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { X, Plus, Search } from "lucide-react";

export interface WatchlistItem {
  symbol: string;
  price: number;
  change: number;
  changePercent: number;
  regime?: "bull" | "bear" | "sideways";
  lastRegime?: "bull" | "bear" | "sideways";
}

export function SearchModal({ onClose, onAdd }: { onClose: () => void; onAdd: (item: WatchlistItem) => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<{ symbol: string; name: string; exchange: string }[]>([]);
  const [searching, setSearching] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (query.trim().length < 1) {
      setResults([]);
      return;
    }
    setSearching(true);
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await stockApi.searchStock(query);
        setResults(res.data.results || []);
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 350);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-background rounded-2xl border border-border shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <div className="flex items-center gap-2">
            <Search className="w-4 h-4 text-muted-foreground" />
            <span className="font-semibold">Add Stock</span>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose}>
            <X className="w-4 h-4" />
          </Button>
        </div>
        <div className="p-4">
          <Input
            autoFocus
            placeholder="Search company name or ticker (e.g. Apple, TSLA)..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="mb-3"
          />
          {searching && <p className="text-sm text-muted-foreground text-center py-2">Searching...</p>}
          {!searching && results.length === 0 && query.length >= 1 && (
            <p className="text-sm text-muted-foreground text-center py-2">No results found</p>
          )}
          {!searching && results.length > 0 && (
            <div className="space-y-1 max-h-72 overflow-y-auto">
              {results.map((r) => (
                <button
                  key={r.symbol}
                  onClick={() => {
                    onAdd({ symbol: r.symbol, price: 0, change: 0, changePercent: 0 });
                    onClose();
                  }}
                  className="w-full flex items-center justify-between px-3 py-2 rounded-lg hover:bg-muted transition-colors text-left"
                >
                  <div>
                    <span className="font-semibold text-sm">{r.symbol}</span>
                    <span className="text-muted-foreground text-xs ml-2">{r.name}</span>
                  </div>
                  <span className="text-xs text-muted-foreground">{r.exchange}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function WatchlistTabs({
  watchlist,
  activeSymbol,
  onSelect,
  onRemove,
  onAdd,
}: {
  watchlist: WatchlistItem[];
  activeSymbol: string;
  onSelect: (symbol: string) => void;
  onRemove: (symbol: string) => void;
  onAdd: (item: WatchlistItem) => void;
}) {
  const handleAddClick = () => { onAdd({ symbol: "", price: 0, change: 0, changePercent: 0 }); };

  if (!watchlist || watchlist.length === 0) {
    return (
      <div className="flex items-center gap-2">
        <p className="text-sm text-muted-foreground">Your watchlist is empty.</p>
        <Button size="sm" variant="outline" onClick={handleAddClick} className="gap-1.5">
          <Plus className="w-4 h-4" /> Add Stock
        </Button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <div className="flex items-center gap-1 overflow-x-auto pb-1 flex-1">
        {watchlist.map((item) => {
          const isActive = item.symbol === activeSymbol;
          const up = (item.changePercent ?? 0) >= 0;
          return (
            <button
              key={item.symbol}
              onClick={() => onSelect(item.symbol)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium whitespace-nowrap transition-colors ${
                isActive
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted/80"
              }`}
            >
              <span>{item.symbol || "—"}</span>
<span className={`text-xs ${isActive ? "opacity-70" : up ? "text-green-500" : "text-red-400"}`}>
                {up ? "+" : ""}{(item.changePercent ?? 0).toFixed(1)}%
              </span>
              <span
                  onClick={(e) => { e.stopPropagation(); onRemove(item.symbol); }}
                  className="ml-0.5 hover:text-red-400 rounded-full p-0.5"
                >
                  <X className="w-3 h-3" />
                </span>
              {item.regime && item.lastRegime && item.regime !== item.lastRegime && (
                <span className="ml-0.5 w-2 h-2 rounded-full bg-orange-400 animate-pulse" title={`Regime flipped ${item.lastRegime}→${item.regime}`} />
              )}
            </button>
          );
        })}
      </div>
      <Button size="sm" variant="outline" onClick={handleAddClick} className="gap-1.5">
        <Plus className="w-4 h-4" /> Add
      </Button>
    </div>
  );
}