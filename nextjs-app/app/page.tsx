import Link from "next/link";
import { ArrowRight, BarChart2, Brain, Search, TrendingUp, Wallet, Calculator } from "lucide-react";

const pages = [
  {
    href: "/dashboard",
    label: "Dashboard",
    desc: "Candlestick + area charts, regime detection, intraday prices, key statistics",
    icon: BarChart2,
    color: "text-blue-400",
  },
  {
    href: "/models",
    label: "Models",
    desc: "Monte Carlo, GARCH, Markov chain, RSI, MACD, Bollinger Bands, VaR, Pairs, Analyst ratings",
    icon: Brain,
    color: "text-purple-400",
  },
  {
    href: "/screener",
    label: "Screener",
    desc: "Ranked stock opportunities by regime stability + momentum",
    icon: Search,
    color: "text-amber-400",
  },
  {
    href: "/advisor",
    label: "Advisor",
    desc: "AI chat grounded in news, SEC filings, price data, regime, RSI, MACD, Bollinger — all cited",
    icon: TrendingUp,
    color: "text-green-400",
  },
  {
    href: "/backtest",
    label: "Backtest",
    desc: "What if you'd invested $X on date Y?",
    icon: Calculator,
    color: "text-cyan-400",
  },
  {
    href: "/portfolio",
    label: "Portfolio",
    desc: "Track holdings, cost basis, and P&L — synced to Supabase",
    icon: Wallet,
    color: "text-pink-400",
  },
];

export default function Home() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[70vh] gap-8 text-center px-4">
      <div className="space-y-4 max-w-2xl">
        <h1 className="text-5xl md:text-6xl font-bold tracking-tight">
          Alpha<span className="text-primary">Stratum</span>
        </h1>
        <p className="text-lg text-muted-foreground leading-relaxed">
          AI-powered quantitative analysis — 10 technical models, grounded AI advisory
          with inline citations, and real-time portfolio tracking. All data sourced from
          Yahoo Finance, NewsAPI, and SEC EDGAR.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 w-full max-w-4xl">
        {pages.map(({ href, label, desc, icon: Icon, color }) => (
          <Link
            key={href}
            href={href}
            className="group flex items-start gap-4 p-5 rounded-xl border bg-card hover:border-primary/50 hover:shadow-md transition-all text-left"
          >
            <Icon className={`w-5 h-5 mt-0.5 shrink-0 ${color} group-hover:scale-110 transition-transform`} />
            <div className="space-y-1">
              <span className="text-base font-semibold group-hover:text-primary transition-colors flex items-center gap-1">
                {label}
                <ArrowRight className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
              </span>
              <span className="text-sm text-muted-foreground leading-relaxed">{desc}</span>
            </div>
          </Link>
        ))}
      </div>

      <p className="text-xs text-muted-foreground max-w-lg leading-relaxed">
        Data sourced from Yahoo Finance, NewsAPI & SEC EDGAR — all AI answers cite
        their sources inline. Not financial advice.
      </p>
    </div>
  );
}