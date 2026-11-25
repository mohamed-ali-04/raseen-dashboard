"""Label every row of a run from how the run ended.

A simulated run knows its own future. If it ends in a grounding at time T,
every earlier row can be labelled with the time left until that grounding.
Nobody labels by hand, and the label is exact.
"""
import numpy as np
import pandas as pd


def label_run(table: pd.DataFrame, outcome: str, critical_within_s: float = 60.0,
              caution_within_s: float = 180.0, end_t: float | None = None) -> pd.DataFrame:
    """end_t: time of the grounding, if it is later than the last stored row."""
    out = table.copy()
    if outcome == "grounded":
        ttg = (out["t"].iloc[-1] if end_t is None else end_t) - out["t"]
    else:
        ttg = pd.Series(np.nan, index=out.index)
    out["time_to_grounding"] = ttg
    out["grounds_within_60s"] = (ttg <= 60.0).astype(int)
    out["grounds_within_180s"] = (ttg <= 180.0).astype(int)
    risk = np.full(len(out), "normal", dtype=object)
    risk[(ttg <= caution_within_s).to_numpy()] = "caution"
    risk[(ttg <= critical_within_s).to_numpy()] = "critical"
    out["risk"] = risk
    return out
