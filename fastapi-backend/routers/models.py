"""
Quantitative model endpoints.

All heavy math lives in services/quant.py (pure functions) and all market
data access in services/market_data.py; this module is HTTP plumbing:
validation, caching, response shaping.
"""
from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import networkx as nx
import numpy as np
from arch import arch_model
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import cache
from services import market_data, quant
from services.errors import bad_request, internal_error, not_found
from services.market_data import ClosesSeries, SymbolError, normalize_symbol

logger = logging.getLogger(__name__)

router = APIRouter()

# Upper bound on positions in a single VaR request. Each position triggers an
# upstream price fetch, so this caps outbound work per request.
MAX_VAR_POSITIONS = 50


def _cached(endpoint: str, params: dict):
    return cache.get_cached(endpoint, params)


def _store(endpoint: str, params: dict, payload) -> None:
    cache.set_cached(endpoint, params, payload)


def _closes_or_404(symbol: str, range_: str = "1y", min_len: int = 20) -> ClosesSeries:
    series = market_data.fetch_closes(symbol, range_=range_)
    if series is None or len(series.closes) < min_len:
        raise not_found(f"Not enough data for {symbol}")
    return series


def _percentile_lists(fans: dict[str, np.ndarray], decimals: int = 4) -> dict[str, list[float]]:
    return {
        key: [round(float(v), decimals) for v in fans[key]]
        for key in ("p5", "p25", "p50", "p75", "p95")
    }


# ── Regime ────────────────────────────────────────────────────────────────────

@router.get("/regime/{symbol}")
def get_regime(symbol: str):
    """
    Threshold-based bull/bear/sideways regime (consistent with /markov).
    Bull: daily return > +0.5%; bear: < -0.5%; sideways otherwise.
    """
    try:
        symbol = normalize_symbol(symbol)
    except SymbolError as e:
        raise bad_request(str(e))
    try:
        cached = _cached("regime", {"symbol": symbol})
        if cached is not None:
            return cached

        series = _closes_or_404(symbol, min_len=30)
        returns = np.diff(np.log(series.closes))
        regimes = quant.threshold_regimes(returns)

        counts = quant.regime_counts(regimes)
        total = len(regimes)
        probabilities = {name: counts[name] / total for name in quant.REGIME_NAMES}

        momentum = float(returns[-20:].sum() * 100) if len(returns) >= 20 else float(returns.sum() * 100)
        volatility = (
            float(returns[-20:].std() * np.sqrt(252) * 100)
            if len(returns) >= 20
            else float(returns.std() * np.sqrt(252) * 100)
        )

        result = {
            "currentRegime": quant.current_regime(regimes),
            "probabilities": probabilities,
            "momentum": round(momentum, 2),
            "volatility": round(volatility, 2),
            "lastUpdated": str(datetime.now().date()),
        }
        _store("regime", {"symbol": symbol}, result)
        return result
    except HTTPException:
        raise
    except Exception:
        raise internal_error(f"regime failed for {symbol}")


# ── Monte Carlo GBM ───────────────────────────────────────────────────────────

VALID_HORIZONS = {15, 30, 60, 90, 180}


