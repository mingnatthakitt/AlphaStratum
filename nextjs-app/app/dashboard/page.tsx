"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { stockApi, type StockInfo, type OHLCVData } from "@/lib/api";
import CandlestickChart from "@/components/CandlestickChart";
import CompareChart from "@/components/CompareChart";
import RegimeBadge from "@/components/RegimeBadge";
import RSIChart from "@/components/RSIChart";
import MACDBarChart from "@/components/MACDBarChart";
import BollingerChart from "@/components/BollingerChart";
import GarchChart from "@/components/GarchChart";
import AtrChart from "@/components/AtrChart";
import RegimeCondChart from "@/components/RegimeCondChart";
import MonteCarloChart from "@/components/MonteCarloChart";
import MarkovChart from "@/components/MarkovChart";
import { QueryRender, ErrorBox } from "@/components/QueryFeedback";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ArrowUpDown, Activity } from "lucide-react";
import { WatchlistTabs, SearchModal } from "@/components/StockWatchlist";
import { Button } from "@/components/ui/button";
import { useWatchlist } from "@/contexts/WatchlistContext";

const MODEL_OPTIONS = [
  { id: "rsi", label: "RSI" },
  { id: "macd", label: "MACD" },
  { id: "bollinger", label: "Bollinger" },
  { id: "garch", label: "GARCH" },
  { id: "atr", label: "ATR" },
  { id: "markov", label: "Markov" },
  { id: "mc-standard", label: "MC (Std)" },
  { id: "mc-regime", label: "MC (Regime)" },
] as const;
type ModelId = (typeof MODEL_OPTIONS)[number]["id"];

