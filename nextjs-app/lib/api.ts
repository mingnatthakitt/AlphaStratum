import axios from "axios";

// All requests go through /api/proxy — server-side route attaches ?key= to FastAPI calls
// AUTH_KEY stays server-only (never in browser bundle)
const api = axios.create({
  baseURL: "/api/proxy",
  timeout: 30000,
});

export interface OHLCVData {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface StockInfo {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  volume: number;
  marketCap: number;
  pe: number;
  weekHigh52: number;
  weekLow52: number;
}

export interface RegimeResult {
  currentRegime: "bull" | "bear" | "sideways";
  probabilities: { bull: number; bear: number; sideways: number };
  momentum: number;
  volatility: number;
  lastUpdated: string;
}

export interface MonteCarloResult {
  paths: number[][];
  percentiles: { p5: number[]; p25: number[]; p50: number[]; p75: number[]; p95: number[] };
  forecastDates: string[];
  lastPrice: number;
  currentRegime?: string;
  regimeAdjusted?: boolean;
  horizon?: number;
}

export interface RegimeProb { date: string; bull: number; bear: number; sideways: number; }
export interface Fan { p5: number[]; p25: number[]; p50: number[]; p75: number[]; p95: number[]; }
export interface MonteCarloRegimeCondResult {
  lastPrice: number;
  horizon: number;
  sigma: number;
  volatilitySource: "garch" | "historical";
  currentRegime: string;
  regimeProbabilities: RegimeProb[];
  fans: { bull: Fan; bear: Fan; sideways: Fan };
  blended: Fan;
}

export interface AtrResult {
  atr: number;
  atrPercent: number;
  currentPrice: number;
  period: number;
  signal: "high" | "normal" | "low";
  history: number[];
}

export interface GarchResult {
  currentVol: number;
  forecast: number[];
  forecastDates: string[];
}

export interface MarkovResult {
  currentRegime: "bull" | "bear" | "sideways";
  currentState: number;
  transitionMatrix: {
    bear:    { bear: number; sideways: number; bull: number };
    sideways: { bear: number; sideways: number; bull: number };
    bull:    { bear: number; sideways: number; bull: number };
  };
  expectedDuration: { bear: number; sideways: number; bull: number };
  stationary: { bear: number; sideways: number; bull: number };
  forecast1Step: { bear: number; sideways: number; bull: number };
  forecast3Step: { bear: number; sideways: number; bull: number };
  forecast10Step: { bear: number; sideways: number; bull: number };
  lastUpdated: string;
}

export interface RSIResult {
  rsi: number;
  signal: "overbought" | "oversold" | "neutral";
  period: number;
  history: number[];
}

export interface MACDResult {
  macd: number;
  signal: number;
  histogram: number;
  macdHistory: number[];
  signalHistory: number[];
  histogramHistory: number[];
}

export interface BollingerResult {
  sma: number;
  upper: number;
  lower: number;
  bandwidth: number;
  percentB: number;
  period: number;
  numStd: number;
  history: { sma: number; upper: number; lower: number; bandwidth: number; percentB: number }[];
}

export interface VaRContribution {
  symbol: string;
  value: number;
  varContribution: number;
}

export interface VaRResult {
  var95: number;
  var99: number;
  portfolioValue: number;
  confidence95: string;
  confidence99: string;
  contributions: VaRContribution[];
}

export interface PairsResult {
  a: string;
  b: string;
  beta: number;
  correlation: number;
  covariance: number;
  nObservations: number;
}

export interface AnalystResult {
  strongBuy: number;
  buy: number;
  hold: number;
  sell: number;
  strongSell: number;
  meanTarget: number;
  numberOfAnalysts: number;
  currentPrice?: number;
}

export interface PortfolioHolding {
  id: number;
  symbol: string;
  shares: number;
  avgCost: number;
  entryDate?: string;
}

export interface ScreenerStock {
  symbol: string;
  name: string;
  price: number;
  change: number;
  regime: "bull" | "bear" | "sideways";
  momentum: number;
  volatility: number;
  score: number;
  probBull: number;
  probBear: number;
  probSideways: number;
}

export interface ScreenerResponse {
  sector: string;
  stocks: ScreenerStock[];
}

export const stockApi = {
  getTicker: (symbol: string) =>
    api.get<{ info: StockInfo; ohlcv: OHLCVData[] }>(`/fetch/ticker/${symbol}`),

  getNews: (symbol: string) =>
    api.get<{ articles: { title: string; source: string; date: string; url: string; snippet: string }[] }>(`/fetch/news/${symbol}`),

  getRegime: (symbol: string) =>
    api.get<RegimeResult>(`/models/regime/${symbol}`),

  getMonteCarlo: (symbol: string, days?: number) =>
    api.get<MonteCarloResult>(`/models/montecarlo/${symbol}`, { params: { days: days || 30 } }),

  getGarch: (symbol: string) =>
    api.get<GarchResult>(`/models/garch/${symbol}`),

  getMarkov: (symbol: string) =>
    api.get<MarkovResult>(`/models/markov/${symbol}`),

  getCorrelationGraph: (sector?: string) =>
    api.get<{ nodes: { id: string; name: string }[]; edges: { source: string; target: string; weight: number }[] }>(`/models/correlation-graph`, { params: { sector } }),

  getRSI: (symbol: string, period?: number) =>
    api.get<RSIResult>(`/models/rsi/${symbol}`, { params: { period: period || 14 } }),

  getMACD: (symbol: string) =>
    api.get<MACDResult>(`/models/macd/${symbol}`),

  getBollinger: (symbol: string, period?: number) =>
    api.get<BollingerResult>(`/models/bollinger/${symbol}`, { params: { period: period || 20 } }),

  getVaR: (positions: { symbol: string; shares: number; avgCost: number }[]) =>
    api.post<VaRResult>("/models/var", { positions }),

  getPairs: (a: string, b: string) =>
    api.get<PairsResult>("/models/pairs", { params: { a, b } }),

  getAnalyst: (symbol: string) =>
    api.get<AnalystResult>(`/models/analyst/${symbol}`),

  getMonteCarloRegimeCond: (symbol: string, days?: number) =>
    api.get<MonteCarloRegimeCondResult>(`/models/montecarlo/${symbol}/regime-cond`, { params: { days: days || 30 } }),

  getAtr: (symbol: string, period?: number) =>
    api.get<AtrResult>(`/models/atr/${symbol}`, { params: { period: period || 14 } }),

  searchStock: (query: string) =>
    api.get<{ results: { symbol: string; name: string; exchange: string; type: string }[] }>(`/fetch/search`, { params: { q: query } }),

  getScreener: (sector: string) =>
    api.get<ScreenerResponse>(`/fetch/screener/${sector}`),

  getProviders: () =>
    api.get<{ default: string; available: { anthropic: boolean; gemini: boolean }; models: { anthropic: string; gemini: string } }>("/rag/providers"),

  chat: (message: string, symbol?: string, provider?: string) =>
    api.post<{ answer: string; citations: { text: string; source: string; url?: string }[]; provider: string; model: string }>("/rag/chat", { message, symbol, provider }),

  // Portfolio (Supabase)
  getHoldings: () => api.get<PortfolioHolding[]>("/portfolio/holdings"),
  upsertHolding: (symbol: string, shares: number, avgCost: number) =>
    api.post<PortfolioHolding>("/portfolio/holdings", { symbol, shares, avgCost }),
  deleteHolding: (lotId: number) =>
    api.delete(`/portfolio/holdings/${lotId}`),

  // Watchlist (Supabase)
  getWatchlist: () => api.get<string[]>("/portfolio/watchlist"),
  addToWatchlist: (symbol: string) =>
    api.post(`/portfolio/watchlist/${symbol}`, {}),
  removeFromWatchlist: (symbol: string) =>
    api.delete(`/portfolio/watchlist/${symbol}`),
};

export default api;