@router.get("/montecarlo/{symbol}")
def get_montecarlo(symbol: str, days: int = 30, regime_adj: bool = True):
    """
    Monte Carlo GBM with percentile fans. `days` ∈ {15, 30, 60, 90, 180};
    `regime_adj` biases drift μ by the current regime (bull +0.5σ, bear −0.5σ).
    """
    if days not in VALID_HORIZONS:
        raise bad_request(f"days must be one of {sorted(VALID_HORIZONS)}")
    try:
        symbol = normalize_symbol(symbol)
    except SymbolError as e:
        raise bad_request(str(e))
    try:
        cached = _cached("montecarlo", {"symbol": symbol, "days": days, "regime_adj": regime_adj})
        if cached is not None:
            return cached

        series = _closes_or_404(symbol, range_="6mo", min_len=30)
        daily_returns = np.diff(np.log(series.closes))
        sigma = float(daily_returns.std())
        S0 = float(series.closes[-1])

        regimes = quant.threshold_regimes(daily_returns)
        current_regime = quant.current_regime(regimes)
        if regime_adj:
            mu = quant.regime_adjusted_drift(daily_returns, current_regime)
        else:
            mu = float(daily_returns.mean())

        fans = quant.gbm_percentile_fans(S0, mu, np.full(days, sigma))
        forecast_dates = quant.trading_day_dates(series.dates, days)

        result = {
            "paths": [[round(float(v), 4) for v in path] for path in fans["samplePaths"]],
            "percentiles": _percentile_lists(fans),
            "forecastDates": forecast_dates,
            "lastPrice": round(S0, 2),
            "currentRegime": current_regime,
            "regimeAdjusted": regime_adj and current_regime != "sideways",
            "horizon": days,
        }
        _store("montecarlo", {"symbol": symbol, "days": days, "regime_adj": regime_adj}, result)
        return result
    except HTTPException:
        raise
    except Exception:
        raise internal_error(f"montecarlo failed for {symbol}")


# ── Regime-Conditional Monte Carlo ────────────────────────────────────────────

@router.get("/montecarlo/{symbol}/regime-cond")
def get_montecarlo_regime_cond(symbol: str, days: int = 30):
    """
    Three regime-conditional GBM fans (bull/bear/sideways) with GARCH(1,1)
    time-varying volatility, blended by Markov n-step transition probabilities
    per forecast day. Converges to the stationary distribution as horizon grows.
    """
    if days not in VALID_HORIZONS:
        raise bad_request(f"days must be one of {sorted(VALID_HORIZONS)}")
    try:
        symbol = normalize_symbol(symbol)
    except SymbolError as e:
        raise bad_request(str(e))
    try:
        cached = _cached("montecarlo_regime_cond", {"symbol": symbol, "days": days})
        if cached is not None:
            return cached

        series = _closes_or_404(symbol, range_="6mo", min_len=60)
        daily_returns = np.diff(np.log(series.closes))
        full_sigma = float(daily_returns.std())  # used only for drift-bias scaling
        S0 = float(series.closes[-1])

        # GARCH(1,1) conditional volatility path (percent returns in, daily out)
        garch_model = arch_model(100 * daily_returns, vol="Garch", p=1, q=1, dist="normal")
        garch_res = garch_model.fit(disp="off", show_warning=False)
        garch_forecast = garch_res.forecast(horizon=30, reindex=False)
        # The model is fit on percent returns, so sqrt(variance) is a percent
        # volatility; /100 converts it to a decimal *daily* sigma. Do not apply
        # an extra annualization factor here — gbm_percentile_fans takes one
        # step = one day, matching /models/garch.
        garch_daily = np.sqrt(garch_forecast.variance.values[-1, :]) / 100
        if days <= 30:
            sigma_series = garch_daily[:days]
        else:
            sigma_series = np.concatenate([garch_daily, np.full(days - 30, garch_daily[-1])])

        regimes = quant.threshold_regimes(daily_returns)
        T_matrix = quant.markov_transition_matrix(regimes)
        current_idx = int(regimes[-1])
        current_regime = quant.REGIME_NAMES[current_idx]

        def mu_for_regime(r: str) -> float:
            if r == "bull":
                return float(daily_returns.mean()) + 0.5 * full_sigma
            if r == "bear":
                return float(daily_returns.mean()) - 0.5 * full_sigma
            return float(daily_returns.mean())

        fans = {r: quant.gbm_percentile_fans(S0, mu_for_regime(r), sigma_series) for r in quant.REGIME_NAMES}

        forecast_dates = quant.trading_day_dates(series.dates, days)
        blended = {k: np.zeros(days) for k in ("p5", "p25", "p50", "p75", "p95")}
        regime_probs_over_time: list[dict] = []
        for t in range(days):
            probs_t = quant.markov_forecast(T_matrix, current_idx, t + 1)
            regime_probs_over_time.append(
                {
                    **{quant.REGIME_NAMES[i]: float(probs_t[i]) for i in range(quant.N_REGIMES)},
                    "date": forecast_dates[t],
                }
            )
            for key in blended:
                blended[key][t] = sum(
                    regime_probs_over_time[t][r] * fans[r][key][t] for r in quant.REGIME_NAMES
                )

        result = {
            "lastPrice": round(S0, 2),
            "horizon": days,
            "sigma": round(float(sigma_series[0]), 6),
            "volatilitySource": "garch",
            "currentRegime": current_regime,
            "regimeProbabilities": regime_probs_over_time,
            "fans": {r: _percentile_lists(fans[r]) for r in quant.REGIME_NAMES},
            "blended": _percentile_lists(blended, decimals=2),
        }
        _store("montecarlo_regime_cond", {"symbol": symbol, "days": days}, result)
        return result
    except HTTPException:
        raise
    except Exception:
        raise internal_error(f"regime-cond montecarlo failed for {symbol}")


