"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api";

export function SkeletonBox({ height = "300px", className = "" }: { height?: string; className?: string }) {
  return <Skeleton className={`w-full ${className}`} style={{ height }} />;
}

export function ErrorBox({
  height = "300px",
  onRetry,
  message = "Couldn't load data",
  className = "",
}: {
  height?: string;
  onRetry?: () => void;
  message?: string;
  className?: string;
}) {
  return (
    <div
      className={`w-full flex flex-col items-center justify-center gap-3 text-muted-foreground text-sm ${className}`}
      style={{ height }}
    >
      <p>{message}</p>
      {onRetry && (
        <Button size="sm" variant="outline" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

export function EmptyBox({
  height = "300px",
  message,
  className = "",
}: {
  height?: string;
  message: string;
  className?: string;
}) {
  return (
    <div
      className={`w-full flex items-center justify-center text-muted-foreground text-sm ${className}`}
      style={{ height }}
    >
      {message}
    </div>
  );
}

interface QueryRenderProps<T> {
  data: T | undefined;
  isLoading: boolean;
  isError: boolean;
  /**
   * react-query's `error`. Optional — when present, a 401/503/429 is reported
   * as what it actually is instead of the generic data-error text. Pass it
   * wherever the query is destructured; omitting it only costs message detail.
   */
  error?: unknown;
  refetch: () => void;
  /**
   * react-query's `isPending`. Optional, but pass it for queries gated by
   * `enabled`: on the render where `enabled` flips true, `isLoading` is still
   * false (the fetch starts in an effect) and data is undefined, so without
   * this the component flashes a permanent "no data" empty state before the
   * skeleton appears.
   */
  isPending?: boolean;
  height?: string;
  emptyMessage?: string;
  errorMessage?: string;
  children: (data: T) => React.ReactNode;
}

/**
 * Consistent loading / error / empty / data rendering for a react-query result.
 * Eliminates the "skeleton forever on error" pattern.
 */
export function QueryRender<T>({
  data,
  isLoading,
  isError,
  error,
  refetch,
  isPending,
  height = "300px",
  emptyMessage = "No data available",
  errorMessage = "Couldn't load data — the market data provider may be rate-limited.",
  children,
}: QueryRenderProps<T>) {
  // `isPending` covers the "gated query just became enabled" render.
  if (isLoading || (isPending === true && data === undefined)) return <SkeletonBox height={height} />;
  if (isError) {
    return <ErrorBox height={height} onRetry={refetch} message={apiErrorMessage(error, errorMessage)} />;
  }
  if (!data) return <EmptyBox height={height} message={emptyMessage} />;
  return <>{children(data)}</>;
}
