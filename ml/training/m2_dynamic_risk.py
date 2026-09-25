"""
M2 Dynamic Landslide Risk & Early Warning Training Pipeline.
Trains an ensemble model on dynamic precipitation forecast, soil moisture, and antecedent indices.
"""
import os
import pickle
from typing import Dict, List, Optional

import numpy as np


class M2DynamicRiskTrainer:
    RISK_TIERS = {
        "Advisory": (0.0, 0.30),
        "Watch": (0.30, 0.55),
        "Warning": (0.55, 0.80),
        "Evacuation": (0.80, 1.00),
    }

    def __init__(
        self,
        n_estimators: int = 120,
        learning_rate: float = 0.08,
        max_depth: int = 5,
        random_state: int = 42,
    ):
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.random_state = random_state
        self.model = None
        self.feature_names: List[str] = []
        self.metrics: Dict[str, float] = {}

    def fit(self, X: np.ndarray, y: np.ndarray, feature_names: Optional[List[str]] = None):
        """Train dynamic risk classifier."""
        self.feature_names = feature_names or [f"dyn_feature_{i}" for i in range(X.shape[1])]

        try:
            from sklearn.ensemble import GradientBoostingClassifier
            self.model = GradientBoostingClassifier(
                n_estimators=self.n_estimators,
                learning_rate=self.learning_rate,
                max_depth=self.max_depth,
                random_state=self.random_state,
            )
            self.model.fit(X, y)
        except ImportError:
            # Fallback simple model
            self.model = _FallbackDynamicRiskModel()
            self.model.fit(X, y)
        return self

    def predict_risk_score(self, X: np.ndarray) -> np.ndarray:
        """Predict continuous probability score (0.0 - 1.0)."""
        if hasattr(self.model, "predict_proba"):
            return self.model.predict_proba(X)[:, 1]
        return self.model.predict(X)

    def classify_risk_tiers(self, scores: np.ndarray) -> List[str]:
        """Classify continuous probability scores into standardized emergency tiers."""
        tiers = []
        for s in scores:
            if s >= 0.80:
                tiers.append("Evacuation")
            elif s >= 0.55:
                tiers.append("Warning")
            elif s >= 0.30:
                tiers.append("Watch")
            else:
                tiers.append("Advisory")
        return tiers

    def determine_triggering_factor(self, sample: np.ndarray) -> Optional[str]:
        """Identify primary meteorological / geotechnical triggering factor."""
        # sample indices: [m1_score, rain_24h, rain_48h, rain_72h, ant_1d, ant_3d, ant_7d, ant_14d, soil_m, rain_int]
        rain_24h = float(sample[1]) if len(sample) > 1 else 0.0
        ant_7d = float(sample[6]) if len(sample) > 6 else 0.0
        soil_m = float(sample[8]) if len(sample) > 8 else 0.0

        if rain_24h >= 60.0:
            return "intense_rainfall_24h"
        if ant_7d >= 120.0:
            return "antecedent_rainfall_saturation"
        if soil_m >= 75.0:
            return "high_soil_moisture"
        if rain_24h >= 25.0:
            return "moderate_rainfall"
        return None

    def save(self, filepath: str):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "wb") as f:
            pickle.dump({
                "model": self.model,
                "feature_names": self.feature_names,
                "metrics": self.metrics,
                "version": "1.0.0",
            }, f)

    @classmethod
    def load(cls, filepath: str) -> "M2DynamicRiskTrainer":
        with open(filepath, "rb") as f:
            data = pickle.load(f)
        trainer = cls()
        trainer.model = data["model"]
        trainer.feature_names = data["feature_names"]
        trainer.metrics = data.get("metrics", {})
        return trainer


class _FallbackDynamicRiskModel:
    def __init__(self):
        self.weights = None
        self.bias = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray):
        n_features = X.shape[1]
        self.weights = np.zeros(n_features)
        lr = 0.01
        for _ in range(250):
            z = np.dot(X, self.weights) + self.bias
            pred = 1.0 / (1.0 + np.exp(-np.clip(z, -25, 25)))
            err = pred - y
            self.weights -= lr * np.dot(X.T, err) / len(y)
            self.bias -= lr * np.mean(err)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        z = np.dot(X, self.weights) + self.bias
        p1 = 1.0 / (1.0 + np.exp(-np.clip(z, -25, 25)))
        p0 = 1.0 - p1
        return np.column_stack([p0, p1])

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.predict_proba(X)[:, 1]


def train_m2_dynamic_risk_model(
    X_train: np.ndarray,
    y_train: np.ndarray,
    feature_names: Optional[List[str]] = None,
    output_path: Optional[str] = None,
) -> M2DynamicRiskTrainer:
    trainer = M2DynamicRiskTrainer()
    trainer.fit(X_train, y_train, feature_names=feature_names)
    if output_path:
        trainer.save(output_path)
    return trainer


def evaluate_m2_model(trainer: M2DynamicRiskTrainer, X_test: np.ndarray, y_test: np.ndarray) -> Dict[str, float]:
    probs = trainer.predict_risk_score(X_test)
    preds = (probs >= 0.5).astype(int)

    tp = np.sum((preds == 1) & (y_test == 1))
    fp = np.sum((preds == 1) & (y_test == 0))
    fn = np.sum((preds == 0) & (y_test == 1))
    tn = np.sum((preds == 0) & (y_test == 0))

    accuracy = float((tp + tn) / len(y_test))
    precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
    f1 = float(2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    pos = probs[y_test == 1]
    neg = probs[y_test == 0]
    if len(pos) > 0 and len(neg) > 0:
        auc = float(np.mean([np.mean(p > neg) for p in pos]))
    else:
        auc = 0.5

    # Brier Score (mean squared error of probability predictions)
    brier_score = float(np.mean((probs - y_test) ** 2))

    metrics = {
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "roc_auc": round(auc, 4),
        "brier_score": round(brier_score, 4),
    }
    trainer.metrics = metrics
    return metrics