# ── GARCH volatility ──────────────────────────────────────────────────────────

@router.get("/garch/{symbol}")
def get_garch(symbol: str):
    """GARCH(1,1) conditional volatility forecast, 30-day horizon."""
    try:
        symbol = normalize_symbol(symbol)
    except SymbolError as e:
        raise bad_request(str(e))
    try:
        cached = _cached("garch", {"symbol": symbol})
        if cached is not None:
            return cached

        series = _closes_or_404(symbol, min_len=30)
        returns_pct = 100 * np.diff(np.log(series.closes))
        model = arch_model(returns_pct, vol="Garch", p=1, q=1, dist="normal")
        res = model.fit(disp="off", show_warning=False)
        forecast = res.forecast(horizon=30, reindex=False)
        cond_vol = np.sqrt(forecast.variance.values[-1, :]) / 100

        result = {
            "currentVol": round(float(res.conditional_volatility[-1] / 100), 6),
            "forecast": [round(float(v), 6) for v in cond_vol],
            "forecastDates": quant.trading_day_dates(series.dates, 30),
        }
        _store("garch", {"symbol": symbol}, result)
        return result
    except HTTPException:
        raise
    except Exception:
        raise internal_error(f"garch failed for {symbol}")


# ── ATR ───────────────────────────────────────────────────────────────────────

@router.get("/atr/{symbol}")
def get_atr(symbol: str, period: int = 14):
    """Average True Range with volatility signal and 30-day TR history."""
    if period < 2 or period > 200:
        raise bad_request("period must be between 2 and 200")
    try:
        symbol = normalize_symbol(symbol)
    except SymbolError as e:
        raise bad_request(str(e))
    try:
        cached = _cached("atr", {"symbol": symbol, "period": period})
        if cached is not None:
            return cached

        chart = market_data.fetch_chart(symbol, range_="3mo")
        if chart is None:
            raise not_found(f"No data for {symbol}")
        highs = np.array([row["high"] for row in chart.ohlcv])
        lows = np.array([row["low"] for row in chart.ohlcv])
        closes = np.array([row["close"] for row in chart.ohlcv])
        if len(closes) < period + 1:
            raise not_found(f"Not enough data for {symbol}")

        tr = quant.true_range(highs, lows, closes)  # aligned with chart.dates[1:]
        current_atr = float(tr[-period:].mean())
        current_price = float(closes[-1])
        atr_pct = current_atr / current_price if current_price > 0 else 0.0
        signal = "high" if atr_pct > 0.03 else "normal" if atr_pct > 0.01 else "low"

        # Show the last 30 TR values with their dates.
        n_show = min(30, len(tr))
        result = {
            "atr": round(current_atr, 4),
            "atrPercent": round(atr_pct * 100, 4),
            "currentPrice": round(current_price, 2),
            "period": period,
            "signal": signal,
            "history": [round(float(v), 4) for v in tr[-n_show:]],
            "dates": chart.dates[-n_show:],
        }
        _store("atr", {"symbol": symbol, "period": period}, result)
        return result
    except HTTPException:
        raise
    except Exception:
        raise internal_error(f"atr failed for {symbol}")


