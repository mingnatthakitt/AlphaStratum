"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { stockApi } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { ErrorBox, QueryRender } from "@/components/QueryFeedback";
import { Plus, Trash2, Wallet, X, BarChart2, ChevronDown, ChevronRight, Check, Pencil } from "lucide-react";
import PortfolioMiniChart from "@/components/PortfolioMiniChart";
import PortfolioCsvExport from "@/components/PortfolioCsvExport";
import VarCard from "@/components/VarCard";
import { zipSettled } from "@/lib/chartData";
import type { PortfolioHolding } from "@/lib/api";

export interface EnrichedLot {
  id: number;
  symbol: string;
  shares: number;
  avgCost: number;
  price: number;
  currentValue: number;
  costBasis: number;
  pnl: number;
  pnlPct: number;
  change: number;
  changePercent: number;
}

interface SymbolGroup {
  symbol: string;
  lots: EnrichedLot[];
  totalShares: number;
  totalCostBasis: number;
  totalValue: number;
  totalPnl: number;
  totalPnlPct: number;
  avgCostPerShare: number;
  price: number;
  change: number;
  changePercent: number;
}

interface LotDraft {
  shares: string;
  avgCost: string;
}

export default function PortfolioPage() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [showAdd, setShowAdd] = useState(false);
  const [addSymbol, setAddSymbol] = useState("");
  const [addShares, setAddShares] = useState("");
  const [addCost, setAddCost] = useState("");
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null);
  const [expandedChart, setExpandedChart] = useState<string | null>(null);
  const [editingLotId, setEditingLotId] = useState<number | null>(null);
  const [lotDraft, setLotDraft] = useState<LotDraft>({ shares: "", avgCost: "" });
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const {
    data: holdings = [],
    isLoading: holdingsLoading,
    isError: holdingsError,
    refetch: refetchHoldings,
  } = useQuery({
    queryKey: ["portfolio-holdings"],
    queryFn: () => stockApi.getHoldings().then((r) => r.data ?? []),
    staleTime: 30_000,
    retry: 1,
  });

  // Deduplicate symbols for price fetching (one price per symbol, not per lot)
  const symbols = useMemo(() => [...new Set(holdings.map((h) => h.symbol))], [holdings]);
  const symbolsKey = symbols.join(",");
  const { data: priceData } = useQuery({
    queryKey: ["portfolio-prices", symbolsKey],
    queryFn: async () => {
      const settled = await Promise.allSettled(
        symbols.map((s) => stockApi.getTicker(s).then((r) => r.data?.info)),
      );
      const bySymbol = zipSettled(symbols, settled, (info, symbol) => (info ? { symbol, info } : null));
      return bySymbol;
    },
    enabled: symbols.length > 0,
    staleTime: 60_000,
    refetchInterval: 120_000,
  });

  const enrichedLots = useMemo<EnrichedLot[]>(() => {
    return holdings.map((h) => {
      const info = priceData?.get(h.symbol)?.info;
      const price = info?.price ?? 0;
      const currentValue = price * h.shares;
      const costBasis = h.avgCost * h.shares;
      const pnl = currentValue - costBasis;
      const pnlPct = costBasis > 0 ? (pnl / costBasis) * 100 : 0;
      return {
        id: h.id,
        symbol: h.symbol,
        shares: h.shares,
        avgCost: h.avgCost,
        price,
        currentValue,
        costBasis,
        pnl,
        pnlPct,
        change: info?.change ?? 0,
        changePercent: info?.changePercent ?? 0,
      };
    });
  }, [holdings, priceData]);

  const symbolGroups = useMemo<SymbolGroup[]>(() => {
    const groups: SymbolGroup[] = [];
    const index = new Map<string, number>();
    for (const lot of enrichedLots) {
      if (!index.has(lot.symbol)) {
        index.set(lot.symbol, groups.length);
        groups.push({
          symbol: lot.symbol,
          lots: [],
          totalShares: 0,
          totalCostBasis: 0,
          totalValue: 0,
          totalPnl: 0,
          totalPnlPct: 0,
          avgCostPerShare: 0,
          price: lot.price,
          change: lot.change,
          changePercent: lot.changePercent,
        });
      }
      const g = groups[index.get(lot.symbol)!];
      g.lots.push(lot);
      g.totalShares += lot.shares;
      g.totalCostBasis += lot.costBasis;
      g.totalValue += lot.currentValue;
      g.totalPnl += lot.pnl;
    }
    for (const g of groups) {
      g.totalPnlPct = g.totalCostBasis > 0 ? (g.totalPnl / g.totalCostBasis) * 100 : 0;
      g.avgCostPerShare = g.totalShares > 0 ? g.totalCostBasis / g.totalShares : 0;
    }
    return groups;
  }, [enrichedLots]);

  const totalValue = symbolGroups.reduce((s, g) => s + g.totalValue, 0);
  const totalCost = symbolGroups.reduce((s, g) => s + g.totalCostBasis, 0);
  const totalPnl = totalValue - totalCost;
  const totalPnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;

  // Mutations
  const addMutation = useMutation({
    mutationFn: ({ symbol, shares, avgCost }: { symbol: string; shares: number; avgCost: number }) =>
      stockApi.upsertHolding(symbol, shares, avgCost),
    onSuccess: (_res, variables) => {
      qc.invalidateQueries({ queryKey: ["portfolio-holdings"] });
      setShowAdd(false);
      setAddSymbol("");
      setAddShares("");
      setAddCost("");
      toast({ title: `Added ${variables.symbol}`, variant: "success" });
    },
    onError: () => {
      toast({ title: "Couldn't add the lot", description: "Please try again.", variant: "error" });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ lotId, shares, avgCost }: { lotId: number; shares: number; avgCost: number }) =>
      stockApi.updateHolding(lotId, shares, avgCost),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["portfolio-holdings"] });
      setEditingLotId(null);
      toast({ title: "Lot updated", variant: "success" });
    },
    onError: () => {
      toast({ title: "Couldn't update the lot", description: "Please try again.", variant: "error" });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (lotId: number) => stockApi.deleteHolding(lotId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["portfolio-holdings"] });
      setConfirmDeleteId(null);
      toast({ title: "Lot deleted", variant: "success" });
    },
    onError: () => {
      toast({ title: "Couldn't delete the lot", description: "Please try again.", variant: "error" });
      setConfirmDeleteId(null);
    },
  });

  // VaR uses all individual lots (not aggregated)
  const varKey = holdings.map((h) => `${h.id}:${h.symbol}:${h.shares}:${h.avgCost}`).join(",");
  const { data: varData, isLoading: varLoading, isError: varError, refetch: varRefetch } = useQuery({
    queryKey: ["var", varKey],
    queryFn: () => stockApi.getVaR(holdings),
    enabled: holdings.length > 0,
    staleTime: 120_000,
  });

  const handleAdd = () => {
    const symbol = addSymbol.trim().toUpperCase();
    const shares = parseFloat(addShares);
    const avgCost = parseFloat(addCost);
    if (!symbol || isNaN(shares) || isNaN(avgCost) || shares <= 0 || avgCost <= 0) return;
    addMutation.mutate({ symbol, shares, avgCost });
  };

  const startEdit = (lot: EnrichedLot) => {
    setEditingLotId(lot.id);
    setLotDraft({ shares: String(lot.shares), avgCost: String(lot.avgCost) });
    setConfirmDeleteId(null);
  };

  const saveEdit = (lotId: number) => {
    const shares = parseFloat(lotDraft.shares);
    const avgCost = parseFloat(lotDraft.avgCost);
    if (isNaN(shares) || isNaN(avgCost) || shares <= 0 || avgCost <= 0) {
      toast({ title: "Shares and cost must be positive numbers", variant: "error" });
      return;
    }
    updateMutation.mutate({ lotId, shares, avgCost });
  };

  useEffect(() => {
    if (!showAdd) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowAdd(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showAdd]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Portfolio</h1>
          <p className="text-muted-foreground text-sm mt-1">Track your holdings, cost basis, and P&L across stocks.</p>
        </div>
        <div className="flex items-center gap-2">
          {symbolGroups.length > 0 && (
            <PortfolioCsvExport
              holdings={enrichedLots}
              totalValue={totalValue}
              totalCost={totalCost}
              totalPnl={totalPnl}
              totalPnlPct={totalPnlPct}
            />
          )}
          <Button size="sm" onClick={() => setShowAdd(true)} className="gap-1.5">
            <Plus className="w-4 h-4" /> Add Lot
          </Button>
        </div>
      </div>

      {/* Total summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground mb-1">Total Value</p>
            <p className="text-2xl font-bold">
              ${totalValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground mb-1">Cost Basis</p>
            <p className="text-2xl font-bold">
              ${totalCost.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground mb-1">Total P&L</p>
            <p className={`text-2xl font-bold ${totalPnl >= 0 ? "text-green-500" : "text-red-500"}`}>
              {totalPnl >= 0 ? "+" : ""}$
              {totalPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground mb-1">Return</p>
            <p className={`text-2xl font-bold ${totalPnlPct >= 0 ? "text-green-500" : "text-red-500"}`}>
              {totalPnlPct >= 0 ? "+" : ""}
              {totalPnlPct.toFixed(2)}%
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Holdings table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Wallet className="w-4 h-4" />
            Positions
          </CardTitle>
        </CardHeader>
        <CardContent>
          {holdingsError ? (
            <ErrorBox height="200px" onRetry={() => refetchHoldings()} message="Couldn't load your holdings." />
          ) : holdingsLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : holdings.length === 0 ? (
            <p className="text-muted-foreground text-center py-8">
              No positions yet. Click &ldquo;Add Lot&rdquo; to get started.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <div className="min-w-[640px] space-y-2">
                {/* Header */}
                <div className="grid grid-cols-8 gap-2 text-xs text-muted-foreground font-medium px-2 mb-1">
                  <span />
                  <span className="text-right">Total Shares</span>
                  <span className="text-right">Avg Cost</span>
                  <span className="text-right">Price</span>
                  <span className="text-right">Value</span>
                  <span className="text-right">P&L</span>
                  <span className="text-right">Return</span>
                  <span />
                </div>

                {symbolGroups.map((group) => {
                  const isExpanded = expandedSymbol === group.symbol;
                  return (
                    <div key={group.symbol} className="space-y-1">
                      {/* Symbol row */}
                      <div className="grid grid-cols-8 gap-2 items-center p-3 rounded-lg border hover:bg-muted/50 transition-colors">
                        <button
                          onClick={() => setExpandedSymbol(isExpanded ? null : group.symbol)}
                          className="flex items-center gap-1.5 hover:text-primary transition-colors text-left"
                          aria-expanded={isExpanded}
                        >
                          {isExpanded ? (
                            <ChevronDown className="w-4 h-4 text-muted-foreground" />
                          ) : (
                            <ChevronRight className="w-4 h-4 text-muted-foreground" />
                          )}
                          <div>
                            <span className="font-semibold">{group.symbol}</span>
                            {group.changePercent !== 0 && (
                              <span className={`text-xs ml-1 ${group.changePercent >= 0 ? "text-green-500" : "text-red-500"}`}>
                                {group.changePercent >= 0 ? "+" : ""}
                                {group.changePercent.toFixed(1)}%
                              </span>
                            )}
                            <span className="text-xs text-muted-foreground ml-1">
                              {group.lots.length} lot{group.lots.length !== 1 ? "s" : ""}
                            </span>
                          </div>
                        </button>

                        <span className="text-right text-sm font-medium">{group.totalShares.toFixed(4)}</span>
                        <span className="text-right text-sm text-muted-foreground">
                          {group.avgCostPerShare > 0 ? `$${group.avgCostPerShare.toFixed(2)}` : "—"}
                        </span>
                        <span className="text-right text-sm font-medium">
                          ${group.price > 0 ? group.price.toFixed(2) : "—"}
                        </span>
                        <span className="text-right text-sm font-medium">
                          ${group.totalValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </span>
                        <div className={`text-right text-sm font-semibold ${group.totalPnl >= 0 ? "text-green-500" : "text-red-500"}`}>
                          {group.totalPnl >= 0 ? "+" : ""}$
                          {group.totalPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </div>
                        <div className={`text-right text-sm ${group.totalPnlPct >= 0 ? "text-green-500" : "text-red-500"}`}>
                          {group.totalPnlPct >= 0 ? "+" : ""}
                          {group.totalPnlPct.toFixed(1)}%
                        </div>
                        <div className="flex items-center justify-end gap-1">
                          <button
                            onClick={() => setExpandedSymbol(isExpanded ? null : group.symbol)}
                            className="p-1 rounded hover:bg-primary/20 text-muted-foreground hover:text-primary transition-colors"
                            aria-label={isExpanded ? `Collapse ${group.symbol}` : `Expand ${group.symbol}`}
                          >
                            <BarChart2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>

                      {/* Expanded lot rows */}
                      {isExpanded &&
                        group.lots.map((lot) => {
                          const chartKey = `${lot.id}`;
                          const isChartExpanded = expandedChart === chartKey;
                          const isEditing = editingLotId === lot.id;
                          return (
                            <div key={lot.id}>
                              <div className="grid grid-cols-8 gap-2 items-center px-4 py-2 bg-muted/20 rounded border ml-4 text-xs">
                                <div className="pl-6 flex items-center gap-1.5">
                                  <button
                                    onClick={() => setExpandedChart(isChartExpanded ? null : chartKey)}
                                    className="text-muted-foreground hover:text-primary transition-colors"
                                    aria-label={isChartExpanded ? "Hide chart" : "Show chart"}
                                  >
                                    {isChartExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                                  </button>
                                  <span className="text-muted-foreground">Lot #{lot.id}</span>
                                </div>
                                <div className="text-right">
                                  {isEditing ? (
                                    <Input
                                      type="number"
                                      value={lotDraft.shares}
                                      onChange={(e) => setLotDraft((d) => ({ ...d, shares: e.target.value }))}
                                      className="h-6 w-20 text-right text-xs ml-auto"
                                      min={0}
                                      step={0.001}
                                      aria-label={`Shares for lot ${lot.id}`}
                                    />
                                  ) : (
                                    <span className="font-medium">{lot.shares}</span>
                                  )}
                                </div>
                                <div className="text-right">
                                  {isEditing ? (
                                    <div className="flex items-center justify-end gap-1">
                                      <span className="text-muted-foreground">$</span>
                                      <Input
                                        type="number"
                                        value={lotDraft.avgCost}
                                        onChange={(e) => setLotDraft((d) => ({ ...d, avgCost: e.target.value }))}
                                        className="h-6 w-16 text-right text-xs"
                                        min={0}
                                        step={0.01}
                                        aria-label={`Average cost for lot ${lot.id}`}
                                      />
                                    </div>
                                  ) : (
                                    <span className="text-muted-foreground">${lot.avgCost.toFixed(2)}</span>
                                  )}
                                </div>
                                <div className="text-right">${lot.price > 0 ? lot.price.toFixed(2) : "—"}</div>
                                <div className="text-right">
                                  ${lot.currentValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                </div>
                                <div className={`text-right ${lot.pnl >= 0 ? "text-green-500" : "text-red-500"}`}>
                                  {lot.pnl >= 0 ? "+" : ""}${lot.pnl.toFixed(2)}
                                </div>
                                <div className="text-right">
                                  <span className={lot.pnlPct >= 0 ? "text-green-500" : "text-red-500"}>
                                    {lot.pnlPct >= 0 ? "+" : ""}
                                    {lot.pnlPct.toFixed(1)}%
                                  </span>
                                </div>
                                <div className="flex items-center justify-end gap-1">
                                  {isEditing ? (
                                    <>
                                      <button
                                        onClick={() => saveEdit(lot.id)}
                                        disabled={updateMutation.isPending}
                                        className="p-1 rounded hover:bg-green-500/20 text-muted-foreground hover:text-green-400 transition-colors"
                                        aria-label="Save changes"
                                      >
                                        <Check className="w-3.5 h-3.5" />
                                      </button>
                                      <button
                                        onClick={() => setEditingLotId(null)}
                                        className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
                                        aria-label="Cancel editing"
                                      >
                                        <X className="w-3.5 h-3.5" />
                                      </button>
                                    </>
                                  ) : confirmDeleteId === lot.id ? (
                                    <>
                                      <button
                                        onClick={() => deleteMutation.mutate(lot.id)}
                                        disabled={deleteMutation.isPending}
                                        className="px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors"
                                      >
                                        Delete?
                                      </button>
                                      <button
                                        onClick={() => setConfirmDeleteId(null)}
                                        className="p-1 rounded hover:bg-muted text-muted-foreground transition-colors"
                                        aria-label="Cancel delete"
                                      >
                                        <X className="w-3.5 h-3.5" />
                                      </button>
                                    </>
                                  ) : (
                                    <>
                                      <button
                                        onClick={() => startEdit(lot)}
                                        className="p-1 rounded hover:bg-primary/20 text-muted-foreground hover:text-primary transition-colors"
                                        aria-label={`Edit lot ${lot.id}`}
                                      >
                                        <Pencil className="w-3.5 h-3.5" />
                                      </button>
                                      <button
                                        onClick={() => setConfirmDeleteId(lot.id)}
                                        className="p-1 rounded hover:bg-red-500/20 text-muted-foreground hover:text-red-400 transition-colors"
                                        aria-label={`Delete lot ${lot.id}`}
                                      >
                                        <Trash2 className="w-3.5 h-3.5" />
                                      </button>
                                    </>
                                  )}
                                </div>
                              </div>
                              {isChartExpanded && (
                                <div className="ml-8 mt-1 mb-2">
                                  <PortfolioMiniChart symbol={lot.symbol} shares={lot.shares} avgCost={lot.avgCost} />
                                </div>
                              )}
                            </div>
                          );
                        })}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* VaR section */}
      {holdings.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BarChart2 className="w-4 h-4" />
              Value at Risk
            </CardTitle>
          </CardHeader>
          <CardContent>
            <QueryRender
              data={varData?.data}
              isLoading={varLoading}
              isError={varError}
              refetch={varRefetch}
              height="200px"
              emptyMessage="Add positions with live prices to see portfolio VaR."
              errorMessage="Couldn't compute VaR — price data may be unavailable."
            >
              {(data) => <VarCard data={data} />}
            </QueryRender>
          </CardContent>
        </Card>
      )}

      <p className="text-xs text-muted-foreground text-center">
        Prices are delayed ~15-20 min. Not financial advice. Verify with official sources.
      </p>

      {/* Add lot modal */}
      {showAdd && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          onClick={() => setShowAdd(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Add lot"
            className="bg-background rounded-2xl border border-border shadow-2xl w-full max-w-sm mx-4 p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold">Add Lot</h2>
              <Button variant="ghost" size="icon" onClick={() => setShowAdd(false)} aria-label="Close">
                <X className="w-4 h-4" />
              </Button>
            </div>
            <div className="space-y-3">
              <div>
                <label htmlFor="add-ticker" className="text-xs text-muted-foreground mb-1 block">
                  Ticker
                </label>
                <Input
                  id="add-ticker"
                  autoFocus
                  placeholder="e.g. AAPL"
                  value={addSymbol}
                  onChange={(e) => setAddSymbol(e.target.value.toUpperCase())}
                  className="uppercase"
                  maxLength={10}
                />
              </div>
              <div>
                <label htmlFor="add-shares" className="text-xs text-muted-foreground mb-1 block">
                  Shares
                </label>
                <Input
                  id="add-shares"
                  type="number"
                  placeholder="e.g. 10"
                  value={addShares}
                  onChange={(e) => setAddShares(e.target.value)}
                  min={0}
                  step={0.001}
                />
              </div>
              <div>
                <label htmlFor="add-cost" className="text-xs text-muted-foreground mb-1 block">
                  Average Cost ($)
                </label>
                <Input
                  id="add-cost"
                  type="number"
                  placeholder="e.g. 150.00"
                  value={addCost}
                  onChange={(e) => setAddCost(e.target.value)}
                  min={0}
                  step={0.01}
                />
              </div>
              <Button
                className="w-full"
                onClick={handleAdd}
                disabled={!addSymbol.trim() || !addShares || !addCost || addMutation.isPending}
              >
                {addMutation.isPending ? "Adding…" : "Add Lot"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
