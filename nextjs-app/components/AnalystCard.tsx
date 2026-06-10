"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AnalystResult } from "@/lib/api";

interface Props {
  data: AnalystResult;
  symbol: string;
  currentPrice?: number;
}

export default function AnalystCard({ data, symbol, currentPrice }: Props) {
  const price = currentPrice ?? data.currentPrice;
  const total = data.strongBuy + data.buy + data.hold + data.sell + data.strongSell;

  if (total === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Analyst Ratings — {symbol}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center h-[200px] gap-3 text-muted-foreground">
            <p className="text-sm">No analyst data available for {symbol}</p>
          </div>
        </CardContent>
      </Card>
    );
  }
  const buyPct = total > 0 ? ((data.strongBuy + data.buy) / total) * 100 : 0;
  const holdPct = total > 0 ? (data.hold / total) * 100 : 0;
  const sellPct = total > 0 ? ((data.sell + data.strongSell) / total) * 100 : 0;

  const ratings = [
    { label: "Strong Buy", value: data.strongBuy, color: "bg-green-500", width: total > 0 ? (data.strongBuy / total) * 100 : 0 },
    { label: "Buy", value: data.buy, color: "bg-green-400", width: total > 0 ? (data.buy / total) * 100 : 0 },
    { label: "Hold", value: data.hold, color: "bg-yellow-500", width: total > 0 ? (data.hold / total) * 100 : 0 },
    { label: "Sell", value: data.sell, color: "bg-red-400", width: total > 0 ? (data.sell / total) * 100 : 0 },
    { label: "Strong Sell", value: data.strongSell, color: "bg-red-500", width: total > 0 ? (data.strongSell / total) * 100 : 0 },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Analyst Ratings — {symbol}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Rating bars */}
        <div className="space-y-2">
          {ratings.map((r) => (
            <div key={r.label} className="flex items-center gap-2">
              <span className="w-20 text-xs text-muted-foreground text-right">{r.label}</span>
              <div className="flex-1 h-4 rounded-full bg-muted overflow-hidden">
                <div
                  className={`h-full ${r.color} rounded-full transition-all`}
                  style={{ width: `${r.width}%` }}
                />
              </div>
              <span className="w-6 text-xs font-medium text-right">{r.value}</span>
            </div>
          ))}
        </div>

        {/* Summary stats */}
        <div className="grid grid-cols-3 gap-4 pt-2 border-t">
          <div className="text-center">
            <p className="text-xs text-muted-foreground">Buy %</p>
            <p className={`text-xl font-bold ${buyPct > 50 ? "text-green-500" : buyPct > 30 ? "text-yellow-500" : "text-red-500"}`}>
              {buyPct.toFixed(0)}%
            </p>
          </div>
          <div className="text-center">
            <p className="text-xs text-muted-foreground">Hold %</p>
            <p className={`text-xl font-bold ${holdPct > 50 ? "text-yellow-500" : "text-muted-foreground"}`}>
              {holdPct.toFixed(0)}%
            </p>
          </div>
          <div className="text-center">
            <p className="text-xs text-muted-foreground">Sell %</p>
            <p className={`text-xl font-bold ${sellPct > 30 ? "text-red-500" : "text-muted-foreground"}`}>
              {sellPct.toFixed(0)}%
            </p>
          </div>
        </div>

        {/* Target price */}
        {data.meanTarget > 0 && price && price > 0 && (
          <div className="pt-2 border-t">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Mean Price Target</span>
              <div className="flex items-center gap-2">
                <span className="font-bold">${data.meanTarget.toFixed(2)}</span>
                <span className={`text-xs ${data.meanTarget > price ? "text-green-500" : "text-red-500"}`}>
                  {((data.meanTarget / price - 1) * 100).toFixed(1)}% upside
                </span>
              </div>
            </div>
            <div className="mt-1 h-1 rounded-full bg-muted overflow-hidden">
              <div
                className={`h-full rounded-full ${data.meanTarget > price ? "bg-green-500" : "bg-red-500"}`}
                style={{ width: `${Math.min(100, Math.max(0, (price / data.meanTarget) * 100))}%` }}
              />
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Based on {data.numberOfAnalysts} analyst{data.numberOfAnalysts !== 1 ? "s" : ""}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
