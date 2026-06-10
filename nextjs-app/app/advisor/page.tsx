"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import ChatAdvisor from "@/components/ChatAdvisor";
import { WatchlistTabs, SearchModal, type WatchlistItem } from "@/components/StockWatchlist";
import { useWatchlist } from "@/contexts/WatchlistContext";

export default function AdvisorPage() {
  const { watchlist, activeSymbol, setActiveSymbol, addStock, removeStock } = useWatchlist();
  const [showSearch, setShowSearch] = useState(false);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-3xl font-bold">AI Stock Advisor</h1>
        <p className="text-muted-foreground mt-1">
          Chat with grounded, cited answers — news headlines, SEC filings, analyst ratings,
          plus live price data: regime, RSI, MACD, Bollinger Bands, market cap, and intraday prices.
        </p>
      </div>

      <WatchlistTabs
        watchlist={watchlist}
        activeSymbol={activeSymbol}
        onSelect={setActiveSymbol}
        onRemove={removeStock}
        onAdd={() => setShowSearch(true)}
      />

      <Card>
        <CardHeader>
          <CardTitle>Chat about {activeSymbol}</CardTitle>
          <p className="text-xs text-muted-foreground mt-1">
            Grounded in NewsAPI headlines, SEC 10-K/10-Q filings, and live Yahoo Finance data — regime, RSI, volatility, market cap, and intraday prices.
          </p>
        </CardHeader>
        <CardContent>
          {/* key={activeSymbol} resets chat history when switching stocks */}
          <ChatAdvisor key={activeSymbol} symbol={activeSymbol} />
        </CardContent>
      </Card>

      {showSearch && <SearchModal onClose={() => setShowSearch(false)} onAdd={addStock} />}
    </div>
  );
}