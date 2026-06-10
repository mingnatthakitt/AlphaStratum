"use client";

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { TrendingUp, TrendingDown, Calculator, ArrowRight } from "lucide-react";
import { WatchlistTabs, SearchModal } from "@/components/StockWatchlist";
import { useWatchlist } from "@/contexts/WatchlistContext";

interface BacktestResult {
  symbol: string;
  entryDate: string;
  exitDate: string;
  investment: number;
  shares: number;
  entryPrice: number;
  exitPrice: number;
  currentValue: number;
  totalReturn: number;
  totalReturnPct: number;
  priceChangePct: number;
}

export default function BacktestPage() {
  const { watchlist, activeSymbol, setActiveSymbol, removeStock, addStock, isLoading: watchlistLoading } = useWatchlist();
  const [showSearch, setShowSearch] = useState(false);
  const [symbol, setSymbol] = useState("");
  const [entryDate, setEntryDate] = useState("");
  const [investment, setInvestment] = useState("");
  const [result, setResult] = useState<BacktestResult | null>(null);

  // Sync symbol from watchlist selection (only on initial load / watchlist changes)
  useEffect(() => {
    if (activeSymbol && !symbol) {
      setSymbol(activeSymbol);
    }
  }, [activeSymbol, symbol]);

  const { data: tickerData, isLoading } = useQuery({
    queryKey: ["ticker", symbol],
    queryFn: () => {
      const params = new URLSearchParams({ key: process.env.AUTH_KEY || "" });
      return fetch(`/api/proxy/fetch/ticker/${symbol}?${params}`).then((r) => r.json());
    },
    enabled: false,
  });

  const runBacktest = async () => {
    if (!symbol || !entryDate || !investment) return;
    const inv = parseFloat(investment);
    if (isNaN(inv) || inv <= 0) return;

    // Fetch ticker data to get current price + historical prices
    const params = new URLSearchParams({ key: process.env.AUTH_KEY || "" });
    const res = await fetch(`/api/proxy/fetch/ticker/${symbol.toUpperCase()}?${params}`);
    if (!res.ok) return;
    const data = await res.json();
    const ohlcv = data.ohlcv || [];
    const currentPrice = data.info?.price;
    if (!currentPrice || ohlcv.length === 0) return;

    // Find entry price on entryDate
    const entryIdx = ohlcv.findIndex((d: { date: string }) => d.date >= entryDate);
    if (entryIdx < 0) return;
    const entryPrice = ohlcv[entryIdx].close;
    const shares = inv / entryPrice;
    const currentValue = shares * currentPrice;
    const totalReturn = currentValue - inv;
    const totalReturnPct = (totalReturn / inv) * 100;
    const priceChangePct = ((currentPrice - entryPrice) / entryPrice) * 100;
    const exitDate = ohlcv[ohlcv.length - 1].date;

    setResult({
      symbol: symbol.toUpperCase(),
      entryDate: ohlcv[entryIdx].date,
      exitDate,
      investment: inv,
      shares,
      entryPrice,
      exitPrice: currentPrice,
      currentValue,
      totalReturn,
      totalReturnPct,
      priceChangePct,
    });
  };

  const fmt = (n: number) =>
    n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Backtest</h1>
          <p className="text-muted-foreground mt-1">
            See what a hypothetical investment would be worth today.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => setShowSearch(true)}>+ Add to Watchlist</Button>
      </div>

      {watchlistLoading ? (
        <Skeleton className="h-12 w-full" />
      ) : (
        <WatchlistTabs
          watchlist={watchlist}
          activeSymbol={activeSymbol}
          onSelect={(sym) => {
            setActiveSymbol(sym);
            setSymbol(sym);
          }}
          onRemove={removeStock}
          onAdd={() => setShowSearch(true)}
        />
      )}

      {symbol && (
        <p className="text-sm text-muted-foreground">Selected: <span className="font-semibold text-foreground">{symbol}</span></p>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Calculator className="w-4 h-4" />
            Investment Calculator
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Ticker</label>
              <Input
                placeholder="e.g. AAPL"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                className="uppercase"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Entry Date</label>
              <Input
                type="date"
                value={entryDate}
                onChange={(e) => setEntryDate(e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Investment ($)</label>
              <Input
                type="number"
                placeholder="e.g. 10000"
                value={investment}
                onChange={(e) => setInvestment(e.target.value)}
                min={0}
              />
            </div>
            <div className="flex items-end">
              <Button onClick={runBacktest} disabled={!symbol || !entryDate || !investment} className="w-full">
                Calculate
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {result && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              {result.totalReturn >= 0 ? (
                <TrendingUp className="w-4 h-4 text-green-500" />
              ) : (
                <TrendingDown className="w-4 h-4 text-red-500" />
              )}
              {result.symbol} — {result.totalReturn >= 0 ? "Profit" : "Loss"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {/* Timeline */}
              <div className="flex items-center gap-3 text-sm">
                <div className="text-center">
                  <p className="text-xs text-muted-foreground">Entry</p>
                  <p className="font-semibold">{result.entryDate}</p>
                  <p className="text-muted-foreground">${result.entryPrice.toFixed(2)}</p>
                </div>
                <ArrowRight className="w-4 h-4 text-muted-foreground shrink-0" />
                <div className="text-center">
                  <p className="text-xs text-muted-foreground">Exit</p>
                  <p className="font-semibold">{result.exitDate}</p>
                  <p className="text-muted-foreground">${result.exitPrice.toFixed(2)}</p>
                </div>
              </div>

              {/* Metrics grid */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="p-4 rounded-lg border">
                  <p className="text-xs text-muted-foreground mb-1">Investment</p>
                  <p className="text-xl font-bold">${fmt(result.investment)}</p>
                </div>
                <div className="p-4 rounded-lg border">
                  <p className="text-xs text-muted-foreground mb-1">Shares Bought</p>
                  <p className="text-xl font-bold">{result.shares.toFixed(4)}</p>
                </div>
                <div className="p-4 rounded-lg border">
                  <p className="text-xs text-muted-foreground mb-1">Current Value</p>
                  <p className={`text-xl font-bold ${result.currentValue >= result.investment ? "text-green-500" : "text-red-500"}`}>
                    ${fmt(result.currentValue)}
                  </p>
                </div>
                <div className="p-4 rounded-lg border">
                  <p className="text-xs text-muted-foreground mb-1">Total Return</p>
                  <p className={`text-xl font-bold ${result.totalReturn >= 0 ? "text-green-500" : "text-red-500"}`}>
                    {result.totalReturn >= 0 ? "+" : ""}${fmt(result.totalReturn)}
                    <span className="text-sm font-normal ml-1">
                      ({result.totalReturn >= 0 ? "+" : ""}{result.totalReturnPct.toFixed(2)}%)
                    </span>
                  </p>
                </div>
              </div>

              {/* Price change breakdown */}
              <div className="text-sm text-muted-foreground flex items-center gap-2">
                <span>Entry ${result.entryPrice.toFixed(2)} → Exit ${result.exitPrice.toFixed(2)}</span>
                <span className={result.priceChangePct >= 0 ? "text-green-500" : "text-red-500"}>
                  {result.priceChangePct >= 0 ? "+" : ""}{result.priceChangePct.toFixed(2)}% price change
                </span>
                <span>|</span>
                <span>{result.shares.toFixed(4)} shares held</span>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <p className="text-xs text-muted-foreground text-center">
        Uses end-of-day closing prices. Does not account for dividends, taxes, or slippage. Not financial advice.
      </p>

      {showSearch && <SearchModal onClose={() => setShowSearch(false)} onAdd={addStock} />}
    </div>
  );
}