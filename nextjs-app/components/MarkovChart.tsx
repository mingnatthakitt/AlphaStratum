"use client";

import type { MarkovResult } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface Props {
  data: MarkovResult;
}

function TransitionCell({ prob, isSelf }: { prob: number; isSelf: boolean }) {
  const pct = (prob * 100).toFixed(1);
  const intensity = prob; // 0 → white, 1 → deep
  const bg = isSelf
    ? `rgba(34, 197, 90, ${0.15 + intensity * 0.7})`
    : `rgba(148, 163, 184, ${0.1 + intensity * 0.4})`;
  return (
    <div
      className="w-16 h-12 flex items-center justify-center rounded text-xs font-medium border border-border/50"
      style={{ backgroundColor: bg }}
    >
      {pct}%
    </div>
  );
}

export default function MarkovChart({ data }: Props) {
  const tm = data.transitionMatrix;
  const regimes = ["bear", "sideways", "bull"] as const;

  const regimeColor = {
    bear: "text-red-500",
    sideways: "text-yellow-500",
    bull: "text-green-500",
  };

  return (
    <div className="space-y-6">
      {/* Current regime + forecast */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {regimes.map((r) => {
          const prob1 = (data.forecast1Step[r] * 100).toFixed(1);
          const prob3 = (data.forecast3Step[r] * 100).toFixed(1);
          const prob10 = (data.forecast10Step[r] * 100).toFixed(1);
          const duration = data.expectedDuration[r];
          const isCurrent = data.currentRegime === r;
          return (
            <Card key={r} className={isCurrent ? "ring-2 ring-primary" : ""}>
              <CardHeader className="pb-2">
                <CardTitle className={`text-base capitalize ${regimeColor[r]} ${isCurrent ? "font-bold" : ""}`}>
                  {r} {isCurrent ? "← current" : ""}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 text-sm">
                <div className="text-xs text-muted-foreground">
                  Avg duration:{" "}
                  <span className="font-medium text-foreground">
                    {duration === Infinity ? "∞" : `${duration} days`}
                  </span>
                </div>
                <div className="text-xs text-muted-foreground">
                  1-step: <span className="font-medium text-foreground">{prob1}%</span>
                </div>
                <div className="text-xs text-muted-foreground">
                  3-step: <span className="font-medium text-foreground">{prob3}%</span>
                </div>
                <div className="text-xs text-muted-foreground">
                  10-step: <span className="font-medium text-foreground">{prob10}%</span>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Transition matrix */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Regime Transition Matrix</CardTitle>
          <p className="text-xs text-muted-foreground">
            Row = from state, Column = to state. Diagonal = probability of staying.
          </p>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="border-collapse">
              <thead>
                <tr>
                  <th className="p-2 text-xs text-muted-foreground" />
                  {regimes.map((r) => (
                    <th key={r} className={`p-2 text-xs font-medium capitalize ${regimeColor[r]}`}>
                      → {r}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {regimes.map((from) => (
                  <tr key={from}>
                    <td className={`p-2 text-xs font-medium capitalize ${regimeColor[from]}`}>
                      {from} →
                    </td>
                    {regimes.map((to) => {
                      const prob = tm[from][to];
                      return (
                        <td key={to} className="p-1">
                          <TransitionCell prob={prob} isSelf={from === to} />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-muted-foreground mt-3">
            Stationary (long-run) distribution:{" "}
            {regimes.map((r) => `${r}: ${(data.stationary[r] * 100).toFixed(1)}%`).join(", ")}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}