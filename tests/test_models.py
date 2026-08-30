from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import SearchConfig
from src.features import CATEGORICAL_FEATURES, NUMERIC_FEATURES
from src.models import build_pipeline, candidate_specs


def _feature_frame(rows: int = 30) -> pd.DataFrame:
    frame = pd.DataFrame(index=range(rows))
    for index, column in enumerate(NUMERIC_FEATURES):
        frame[column] = np.arange(rows, dtype=float) % (index + 3)
    frame.loc[0, "lead_time"] = np.nan
    for index, column in enumerate(CATEGORICAL_FEATURES):
        frame[column] = np.where(np.arange(rows) % 2 == 0, f"A-{index}", f"B-{index}")
    return frame


def test_candidate_specs_are_modest_and_deterministic() -> None:
    """Break caught: model search silently expands into a large or unstable grid."""
    config = SearchConfig()

    specs = candidate_specs(config)

    assert [spec.candidate_id for spec in specs] == [
        "dummy_most_frequent",
        "logistic_c_0.2",
        "logistic_c_1",
        "hgb_lr_0.05_leaves_15",
        "hgb_lr_0.05_leaves_31",
        "hgb_lr_0.1_leaves_15",
        "hgb_lr_0.1_leaves_31",
    ]


def test_model_pipelines_handle_missing_numeric_and_unseen_categories() -> None:
    """Break caught: train-fitted preprocessing crashes on realistic validation drift."""
    config = SearchConfig(hgb_max_iter=10)
    train = _feature_frame()
    target = np.array([0, 1] * 15)
    validation = train.iloc[:2].copy()
    validation.loc[:, CATEGORICAL_FEATURES[0]] = "UNSEEN-HOTEL"

    for spec in [candidate_specs(config)[1], candidate_specs(config)[3]]:
        pipeline = build_pipeline(spec, config)
        pipeline.fit(train, target)
        probabilities = pipeline.predict_proba(validation)[:, 1]

        assert probabilities.shape == (2,)
        assert np.isfinite(probabilities).all()
        assert ((probabilities >= 0) & (probabilities <= 1)).all()
