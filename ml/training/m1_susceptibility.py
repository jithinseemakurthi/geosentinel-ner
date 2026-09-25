"""
M1 Landslide Susceptibility Model Training Pipeline.
Trains an ensemble tree-based model (Gradient Boosting / Random Forest / XGBoost)
on terrain, geology, and historical inventory data.
"""
import os
import pickle
from typing import Dict, List, Optional, Tuple

import numpy as np


class M1SusceptibilityTrainer:
    def __init__(
        self,
        n_estimators: int = 100,
        learning_rate: float = 0.1,
        max_depth: int = 4,
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
        """Train the susceptibility classification model."""
        self.feature_names = feature_names or [f"feature_{i}" for i in range(X.shape[1])]

        # Train using sklearn's GradientBoostingClassifier (or HistGradientBoostingClassifier)
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
            # Fallback simple logistic model if sklearn is not present
            self.model = _FallbackLinearClassifier()
            self.model.fit(X, y)

        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("Model must be trained before predicting.")
        return self.model.predict_proba(X)

    def predict_susceptibility(self, X: np.ndarray) -> Tuple[np.ndarray, List[str]]:
        """Predict continuous susceptibility score (0-1) and categorical class."""
        probs = self.predict_proba(X)[:, 1]
        classes = []
        for p in probs:
            if p >= 0.75:
                classes.append("Very High")
            elif p >= 0.55:
                classes.append("High")
            elif p >= 0.35:
                classes.append("Moderate")
            elif p >= 0.15:
                classes.append("Low")
            else:
                classes.append("Very Low")
        return probs, classes

    def compute_feature_importance(self) -> Dict[str, float]:
        """Compute relative importance of each terrain and geological factor."""
        if hasattr(self.model, "feature_importances_"):
            importances = self.model.feature_importances_
        else:
            importances = np.ones(len(self.feature_names)) / len(self.feature_names)

        return {name: float(imp) for name, imp in zip(self.feature_names, importances)}

    def explain_sample_shap(self, sample: np.ndarray) -> Dict[str, float]:
        """Approximate SHAP feature contributions for a specific terrain zone."""
        importances = self.compute_feature_importance()
        # Scale by feature magnitude relative to baseline
        shap_values = {}
        for idx, name in enumerate(self.feature_names):
            val = float(sample[idx])
            weight = importances.get(name, 0.1)
            shap_values[name] = round(weight * (val / (abs(val) + 1.0)), 4)
        return shap_values

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
    def load(cls, filepath: str) -> "M1SusceptibilityTrainer":
        with open(filepath, "rb") as f:
            data = pickle.load(f)
        trainer = cls()
        trainer.model = data["model"]
        trainer.feature_names = data["feature_names"]
        trainer.metrics = data.get("metrics", {})
        return trainer


class _FallbackLinearClassifier:
    """Lightweight fallback classifier when sklearn is not installed."""
    def __init__(self):
        self.weights = None
        self.bias = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray):
        n_features = X.shape[1]
        self.weights = np.zeros(n_features)
        lr = 0.01
        for _ in range(200):
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


def train_m1_susceptibility_model(
    X_train: np.ndarray,
    y_train: np.ndarray,
    feature_names: Optional[List[str]] = None,
    output_path: Optional[str] = None,
) -> M1SusceptibilityTrainer:
    """Train M1 model, evaluate, and optionally save model artifact."""
    trainer = M1SusceptibilityTrainer()
    trainer.fit(X_train, y_train, feature_names=feature_names)
    if output_path:
        trainer.save(output_path)
    return trainer


def evaluate_m1_model(trainer: M1SusceptibilityTrainer, X_test: np.ndarray, y_test: np.ndarray) -> Dict[str, float]:
    """Evaluate susceptibility model accuracy, ROC-AUC, Precision, Recall, and F1."""
    probs = trainer.predict_proba(X_test)[:, 1]
    preds = (probs >= 0.5).astype(int)

    tp = np.sum((preds == 1) & (y_test == 1))
    fp = np.sum((preds == 1) & (y_test == 0))
    fn = np.sum((preds == 0) & (y_test == 1))
    tn = np.sum((preds == 0) & (y_test == 0))

    accuracy = float((tp + tn) / len(y_test))
    precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
    f1 = float(2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    # Fast ROC-AUC approximation
    pos = probs[y_test == 1]
    neg = probs[y_test == 0]
    if len(pos) > 0 and len(neg) > 0:
        auc = float(np.mean([np.mean(p > neg) for p in pos]))
    else:
        auc = 0.5

    metrics = {
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "roc_auc": round(auc, 4),
    }
    trainer.metrics = metrics
    return metrics
