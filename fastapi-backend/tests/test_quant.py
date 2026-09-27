"""Unit tests for services/quant.py — pure math, no network."""

import numpy as np
import pytest

from services import quant


class TestThresholdRegimes:
    def test_classification(self):
        returns = np.array([0.006, -0.006, 0.0, 0.005, -0.005, 0.0051])
        # > +0.5% → bull(2), < -0.5% → bear(0), boundary is sideways(1)
        assert quant.threshold_regimes(returns).tolist() == [2, 0, 1, 1, 1, 2]

    def test_counts_and_current(self):
        regimes = quant.threshold_regimes(np.array([0.01, 0.01, -0.01, 0.0, 0.02]))
        counts = quant.regime_counts(regimes)
        assert counts == {"bear": 1, "sideways": 1, "bull": 3}
        assert quant.current_regime(regimes) == "bull"

    def test_current_regime_empty_raises(self):
        with pytest.raises(ValueError):
            quant.current_regime(np.array([]))


class TestWilderRSI:
    def test_hand_computed_case(self):
        # deltas = [1, -0.5, 1], period=2
        # seed: avg_gain=0.5, avg_loss=0.25 → rs=2 → rsi=66.667
        # next: avg_gain=(0.5+1)/2=0.75, avg_loss=0.125 → rs=6 → rsi=85.714
        closes = np.array([10.0, 11.0, 10.5, 11.5])
        current, history = quant.wilder_rsi(closes, period=2)
        assert history.tolist() == pytest.approx([100 - 100 / 3, 100 - 100 / 7])
        assert current == pytest.approx(100 - 100 / 7)

    def test_monotonic_up_is_100(self):
        closes = np.linspace(100, 200, 50)
        current, _ = quant.wilder_rsi(closes, period=14)
        assert current == pytest.approx(100.0)

    def test_monotonic_down_is_0(self):
        closes = np.linspace(200, 100, 50)
        current, _ = quant.wilder_rsi(closes, period=14)
        assert current == pytest.approx(0.0)

    def test_flat_is_50(self):
        closes = np.full(50, 123.45)
        current, _ = quant.wilder_rsi(closes, period=14)
        assert current == pytest.approx(50.0)

    def test_history_length_and_bounds(self):
        closes = np.cumsum(np.sin(np.arange(200)) * 0.5) + 100
        current, history = quant.wilder_rsi(closes, period=14)
        assert len(history) == len(closes) - 14
        assert ((history >= 0) & (history <= 100)).all()
        assert current == pytest.approx(history[-1])

    def test_insufficient_data_raises(self):
        with pytest.raises(ValueError):
            quant.wilder_rsi(np.array([1.0, 2.0, 3.0]), period=14)


class TestEmaMacd:
    def test_ema_of_constant_is_constant(self):
        values = np.full(30, 5.0)
        assert quant.ema(values, span=12).tolist() == pytest.approx([5.0] * 30)

    def test_macd_zero_for_constant_series(self):
        closes = np.full(100, 50.0)
        result = quant.macd(closes)
        assert result["macd"] == pytest.approx(0.0, abs=1e-12)
        assert result["histogram"] == pytest.approx(0.0, abs=1e-12)

    def test_macd_shape_and_history_lengths(self):
        closes = np.linspace(10, 40, 120)
        result = quant.macd(closes)
        for key in ("macdHistory", "signalHistory", "histogramHistory"):
            assert len(result[key]) == 120
        assert result["histogram"] == pytest.approx(result["macd"] - result["signal"])

    def test_macd_validation(self):
        closes = np.full(100, 1.0)
        with pytest.raises(ValueError):
            quant.macd(closes, fast=26, slow=12)  # fast >= slow
        with pytest.raises(ValueError):
            quant.macd(closes, signal_span=0)
        with pytest.raises(ValueError):
            quant.macd(np.full(10, 1.0))  # too short


class TestBollinger:
    def test_known_small_case(self):
        closes = np.arange(1.0, 21.0)  # 1..20
        result = quant.bollinger(closes, period=5, num_std=2.0)
        # last window [16..20]: sma=18, population std=sqrt(2)
        assert result["sma"] == pytest.approx(18.0)
        assert result["upper"] == pytest.approx(18 + 2 * np.sqrt(2))
        assert result["lower"] == pytest.approx(18 - 2 * np.sqrt(2))
        assert result["percentB"] == pytest.approx(0.5 + 1 / (2 * np.sqrt(2)))

    def test_constant_series_flat_bands(self):
        closes = np.full(30, 7.0)
        result = quant.bollinger(closes)
        assert result["upper"] == pytest.approx(7.0)
        assert result["lower"] == pytest.approx(7.0)
        assert result["percentB"] == 0.0

    def test_history_length(self):
        closes = np.arange(1.0, 61.0)
        result = quant.bollinger(closes, period=20)
        assert len(result["history"]) == len(closes) - 19

    def test_validation(self):
        with pytest.raises(ValueError):
            quant.bollinger(np.arange(1.0, 31.0), period=1)
        with pytest.raises(ValueError):
            quant.bollinger(np.arange(1.0, 31.0), num_std=0)


