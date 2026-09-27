"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { stockApi, type ScreenerStock } from "@/lib/api";
import { zipSettled } from "@/lib/chartData";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { ArrowUpDown, TrendingUp, TrendingDown, Info, Star } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyBox, ErrorBox } from "@/components/QueryFeedback";
import { screenerScore } from "@/lib/screener";

const SCORE_LEGEND = [
  {
    label: "Momentum",
    desc: "20-day return (%)\nPositive = recent uptrend",
  },
  {
    label: "Vol",
    desc: "Annualized volatility (%)\nLower = more stable",
  },
  {
    label: "Score",
    desc: "Sharpe-inspired composite (0-100)\n= regime + momentum − vol_penalty\nBull regime (40) + positive momentum (40) − low vol (0)",
  },
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

const BATCH_SIZE = 5;
const BATCH_STAGGER_MS = 150;

export default function ScreenerPage() {
  const [sector, setSector] = useState<Sector>("tech");

  const {
    data: holdings = [],
    isError: holdingsError,
    refetch: refetchHoldings,
  } = useQuery({
    queryKey: ["portfolio-holdings"],
    queryFn: () => stockApi.getHoldings().then((r) => r.data ?? []),
    staleTime: 30_000,
    retry: 1,
  });

  const portfolioSymbols = holdings.map((h) => h.symbol);

  const {
    data: sectorData,
    isLoading,
    isError: sectorError,
    refetch: refetchSector,
  } = useQuery({
    queryKey: ["screener", sector],
    queryFn: async () => (await stockApi.getScreener(sector)).data,
    staleTime: 60_000,
    retry: 1,
  });

  // Portfolio symbols: fetch ticker + regime per symbol in small staggered
  // batches. Results are attributed BY SYMBOL (never re-indexed after
  // filtering — the previous code corrupted rows after any failed fetch).
  const { data: portfolioStocks, isLoading: portfolioLoading, isError: portfolioError } = useQuery({
    queryKey: ["screener", "portfolio", portfolioSymbols.join(",")],
    queryFn: async (): Promise<ScreenerStock[]> => {
      const fetchOne = async (sym: string) => {
        const [ticker, regime] = await Promise.all([
          stockApi.getTicker(sym).then((r) => r.data),
          stockApi.getRegime(sym).then((r) => r.data),
        ]);
        return { ticker, regime };
      };

      const pending: ReturnType<typeof fetchOne>[] = [];
      for (let i = 0; i < portfolioSymbols.length; i++) {
        pending.push(fetchOne(portfolioSymbols[i]));
        if ((i + 1) % BATCH_SIZE === 0 && i < portfolioSymbols.length - 1) {
          await new Promise((r) => setTimeout(r, BATCH_STAGGER_MS));
        }
      }

      const settled = await Promise.allSettled(pending);
      const bySymbol = zipSettled(portfolioSymbols, settled, (value, symbol) => {
        const regime = value.regime;
        if (!regime) return null;
        return {
          symbol,
          name: value.ticker?.info?.name || symbol,
          price: value.ticker?.info?.price || 0,
          change: value.ticker?.info?.changePercent || 0,
          regime: regime.currentRegime,
          momentum: regime.momentum || 0,
          volatility: regime.volatility || 0,
          score: screenerScore(regime.currentRegime, regime.momentum || 0, regime.volatility || 0),
          probBull: regime.probabilities?.bull || 0,
          probBear: regime.probabilities?.bear || 0,
          probSideways: regime.probabilities?.sideways || 0,
        } satisfies ScreenerStock;
      });

      // Preserve the original portfolio order, dropping failed symbols.
      return portfolioSymbols
        .map((symbol) => bySymbol.get(symbol))
        .filter((s): s is ScreenerStock => s !== undefined);
    },
    enabled: portfolioSymbols.length > 0,
    staleTime: 60_000,
    retry: 1,
  });

  // Combine sector + portfolio stocks (portfolio stocks only count when they
  // belong to the active sector), dedupe by symbol, rank by score.
  const stocks = useMemo(() => {
    const sectorStocks = sectorData?.stocks || [];
    const sectorSymbols = new Set(sectorStocks.map((s) => s.symbol));
    const watchlistStocks = (portfolioStocks || []).filter((w) => sectorSymbols.has(w.symbol));
    const all: ScreenerStock[] = [...sectorStocks, ...watchlistStocks];
    const seen = new Set<string>();
    return all
      .filter((s) => {
        if (seen.has(s.symbol)) return false;
        seen.add(s.symbol);
        return true;
      })
      .sort((a, b) => b.score - a.score);
  }, [sectorData, portfolioStocks]);

  const loading = isLoading || portfolioLoading;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Stock Screener</h1>
        <div className="flex gap-2">
          {SECTORS.map((s) => (
            <Button key={s} size="sm" variant={sector === s ? "default" : "outline"} onClick={() => setSector(s)}>
              {SECTOR_LABELS[s]}
            </Button>
          ))}
        </div>
      </div>

      <div className="flex items-start gap-2 text-xs text-muted-foreground">
        <Info className="w-3.5 h-3.5 mt-0.5 shrink-0" />
        <p>
          Rank stocks by regime stability + momentum. Portfolio stocks (starred) appear in their actual sector category.{" "}
          {SCORE_LEGEND[2].desc.split("\n").slice(1).join(" · ")}
        </p>
      </div>

      {sectorError ? (
        <ErrorBox height="300px" onRetry={() => refetchSector()} message="Couldn't load the sector screener — try again." />
      ) : holdingsError ? (
        <ErrorBox
          height="300px"
          onRetry={() => refetchHoldings()}
          message="Couldn't load your portfolio — starred rows may be incomplete."
        />
      ) : loading ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      ) : stocks.length === 0 ? (
        <EmptyBox height="300px" message={`No ${SECTOR_LABELS[sector]} stocks loaded — the market data provider may be rate-limited. Try again shortly.`} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ArrowUpDown className="w-4 h-4" /> {SECTOR_LABELS[sector]} — ranked by score
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {stocks.map((stock, index) => (
              <div key={stock.symbol} className="flex items-center justify-between p-3 rounded-lg border gap-3">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-xs text-muted-foreground w-6">#{index + 1}</span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold">{stock.symbol}</span>
                      {portfolioSymbols.includes(stock.symbol) && (
                        <Star className="w-3.5 h-3.5 text-yellow-400 fill-yellow-400" aria-label="In your portfolio" />
                      )}
                      <Badge variant={stock.regime === "bull" ? "default" : "secondary"} className="capitalize text-xs">
                        {stock.regime}
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground truncate">{stock.name}</p>
                  </div>
                </div>
                <div className="flex items-center gap-4 text-xs shrink-0">
                  <span className={stock.change >= 0 ? "text-green-500" : "text-red-400"}>
                    {stock.change >= 0 ? "+" : ""}
                    {stock.change.toFixed(2)}%
                  </span>
                  <span className="hidden sm:block text-muted-foreground">Mom {stock.momentum.toFixed(1)}%</span>
                  <span className="hidden sm:block text-muted-foreground">Vol {stock.volatility.toFixed(1)}%</span>
                  <span className="font-bold text-primary text-base">{stock.score}</span>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
