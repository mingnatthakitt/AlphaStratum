"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { PairsResult } from "@/lib/api";

interface Props {
  data: PairsResult;
}

export default function PairsCard({ data }: Props) {
  const betaColor = data.beta > 1.5 ? "text-red-500" : data.beta < 0.8 ? "text-green-500" : "text-blue-500";
  const corrAbs = Math.abs(data.correlation);
  const corrColor = corrAbs > 0.7 ? "text-red-500" : corrAbs > 0.4 ? "text-yellow-500" : "text-green-500";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">{data.a} / {data.b}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <p className="text-xs text-muted-foreground mb-1">Beta</p>
            <p className={`text-2xl font-bold ${betaColor}`}>{data.beta.toFixed(3)}</p>
            <p className="text-xs text-muted-foreground mt-1">
              {data.beta > 1 ? `${data.a} is more volatile than ${data.b}` : data.beta < 1 ? `${data.a} is less volatile than ${data.b}` : "Same volatility as benchmark"}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground mb-1">Correlation</p>
            <p className={`text-2xl font-bold ${corrColor}`}>{data.correlation.toFixed(3)}</p>
            <p className="text-xs text-muted-foreground mt-1">
              {corrAbs > 0.7 ? "Strong positive relationship" : corrAbs > 0.4 ? "Moderate relationship" : "Weak relationship"}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground mb-1">Covariance</p>
            <p className="text-2xl font-bold">{data.covariance.toFixed(6)}</p>
            <p className="text-xs text-muted-foreground mt-1">Covariance of returns</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground mb-1">Observations</p>
            <p className="text-2xl font-bold">{data.nObservations.toLocaleString()}</p>
            <p className="text-xs text-muted-foreground mt-1">Trading days used</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
