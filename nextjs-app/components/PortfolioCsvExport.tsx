"use client";

import { useRef } from "react";
import { Button } from "@/components/ui/button";
import { Download } from "lucide-react";
import type { EnrichedHolding } from "@/app/portfolio/page";

interface Props {
  holdings: EnrichedHolding[];
  totalValue: number;
  totalCost: number;
  totalPnl: number;
  totalPnlPct: number;
}

export default function PortfolioCsvExport({
  holdings,
  totalValue,
  totalCost,
  totalPnl,
  totalPnlPct,
}: Props) {
  const ref = useRef<HTMLButtonElement>(null);

  const exportCsv = () => {
    const header = ["Symbol", "Shares", "Avg Cost", "Price", "Value", "Cost Basis", "P&L ($)", "P&L (%)", "Daily Change %"];
    const rows = holdings.map((h) => [
      h.symbol,
      h.shares.toFixed(4),
      h.avgCost.toFixed(2),
      h.price.toFixed(2),
      h.currentValue.toFixed(2),
      h.costBasis.toFixed(2),
      h.pnl.toFixed(2),
      h.pnlPct.toFixed(2),
      h.changePercent.toFixed(2),
    ]);
    const summary = [
      ["", "", "", "", "", "", "", "", ""],
      ["TOTAL", "", "", "", totalValue.toFixed(2), totalCost.toFixed(2), totalPnl.toFixed(2), totalPnlPct.toFixed(2), ""],
    ];
    const csv = [header, ...rows, ...summary]
      .map((row) => row.join(","))
      .join("\n");

    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `portfolio-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Button
      ref={ref}
      variant="outline"
      size="sm"
      onClick={exportCsv}
      className="gap-1.5"
    >
      <Download className="w-3.5 h-3.5" />
      Export CSV
    </Button>
  );
}