# ── Markov chain ──────────────────────────────────────────────────────────────

@router.get("/markov/{symbol}")
def get_markov(symbol: str):
    """Threshold-regime Markov transition matrix + 1/3/10-step forecasts."""
    try:
        symbol = normalize_symbol(symbol)
    except SymbolError as e:
        raise bad_request(str(e))
    try:
        cached = _cached("markov", {"symbol": symbol})
        if cached is not None:
            return cached

        series = _closes_or_404(symbol, min_len=60)
        returns = np.diff(np.log(series.closes))
        regimes = quant.threshold_regimes(returns)
        T_matrix = quant.markov_transition_matrix(regimes)
        names = quant.REGIME_NAMES
        current_idx = int(regimes[-1])

        expected_durations = {}
        for i, name in enumerate(names):
            p_self = float(T_matrix[i, i])
            if p_self < 1.0:
                expected_durations[name] = round(1.0 / (1.0 - p_self), 1)
            else:
                # Absorbing state → mathematically infinite; cap so the JSON
                # response stays serializable (allow_nan=False).
                expected_durations[name] = 999.9

        def forecast_dict(step: int) -> dict:
            probs = quant.markov_forecast(T_matrix, current_idx, step)
            return {names[i]: round(float(probs[i]), 4) for i in range(quant.N_REGIMES)}

        result = {
            "currentRegime": names[current_idx],
            "currentState": current_idx,
            "transitionMatrix": {
                frm: {to: round(float(T_matrix[i, j]), 4) for j, to in enumerate(names)}
                for i, frm in enumerate(names)
            },
            "expectedDuration": expected_durations,
            "stationary": {
                names[i]: round(float(v), 4)
                for i, v in enumerate(quant.markov_stationary(T_matrix))
            },
            "forecast1Step": forecast_dict(1),
            "forecast3Step": forecast_dict(3),
            "forecast10Step": forecast_dict(10),
            "lastUpdated": str(datetime.now().date()),
        }
        _store("markov", {"symbol": symbol}, result)
        return result
    except HTTPException:
        raise
    except Exception:
        raise internal_error(f"markov failed for {symbol}")


# ── RSI ───────────────────────────────────────────────────────────────────────

RSI_HISTORY_DAYS = 30


@router.get("/rsi/{symbol}")
def get_rsi(symbol: str, period: int = 14):
    """Wilder RSI with overbought/oversold signal and a 30-point history."""
    if period < 2:
        raise bad_request("period must be >= 2")
    try:
        symbol = normalize_symbol(symbol)
    except SymbolError as e:
        raise bad_request(str(e))
    try:
        cached = _cached("rsi", {"symbol": symbol, "period": period})
        if cached is not None:
            return cached

        series = _closes_or_404(symbol, min_len=period + 5)
        current_rsi, full_history = quant.wilder_rsi(series.closes, period)
        # history[j] ↔ closes[period + j] ↔ dates[period + j]
        history_dates = series.dates[period:]
        n_show = min(RSI_HISTORY_DAYS, len(full_history))
        signal = "overbought" if current_rsi > 70 else "oversold" if current_rsi < 30 else "neutral"

        result = {
            "rsi": round(float(current_rsi), 2),
            "signal": signal,
            "period": period,
            "history": [round(float(v), 2) for v in full_history[-n_show:]],
            "dates": history_dates[-n_show:],
        }
        _store("rsi", {"symbol": symbol, "period": period}, result)
        return result
    except HTTPException:
        raise
    except Exception:
        raise internal_error(f"rsi failed for {symbol}")


# ── MACD ──────────────────────────────────────────────────────────────────────

MACD_HISTORY_DAYS = 60


