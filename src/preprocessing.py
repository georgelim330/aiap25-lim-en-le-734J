"""Train-fitted preprocessing for linear and histogram-boosted models."""

from __future__ import annotations

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, RobustScaler

from src.features import CATEGORICAL_FEATURES, NUMERIC_FEATURES


def build_preprocessor(model_family: str, *, one_hot_min_frequency: int) -> ColumnTransformer:
    """Create a transformer whose learned state is fitted only by sklearn Pipeline.fit."""
    numeric_steps = [("impute", SimpleImputer(strategy="median"))]
    if model_family == "logistic":
        numeric_steps.append(("scale", RobustScaler()))
        categorical = Pipeline(
            [
                (
                    "encode",
                    OneHotEncoder(
                        handle_unknown="infrequent_if_exist",
                        min_frequency=one_hot_min_frequency,
                        sparse_output=True,
                    ),
                )
            ]
        )
        sparse_threshold = 0.3
    elif model_family == "hist_gradient_boosting":
        categorical = Pipeline(
            [
                (
                    "encode",
                    OrdinalEncoder(
                        handle_unknown="use_encoded_value",
                        unknown_value=np.nan,
                        encoded_missing_value=np.nan,
                    ),
                )
            ]
        )
        sparse_threshold = 0.0
    else:
        raise ValueError(f"Unsupported preprocessor family: {model_family}")

    return ColumnTransformer(
        [
            ("numeric", Pipeline(numeric_steps), NUMERIC_FEATURES),
            ("categorical", categorical, CATEGORICAL_FEATURES),
        ],
        remainder="drop",
        sparse_threshold=sparse_threshold,
        verbose_feature_names_out=True,
    )
