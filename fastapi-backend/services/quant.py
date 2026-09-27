"""
Pure quantitative functions — no network, no I/O, fully unit-testable.

Conventions:
- Regime labels: 0 = bear, 1 = sideways, 2 = bull.
  Threshold classification: daily log-return > +0.5% → bull, < -0.5% → bear.
- Indicator histories are returned full-length; routers slice the tail they
  expose and slice the corresponding dates with the same offset.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np

BULL_THRESHOLD = 0.005   # +0.5% daily log-return
BEAR_THRESHOLD = -0.005  # -0.5% daily log-return
REGIME_NAMES = ("bear", "sideways", "bull")
N_REGIMES = 3

TRADING_DAYS_PER_YEAR = 252  # annualization factor


# ── Regime classification ─────────────────────────────────────────────────────

def threshold_regimes(returns: np.ndarray) -> np.ndarray:
    """Label each daily log-return: 0=bear, 1=sideways, 2=bull."""
    returns = np.asarray(returns, dtype=float)
    return np.where(
        returns > BULL_THRESHOLD,
        2,
        np.where(returns < BEAR_THRESHOLD, 0, 1),
    )


def regime_counts(regimes: np.ndarray) -> dict[str, int]:
    return {name: int(np.sum(regimes == i)) for i, name in enumerate(REGIME_NAMES)}


def current_regime(regimes: np.ndarray) -> str:
    """Regime label of the most recent observation."""
    if len(regimes) == 0:
        raise ValueError("empty regimes array")
    return REGIME_NAMES[int(regimes[-1])]


def regime_adjusted_drift(returns: np.ndarray, regime: str) -> float:
    """
    Drift μ adjusted by the current regime: bull adds +0.5σ, bear subtracts
    0.5σ, sideways leaves the sample mean unchanged.
    """
    sigma = float(np.asarray(returns).std())
    if regime == "bull":
        return float(np.asarray(returns).mean()) + 0.5 * sigma
    if regime == "bear":
        return float(np.asarray(returns).mean()) - 0.5 * sigma
    return float(np.asarray(returns).mean())


# ── RSI (Wilder) ──────────────────────────────────────────────────────────────

def wilder_rsi(closes: np.ndarray, period: int = 14) -> tuple[float, np.ndarray]:
    """
    Wilder-smoothed RSI.

    Returns (current_rsi, history) where history[j] corresponds to
    closes[period + j] (history length = len(closes) - period).

    The seed averages are the mean of the *first* `period` gains/losses, then
    Wilder smoothing runs forward — the conventional definition. (The previous
    implementation seeded from the last `period` values and smoothed forward
    through the whole series, producing a wrong early history.)
    """
    closes = np.asarray(closes, dtype=float)
    if len(closes) < period + 1:
        raise ValueError(f"need at least {period + 1} closes for RSI({period})")
    if period < 1:
        raise ValueError("period must be >= 1")

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    def _rsi(avg_gain: float, avg_loss: float) -> float:
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100.0 - 100.0 / (1.0 + rs)

    avg_gain = float(gains[:period].mean())
    avg_loss = float(losses[:period].mean())
    history = [_rsi(avg_gain, avg_loss)]
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + float(gains[i])) / period
        avg_loss = (avg_loss * (period - 1) + float(losses[i])) / period
        history.append(_rsi(avg_gain, avg_loss))

    return float(history[-1]), np.array(history)


# ── EMA / MACD ────────────────────────────────────────────────────────────────

def ema(values: np.ndarray, span: int) -> np.ndarray:
    """Exponential moving average seeded with the first value."""
    values = np.asarray(values, dtype=float)
    if span < 1:
        raise ValueError("span must be >= 1")
    ema_out = np.zeros(len(values))
    ema_out[0] = values[0]
    alpha = 2.0 / (span + 1)
    for i in range(1, len(values)):
        ema_out[i] = alpha * values[i] + (1 - alpha) * ema_out[i - 1]
    return ema_out


def macd(closes: np.ndarray, fast: int = 12, slow: int = 26, signal_span: int = 9) -> dict:
    """
    MACD(fast, slow, signal). Returns full-length histories:
    {macd, signal, histogram, macdHistory, signalHistory, histogramHistory}.
    """
    closes = np.asarray(closes, dtype=float)
    if not (2 <= fast < slow):
        raise ValueError("fast must be >= 2 and < slow")
    if signal_span < 1:
        raise ValueError("signal_span must be >= 1")
    if len(closes) < slow + signal_span:
        raise ValueError("not enough closes for MACD")

    macd_line = ema(closes, fast) - ema(closes, slow)
    signal_line = ema(macd_line, signal_span)
    histogram = macd_line - signal_line
    return {
        "macd": float(macd_line[-1]),
        "signal": float(signal_line[-1]),
        "histogram": float(histogram[-1]),
        "macdHistory": macd_line,
        "signalHistory": signal_line,
        "histogramHistory": histogram,
    }


# ── Bollinger Bands ───────────────────────────────────────────────────────────

def bollinger(closes: np.ndarray, period: int = 20, num_std: float = 2.0) -> dict:
    """
    Bollinger Bands. Returns the latest snapshot plus a full-length history of
    {sma, upper, lower, bandwidth, percentB} rows; history[j] corresponds to
    closes[period - 1 + j].
    """
    closes = np.asarray(closes, dtype=float)
    if period < 2:
        raise ValueError("period must be >= 2")
    if not math.isfinite(num_std) or num_std <= 0:
        raise ValueError("num_std must be a finite number > 0")
    if len(closes) < period:
        raise ValueError(f"need at least {period} closes")

    history = []
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        sma = window.mean()
        std = window.std()  # population std (ddof=0) — standard Bollinger convention
        upper = sma + num_std * std
        lower = sma - num_std * std
        bandwidth = (upper - lower) / sma if sma != 0 else 0.0
        pct_b = (closes[i] - lower) / (upper - lower) if (upper - lower) != 0 else 0.0
        history.append(
            {
                "sma": float(sma),
                "upper": float(upper),
                "lower": float(lower),
                "bandwidth": float(bandwidth),
                "percentB": float(pct_b),
            }
        )
    latest = history[-1]
    return {
        "sma": latest["sma"],
        "upper": latest["upper"],
        "lower": latest["lower"],
        "bandwidth": latest["bandwidth"],
        "percentB": latest["percentB"],
        "history": history,
    }


# ── ATR ───────────────────────────────────────────────────────────────────────

def true_range(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
    """
    True Range series (length = len(closes) - 1; the first bar has no
    previous close). TR = max(h - l, |h - prev_close|, |l - prev_close|).
    """
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs/lows/closes must have equal length")
    if len(closes) < 2:
        raise ValueError("need at least 2 bars")
    prev_closes = closes[:-1]
    tr = np.maximum(
        np.maximum(highs[1:] - lows[1:], np.abs(highs[1:] - prev_closes)),
        np.abs(lows[1:] - prev_closes),
    )
    return tr


def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    """Simple average of the last `period` True Range values."""
    if period < 1:
        raise ValueError("period must be >= 1")
    tr = true_range(highs, lows, closes)
    if len(tr) < period:
        raise ValueError(f"need at least {period + 1} bars for ATR({period})")
    return float(tr[-period:].mean())


# ── Markov chain ──────────────────────────────────────────────────────────────

def markov_transition_matrix(regimes: np.ndarray, n_states: int = N_REGIMES) -> np.ndarray:
    """
    Row-normalized transition matrix estimated from regime counts.
    Unseen states get a uniform row so matrix powers stay well-defined.
    """
    regimes = np.asarray(regimes, dtype=int)
    counts = np.zeros((n_states, n_states), dtype=float)
    for i in range(len(regimes) - 1):
        counts[int(regimes[i])][int(regimes[i + 1])] += 1
    row_sums = counts.sum(axis=1)
    matrix = np.zeros((n_states, n_states))
    for i in range(n_states):
        if row_sums[i] > 0:
            matrix[i] = counts[i] / row_sums[i]
        else:
            matrix[i] = np.full(n_states, 1.0 / n_states)
    return matrix


def markov_forecast(matrix: np.ndarray, current_idx: int, step: int) -> np.ndarray:
    """n-step regime probability vector from `current_idx`."""
    if step < 1:
        raise ValueError("step must be >= 1")
    return np.linalg.matrix_power(matrix, step)[current_idx]


def markov_stationary(matrix: np.ndarray) -> np.ndarray:
    """Stationary distribution (left eigenvector for eigenvalue 1), uniform fallback."""
    n_states = matrix.shape[0]
    try:
        eigvals, eigvecs = np.linalg.eig(matrix.T)
        idx = np.argmin(np.abs(eigvals - 1.0))
        stationary = np.abs(eigvecs[:, idx])
        total = stationary.sum()
        if total == 0:
            return np.full(n_states, 1.0 / n_states)
        return stationary / total
    except np.linalg.LinAlgError:
        return np.full(n_states, 1.0 / n_states)


# ── Monte Carlo GBM ───────────────────────────────────────────────────────────

def gbm_percentile_fans(
    S0: float,
    mu: float,
    sigma_series: np.ndarray,
    n_sims: int = 1000,
    rng: np.random.Generator | None = None,
    n_sample_paths: int = 10,
) -> dict:
    """
    Simulate GBM paths and return the p5/p25/p50/p75/p95 percentile fans across
    simulated paths, one value per forecast day, plus `samplePaths` (the first
    `n_sample_paths` raw paths, len 0 when `n_sample_paths` <= 0).

    `mu` and each entry of `sigma_series` are **per-day** (one step = one
    trading day): log-return = (mu − σ²/2) + σ·Z each day. Annualized inputs
    must be converted by the caller. Deterministic given `rng`.
    """
    if S0 <= 0:
        raise ValueError("S0 must be positive")
    if n_sims < 1:
        raise ValueError("n_sims must be >= 1")
    sigma_series = np.asarray(sigma_series, dtype=float)
    if np.any(sigma_series < 0):
        raise ValueError("sigma must be non-negative")
    rng = rng if rng is not None else np.random.default_rng()

    days = len(sigma_series)
    Z = rng.standard_normal((n_sims, days))
    sigma_col = sigma_series[np.newaxis, :]
    log_rets = (mu - 0.5 * sigma_col**2) + sigma_col * Z
    all_rets = np.hstack([np.zeros((n_sims, 1)), log_rets])
    paths = S0 * np.exp(np.cumsum(all_rets, axis=1))
    forecast_paths = paths[:, 1:]  # drop the S0 column

    sample = paths[: min(n_sample_paths, n_sims), 1:] if n_sample_paths > 0 else np.zeros((0, days))
    return {
        "p5": np.percentile(forecast_paths, 5, axis=0),
        "p25": np.percentile(forecast_paths, 25, axis=0),
        "p50": np.percentile(forecast_paths, 50, axis=0),
        "p75": np.percentile(forecast_paths, 75, axis=0),
        "p95": np.percentile(forecast_paths, 95, axis=0),
        "samplePaths": sample,
    }


# ── Trading-day dates ─────────────────────────────────────────────────────────

def trading_day_dates(last_dates: list[str], horizon: int) -> list[str]:
    """
    Forecast dates as ISO strings, continuing from the last actual trading
    date and skipping weekends. (Market holidays are not modeled — an
    accepted approximation, documented in LIMITATIONS.md.)
    """
    if horizon < 0:
        raise ValueError("horizon must be >= 0")
    if not last_dates:
        raise ValueError("last_dates must not be empty")
    current = date.fromisoformat(last_dates[-1])
    out: list[str] = []
    for _ in range(horizon):
        current += timedelta(days=1)
        while current.weekday() >= 5:  # 5=Sat, 6=Sun
            current += timedelta(days=1)
        out.append(current.isoformat())
    return out


# ── Screener scoring ──────────────────────────────────────────────────────────

def screener_score(regime: str, momentum_pct: float, volatility_pct: float) -> int:
    """
    Sharpe-inspired 0-100 score: regime (0-40) + momentum (0-40) - volatility
    penalty (0-20). Shared by the screener endpoint and the frontend fallback.
    """
    regime_score = 40 if regime == "bull" else 20 if regime == "sideways" else 0
    momentum_score = max(0.0, min(40.0, momentum_pct * 2))
    vol_penalty = min(20.0, max(0.0, volatility_pct) * 0.4)
    return max(0, round(regime_score + momentum_score - vol_penalty))