@router.get("/macd/{symbol}")
def get_macd(symbol: str, fast: int = 12, slow: int = 26, signal_span: int = 9):
    """MACD(fast, slow, signal) with a 60-day chart history."""
    if not (2 <= fast < slow):
        raise bad_request("fast must be >= 2 and < slow")
    if signal_span < 1:
        raise bad_request("signal_span must be >= 1")
    try:
        symbol = normalize_symbol(symbol)
    except SymbolError as e:
        raise bad_request(str(e))
    try:
        cached = _cached("macd", {"symbol": symbol, "fast": fast, "slow": slow, "signal_span": signal_span})
        if cached is not None:
            return cached

        series = _closes_or_404(symbol, range_="6mo", min_len=slow + signal_span + 5)
        computed = quant.macd(series.closes, fast, slow, signal_span)
        n_show = min(MACD_HISTORY_DAYS, len(series.closes))

        result = {
            "macd": round(computed["macd"], 4),
            "signal": round(computed["signal"], 4),
            "histogram": round(computed["histogram"], 4),
            "macdHistory": [round(float(v), 4) for v in computed["macdHistory"][-n_show:]],
            "signalHistory": [round(float(v), 4) for v in computed["signalHistory"][-n_show:]],
            "histogramHistory": [round(float(v), 4) for v in computed["histogramHistory"][-n_show:]],
            "dates": series.dates[-n_show:],
        }
        _store("macd", {"symbol": symbol, "fast": fast, "slow": slow, "signal_span": signal_span}, result)
        return result
    except HTTPException:
        raise
    except Exception:
        raise internal_error(f"macd failed for {symbol}")


# ── Bollinger Bands ───────────────────────────────────────────────────────────

BOLLINGER_HISTORY_DAYS = 60


@router.get("/bollinger/{symbol}")
def get_bollinger(symbol: str, period: int = 20, num_std: float = 2.0):
    """Bollinger Bands (period, num_std) with %B, bandwidth, and chart history."""
    if period < 2:
        raise bad_request("period must be >= 2")
    # NaN fails every comparison, so an explicit isfinite check is required —
    # `nan <= 0` is False and the NaN would flow into the bands and out to
    # JSON, which Starlette rejects outside this handler's try/except.
    if not math.isfinite(num_std) or num_std <= 0:
        raise bad_request("num_std must be a finite number > 0")
    try:
        symbol = normalize_symbol(symbol)
    except SymbolError as e:
        raise bad_request(str(e))
    try:
        cached = _cached("bollinger", {"symbol": symbol, "period": period, "num_std": num_std})
        if cached is not None:
            return cached

        series = _closes_or_404(symbol, min_len=period)
        computed = quant.bollinger(series.closes, period, num_std)
        # history[j] ↔ closes[period - 1 + j] ↔ dates[period - 1 + j]
        history_dates = series.dates[period - 1 :]
        n_show = min(BOLLINGER_HISTORY_DAYS, len(computed["history"]))

        result = {
            "sma": round(computed["sma"], 2),
            "upper": round(computed["upper"], 2),
            "lower": round(computed["lower"], 2),
            "bandwidth": round(computed["bandwidth"], 4),
            "percentB": round(computed["percentB"], 4),
            "period": period,
            "numStd": num_std,
            "history": [
                {
                    "sma": round(row["sma"], 2),
                    "upper": round(row["upper"], 2),
                    "lower": round(row["lower"], 2),
                    "bandwidth": round(row["bandwidth"], 4),
                    "percentB": round(row["percentB"], 4),
                }
                for row in computed["history"][-n_show:]
            ],
            "dates": history_dates[-n_show:],
        }
        _store("bollinger", {"symbol": symbol, "period": period, "num_std": num_std}, result)
        return result
    except HTTPException:
        raise
    except Exception:
        raise internal_error(f"bollinger failed for {symbol}")


# ── VaR ───────────────────────────────────────────────────────────────────────

class Position(BaseModel):
    symbol: str = Field(min_length=1, max_length=15)
    shares: float = Field(gt=0, allow_inf_nan=False)
    avgCost: float = Field(gt=0, allow_inf_nan=False)


