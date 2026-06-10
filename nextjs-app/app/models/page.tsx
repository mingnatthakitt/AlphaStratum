"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { stockApi } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import MonteCarloChart from "@/components/MonteCarloChart";
import RegimeCondChart from "@/components/RegimeCondChart";
import GarchChart from "@/components/GarchChart";
import CorrelationGraph from "@/components/CorrelationGraph";
import MarkovChart from "@/components/MarkovChart";
import RSIChart from "@/components/RSIChart";
import MACDBarChart from "@/components/MACDBarChart";
import BollingerChart from "@/components/BollingerChart";
import PairsCard from "@/components/PairsCard";
import AnalystCard from "@/components/AnalystCard";
import AtrChart from "@/components/AtrChart";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { WatchlistTabs, SearchModal, type WatchlistItem } from "@/components/StockWatchlist";
import { useWatchlist } from "@/contexts/WatchlistContext";
import { Info, TrendingUp, Activity, BarChart2, AlertTriangle, GitBranch, Users, Zap } from "lucide-react";

const MODELS_LEGEND = [
  {
    tab: "montecarlo",
    title: "Monte Carlo (GBM)",
    desc: "Simulates 1,000 price paths using Geometric Brownian Motion. Shows percentile bands (p5–p95) for the forecast range. Helps assess the range of possible outcomes given current volatility.",
    formula: "S(t+dt) = S(t) · exp((μ − σ²/2)·dt + σ·√dt·Z)",
  },
  {
    tab: "garch",
    title: "GARCH Volatility",
    desc: "GARCH(1,1) models conditional volatility — how uncertainty evolves over time. Forecasts the next 30 days of daily volatility, annualized for comparison with historical levels.",
    formula: "σ²ₜ = ω + α·r²ₜ₋₁ + β·σ²ₜ₋₁",
  },
  {
    tab: "markov",
    title: "Markov Regime Chain",
    desc: "Classifies daily returns into Bull (>+0.5%), Bear (<−0.5%), or Sideways regimes using threshold rules. Computes the transition probability matrix and forecasts regime probabilities 1, 3, and 10 days ahead.",
    formula: "Regime: return > +0.5% → Bull | return < −0.5% → Bear | else → Sideways",
  },
  {
    tab: "correlation",
    title: "Correlation Network",
    desc: "Builds a correlation matrix from 60-day returns and extracts the Minimum Spanning Tree to show the most important relationships. Nodes are sized by connectivity — more connected stocks are larger.",
    formula: "Pearson correlation on log-returns → MST → community clusters",
  },
];

const CORRELATION_SECTORS = [
  { key: "tech", label: "Tech" },
  { key: "broad", label: "Broad Market" },
  { key: "semiconductors", label: "Semiconductors" },
  { key: "dividends", label: "Dividends" },
  { key: "finance", label: "Finance" },
  { key: "healthcare", label: "Healthcare" },
  { key: "energy", label: "Energy" },
];

const MODELS_NAV = [
  { id: "montecarlo", label: "Monte Carlo", icon: TrendingUp },
  { id: "garch", label: "GARCH", icon: Activity },
  { id: "markov", label: "Markov Chain", icon: BarChart2 },
  { id: "rsi", label: "RSI", icon: Activity },
  { id: "macd", label: "MACD", icon: Activity },
  { id: "bollinger", label: "Bollinger", icon: BarChart2 },
  { id: "atr", label: "ATR", icon: Zap },
  { id: "pairs", label: "Pairs / Beta", icon: GitBranch },
  { id: "analyst", label: "Analyst", icon: Users },
  { id: "correlation", label: "Correlation", icon: GitBranch },
];

