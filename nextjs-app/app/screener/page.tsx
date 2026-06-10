"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { stockApi, type ScreenerStock } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { ArrowUpDown, TrendingUp, TrendingDown, Info, Star } from "lucide-react";
import { Button } from "@/components/ui/button";

const SCORE_LEGEND = [
  { label: "Momentum", desc: "20-day return (%)\nPositive = recent uptrend" },
  { label: "Vol", desc: "Annualized volatility (%)\nLower = more stable" },
  { label: "Score", desc: "Sharpe-inspired composite (0-100)\n= regime + momentum − vol_penalty\nBull regime (40) + positive momentum (40) − low vol (0)" },
];

const SECTORS = ["tech", "finance", "healthcare", "energy", "etf"] as const;
  type Sector = (typeof SECTORS)[number];
  const SECTOR_LABELS: Record<Sector, string> = {
    tech: "Tech",
    finance: "Finance",
    healthcare: "Healthcare",
    energy: "Energy",
    etf: "ETF",
  };

export default function ScreenerPage() {
  const [sector, setSector] = useState<Sector>("tech");

  // Load portfolio holdings from Supabase
  const { data: holdings = [] } = useQuery({
    queryKey: ["portfolio-holdings"],
    queryFn: () => stockApi.getHoldings().then((r) => r.data ?? []),
    staleTime: 30_000,
  });

  const portfolioSymbols = holdings.map((h) => h.symbol);

  const { data: sectorData, isLoading } = useQuery({
    queryKey: ["screener", sector],
    queryFn: async () => (await stockApi.getScreener(sector)).data,
    enabled: true,
    staleTime: 60_000,
  });

  // Also fetch portfolio holdings regime/score data if any
  // Batched with 150ms stagger per batch of 5 to avoid Yahoo Finance rate limiting
  const { data: watchlistScreenerData } = useQuery({
    queryKey: ["screener", "portfolio"],
    queryFn: async () => {
      if (portfolioSymbols.length === 0) return null;
      const BATCH_SIZE = 5;
      const STAGGER_MS = 150;

      const fetchOne = async (sym: string) => {
        const ticker = await stockApi.getTicker(sym).then((r) => r.data);
        const reg = await stockApi.getRegime(sym).then((r) => r.data);
        return { ticker, reg };
      };

      const batches: Promise<{ ticker: any; reg: any; sym: string }>[] = [];
      for (let i = 0; i < portfolioSymbols.length; i++) {
        batches.push(fetchOne(portfolioSymbols[i]));
        if ((i + 1) % BATCH_SIZE === 0 && i < portfolioSymbols.length - 1) {
          await new Promise((r) => setTimeout(r, STAGGER_MS));
        }
      }

      const results = await Promise.allSettled(batches);
      return results
        .filter((r) => r.status === "fulfilled")
        .map((r, i) => {
          const { ticker, reg } = r.value as { ticker: any; reg: any };
          const sym = portfolioSymbols[i];
          return {
            symbol: sym,
            name: ticker?.info?.name || sym,
            price: ticker?.info?.price || 0,
            change: ticker?.info?.changePercent || 0,
            regime: reg?.currentRegime || "sideways",
            momentum: reg?.momentum || 0,
            volatility: reg?.volatility || 0,
            score: 0,
            probBull: reg?.probabilities?.bull || 0,
            probBear: reg?.probabilities?.bear || 0,
            probSideways: reg?.probabilities?.sideways || 0,
          } as ScreenerStock;
        });
    },
    enabled: portfolioSymbols.length > 0,
    staleTime: 60_000,
  });

  // Combine sector + watchlist, dedupe by symbol, rank by score.
  // Portfolio stocks (watchlistScreenerData) are only included if their symbol
  // actually appears in the current sector's stock list — prevents NVDA from
  // showing up in finance/healthcare when it's a tech stock.
  const stocks = useMemo(() => {
    const sectorStocks = sectorData?.stocks || [];
    const sectorSymbols = new Set(sectorStocks.map((s) => s.symbol));
    const watchlistStocks = (watchlistScreenerData || []).filter((w) =>
      sectorSymbols.has(w.symbol)
    );
    const seen = new Set<string>();
    const all: ScreenerStock[] = [...sectorStocks, ...watchlistStocks];
    const scored = all.map((s) => {
      if (s.score === 0) {
        const regimeScore = s.regime === "bull" ? 40 : s.regime === "bear" ? 0 : 20;
        const momentumScore = Math.max(0, Math.min(40, (s.momentum as number) * 2));
        const volPenalty = Math.min(20, (s.volatility as number) * 0.4);
        return { ...s, score: Math.max(0, Math.round(regimeScore + momentumScore - volPenalty)) };
      }
      return s;
    });
    return scored.filter((s) => {
      if (seen.has(s.symbol)) return false;
      seen.add(s.symbol);
      return true;
    }).sort((a, b) => b.score - a.score);
  }, [sectorData, watchlistScreenerData]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Stock Screener</h1>
        <div className="flex gap-2">
          {SECTORS.map((s) => (
            <Button
              key={s}
              variant={sector === s ? "default" : "outline"}
              size="sm"
              onClick={() => setSector(s)}
            >
              {SECTOR_LABELS[s]}
            </Button>
          ))}
        </div>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <ArrowUpDown className="w-4 h-4" />
            <CardTitle>
              Top Opportunities — {SECTOR_LABELS[sector]} Sector
            </CardTitle>
          </div>
          {/* Legend — full width below title */}
          <div className="flex items-start gap-6 mt-2 text-xs text-muted-foreground flex-wrap">
            {SCORE_LEGEND.map((l) => (
              <div key={l.label} className="flex items-start gap-1.5">
                <Info className="w-3 h-3 mt-0.5 text-primary/60 shrink-0" />
                <span className="font-medium">{l.label}:</span>
                <span className="whitespace-pre-line leading-relaxed">{l.desc}</span>
              </div>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          {isLoading || (holdings.length > 0 && !watchlistScreenerData) ? (
            <div className="space-y-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : stocks.length === 0 ? (
            <p className="text-muted-foreground text-center py-8">
              No data available. Yahoo Finance may be rate-limited. Try again shortly.
            </p>
          ) : (
            <div className="space-y-3">
              {stocks.map((stock) => (
                <div
                  key={stock.symbol}
                  className="flex items-center justify-between p-4 rounded-lg border hover:border-primary/50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <div className="text-left min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="font-semibold">{stock.symbol}</p>
                        {portfolioSymbols.includes(stock.symbol) && (
                          <span className="flex items-center gap-0.5 text-amber-400 text-xs">
                            <Star className="w-3 h-3 fill-amber-400" /> Portfolio
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground truncate max-w-[160px]">{stock.name}</p>
                    </div>
                    <Badge
                      variant={stock.regime === "bull" ? "default" : stock.regime === "bear" ? "destructive" : "secondary"}
                      className="capitalize"
                    >
                      {stock.regime}
                    </Badge>
                  </div>

                  <div className="flex items-center gap-6 text-sm">
                    <div className="text-right">
                      <p className="font-semibold">${stock.price > 0 ? stock.price.toFixed(2) : "—"}</p>
                      <p className={`text-xs ${stock.change >= 0 ? "text-green-500" : "text-red-500"} flex items-center justify-end gap-0.5`}>
                        {stock.change >= 0 ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                        {stock.change !== 0 ? `${stock.change >= 0 ? "+" : ""}${stock.change.toFixed(2)}%` : "—"}
                      </p>
                    </div>
                    <div className="text-right w-16">
                      <p className="text-xs text-muted-foreground">Momentum</p>
                      <p className="font-medium">{stock.momentum.toFixed(1)}%</p>
                    </div>
                    <div className="text-right w-16">
                      <p className="text-xs text-muted-foreground">Vol</p>
                      <p className="font-medium">{stock.volatility.toFixed(1)}%</p>
                    </div>
                    <div className="text-right w-16">
                      <p className="text-xs text-muted-foreground">Score</p>
                      <p className="font-bold text-primary">{stock.score}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground text-center">
        Scores based on regime stability, momentum, and volatility. Not financial advice.
      </p>
    </div>
  );
}