class VaRRequest(BaseModel):
    # Each position costs one upstream price fetch, so cap the list to keep a
    # single request from driving an unbounded number of outbound calls.
    positions: list[Position] = Field(max_length=MAX_VAR_POSITIONS)


@router.post("/var")
def get_var(req: VaRRequest):
    """
    1-day historical Value at Risk (95%/99%) for a portfolio.

    Method: per-symbol daily log-returns aligned on common trading dates,
    combined into portfolio returns using **value weights** (position value /
    total value) — the previous equal-weight average ignored position sizes.
    Symbols with no fetchable price data are excluded and reported in
    `excludedSymbols`.
    """
    if not req.positions:
        raise bad_request("At least one position required")
    try:
        # Aggregate duplicate symbols into a single net position.
        shares_by_symbol: dict[str, float] = {}
        for position in req.positions:
            try:
                sym = normalize_symbol(position.symbol)
            except SymbolError as e:
                raise bad_request(str(e))
            shares_by_symbol[sym] = shares_by_symbol.get(sym, 0.0) + position.shares

        series_by_symbol: dict[str, ClosesSeries] = {}
        price_by_symbol: dict[str, float] = {}
        # Fetch in parallel: serial fetches made latency scale with position
        # count (each up to the 15s Yahoo timeout).
        with ThreadPoolExecutor(max_workers=min(8, len(shares_by_symbol))) as pool:
            fetched = pool.map(lambda s: market_data.fetch_closes(s, range_="1y"), shares_by_symbol)
            for sym, series in zip(shares_by_symbol, fetched, strict=True):
                if series is not None and len(series.closes) >= 60:
                    series_by_symbol[sym] = series
                    price_by_symbol[sym] = float(series.closes[-1])

        if not series_by_symbol:
            raise not_found("Could not fetch price data for any symbol")

        try:
            _common_dates, aligned = market_data.align_closes(series_by_symbol)
        except ValueError as e:
            raise bad_request(f"Cannot align price history: {e}")

        if min(len(v) for v in aligned.values()) < 61:
            raise not_found("Not enough overlapping return data")

        returns_by_symbol = {sym: np.diff(np.log(closes)) for sym, closes in aligned.items()}
        values = {sym: price_by_symbol[sym] * shares_by_symbol[sym] for sym in aligned}
        portfolio_value = sum(values.values())
        if portfolio_value <= 0:
            raise bad_request("Portfolio value must be positive")

        # Value-weighted portfolio return series.
        weights = {sym: values[sym] / portfolio_value for sym in aligned}
        portfolio_returns = np.zeros(len(next(iter(returns_by_symbol.values()))))
        for sym, rets in returns_by_symbol.items():
            portfolio_returns += weights[sym] * rets

        var_95 = round(float(-np.percentile(portfolio_returns, 5) * portfolio_value), 2)
        var_99 = round(float(-np.percentile(portfolio_returns, 1) * portfolio_value), 2)

        contributions = []
        for sym in sorted(aligned):
            sym_var_pct = abs(float(np.percentile(returns_by_symbol[sym], 5)))
            contributions.append(
                {
                    "symbol": sym,
                    "value": round(values[sym], 2),
                    "varContribution": round(sym_var_pct * values[sym], 2),
                }
            )

        result = {
            "var95": var_95,
            "var99": var_99,
            "portfolioValue": round(portfolio_value, 2),
            "confidence95": "95%",
            "confidence99": "99%",
            "contributions": contributions,
            "excludedSymbols": sorted(set(shares_by_symbol) - set(aligned)),
        }
        return result
    except HTTPException:
        raise
    except Exception:
        raise internal_error("var computation failed")


# ── Pairs / Beta ──────────────────────────────────────────────────────────────