export default function ModelsPage() {
  const { watchlist, activeSymbol, setActiveSymbol, addStock, removeStock } = useWatchlist();
  const [showSearch, setShowSearch] = useState(false);
  const [corrSector, setCorrSector] = useState("tech");
  const [mcHorizon, setMcHorizon] = useState(30);
  const [mcMode, setMcMode] = useState<"standard" | "regime-cond">("standard");
  // Pairs second ticker
  const [pairsB, setPairsB] = useState("AMD");
  const { data: mcData, isLoading: mcLoading } = useQuery({
    queryKey: ["montecarlo", activeSymbol, mcHorizon],
    queryFn: () => stockApi.getMonteCarlo(activeSymbol, mcHorizon),
    enabled: !!activeSymbol,
  });

  const { data: mcRegimeCondData, isLoading: mcRegimeCondLoading } = useQuery({
    queryKey: ["montecarlo-regime-cond", activeSymbol, mcHorizon],
    queryFn: () => stockApi.getMonteCarloRegimeCond(activeSymbol, mcHorizon),
    enabled: !!activeSymbol && mcMode === "regime-cond",
  });

  const { data: garchData, isLoading: garchLoading } = useQuery({
    queryKey: ["garch", activeSymbol],
    queryFn: () => stockApi.getGarch(activeSymbol),
    enabled: !!activeSymbol,
  });

  const { data: corrData, isLoading: corrLoading } = useQuery({
    queryKey: ["correlation-graph", corrSector],
    queryFn: () => stockApi.getCorrelationGraph(corrSector),
    enabled: true,
  });

  const { data: markovData, isLoading: markovLoading } = useQuery({
    queryKey: ["markov", activeSymbol],
    queryFn: () => stockApi.getMarkov(activeSymbol),
    enabled: !!activeSymbol,
  });

  const { data: rsiData, isLoading: rsiLoading } = useQuery({
    queryKey: ["rsi", activeSymbol],
    queryFn: () => stockApi.getRSI(activeSymbol),
    enabled: !!activeSymbol,
  });

  const { data: macdData, isLoading: macdLoading } = useQuery({
    queryKey: ["macd", activeSymbol],
    queryFn: () => stockApi.getMACD(activeSymbol),
    enabled: !!activeSymbol,
  });

  const { data: bollingerData, isLoading: bollingerLoading } = useQuery({
    queryKey: ["bollinger", activeSymbol],
    queryFn: () => stockApi.getBollinger(activeSymbol),
    enabled: !!activeSymbol,
  });

  const { data: pairsData, isLoading: pairsLoading } = useQuery({
    queryKey: ["pairs", activeSymbol, pairsB],
    queryFn: () => stockApi.getPairs(activeSymbol, pairsB),
    enabled: !!activeSymbol && !!pairsB && activeSymbol !== pairsB,
  });

  const { data: analystData, isLoading: analystLoading } = useQuery({
    queryKey: ["analyst", activeSymbol],
    queryFn: () => stockApi.getAnalyst(activeSymbol),
    enabled: !!activeSymbol,
  });

  const { data: atrData, isLoading: atrLoading } = useQuery({
    queryKey: ["atr", activeSymbol],
    queryFn: () => stockApi.getAtr(activeSymbol),
    enabled: !!activeSymbol,
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Quantitative Models</h1>
      </div>

      <WatchlistTabs
        watchlist={watchlist}
        activeSymbol={activeSymbol}
        onSelect={setActiveSymbol}
        onRemove={removeStock}
        onAdd={() => setShowSearch(true)}
      />

      {/* Sticky anchor nav */}
      <div className="sticky top-0 z-10 bg-background/95 backdrop-blur border-b mb-4">
        <div className="flex gap-1.5 overflow-x-auto py-2 px-1">
          {MODELS_NAV.map((m) => {
            const Icon = m.icon;
            return (
              <button
                key={m.id}
                onClick={() => document.getElementById(m.id)?.scrollIntoView({ behavior: "smooth", block: "start" })}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-muted text-muted-foreground hover:bg-primary/20 hover:text-primary whitespace-nowrap transition-colors shrink-0"
              >
                <Icon className="w-3.5 h-3.5" />
                {m.label}
              </button>
            );
          })}
        </div>
      </div>

      <Tabs defaultValue="montecarlo" className="w-full">

        <TabsContent value="montecarlo" id="montecarlo" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Monte Carlo — {activeSymbol}</CardTitle>
              <div className="flex items-start gap-2 text-xs text-muted-foreground mt-1">
                <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-primary/60" />
                <p>{MODELS_LEGEND[0].desc}</p>
              </div>
              <p className="text-[10px] font-mono text-muted-foreground/60 mt-1">
                {MODELS_LEGEND[0].formula}
              </p>
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <span className="text-xs text-muted-foreground">Horizon:</span>
                <div className="flex gap-1">
                  {[15, 30, 60, 90, 180].map((d) => (
                    <button
                      key={d}
                      onClick={() => setMcHorizon(d)}
                      className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                        mcHorizon === d
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted text-muted-foreground hover:bg-muted/80"
                      }`}
                    >
                      {d}d
                    </button>
                  ))}
                </div>
                <div className="flex rounded border border-border overflow-hidden text-xs ml-2">
                  {(["standard", "regime-cond"] as const).map((m) => (
                    <button
                      key={m}
                      onClick={() => setMcMode(m)}
                      className={`px-2.5 py-1 font-medium transition-colors ${
                        mcMode === m ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:bg-muted/80"
                      }`}
                    >
                      {m === "standard" ? "Standard" : "Regime-Cond"}
                    </button>
                  ))}
                </div>
                {mcData?.data?.currentRegime && mcMode === "standard" && (
                  <span className="text-xs text-muted-foreground ml-2">
                    <span className="capitalize font-medium">{mcData.data.currentRegime}</span> regime
                    {mcData.data.regimeAdjusted && " (drift adjusted)"}
                  </span>
                )}
              </div>
            </CardHeader>
            <CardContent>
              {mcMode === "standard" ? (
                mcLoading ? (
                  <Skeleton className="h-[400px] w-full" />
                ) : mcData?.data ? (
                  <MonteCarloChart data={mcData.data} />
                ) : (
                  <div className="h-[400px] flex items-center justify-center text-muted-foreground">No data available</div>
                )
              ) : mcRegimeCondLoading ? (
                <Skeleton className="h-[400px] w-full" />
              ) : mcRegimeCondData?.data ? (
                <RegimeCondChart data={mcRegimeCondData.data} />
              ) : (
                <div className="h-[400px] flex items-center justify-center text-muted-foreground">No data available</div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="garch" id="garch" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>GARCH Volatility — {activeSymbol}</CardTitle>
              <div className="flex items-start gap-2 text-xs text-muted-foreground mt-1">
                <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-primary/60" />
                <p>{MODELS_LEGEND[1].desc}</p>
              </div>
              <p className="text-[10px] font-mono text-muted-foreground/60 mt-1">
                {MODELS_LEGEND[1].formula}
              </p>
            </CardHeader>
            <CardContent>
              {garchLoading ? (
                <Skeleton className="h-[400px] w-full" />
              ) : garchData?.data ? (
                <GarchChart data={garchData.data} />
              ) : (
                <div className="h-[400px] flex items-center justify-center text-muted-foreground">
                  No data available
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="markov" id="markov" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Markov Regime Chain — {activeSymbol}</CardTitle>
              <div className="flex items-start gap-2 text-xs text-muted-foreground mt-1">
                <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-primary/60" />
                <p>{MODELS_LEGEND[2].desc}</p>
              </div>
              <p className="text-[10px] font-mono text-muted-foreground/60 mt-1">
                {MODELS_LEGEND[2].formula}
              </p>
            </CardHeader>
            <CardContent>
              {markovLoading ? (
                <Skeleton className="h-[400px] w-full" />
              ) : markovData?.data ? (
                <MarkovChart data={markovData.data} />
              ) : (
                <div className="h-[400px] flex items-center justify-center text-muted-foreground">
                  No data available
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="rsi" id="rsi" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>RSI — {activeSymbol}</CardTitle>
              <div className="flex items-start gap-2 text-xs text-muted-foreground mt-1">
                <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-primary/60" />
                <p>14-day Relative Strength Index. Above 70 = overbought (potential pullback). Below 30 = oversold (potential bounce). RSI above 50 confirms bullish momentum.</p>
              </div>
            </CardHeader>
            <CardContent>
              {rsiLoading ? (
                <Skeleton className="h-[300px] w-full" />
              ) : rsiData?.data ? (
                <RSIChart rsi={rsiData.data.rsi} signal={rsiData.data.signal} history={rsiData.data.history} />
              ) : (
                <div className="h-[300px] flex items-center justify-center text-muted-foreground">No data available</div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="macd" id="macd" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>MACD — {activeSymbol}</CardTitle>
              <div className="flex items-start gap-2 text-xs text-muted-foreground mt-1">
                <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-primary/60" />
                <p>12/26/9 MACD. Histogram bars show the difference between MACD line and signal line. Positive histogram = momentum bullish; negative = bearish.</p>
              </div>
            </CardHeader>
            <CardContent>
              {macdLoading ? (
                <Skeleton className="h-[300px] w-full" />
              ) : macdData?.data ? (
                <MACDBarChart
                  macd={macdData.data.macd}
                  signal={macdData.data.signal}
                  histogram={macdData.data.histogram}
                  macdHistory={macdData.data.macdHistory}
                  signalHistory={macdData.data.signalHistory}
                  histogramHistory={macdData.data.histogramHistory}
                />
              ) : (
                <div className="h-[300px] flex items-center justify-center text-muted-foreground">No data available</div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="bollinger" id="bollinger" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Bollinger Bands — {activeSymbol}</CardTitle>
              <div className="flex items-start gap-2 text-xs text-muted-foreground mt-1">
                <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-primary/60" />
                <p>20-day SMA ± 2 standard deviations. %B shows where price sits within the bands (above1 = above upper band, below 0 = below lower band). Bandwidth measures volatility expansion/contraction.</p>
              </div>
            </CardHeader>
            <CardContent>
              {bollingerLoading ? (
                <Skeleton className="h-[300px] w-full" />
              ) : bollingerData?.data ? (
                <BollingerChart
                  sma={bollingerData.data.sma}
                  upper={bollingerData.data.upper}
                  lower={bollingerData.data.lower}
                  bandwidth={bollingerData.data.bandwidth}
                  percentB={bollingerData.data.percentB}
                  period={bollingerData.data.period}
                  numStd={bollingerData.data.numStd}
                  history={bollingerData.data.history}
                />
              ) : (
                <div className="h-[300px] flex items-center justify-center text-muted-foreground">No data available</div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="atr" id="atr" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Average True Range — {activeSymbol}</CardTitle>
              <div className="flex items-start gap-2 text-xs text-muted-foreground mt-1">
                <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-primary/60" />
                <p>ATR measures realized volatility over the last14 trading days. Use it to size positions: larger ATR = wider stop-loss, smaller position. ATR% (ATR/price) lets you compare volatility across price levels.</p>
              </div>
            </CardHeader>
            <CardContent>
              {atrLoading ? (
                <Skeleton className="h-[300px] w-full" />
              ) : atrData?.data ? (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="p-3 rounded-lg border">
                      <p className="text-xs text-muted-foreground">ATR (14)</p>
                      <p className="text-xl font-bold">${atrData.data.atr.toFixed(2)}</p>
                    </div>
                    <div className="p-3 rounded-lg border">
                      <p className="text-xs text-muted-foreground">ATR %</p>
                      <p className={`text-xl font-bold ${atrData.data.atrPercent > 3 ? "text-red-400" : atrData.data.atrPercent > 1 ? "text-yellow-400" : "text-green-400"}`}>
                        {atrData.data.atrPercent.toFixed(2)}%
                      </p>
                    </div>
                    <div className="p-3 rounded-lg border">
                      <p className="text-xs text-muted-foreground">Signal</p>
                      <p className={`text-xl font-bold capitalize ${atrData.data.signal === "high" ? "text-red-400" : atrData.data.signal === "normal" ? "text-yellow-400" : "text-green-400"}`}>
                        {atrData.data.signal}
                      </p>
                    </div>
                    <div className="p-3 rounded-lg border">
                      <p className="text-xs text-muted-foreground">Last Price</p>
                      <p className="text-xl font-bold">${atrData.data.currentPrice.toFixed(2)}</p>
                    </div>
                  </div>
                  <AtrChart data={atrData.data} />
                  <div className="text-xs text-muted-foreground space-y-1">
                    <p>Volatility signal: <span className="font-medium capitalize">{atrData.data.signal}</span> — {atrData.data.signal === "high" ? "High volatility (>3% ATR), consider smaller positions" : atrData.data.signal === "normal" ? "Normal volatility (1-3% ATR)" : "Low volatility (<1% ATR), wider stop-loss tolerance"}</p>
                    <p>Position sizing example: risk2% of a $50,000 portfolio =<span className="font-medium">$1,000</span>. Position size = $1,000 / ATR = <span className="font-medium">{atrData.data.atr > 0 ? `$${(1000 / atrData.data.atr).toFixed(0)}` : "—"}</span> worth of {activeSymbol}.</p>
                  </div>
                </div>
              ) : (
                <div className="h-[300px] flex items-center justify-center text-muted-foreground">No ATR data available</div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="pairs" id="pairs" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Pairs / Beta — {activeSymbol} vs ?</CardTitle>
              <div className="flex items-start gap-2 text-xs text-muted-foreground mt-1">
                <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-primary/60" />
                <p>Beta measures {activeSymbol}&rsquo;s sensitivity to market moves. Correlation shows how directionally aligned the two stocks are. Based on 1-year daily log returns.</p>
              </div>
              <div className="flex items-center gap-2 mt-2">
                <span className="text-xs text-muted-foreground">Compare with:</span>
                <input
                  value={pairsB}
                  onChange={(e) => setPairsB(e.target.value.toUpperCase())}
                  className="w-20 h-7 rounded border border-input bg-background px-2 text-xs uppercase"
                  maxLength={10}
                />
              </div>
            </CardHeader>
            <CardContent>
              {pairsLoading ? (
                <Skeleton className="h-[200px] w-full" />
              ) : pairsData?.data ? (
                <PairsCard data={pairsData.data} />
              ) : (
                <div className="h-[200px] flex items-center justify-center text-muted-foreground">
                  Enter a ticker to compare
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="analyst" id="analyst" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Analyst Ratings — {activeSymbol}</CardTitle>
              <div className="flex items-start gap-2 text-xs text-muted-foreground mt-1">
                <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-primary/60" />
                <p>Yahoo Finance analyst consensus. Shows buy/hold/sell distribution, mean price target, and upside/downside vs current price.</p>
              </div>
            </CardHeader>
            <CardContent>
              {analystLoading ? (
                <Skeleton className="h-[300px] w-full" />
              ) : analystData?.data ? (
                <AnalystCard data={analystData.data} symbol={activeSymbol} />
              ) : (
                <div className="h-[300px] flex items-center justify-center text-muted-foreground">No analyst data available</div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="correlation" id="correlation" className="mt-4">
          <Card>
            <CardHeader>
              <div className="flex items-start gap-2 text-xs text-muted-foreground mt-1">
                <Info className="w-3.5 h-3.5 mt-0.5 shrink-0 text-primary/60" />
                <p>{MODELS_LEGEND[3].desc}</p>
              </div>
              <p className="text-[10px] font-mono text-muted-foreground/60 mt-1">
                {MODELS_LEGEND[3].formula}
              </p>
              <div className="flex gap-2 mt-3">
                {CORRELATION_SECTORS.map((s) => (
                  <button
                    key={s.key}
                    onClick={() => setCorrSector(s.key)}
                    className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                      corrSector === s.key
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted text-muted-foreground hover:bg-muted/80"
                    }`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </CardHeader>
            <CardContent>
              {corrLoading ? (
                <Skeleton className="h-[500px] w-full" />
              ) : corrData?.data ? (
                <CorrelationGraph nodes={corrData.data.nodes} edges={corrData.data.edges} />
              ) : (
                <div className="h-[500px] flex items-center justify-center text-muted-foreground">
                  Loading sector correlation network...
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <p className="text-xs text-muted-foreground text-center">
        All models use 15-minute cached results. Regime detection is threshold-based (20-day rolling returns), not HMM-smoothed. Monte Carlo forecasts are probability distributions — not predictions. Not financial advice.
      </p>

      {showSearch && <SearchModal onClose={() => setShowSearch(false)} onAdd={addStock} />}
    </div>
  );
}