class TestTrueRangeAtr:
    def test_hand_computed(self):
        highs = np.array([10.0, 11.0])
        lows = np.array([9.0, 10.0])
        closes = np.array([9.5, 10.5])
        tr = quant.true_range(highs, lows, closes)
        assert tr.tolist() == pytest.approx([1.5])  # max(1, 1.5, 0.5)
        assert quant.atr(highs, lows, closes, period=1) == pytest.approx(1.5)

    def test_validation(self):
        with pytest.raises(ValueError):
            quant.true_range(np.array([1.0]), np.array([1.0]), np.array([1.0]))
        with pytest.raises(ValueError):
            quant.true_range(np.array([2.0, 1.0]), np.array([1.0]), np.array([1.5]))


class TestMarkov:
    def test_transition_matrix_rows_sum_to_one(self):
        regimes = np.array([0, 0, 1, 2, 2, 1, 0])
        T = quant.markov_transition_matrix(regimes)
        assert T.shape == (3, 3)
        assert T.sum(axis=1).tolist() == pytest.approx([1.0, 1.0, 1.0])
        # observed transitions from bear(0): →bear, →sideways
        assert T[0].tolist() == pytest.approx([0.5, 0.5, 0.0])

    def test_unseen_state_uniform(self):
        regimes = np.array([0, 1, 0, 1])  # bull never visited
        T = quant.markov_transition_matrix(regimes)
        assert T[2].tolist() == pytest.approx([1 / 3, 1 / 3, 1 / 3])

    def test_forecast_absorbing(self):
        regimes = np.array([0, 0, 1, 2, 2])
        T = quant.markov_transition_matrix(regimes)
        probs = quant.markov_forecast(T, current_idx=2, step=3)
        # bull is absorbing in this matrix → stays bull
        assert probs.tolist() == pytest.approx([0.0, 0.0, 1.0])

    def test_stationary_sums_to_one(self):
        T = quant.markov_transition_matrix(np.array([0, 1, 2, 0, 1, 2, 0, 1]))
        stationary = quant.markov_stationary(T)
        assert stationary.sum() == pytest.approx(1.0)


class TestGbmPercentileFans:
    def test_zero_sigma_degenerates_to_forward_price(self):
        days = 10
        fans = quant.gbm_percentile_fans(
            100.0, 0.0, np.zeros(days), n_sims=500, rng=np.random.default_rng(42)
        )
        for key in ("p5", "p25", "p50", "p75", "p95"):
            assert fans[key].tolist() == pytest.approx([100.0] * days)
        assert fans["samplePaths"].shape == (10, days)

    def test_fans_are_ordered(self):
        days = 30
        fans = quant.gbm_percentile_fans(
            100.0, 0.005, np.full(days, 0.02), n_sims=2000, rng=np.random.default_rng(7)
        )
        assert (fans["p5"] <= fans["p25"]).all()
        assert (fans["p25"] <= fans["p50"]).all()
        assert (fans["p50"] <= fans["p75"]).all()
        assert (fans["p75"] <= fans["p95"]).all()
        # per-day drift 0.5% → median ≈ 100·exp((0.005 − 0.0002)·30) ≈ 115
        assert fans["p50"][-1] > 110.0

    def test_fan_width_scales_with_volatility(self):
        # Pins the daily-units convention: daily sigma=0.01 over 30 steps must
        # give a p5–p95 width of ≈ 2·1.645·0.01·√30 ≈ 18% of spot.
        fans = quant.gbm_percentile_fans(
            100.0, 0.0, np.full(30, 0.01), n_sims=5000, rng=np.random.default_rng(11)
        )
        width_pct = (fans["p95"][-1] - fans["p5"][-1]) / 100.0
        expected = 2 * 1.645 * 0.01 * 30**0.5
        assert abs(width_pct - expected) < 0.02

    def test_deterministic_given_rng(self):
        sigma = np.full(5, 0.01)
        a = quant.gbm_percentile_fans(100.0, 0.0, sigma, n_sims=100, rng=np.random.default_rng(1))
        b = quant.gbm_percentile_fans(100.0, 0.0, sigma, n_sims=100, rng=np.random.default_rng(1))
        assert a["p50"].tolist() == b["p50"].tolist()

    def test_validation(self):
        with pytest.raises(ValueError):
            quant.gbm_percentile_fans(-1.0, 0.0, np.zeros(5))
        with pytest.raises(ValueError):
            quant.gbm_percentile_fans(100.0, 0.0, np.array([0.01, -0.01]))


class TestTradingDayDates:
    def test_skips_weekend(self):
        # 2024-01-05 is a Friday
        dates = quant.trading_day_dates(["2024-01-05"], 1)
        assert dates == ["2024-01-08"]

    def test_span_and_count(self):
        dates = quant.trading_day_dates(["2024-01-05"], 5)
        assert dates == ["2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11", "2024-01-12"]

    def test_horizon_zero(self):
        assert quant.trading_day_dates(["2024-01-05"], 0) == []

    def test_does_not_repeat_anchor(self):
        dates = quant.trading_day_dates(["2024-01-05"], 3)
        assert "2024-01-05" not in dates


class TestScreenerScore:
    def test_bull_low_vol_beats_bear_high_vol(self):
        assert quant.screener_score("bull", 5.0, 10.0) > quant.screener_score("bear", 5.0, 40.0)

    def test_bounds(self):
        assert quant.screener_score("bear", -100.0, 100.0) == 0
        assert quant.screener_score("bull", 100.0, 0.0) == 80  # 40 + 40 - 0