@router.get("/pairs")
def get_pairs(a: str, b: str):
    """
    Beta and Pearson correlation between two tickers over one year of
    **date-aligned** common trading days (b regressed on a: b ≈ α + β·a).
    """
    if not a or not b:
        raise bad_request("Both 'a' and 'b' query params required")
    try:
        a, b = normalize_symbol(a), normalize_symbol(b)
    except SymbolError as e:
        raise bad_request(str(e))
    if a == b:
        raise bad_request("'a' and 'b' must be different symbols")

    try:
        cached = _cached("pairs", {"a": a, "b": b})
        if cached is not None:
            return cached

        series_a = _closes_or_404(a, min_len=60)
        series_b = _closes_or_404(b, min_len=60)
        try:
            _common_dates, aligned = market_data.align_closes({a: series_a, b: series_b})
        except ValueError as e:
            raise bad_request(f"Cannot align price history: {e}")

        returns_a = np.diff(np.log(aligned[a]))
        returns_b = np.diff(np.log(aligned[b]))

        # Guard against zero-variance series (constant prices) and against any
        # non-finite value reaching the response: corrcoef on a series holding
        # an infinite return yields NaN, and Starlette refuses to serialize NaN
        # (it raises *after* this handler returns, escaping the try/except).
        if not (np.all(np.isfinite(returns_a)) and np.all(np.isfinite(returns_b))):
            raise bad_request("Price history contains invalid values for one of the symbols")
        cov_matrix = np.cov(returns_a, returns_b, ddof=1)
        var_a = float(cov_matrix[0, 0])
        var_b = float(cov_matrix[1, 1])
        if not (var_a > 0.0 and var_b > 0.0):
            cov_ab = 0.0
            beta = 0.0
            correlation = 1.0 if np.array_equal(returns_a, returns_b) else 0.0
        else:
            # Sample covariance AND sample variance (consistent ddof=1) — the
            # previous code divided sample covariance by population variance,
            # inflating beta by n/(n-1).
            cov_ab = float(cov_matrix[0, 1])
            beta = cov_ab / var_a
            correlation = float(np.corrcoef(returns_a, returns_b)[0, 1])

        result = {
            "a": a,
            "b": b,
            "beta": round(float(beta), 4),
            "correlation": round(correlation, 4),
            "covariance": round(cov_ab, 6),
            "nObservations": len(returns_a),
        }
        _store("pairs", {"a": a, "b": b}, result)
        return result
    except HTTPException:
        raise
    except Exception:
        raise internal_error(f"pairs failed for {a}/{b}")


# ── Analyst rating ────────────────────────────────────────────────────────────

@router.get("/analyst/{symbol}")
def get_analyst(symbol: str):
    """Analyst consensus from Yahoo Finance (yfinance info + recommendations)."""
    try:
        symbol = normalize_symbol(symbol)
    except SymbolError as e:
        raise bad_request(str(e))
    try:
        cached = _cached("analyst", {"symbol": symbol})
        if cached is not None:
            return cached

        import yfinance as yf

        ticker = yf.Ticker(symbol)
        info = ticker.info
        current_price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
        mean_target = float(info.get("targetMeanPrice", 0) or 0)

        strong_buy = buy = hold = sell = strong_sell = 0
        num_analysts = 0
        try:
            recs = ticker.recommendations
            if recs is not None and len(recs) > 0:
                latest = recs.iloc[0]
                strong_buy = int(latest.get("strongBuy", 0) or 0)
                buy = int(latest.get("buy", 0) or 0)
                hold = int(latest.get("hold", 0) or 0)
                sell = int(latest.get("sell", 0) or 0)
                strong_sell = int(latest.get("strongSell", 0) or 0)
                num_analysts = strong_buy + buy + hold + sell + strong_sell
        except Exception:
            logger.debug("recommendations unavailable for %s", symbol, exc_info=True)
        if num_analysts == 0:
            # Fallback: consensus key only.
            rec_key = (info.get("recommendationKey") or "").lower()
            rec_map = {
                "strong_buy": (1, 0, 0, 0, 0),
                "buy": (0, 1, 0, 0, 0),
                "overweight": (0, 1, 0, 0, 0),
                "hold": (0, 0, 1, 0, 0),
                "equal_weight": (0, 0, 1, 0, 0),
                "sell": (0, 0, 0, 1, 0),
                "underweight": (0, 0, 0, 1, 0),
                "strong_sell": (0, 0, 0, 0, 1),
            }
            strong_buy, buy, hold, sell, strong_sell = rec_map.get(rec_key, (0, 0, 0, 0, 0))
            num_analysts = int(info.get("numberOfAnalystOpinions", 0) or 0)

        result = {
            "strongBuy": strong_buy,
            "buy": buy,
            "hold": hold,
            "sell": sell,
            "strongSell": strong_sell,
            "meanTarget": round(mean_target, 2),
            "numberOfAnalysts": num_analysts,
            "currentPrice": round(current_price, 2),
        }
        _store("analyst", {"symbol": symbol}, result)
        return result
    except HTTPException:
        raise
    except Exception:
        raise internal_error(f"analyst failed for {symbol}")


