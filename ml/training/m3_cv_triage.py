"""
M3 Citizen Report Computer Vision Triage Training Pipeline.
Multi-class classifier for landslide field damage photos.
Classes: crack, bulge, debris, rockfall, road_block, normal.
"""
import os
import pickle
from typing import Any, Dict, List, Optional

import numpy as np


class M3CVTriageTrainer:
    CLASSES = ["crack", "bulge", "debris", "rockfall", "road_block", "normal"]

    def __init__(self, random_state: int = 42):
        self.random_state = random_state
        self.model = None
        self.classes = self.CLASSES
        self.metrics: Dict[str, float] = {}

    def fit(self, X: np.ndarray, y: np.ndarray):
        """Train multi-class CV classifier."""
        try:
            from sklearn.neural_network import MLPClassifier
            self.model = MLPClassifier(
                hidden_layer_sizes=(64, 32),
                max_iter=200,
                random_state=self.random_state,
            )
            self.model.fit(X, y)
        except ImportError:
            self.model = _FallbackMultiClassModel(n_classes=len(self.classes))
            self.model.fit(X, y)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict_proba(X)

    def predict_classification(self, X: np.ndarray) -> List[Dict[str, Any]]:
        """Predict class name, confidence, and class probabilities."""
        probs = self.predict_proba(X)
        results = []
        for p in probs:
            top_idx = int(np.argmax(p))
            confidence = float(p[top_idx])
            class_name = self.classes[top_idx]
            class_probs = {cls_name: float(p[i]) for i, cls_name in enumerate(self.classes)}
            results.append({
                "classification": class_name,
                "confidence": round(confidence, 4),
                "class_probabilities": {k: round(v, 4) for k, v in class_probs.items()},
            })
        return results

    def save(self, filepath: str):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "wb") as f:
            pickle.dump({
                "model": self.model,
                "classes": self.classes,
                "metrics": self.metrics,
                "version": "1.0.0",
            }, f)

    @classmethod
    def load(cls, filepath: str) -> "M3CVTriageTrainer":
        with open(filepath, "rb") as f:
            data = pickle.load(f)
        trainer = cls()
        trainer.model = data["model"]
        trainer.classes = data.get("classes", cls.CLASSES)
        trainer.metrics = data.get("metrics", {})
        return trainer


class _FallbackMultiClassModel:
    def __init__(self, n_classes: int = 6):
        self.n_classes = n_classes
        self.weights = None

    def fit(self, X: np.ndarray, y: np.ndarray):
        n_features = X.shape[1]
        self.weights = np.zeros((n_features, self.n_classes))
        # Simple centroid-based projection
        for c in range(self.n_classes):
            mask = (y == c)
            if np.any(mask):
                self.weights[:, c] = np.mean(X[mask], axis=0)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        # Distance-based softmax probabilities
        scores = np.dot(X, self.weights)
        exp_scores = np.exp(scores - np.max(scores, axis=1, keepdims=True))
        return exp_scores / np.sum(exp_scores, axis=1, keepdims=True)


def train_m3_cv_triage_model(
    X_train: np.ndarray,
    y_train: np.ndarray,
    output_path: Optional[str] = None,
) -> M3CVTriageTrainer:
    trainer = M3CVTriageTrainer()
    trainer.fit(X_train, y_train)
    if output_path:
        trainer.save(output_path)
    return trainer


def evaluate_m3_model(trainer: M3CVTriageTrainer, X_test: np.ndarray, y_test: np.ndarray) -> Dict[str, float]:
    probs = trainer.predict_proba(X_test)
    preds = np.argmax(probs, axis=1)

    accuracy = float(np.mean(preds == y_test))

    # Macro-F1 across classes
    f1_scores = []
    for c in range(len(trainer.classes)):
        tp = np.sum((preds == c) & (y_test == c))
        fp = np.sum((preds == c) & (y_test != c))
        fn = np.sum((preds != c) & (y_test == c))
        prec = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
        rec = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
        f1_c = float(2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
        f1_scores.append(f1_c)

    macro_f1 = float(np.mean(f1_scores))

    metrics = {
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
    }
    trainer.metrics = metrics
    return metrics
