import os
import numpy as np
import requests
import networkx as nx
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from arch import arch_model
from hmmlearn import hmm

import cache

router = APIRouter()


def _cached(endpoint: str, params: dict):
    """
    Return cached result if fresh, else None.
    Usage: result = _cached('regime', {'symbol': symbol}); if result: return result
    """
    return cache.get_cached(endpoint, params)


def _store(endpoint: str, params: dict, payload) -> None:
    """Write a result to the cache (best-effort)."""
    cache.set_cached(endpoint, params, payload)


# ── Yahoo Finance chart API ───────────────────────────────────────────────────
_yf_session = requests.Session()
_yf_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
})


def _get_closes_yahoo(symbol: str, range_: str = "1y") -> np.ndarray | None:
    """Fetch closing prices from Yahoo Finance chart API."""
    try:
        resp = _yf_session.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"interval": "1d", "range": range_},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None
        closes = result[0]["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]
        return np.array(closes) if len(closes) >= 20 else None
    except Exception:
        return None


# ── Markov Regime Detection ──────────────────────────────────────────────────

@router.get("/regime/{symbol}")
def get_regime(symbol: str):
    """
    Detect current regime (bull/bear/sideways) using threshold-based classification.
    Bull:    daily return > +0.5%
    Bear:    daily return < -0.5%
    Sideways: -0.5% <= daily return <= +0.5%
    This is consistent with the Markov chain endpoint.
    """
    try:
        cached = _cached("regime", {"symbol": symbol})
        if cached is not None:
            return cached

        closes = _get_closes_yahoo(symbol)
        if closes is None or len(closes) < 30:
            raise HTTPException(status_code=404, detail=f"No data found for {symbol}")

        returns = np.diff(np.log(closes))

        # Use same threshold-based labeling as Markov chain (consistent)
        regimes = _get_threshold_regimes(returns)

        regime_counts = {
            "bear": int(np.sum(regimes == 0)),
            "sideways": int(np.sum(regimes == 1)),
            "bull": int(np.sum(regimes == 2)),
        }
        total = len(regimes)
        prob_bull = regime_counts["bull"] / total
        prob_bear = regime_counts["bear"] / total
        prob_sideways = regime_counts["sideways"] / total

        current_regime = {0: "bear", 1: "sideways", 2: "bull"}[int(regimes[-1])]

        momentum = float(returns[-20:].sum() * 100) if len(returns) >= 20 else float(returns.sum() * 100)
        volatility = float(returns[-20:].std() * np.sqrt(252) * 100) if len(returns) >= 20 else float(returns.std() * np.sqrt(252) * 100)

        result = {
            "currentRegime": current_regime,
            "probabilities": {"bull": prob_bull, "bear": prob_bear, "sideways": prob_sideways},
            "momentum": round(momentum, 2),
            "volatility": round(volatility, 2),
            "lastUpdated": str(datetime.now().date()),
        }
        _store("regime", {"symbol": symbol}, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Monte Carlo GBM ───────────────────────────────────────────────────────────

class MonteCarloResult(BaseModel):
    paths: list
    percentiles: dict
    forecastDates: list
    lastPrice: float


def _get_threshold_regimes_for_mc(returns: np.ndarray) -> tuple[str, float]:
    """
    Threshold-based regime detection consistent with regime/markov endpoints.
    Bull:    return > +0.5% per day
    Bear:    return < -0.5% per day
    Sideways: -0.5% <= return <= +0.5%
    Returns (regime_name, regime_adjusted_drift).
    """
    regimes = np.where(returns > 0.005, 2, np.where(returns < -0.005, 0, 1))
    current = int(regimes[-1])
    regime_names = {0: "bear", 1: "sideways", 2: "bull"}
    regime = regime_names[current]

    # Regime bias: adjust the drift μ
    # Bull regime adds +0.5*σ to expected daily return
    # Bear regime subtracts -0.5*σ
    # Sideways leaves μ unchanged
    sigma = returns.std()
    if regime == "bull":
        mu_adj = returns.mean() + 0.5 * sigma
    elif regime == "bear":
        mu_adj = returns.mean() - 0.5 * sigma
    else:
        mu_adj = returns.mean()

    return regime, mu_adj


@router.get("/montecarlo/{symbol}")
def get_montecarlo(symbol: str, days: int = 30, regime_adj: bool = True):
    """
    Monte Carlo GBM price simulation.
    days: forecast horizon — 15, 30, 60, 90, or 180 (default 30)
    regime_adj: if True, adjusts drift μ based on current regime
                (bull adds +0.5σ, bear subtracts -0.5σ, sideways unchanged)
    """
    valid_days = {15, 30, 60, 90, 180}
    if days not in valid_days:
        raise HTTPException(status_code=400, detail=f"days must be one of {valid_days}")

    try:
        cached = _cached("montecarlo", {"symbol": symbol, "days": days, "regime_adj": regime_adj})
        if cached is not None:
            return cached

        closes = _get_closes_yahoo(symbol, range_="6mo")
        if closes is None or len(closes) < 30:
            raise HTTPException(status_code=404, detail=f"No data found for {symbol}")

        daily_returns = np.diff(np.log(closes))
        sigma = daily_returns.std()
        S0 = closes[-1]

        # Apply regime adjustment if enabled
        current_regime, mu = _get_threshold_regimes_for_mc(daily_returns)
        if not regime_adj:
            mu = daily_returns.mean()

        n_sims = 1000
        dt = 1 / 252
        n_steps = days

        Z = np.random.standard_normal((n_sims, n_steps))
        log_rets = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * Z

        first_col = np.zeros((n_sims, 1))
        all_rets = np.hstack([first_col, log_rets])
        paths = S0 * np.exp(np.cumsum(all_rets, axis=1))

        # Slice to exclude S0 (column 0) — keep only forecast steps (columns 1..n_steps)
        forecast_paths = paths[:, 1:]

        percentiles = {
            "p5": np.percentile(forecast_paths, 5, axis=0).tolist(),
            "p25": np.percentile(forecast_paths, 25, axis=0).tolist(),
            "p50": np.percentile(forecast_paths, 50, axis=0).tolist(),
            "p75": np.percentile(forecast_paths, 75, axis=0).tolist(),
            "p95": np.percentile(forecast_paths, 95, axis=0).tolist(),
        }

        base_date = datetime.now()
        forecast_dates = [(base_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, days + 1)]

        result = {
            "paths": forecast_paths[:10].tolist(),
            "percentiles": percentiles,
            "forecastDates": forecast_dates,
            "lastPrice": round(float(S0), 2),
            "currentRegime": current_regime,
            "regimeAdjusted": regime_adj and current_regime != "sideways",
            "horizon": days,
        }
        _store("montecarlo", {"symbol": symbol, "days": days, "regime_adj": regime_adj}, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Regime-Conditional Monte Carlo ───────────────────────────────────────────

@router.get("/montecarlo/{symbol}/regime-cond")
def get_montecarlo_regime_cond(symbol: str, days: int = 30):
    """
    Regime-conditioned Monte Carlo GBM.
    Runs3 separate GBM fans (bull/bear/sideways) and blends them using
    Markov chain n-step forecast probabilities at each horizon day.
    Converges toward stationary distribution as horizon → ∞.
    """
    valid_days = {15, 30, 60, 90, 180}
    if days not in valid_days:
        raise HTTPException(status_code=400, detail=f"days must be one of {valid_days}")

    try:
        cached = _cached("montecarlo_regime_cond", {"symbol": symbol, "days": days})
        if cached is not None:
            return cached

        closes = _get_closes_yahoo(symbol, range_="6mo")
        if closes is None or len(closes) < 60:
            raise HTTPException(status_code=404, detail=f"Not enough data for {symbol}")

        daily_returns = np.diff(np.log(closes))
        full_sigma = daily_returns.std()  # used only for drift-bias scaling
        S0 = closes[-1]

        # ── GARCH(1,1) conditional volatility ──────────────────────────────────
        # Computed inline so the MC simulation adapts to time-varying vol
        returns_pct = 100 * daily_returns
        garch_model = arch_model(returns_pct, vol="Garch", p=1, q=1, dist="normal")
        garch_res = garch_model.fit(disp="off", show_warning=False)
        garch_forecast = garch_res.forecast(horizon=30, reindex=False)
        # cond_vol from GARCH is annualized ÷100; convert to daily by ÷ sqrt(252)
        garch_daily = np.sqrt(garch_forecast.variance.values[-1, :]) / 100 / np.sqrt(252)
        # Extend to cover all horizons: hold last GARCH value for days beyond 30
        if days <= 30:
            sigma_series = garch_daily[:days]
        else:
            sigma_series = np.concatenate([
                garch_daily,
                np.full(days - 30, garch_daily[-1]),
            ])

        # ── Build Markov transition matrix (inline, same logic as /markov endpoint) ──
        regimes = _get_threshold_regimes(daily_returns)
        n_states = 3
        transition_counts = np.zeros((n_states, n_states), dtype=float)
        for i in range(len(regimes) - 1):
            s_from = int(regimes[i])
            s_to = int(regimes[i + 1])
            transition_counts[s_from][s_to] += 1
        row_sums = transition_counts.sum(axis=1)
        T_matrix = np.zeros((n_states, n_states))
        for i in range(n_states):
            if row_sums[i] > 0:
                T_matrix[i] = transition_counts[i] / row_sums[i]
            else:
                T_matrix[i] = np.full(n_states, 1.0 / n_states)
        regime_names = ["bear", "sideways", "bull"]
        current_idx = int(regimes[-1])
        current_regime = regime_names[current_idx]

        # ── Drift biases per regime — scaled to current GARCH sigma ─────────────
        # Bias is expressed as ±0.5σ from mean return; using GARCH sigma makes
        # the drift responsive to current volatility regime rather than the
        # full-sample average.
        def mu_for_regime(r: str) -> float:
            if r == "bull":
                return daily_returns.mean() + 0.5 * full_sigma
            elif r == "bear":
                return daily_returns.mean() - 0.5 * full_sigma
            return daily_returns.mean()

        # ── GBM simulation helper — time-varying sigma from GARCH ───────────────
        def gbm_fan(mu: float, n_sims: int = 1000) -> dict:
            dt = 1 / 252
            Z = np.random.standard_normal((n_sims, days))
            # Vectorised time-varying sigma: element-wise multiply each column
            # by the corresponding GARCH sigma for that forecast day
            sigma_col = sigma_series[np.newaxis, :]  # shape (1, days)
            log_rets = (mu - 0.5 * sigma_col**2) * dt + sigma_col * np.sqrt(dt) * Z
            first_col = np.zeros((n_sims, 1))
            all_rets = np.hstack([first_col, log_rets])
            paths = S0 * np.exp(np.cumsum(all_rets, axis=1))
            forecast_paths = paths[:, 1:]
            return {
                "p5": np.percentile(forecast_paths, 5, axis=0).tolist(),
                "p25": np.percentile(forecast_paths, 25, axis=0).tolist(),
                "p50": np.percentile(forecast_paths, 50, axis=0).tolist(),
                "p75": np.percentile(forecast_paths, 75, axis=0).tolist(),
                "p95": np.percentile(forecast_paths, 95, axis=0).tolist(),
            }

        # ── Run3 regime fans ──
        fans = {r: gbm_fan(mu_for_regime(r)) for r in regime_names}

        # ── Blend using Markov n-step probabilities ──
        base_date = datetime.now()
        forecast_dates = [(base_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, days + 1)]

        blended = {k: [0.0] * days for k in ("p5", "p25", "p50", "p75", "p95")}
        regime_probs_over_time: list[dict] = []

        for t in range(days):
            # n-step probability from current regime
            P_t = np.linalg.matrix_power(T_matrix, t + 1)[current_idx]
            probs = {regime_names[i]: float(P_t[i]) for i in range(n_states)}
            regime_probs_over_time.append({**probs, "date": forecast_dates[t]})

            for key in blended:
                blended[key][t] = sum(
                    probs[r] * fans[r][key][t] for r in regime_names
                )

        result = {
            "lastPrice": round(float(S0), 2),
            "horizon": days,
            "sigma": round(float(sigma_series[0]), 6),  # current GARCH daily vol
            "volatilitySource": "garch", # vs full-sample historical
            "currentRegime": current_regime,
            "regimeProbabilities": regime_probs_over_time,
            "fans": {
                r: {pk: [round(float(v), 4) for v in fans[r][pk]] for pk in fans[r]} for r in regime_names
            },
            "blended": {k: [round(float(v), 2) for v in blended[k]] for k in blended},
        }
        _store("montecarlo_regime_cond", {"symbol": symbol, "days": days}, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── GARCH Volatility ──────────────────────────────────────────────────────────

@router.get("/garch/{symbol}")
def get_garch(symbol: str):
    try:
        cached = _cached("garch", {"symbol": symbol})
        if cached is not None:
            return cached

        closes = _get_closes_yahoo(symbol)
        if closes is None or len(closes) < 30:
            raise HTTPException(status_code=404, detail=f"No data found for {symbol}")

        returns = 100 * np.diff(np.log(closes))
        model = arch_model(returns, vol="Garch", p=1, q=1, dist="normal")
        res = model.fit(disp="off", show_warning=False)

        forecast = res.forecast(horizon=30, reindex=False)
        cond_vol = np.sqrt(forecast.variance.values[-1, :]) / 100

        base_date = datetime.now()
        forecast_dates = [(base_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 31)]

        result = {
            "currentVol": round(float(res.conditional_volatility[-1] / 100), 6),
            "forecast": [round(float(v), 6) for v in cond_vol],
            "forecastDates": forecast_dates,
        }
        _store("garch", {"symbol": symbol}, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── ATR (Average True Range) ─────────────────────────────────────────────────

@router.get("/atr/{symbol}")
def get_atr(symbol: str, period: int = 14):
    """
    Average True Range — measures current volatility for stop-loss sizing.
    ATR = average of True Range over the last `period` trading days.
    True Range = max(high - low, |high - prev_close|, |low - prev_close|)
    """
    if period < 2 or period > 200:
        raise HTTPException(status_code=400, detail="period must be between 2 and 200")
    try:
        cached = _cached("atr", {"symbol": symbol, "period": period})
        if cached is not None:
            return cached

        resp = _yf_session.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"interval": "1d", "range": "3mo"},
            timeout=15,
        )
        if resp.status_code != 200 or not resp.json().get("chart", {}).get("result"):
            raise HTTPException(status_code=404, detail=f"No data for {symbol}")

        result_data = resp.json()["chart"]["result"][0]
        quote = result_data["indicators"]["quote"][0]
        highs = quote.get("high")
        lows = quote.get("low")
        closes = quote.get("close")

        if not highs or not lows or not closes:
            raise HTTPException(status_code=404, detail=f"Incomplete data for {symbol}")

        # Filter None values
        data_points = [
            (h, l, c) for h, l, c in zip(highs, lows, closes)
            if h is not None and l is not None and c is not None
        ]
        if len(data_points) < period + 1:
            raise HTTPException(status_code=404, detail=f"Not enough data for {symbol}")

        highs, lows, closes = zip(*data_points)
        highs = np.array(highs)
        lows = np.array(lows)
        closes = np.array(closes)

        prev_closes = closes[:-1]
        tr1 = highs[1:] - lows[1:]
        tr2 = np.abs(highs[1:] - prev_closes)
        tr3 = np.abs(lows[1:] - prev_closes)
        true_ranges = np.maximum(np.maximum(tr1, tr2), tr3)

        atr = float(np.mean(true_ranges[-period:]))
        current_price = float(closes[-1])
        atr_pct = atr / current_price if current_price > 0 else 0

        history = true_ranges.tolist()
        signal = "high" if atr_pct > 0.03 else "normal" if atr_pct > 0.01 else "low"

        result = {
            "atr": round(atr, 4),
            "atrPercent": round(atr_pct * 100, 4),
            "currentPrice": round(current_price, 2),
            "period": period,
            "signal": signal,
            "history": [round(float(v), 4) for v in history],
        }
        _store("atr", {"symbol": symbol, "period": period}, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Markov Chain ───────────────────────────────────────────────────────────────

def _get_threshold_regimes(returns: np.ndarray) -> np.ndarray:
    """
    Label each daily return as bull/bear/sideways using threshold-based classification.
    Bull:    return > +0.5% per day  (~127% annualized if sustained)
    Bear:    return < -0.5% per day
    Sideways: -0.5% <= return <= +0.5%
    This is more robust than HMM clustering for financial data.
    """
    labels = np.where(returns > 0.005, 2, np.where(returns < -0.005, 0, 1))
    return labels  # 0=bear, 1=sideways, 2=bull


@router.get("/markov/{symbol}")
def get_markov(symbol: str):
    """
    Compute the Markov regime transition matrix and forecast regime probabilities.
    Uses threshold-based regime classification (bull/bear/sideways) rather than HMM,
    which is more reliable for financial return data.
    """
    try:
        cached = _cached("markov", {"symbol": symbol})
        if cached is not None:
            return cached

        closes = _get_closes_yahoo(symbol)
        if closes is None or len(closes) < 60:
            raise HTTPException(status_code=404, detail=f"Not enough data for {symbol}")

        returns = np.diff(np.log(closes))

        # Classify each day into a regime
        regimes = _get_threshold_regimes(returns)
        n_states = 3

        # Count transitions to build transition matrix
        transition_counts = np.zeros((n_states, n_states), dtype=float)
        for i in range(len(regimes) - 1):
            s_from = int(regimes[i])
            s_to = int(regimes[i + 1])
            transition_counts[s_from][s_to] += 1

        # Row-normalize to get probabilities
        row_sums = transition_counts.sum(axis=1)
        T_matrix = np.zeros((n_states, n_states))
        for i in range(n_states):
            if row_sums[i] > 0:
                T_matrix[i] = transition_counts[i] / row_sums[i]
            else:
                T_matrix[i] = np.full(n_states, 1.0 / n_states)  # unseen state → uniform

        # Current regime (last day)
        regime_names = ["bear", "sideways", "bull"]
        current_regime = regime_names[int(regimes[-1])]

        # Expected duration in each regime = 1 / (1 - p_stay)
        expected_durations = []
        for i in range(n_states):
            p_self = T_matrix[i, i]
            expected_durations.append(round(1.0 / (1.0 - p_self), 1) if p_self < 1.0 else float("inf"))

        # Stationary distribution (left eigenvector of T with eigenvalue=1)
        stationary = np.full(n_states, 1.0 / n_states)
        try:
            eigvals, eigvecs = np.linalg.eig(T_matrix.T)
            idx = np.argmin(np.abs(eigvals - 1.0))
            stationary = np.abs(eigvecs[:, idx])
            stationary = stationary / stationary.sum()
        except Exception:
            pass

        # Forecast: n-step regime probability from current state
        current_idx = int(regimes[-1])

        def forecast_probs(step: int) -> dict:
            probs = np.linalg.matrix_power(T_matrix, step)
            return {regime_names[i]: round(float(probs[current_idx, i]), 4) for i in range(n_states)}

        forecast_1 = forecast_probs(1)
        forecast_3 = forecast_probs(3)
        forecast_10 = forecast_probs(10)

        result = {
            "currentRegime": current_regime,
            "currentState": int(regimes[-1]),
            "transitionMatrix": {
                "bear":    {"bear": round(T_matrix[0, 0], 4),    "sideways": round(T_matrix[0, 1], 4), "bull": round(T_matrix[0, 2], 4)},
                "sideways": {"bear": round(T_matrix[1, 0], 4), "sideways": round(T_matrix[1, 1], 4), "bull": round(T_matrix[1, 2], 4)},
                "bull":    {"bear": round(T_matrix[2, 0], 4),    "sideways": round(T_matrix[2, 1], 4), "bull": round(T_matrix[2, 2], 4)},
            },
            "expectedDuration": {
                "bear":    expected_durations[0],
                "sideways": expected_durations[1],
                "bull":    expected_durations[2],
            },
            "stationary": {regime_names[i]: round(float(stationary[i]), 4) for i in range(n_states)},
            "forecast1Step": forecast_1,
            "forecast3Step": forecast_3,
            "forecast10Step": forecast_10,
            "lastUpdated": str(datetime.now().date()),
        }
        _store("markov", {"symbol": symbol}, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── RSI ───────────────────────────────────────────────────────────────────────

def _compute_rsi(closes: np.ndarray, period: int = 14) -> tuple[float, list[float]]:
    """Compute RSI(period). Returns (current_rsi, rsi_history)."""
    returns = np.diff(np.log(closes))
    gains = np.where(returns > 0, returns, 0.0)
    losses = np.where(returns < 0, -returns, 0.0)

    # Use Wilder's smoothing (EMA-like)
    avg_gain = gains[-period:].mean()
    avg_loss = losses[-period:].mean()
    rsi_history = []
    for i in range(period, len(closes)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 0
        rsi_history.append(100 - 100 / (1 + rs))
    current_rsi = rsi_history[-1] if rsi_history else 50.0
    return current_rsi, rsi_history[-30:]


@router.get("/rsi/{symbol}")
def get_rsi(symbol: str, period: int = 14):
    """14-day RSI with overbought/oversold signal and 30-day history."""
    if period < 2:
        raise HTTPException(status_code=400, detail="period must be >= 2")
    try:
        cached = _cached("rsi", {"symbol": symbol, "period": period})
        if cached is not None:
            return cached

        closes = _get_closes_yahoo(symbol)
        if closes is None or len(closes) < period + 5:
            raise HTTPException(status_code=404, detail=f"Not enough data for {symbol}")

        current_rsi, rsi_history = _compute_rsi(closes, period)
        signal = "overbought" if current_rsi > 70 else "oversold" if current_rsi < 30 else "neutral"

        result = {
            "rsi": round(float(current_rsi), 2),
            "signal": signal,
            "period": period,
            "history": [round(float(v), 2) for v in rsi_history],
        }
        _store("rsi", {"symbol": symbol, "period": period}, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── MACD ────────────────────────────────────────────────────────────────────────

def _ema(values: np.ndarray, span: int) -> np.ndarray:
    """Compute EMA over a numpy array."""
    ema = np.zeros(len(values))
    ema[0] = values[0]
    alpha = 2 / (span + 1)
    for i in range(1, len(values)):
        ema[i] = alpha * values[i] + (1 - alpha) * ema[i - 1]
    return ema


@router.get("/macd/{symbol}")
def get_macd(symbol: str, fast: int = 12, slow: int = 26, signal_span: int = 9):
    """MACD(12,26,9) — returns current values and 60-day history for charting."""
    if not (2 <= fast< slow):
        raise HTTPException(status_code=400, detail="fast must be >= 2 and < slow")
    try:
        cached = _cached("macd", {"symbol": symbol, "fast": fast, "slow": slow, "signal_span": signal_span})
        if cached is not None:
            return cached

        closes = _get_closes_yahoo(symbol, range_="6mo")
        if closes is None or len(closes) < slow + signal_span + 5:
            raise HTTPException(status_code=404, detail=f"Not enough data for {symbol}")

        closes = np.array(closes)
        ema_fast = _ema(closes, fast)
        ema_slow = _ema(closes, slow)
        macd_line = ema_fast - ema_slow
        signal_line = _ema(macd_line, signal_span)
        histogram = macd_line - signal_line

        # Last 60 values for charting
        n_show = 60
        macd_hist = macd_line[-n_show:]
        sig_hist = signal_line[-n_show:]
        hist_hist = histogram[-n_show:]

        result = {
            "macd": round(float(macd_line[-1]), 4),
            "signal": round(float(signal_line[-1]), 4),
            "histogram": round(float(histogram[-1]), 4),
            "macdHistory": [round(float(v), 4) for v in macd_hist],
            "signalHistory": [round(float(v), 4) for v in sig_hist],
            "histogramHistory": [round(float(v), 4) for v in hist_hist],
        }
        _store("macd", {"symbol": symbol, "fast": fast, "slow": slow, "signal_span": signal_span}, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Bollinger Bands ────────────────────────────────────────────────────────────

@router.get("/bollinger/{symbol}")
def get_bollinger(symbol: str, period: int = 20, num_std: float = 2.0):
    """20-day Bollinger Bands (±2σ) with %B and bandwidth."""
    if period < 2:
        raise HTTPException(status_code=400, detail="period must be >= 2")
    try:
        cached = _cached("bollinger", {"symbol": symbol, "period": period, "num_std": num_std})
        if cached is not None:
            return cached

        closes = _get_closes_yahoo(symbol)
        if closes is None or len(closes) < period:
            raise HTTPException(status_code=404, detail=f"Not enough data for {symbol}")

        closes = np.array(closes)
        history = []
        for i in range(period - 1, len(closes)):
            window = closes[i - period + 1:i + 1]
            sma = window.mean()
            std = window.std()
            upper = sma + num_std * std
            lower = sma - num_std * std
            bandwidth = (upper - lower) / sma if sma != 0 else 0
            pct_b = (closes[i] - lower) / (upper - lower) if (upper - lower) != 0 else 0
            history.append({
                "sma": round(float(sma), 2),
                "upper": round(float(upper), 2),
                "lower": round(float(lower), 2),
                "bandwidth": round(float(bandwidth), 4),
                "percentB": round(float(pct_b), 4),
            })

        latest = history[-1]
        result = {
            "sma": latest["sma"],
            "upper": latest["upper"],
            "lower": latest["lower"],
            "bandwidth": latest["bandwidth"],
            "percentB": latest["percentB"],
            "period": period,
            "numStd": num_std,
            "history": history[-60:],  # last 60 bars for charting
        }
        _store("bollinger", {"symbol": symbol, "period": period, "num_std": num_std}, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── VaR ───────────────────────────────────────────────────────────────────────

class Position(BaseModel):
    symbol: str
    shares: float
    avgCost: float


class VaRRequest(BaseModel):
    positions: list[Position]


@router.post("/var")
def get_var(req: VaRRequest):
    """
    1-day 95% and 99% Historical Value at Risk.
    POST with: {"positions": [{"symbol": "AAPL", "shares": 10, "avgCost": 150}, ...]}
    """
    if not req.positions:
        raise HTTPException(status_code=400, detail="At least one position required")

    # Fetch prices for all symbols
    symbols = list({p.symbol for p in req.positions})
    price_map: dict[str, float] = {}
    for sym in symbols:
        closes = _get_closes_yahoo(sym, range_="1y")
        if closes is not None and len(closes) >= 60:
            price_map[sym] = float(closes[-1])

    if not price_map:
        raise HTTPException(status_code=404, detail="Could not fetch price data for any symbol")

    # Build return series for each symbol (aligned)
    aligned: dict[str, np.ndarray] = {}
    for sym in symbols:
        closes = _get_closes_yahoo(sym, range_="1y")
        if closes is not None and len(closes) >= 60:
            aligned[sym] = np.array(closes)

    if not aligned:
        raise HTTPException(status_code=404, detail="Not enough return data")

    min_len = min(len(v) for v in aligned.values())
    returns_by_symbol = {sym: np.diff(np.log(v[:min_len])) for sym, v in aligned.items()}

    # Compute portfolio value and per-symbol weights
    portfolio_value = sum(
        price_map.get(p.symbol, 0) * p.shares for p in req.positions if p.symbol in price_map
    )
    if portfolio_value <= 0:
        raise HTTPException(status_code=400, detail="Portfolio value must be positive")

    # VaR at portfolio level using equal-weighted returns (simplified)
    # For a proper VaR we'd need per-symbol weights; use average correlation effect
    combined_returns = np.mean([r for r in returns_by_symbol.values()], axis=0)

    var_95 = round(float(np.percentile(combined_returns, 5) * portfolio_value * -1), 2)
    var_99 = round(float(np.percentile(combined_returns, 1) * portfolio_value * -1), 2)

    # Per-symbol VaR contribution (weight × individual VaR)
    contributions = []
    for p in req.positions:
        if p.symbol in returns_by_symbol and p.symbol in price_map:
            pos_value = price_map[p.symbol] * p.shares
            sym_returns = returns_by_symbol[p.symbol]
            var_pct = abs(float(np.percentile(sym_returns, 5)))
            contributions.append({
                "symbol": p.symbol,
                "value": round(pos_value, 2),
                "varContribution": round(var_pct * pos_value, 2),
            })

    result = {
        "var95": var_95,
        "var99": var_99,
        "portfolioValue": round(portfolio_value, 2),
        "confidence95": "95%",
        "confidence99": "99%",
        "contributions": contributions,
    }
    return result


# ── Pairs / Beta ──────────────────────────────────────────────────────────────

@router.get("/pairs")
def get_pairs(a: str, b: str):
    """Compute beta and Pearson correlation between two tickers over 1 year."""
    if not a or not b:
        raise HTTPException(status_code=400, detail="Both 'a' and 'b' query params required")
    a, b = a.upper(), b.upper()
    if a == b:
        raise HTTPException(status_code=400, detail="'a' and 'b' must be different symbols")

    try:
        cached = _cached("pairs", {"a": a, "b": b})
        if cached is not None:
            return cached

        closes_a = _get_closes_yahoo(a, range_="1y")
        closes_b = _get_closes_yahoo(b, range_="1y")
        if closes_a is None or closes_b is None or len(closes_a) < 60 or len(closes_b) < 60:
            raise HTTPException(status_code=404, detail=f"Not enough data for {a} or {b}")

        # Align by taking minimum length
        min_len = min(len(closes_a), len(closes_b))
        arr_a = np.array(closes_a[:min_len])
        arr_b = np.array(closes_b[:min_len])
        returns_a = np.diff(np.log(arr_a))
        returns_b = np.diff(np.log(arr_b))

        var_a = returns_a.var()
        cov_ab = np.cov(returns_a, returns_b)[0, 1]
        beta = cov_ab / var_a if var_a != 0 else 0.0
        correlation = float(np.corrcoef(returns_a, returns_b)[0, 1])

        result = {
            "a": a,
            "b": b,
            "beta": round(float(beta), 4),
            "correlation": round(float(correlation), 4),
            "covariance": round(float(cov_ab), 6),
            "nObservations": len(returns_a),
 }
        _store("pairs", {"a": a, "b": b}, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Analyst Rating ────────────────────────────────────────────────────────────

@router.get("/analyst/{symbol}")
def get_analyst(symbol: str):
    """Yahoo Finance analyst recommendation via quoteSummary recommendationTrend module."""
    try:
        cached = _cached("analyst", {"symbol": symbol})
        if cached is not None:
            return cached

        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info
        # Current price from info (fallback)
        current_price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
        mean_target = float(info.get("targetMeanPrice", 0) or 0)

        # Use quoteSummary recommendationTrend for actual per-analyst counts
        try:
            trend_data = ticker.quotes_df if hasattr(ticker, "quotes_df") else None
        except Exception:
            trend_data = None

        # Fetch via quoteSummary REST API for recommendationTrend
        import requests
        try:
            url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
            params = {"modules": "recommendationTrend"}
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            json = resp.json()
            trend = json.get("quoteSummary", {}).get("result", [{}])[0].get("recommendationTrend", {})
            # 'trend' is a list of periods; [0] is the most recent
            periods = trend.get("trend", [])
            latest = periods[0] if periods else {}
            strong_buy = int(latest.get("strongBuy", 0) or 0)
            buy = int(latest.get("buy", 0) or 0)
            hold = int(latest.get("hold", 0) or 0)
            sell = int(latest.get("sell", 0) or 0)
            strong_sell = int(latest.get("strongSell", 0) or 0)
            num_analysts = strong_buy + buy + hold + sell + strong_sell
        except Exception:
            # Fallback to info fields if REST call fails
            rec_key = info.get("recommendationKey", "") or ""
            num_analysts = int(info.get("numberOfAnalystOpinions", 0) or 0)
            rec_map = {
                "strong_buy":  {"strongBuy": 1, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0},
                "buy":         {"strongBuy": 0, "buy": 1, "hold": 0, "sell": 0, "strongSell": 0},
                "hold":       {"strongBuy": 0, "buy": 0, "hold": 1, "sell": 0, "strongSell": 0},
                "sell":       {"strongBuy": 0, "buy": 0, "hold": 0, "sell": 1, "strongSell": 0},
                "strong_sell":{"strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 1},
                "underweight": {"strongBuy": 0, "buy": 0, "hold": 0, "sell": 1, "strongSell": 0},
                "overweight":  {"strongBuy": 0, "buy": 1, "hold": 0, "sell": 0, "strongSell": 0},
                "equal_weight":{"strongBuy": 0, "buy": 0, "hold": 1, "sell": 0, "strongSell": 0},
            }
            dist = rec_map.get(rec_key.lower(), {"strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0})
            strong_buy = dist["strongBuy"]
            buy = dist["buy"]
            hold = dist["hold"]
            sell = dist["sell"]
            strong_sell = dist["strongSell"]

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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Correlation Graph ─────────────────────────────────────────────────────────

@router.get("/cache/stats")
def get_cache_stats():
    """Return cache size + per-endpoint counts. Best-effort."""
    return cache.stats()


@router.post("/cache/purge")
def post_cache_purge(max_age_seconds: int = 24 * 3600):
    """Delete cache entries older than max_age_seconds. Returns row count."""
    deleted = cache.purge_stale(max_age_seconds)
    return {"deleted": deleted}


@router.get("/correlation-graph")
def get_correlation_graph(sector: str = "tech"):
    sector_tickers = {
        "tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "NFLX", "AMD", "INTC", "ORCL", "CRM", "ADBE", "CSCO", "ACN", "QCOM", "AVGO", "TXN", "MU", "PANW", "NOW", "INTU", "SNOW", "UBER", "SQ"],
        "finance": ["JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "AXP", "COF", "USB"],
        "healthcare": ["UNH", "JNJ", "PFE", "ABBV", "MRK", "LLY", "TMO", "ABT", "DHR", "AMGN"],
        "energy": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "VLO", "PSX", "OXY", "HAL"],
        "broad": ["SPY", "QQQ", "IWM", "DIA", "VTI", "VEA", "VWO", "BND", "GLD", "TLT"],
        "dividends": ["JEPI", "JEPQ", "SCHD", "VYM", "HDV", "DGRO", "DVY", "VIG", "SPHD", "HYLG"],
        "semiconductors": ["NVDA", "AMD", "INTC", "QCOM", "AVGO", "TXN", "MU", "AMAT", "LRCX", "ASML", "KLAC", "AMKR"],
    }

    tickers = sector_tickers.get(sector, sector_tickers["tech"])

    try:
        cached = _cached("correlation_graph", {"sector": sector})
        if cached is not None:
            return cached

        price_data: dict[str, np.ndarray] = {}
        for t in tickers:
            try:
                closes = _get_closes_yahoo(t, range_="60d")
                if closes is not None and len(closes) >= 20:
                    price_data[t] = closes
            except Exception:
                pass

        if len(price_data) < 3:
            raise HTTPException(status_code=503, detail="Not enough tickers loaded. Try again shortly.")

        min_len = min(len(v) for v in price_data.values())
        aligned = {t: v[:min_len] for t, v in price_data.items()}
        tickers_list = list(aligned.keys())
        arr = np.column_stack([aligned[t] for t in tickers_list])
        corr_matrix = np.corrcoef(arr, rowvar=False)

        G = nx.Graph()
        for t in tickers_list:
            G.add_node(t, name=t)

        for i, t1 in enumerate(tickers_list):
            for j, t2 in enumerate(tickers_list):
                if i < j:
                    w = corr_matrix[i, j]
                    if abs(w) > 0.5:
                        G.add_edge(t1, t2, weight=abs(w))

        mst = nx.minimum_spanning_tree(G)

        nodes = [{"id": n, "name": G.nodes[n].get("name", n)} for n in G.nodes()]
        edges = [{"source": u, "target": v, "weight": round(d["weight"], 3)} for u, v, d in mst.edges(data=True)]

        result = {"nodes": nodes, "edges": edges}
        _store("correlation_graph", {"sector": sector}, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))