# ── Correlation graph ─────────────────────────────────────────────────────────

@router.get("/correlation-graph")
def get_correlation_graph(sector: str = "tech"):
    """
    Pearson-correlation minimum spanning tree for a sector universe, computed
    on **date-aligned** closes (60-day window).
    """
    tickers = market_data.SECTOR_TICKERS.get(sector)
    if tickers is None:
        raise bad_request(f"Unknown sector: {sector}. Available: {sorted(market_data.SECTOR_TICKERS)}")
    try:
        cached = _cached("correlation_graph", {"sector": sector})
        if cached is not None:
            return cached

        series_by_symbol: dict[str, ClosesSeries] = {}

        def load(sym: str):
            return sym, market_data.fetch_closes(sym, range_="60d")

        with ThreadPoolExecutor(max_workers=8) as pool:
            for sym, series in pool.map(load, tickers):
                if series is not None and len(series.closes) >= 20:
                    series_by_symbol[sym] = series

        if len(series_by_symbol) < 3:
            raise HTTPException(status_code=503, detail="Not enough tickers loaded. Try again shortly.")

        try:
            _common_dates, aligned = market_data.align_closes(series_by_symbol)
        except ValueError as e:
            raise HTTPException(status_code=503, detail=f"Cannot align price history: {e}")

        tickers_list = sorted(aligned)
        arr = np.column_stack([aligned[t] for t in tickers_list])
        corr_matrix = np.corrcoef(arr, rowvar=False)

        G = nx.Graph()
        for t in tickers_list:
            G.add_node(t, name=t)
        for i, t1 in enumerate(tickers_list):
            for j, t2 in enumerate(tickers_list):
                if i < j:
                    strength = abs(corr_matrix[i, j])
                    if strength > 0.5:
                        # MST minimizes total weight — use correlation DISTANCE
                        # (1 − |corr|) so the tree connects the strongest
                        # relationships. `corr` carries the displayed value.
                        G.add_edge(t1, t2, weight=1.0 - strength, corr=strength)

        mst = nx.minimum_spanning_tree(G)
        result = {
            "nodes": [{"id": n, "name": G.nodes[n].get("name", n)} for n in G.nodes()],
            "edges": [
                {"source": u, "target": v, "weight": round(float(d["corr"]), 3)}
                for u, v, d in mst.edges(data=True)
            ],
        }
        _store("correlation_graph", {"sector": sector}, result)
        return result
    except HTTPException:
        raise
    except Exception:
        raise internal_error(f"correlation-graph failed for {sector}")


# ── Cache management ──────────────────────────────────────────────────────────

@router.get("/cache/stats")
def get_cache_stats():
    """Cache size + per-endpoint counts (best-effort)."""
    return cache.stats()


@router.post("/cache/purge")
def post_cache_purge(max_age_seconds: int = 24 * 3600):
    """Delete model-cache entries older than max_age_seconds (bounded)."""
    if max_age_seconds < 0 or max_age_seconds > 30 * 24 * 3600:
        raise bad_request("max_age_seconds must be between 0 and 2592000")
    deleted = cache.purge_stale(max_age_seconds)
    return {"deleted": deleted}
