"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { VaRResult } from "@/lib/api";

interface Props {
  data: VaRResult;
}

export default function VarCard({ data }: Props) {
  const totalVarContr = data.contributions.reduce((s, c) => s + c.varContribution, 0);

  return (
    <div className="space-y-4">
      {/* Top-level VaR numbers */}
      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground mb-1">1-Day VaR (95%)</p>
            <p className="text-2xl font-bold text-red-500">${data.var95.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
            <p className="text-xs text-muted-foreground mt-1">Worst loss over 1 trading day at 95% confidence</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground mb-1">1-Day VaR (99%)</p>
            <p className="text-2xl font-bold text-red-700">${data.var99.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
            <p className="text-xs text-muted-foreground mt-1">Worst loss over 1 trading day at 99% confidence</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Portfolio Value: ${data.portfolioValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="grid grid-cols-4 text-xs text-muted-foreground font-medium border-b pb-1">
              <span>Symbol</span>
              <span className="text-right">Position Value</span>
              <span className="text-right">VaR Contribution</span>
              <span className="text-right">VaR %</span>
            </div>
            {data.contributions.map((c) => (
              <div key={c.symbol} className="grid grid-cols-4 text-xs items-center">
                <span className="font-semibold">{c.symbol}</span>
                <span className="text-right">${c.value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                <span className="text-right text-red-400">${c.varContribution.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                <span className="text-right text-muted-foreground">
                  {c.value > 0 ? ((c.varContribution / c.value) * 100).toFixed(1) : "—"}%
                </span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
