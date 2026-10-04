"""Trading module: MetaTrader 5 analysis, alerts, simulation and guarded execution.

Design rules enforced throughout this package:

  * The public site never touches a trading account. All MT5 access happens on
    the user's PC through the OpenHUD Agent.
  * The default mode is ANALYSIS ONLY. Real trading is disabled until the user
    explicitly enables it.
  * Nothing is invented: if MT5 data is unavailable, every layer reports that
    explicitly instead of fabricating prices, balances or executions.
  * Every action is auditable and order submission is idempotent.
"""
from .core import (
    TRADING_PERMISSION_KEYS,
    DEFAULT_TRADING_PERMISSIONS,
    MODES,
    RiskLimits,
    Strategy,
    parse_strategy,
    evaluate_strategy,
    compute_risk,
    run_backtest,
    PaperAccount,
    utc_now,
)

__all__ = [
    "TRADING_PERMISSION_KEYS",
    "DEFAULT_TRADING_PERMISSIONS",
    "MODES",
    "RiskLimits",
    "Strategy",
    "parse_strategy",
    "evaluate_strategy",
    "compute_risk",
    "run_backtest",
    "PaperAccount",
    "utc_now",
]