export default function DashboardPage() {
  const { watchlist, activeSymbol, setActiveSymbol, addStock, removeStock, isLoading: watchlistLoading } = useWatchlist();
  const [showSearch, setShowSearch] = useState(false);
  const [mcHorizon, setMcHorizon] = useState(30);
  const [chartView, setChartView] = useState<"candle" | "area">("candle");
  const [showCompare, setShowCompare] = useState(false);
  const [compareSymbol, setCompareSymbol] = useState<string | null>(null);
  const [showCompareSearch, setShowCompareSearch] = useState(false);
  const [compareModel, setCompareModel] = useState<ModelId | null>(null);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["ticker", activeSymbol],
    queryFn: () => stockApi.getTicker(activeSymbol),
    enabled: !!activeSymbol,
  });

  // Model queries are gated on the compare panel being open for that model —
  // switching symbols no longer fires ~10 requests for hidden charts.
  const { data: regimeData, isError: regimeError, error: regimeErrorDetails } = useQuery({
    queryKey: ["regime", activeSymbol],
    queryFn: () => stockApi.getRegime(activeSymbol),
    enabled: !!activeSymbol,
  });

  const { data: mcData, isLoading: mcLoading, isPending: mcPending, isError: mcError, error: mcErrorDetails, refetch: mcRefetch } = useQuery({
    queryKey: ["montecarlo", activeSymbol, mcHorizon],
    queryFn: () => stockApi.getMonteCarlo(activeSymbol, mcHorizon),
    enabled: compareModel === "mc-standard",
  });

  const { data: mcRegimeCondData, isLoading: mcRegimeCondLoading, isPending: mcRegimeCondPending, isError: mcRegimeCondError, error: mcRegimeCondErrorDetails, refetch: mcRegimeCondRefetch } = useQuery({
    queryKey: ["montecarlo-regime-cond", activeSymbol, mcHorizon] as const,
    queryFn: () => stockApi.getMonteCarloRegimeCond(activeSymbol, mcHorizon),
    enabled: compareModel === "mc-regime",
  });

  const { data: rsiData, isLoading: rsiLoading, isPending: rsiPending, isError: rsiError, error: rsiErrorDetails, refetch: rsiRefetch } = useQuery({
    queryKey: ["rsi", activeSymbol],
    queryFn: () => stockApi.getRSI(activeSymbol),
    enabled: compareModel === "rsi",
  });

  const { data: macdData, isLoading: macdLoading, isPending: macdPending, isError: macdError, error: macdErrorDetails, refetch: macdRefetch } = useQuery({
    queryKey: ["macd", activeSymbol],
    queryFn: () => stockApi.getMACD(activeSymbol),
    enabled: compareModel === "macd",
  });

  const { data: bollingerData, isLoading: bollingerLoading, isPending: bollingerPending, isError: bollingerError, error: bollingerErrorDetails, refetch: bollingerRefetch } = useQuery({
    queryKey: ["bollinger", activeSymbol],
    queryFn: () => stockApi.getBollinger(activeSymbol),
    enabled: compareModel === "bollinger",
  });

  const { data: garchData, isLoading: garchLoading, isPending: garchPending, isError: garchError, error: garchErrorDetails, refetch: garchRefetch } = useQuery({
    queryKey: ["garch", activeSymbol],
    queryFn: () => stockApi.getGarch(activeSymbol),
    enabled: compareModel === "garch",
  });

  const { data: atrData, isLoading: atrLoading, isPending: atrPending, isError: atrError, error: atrErrorDetails, refetch: atrRefetch } = useQuery({
    queryKey: ["atr", activeSymbol],
    queryFn: () => stockApi.getAtr(activeSymbol),
    enabled: compareModel === "atr",
  });

  const { data: markovData, isLoading: markovLoading, isPending: markovPending, isError: markovError, error: markovErrorDetails, refetch: markovRefetch } = useQuery({
    queryKey: ["markov", activeSymbol],
    queryFn: () => stockApi.getMarkov(activeSymbol),
    enabled: compareModel === "markov",
  });

  const { data: compareData, isLoading: compareLoading } = useQuery({
    queryKey: ["ticker", compareSymbol],
    queryFn: () => stockApi.getTicker(compareSymbol as string),
    enabled: showCompare && !!compareSymbol,
  });

  const info: StockInfo | undefined = data?.data?.info;
  const ohlcv: OHLCVData[] = data?.data?.ohlcv || [];
  const compareOhlcv: OHLCVData[] = compareData?.data?.ohlcv || [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Dashboard</h1>
      </div>

      {watchlistLoading ? (
        <div className="flex items-center gap-2">
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-8 w-32" />
        </div>
      ) : (
        <WatchlistTabs
          watchlist={watchlist}
          activeSymbol={activeSymbol}
          onSelect={setActiveSymbol}
          onRemove={removeStock}
          onOpenSearch={() => setShowSearch(true)}
        />
      )}

      {error && (
        <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-500 text-sm flex items-center justify-between">
          <span>Failed to load data for {activeSymbol}. Check the ticker symbol or try again.</span>
          <Button size="sm" variant="outline" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <div className="flex items-center gap-2">
                <CardTitle className="text-xl">{activeSymbol}</CardTitle>
                {info && <span className="text-2xl font-bold">${info.price.toFixed(2)}</span>}
                {info && (
                  <span className={`text-sm ${info.change >= 0 ? "text-green-500" : "text-red-500"}`}>
                    {info.change >= 0 ? "+" : ""}
                    {info.change.toFixed(2)} ({info.changePercent.toFixed(2)}%)
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <div className="flex rounded border border-border overflow-hidden text-xs">
                  {(["candle", "area"] as const).map((v) => (
                    <button
                      key={v}
                      onClick={() => setChartView(v)}
                      className={`px-2.5 py-1 font-medium capitalize ${chartView === v ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:bg-muted/80"}`}
                    >
                      {v}
                    </button>
                  ))}
                </div>
                {regimeData?.data && <RegimeBadge regime={regimeData.data.currentRegime} />}
                {(compareModel === "mc-standard" || compareModel === "mc-regime") && (
                  <select
                    value={mcHorizon}
                    onChange={(e) => setMcHorizon(Number(e.target.value))}
                    className="rounded border border-input bg-background px-2 py-1 text-xs"
                    aria-label="Monte Carlo horizon"
                  >
                    <option value={15}>15d</option>
                    <option value={30}>30d</option>
                    <option value={60}>60d</option>
                    <option value={90}>90d</option>
                    <option value={180}>180d</option>
                  </select>
                )}
                <select
                  value={compareModel ?? ""}
                  onChange={(e) => setCompareModel(e.target.value ? (e.target.value as ModelId) : null)}
                  className="rounded border border-input bg-background px-2 py-1 text-xs"
                  aria-label="Add a model comparison panel"
                >
                  <option value="">+ Model</option>
                  {MODEL_OPTIONS.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                </select>
                <Button
                  variant={showCompare ? "default" : "outline"}
                  size="sm"
                  onClick={() => {
                    if (!showCompare) setShowCompareSearch(true);
                    else {
                      setShowCompare(false);
                      setCompareSymbol(null);
                    }
                  }}
                  className="gap-1.5 text-xs"
                >
                  {showCompare ? "Exit Compare" : "Compare"}
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {showCompare ? (
                compareSymbol && compareOhlcv.length > 0 ? (
                  <CompareChart
                    primary={{ data: ohlcv, symbol: activeSymbol }}
                    secondary={{ data: compareOhlcv, symbol: compareSymbol }}
                  />
                ) : compareLoading ? (
                  <Skeleton className="h-[400px] w-full" />
                ) : (
                  <div className="h-[400px] flex items-center justify-center text-muted-foreground">
                    {compareSymbol
                      ? `Couldn't load data for ${compareSymbol} — try another ticker.`
                      : "Pick a ticker to compare."}
                  </div>
                )
              ) : isLoading ? (
                <Skeleton className="h-[400px] w-full" />
              ) : ohlcv.length > 0 ? (
                <CandlestickChart data={ohlcv} symbol={activeSymbol} view={chartView} />
              ) : (
                <div className="h-[400px] flex items-center justify-center text-muted-foreground">No chart data available</div>
              )}
            </CardContent>
          </Card>

          {/* Model comparison panel */}
          {compareModel && (
            <Card className="mt-4">
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base capitalize">
                    {MODEL_OPTIONS.find((m) => m.id === compareModel)?.label} — {activeSymbol}
                  </CardTitle>
                  <button onClick={() => setCompareModel(null)} className="text-xs text-muted-foreground hover:text-primary">
                    ✕ Close
                  </button>
                </div>
              </CardHeader>
              <CardContent>
                {compareModel === "rsi" && (
                  <QueryRender data={rsiData?.data} isLoading={rsiLoading} isPending={rsiPending} isError={rsiError} error={rsiErrorDetails} refetch={rsiRefetch}>
                    {(d) => <RSIChart rsi={d.rsi} signal={d.signal} history={d.history} dates={d.dates} />}
                  </QueryRender>
                )}
                {compareModel === "macd" && (
                  <QueryRender data={macdData?.data} isLoading={macdLoading} isPending={macdPending} isError={macdError} error={macdErrorDetails} refetch={macdRefetch}>
                    {(d) => (
                      <MACDBarChart
                        macd={d.macd}
                        signal={d.signal}
                        histogram={d.histogram}
                        macdHistory={d.macdHistory}
                        signalHistory={d.signalHistory}
                        histogramHistory={d.histogramHistory}
                        dates={d.dates}
                      />
                    )}
                  </QueryRender>
                )}
                {compareModel === "bollinger" && (
                  <QueryRender data={bollingerData?.data} isLoading={bollingerLoading} isPending={bollingerPending} isError={bollingerError} error={bollingerErrorDetails} refetch={bollingerRefetch}>
                    {(d) => (
                      <BollingerChart
                        sma={d.sma}
                        upper={d.upper}
                        lower={d.lower}
                        bandwidth={d.bandwidth}
                        percentB={d.percentB}
                        period={d.period}
                        numStd={d.numStd}
                        history={d.history}
                        dates={d.dates}
                      />
                    )}
                  </QueryRender>
                )}
                {compareModel === "garch" && (
                  <QueryRender data={garchData?.data} isLoading={garchLoading} isPending={garchPending} isError={garchError} error={garchErrorDetails} refetch={garchRefetch}>
                    {(d) => <GarchChart data={d} />}
                  </QueryRender>
                )}
                {compareModel === "atr" && (
                  <QueryRender data={atrData?.data} isLoading={atrLoading} isPending={atrPending} isError={atrError} error={atrErrorDetails} refetch={atrRefetch}>
                    {(d) => <AtrChart data={d} />}
                  </QueryRender>
                )}
                {compareModel === "markov" && (
                  <QueryRender data={markovData?.data} isLoading={markovLoading} isPending={markovPending} isError={markovError} error={markovErrorDetails} refetch={markovRefetch}>
                    {(d) => <MarkovChart data={d} />}
                  </QueryRender>
                )}
                {compareModel === "mc-standard" && (
                  <QueryRender data={mcData?.data} isLoading={mcLoading} isPending={mcPending} isError={mcError} error={mcErrorDetails} refetch={mcRefetch} height="400px">
                    {(d) => <MonteCarloChart data={d} />}
                  </QueryRender>
                )}
                {compareModel === "mc-regime" && (
                  <QueryRender
                    data={mcRegimeCondData?.data}
                    isLoading={mcRegimeCondLoading} isPending={mcRegimeCondPending}
                    isError={mcRegimeCondError} error={mcRegimeCondErrorDetails}
                    refetch={mcRegimeCondRefetch}
                    height="400px"
                  >
                    {(d) => <RegimeCondChart data={d} />}
                  </QueryRender>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Activity className="w-4 h-4" />
                Key Statistics
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-0">
              {isLoading ? (
                Array.from({ length: 7 }).map((_, i) => <Skeleton key={i} className="h-8 w-full mb-2" />)
              ) : info ? (
                <>
                  <div className="flex justify-between items-center py-2 border-b border-border/50">
                    <span className="text-sm text-muted-foreground">Market Cap</span>
                    <span className="text-sm font-medium">
                      {info.marketCap > 0
                        ? info.marketCap >= 1e12
                          ? `$${(info.marketCap / 1e12).toFixed(2)}T`
                          : `$${(info.marketCap / 1e9).toFixed(2)}B`
                        : "N/A"}
                    </span>
                  </div>
                  <div className="flex justify-between items-center py-2 border-b border-border/50">
                    <span className="text-sm text-muted-foreground">P/E Ratio</span>
                    <span className="text-sm font-medium">{info.pe > 0 ? info.pe.toFixed(2) : "N/A"}</span>
                  </div>
                  <div className="flex justify-between items-center py-2 border-b border-border/50">
                    <span className="text-sm text-muted-foreground">Volume</span>
                    <span className="text-sm font-medium">
                      {info.volume >= 1e6 ? `${(info.volume / 1e6).toFixed(2)}M` : `${(info.volume / 1e3).toFixed(0)}K`}
                    </span>
                  </div>
                  <div className="flex justify-between items-center py-2 border-b border-border/50">
                    <span className="text-sm text-muted-foreground">52W High</span>
                    <span className="text-sm font-medium">${info.weekHigh52.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between items-center py-2 border-b border-border/50">
                    <span className="text-sm text-muted-foreground">52W Low</span>
                    <span className="text-sm font-medium">${info.weekLow52.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between items-center py-2 border-b border-border/50">
                    <span className="text-sm text-muted-foreground">Daily Change</span>
                    <span className={`text-sm font-medium ${info.change >= 0 ? "text-green-500" : "text-red-500"}`}>
                      {info.change >= 0 ? "+" : ""}
                      {info.change.toFixed(2)} ({info.changePercent.toFixed(2)}%)
                    </span>
                  </div>
                  {regimeData?.data && (
                    <>
                      <div className="flex justify-between items-center py-2 border-b border-border/50">
                        <span className="text-sm text-muted-foreground">20D Momentum</span>
                        <span
                          className={`text-sm font-medium ${regimeData.data.momentum >= 0 ? "text-green-500" : "text-red-500"}`}
                        >
                          {regimeData.data.momentum >= 0 ? "+" : ""}
                          {regimeData.data.momentum.toFixed(1)}%
                        </span>
                      </div>
                      <div className="flex justify-between items-center py-2 border-b border-border/50">
                        <span className="text-sm text-muted-foreground">Ann. Volatility</span>
                        <span className="text-sm font-medium">{regimeData.data.volatility.toFixed(1)}%</span>
                      </div>
                    </>
                  )}
                </>
              ) : (
                <p className="text-sm text-muted-foreground">No data available</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <ArrowUpDown className="w-4 h-4" />
                Regime Detection
              </CardTitle>
            </CardHeader>
            <CardContent>
              {regimeError ? (
                <ErrorBox height="80px" message="Regime data unavailable" />
              ) : regimeData?.data ? (
                <div className="space-y-3">
                  <div className="flex justify-between">
                    <span className="text-sm text-muted-foreground">Current Regime</span>
                    <RegimeBadge regime={regimeData.data.currentRegime} />
                  </div>
                  {Object.entries(regimeData.data.probabilities).map(([regime, prob]) => (
                    <div key={regime} className="space-y-1">
                      <div className="flex justify-between text-xs">
                        <span className="capitalize">{regime}</span>
                        <span>{((prob as number) * 100).toFixed(1)}%</span>
                      </div>
                      <div
                        className="h-1.5 rounded-full bg-muted overflow-hidden"
                        role="meter"
                        aria-label={`${regime} probability`}
                        aria-valuenow={Math.round((prob as number) * 100)}
                        aria-valuemin={0}
                        aria-valuemax={100}
                      >
                        <div
                          className={`h-full rounded-full ${regime === "bull" ? "bg-green-500" : regime === "bear" ? "bg-red-500" : "bg-yellow-500"}`}
                          style={{ width: `${(prob as number) * 100}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <Skeleton className="h-20 w-full" />
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <p className="text-xs text-muted-foreground text-center">
        Regime detection uses daily return thresholds. Monte Carlo forecasts are probability distributions, not predictions. Not
        financial advice.
      </p>

      {showSearch && <SearchModal onClose={() => setShowSearch(false)} onAdd={addStock} />}
      {showCompareSearch && (
        <SearchModal
          onClose={() => setShowCompareSearch(false)}
          onAdd={(item) => {
            setCompareSymbol(item.symbol);
            setShowCompareSearch(false);
            setShowCompare(true);
          }}
        />
      )}
    </div>
  );
}
