"""
Model Registry Loader for GeoSentinel ML Engine.
Loads serialised model weights (joblib/pickle/onnx) from disk/MinIO or provides fallback heuristics.
"""
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ml.training.m1_susceptibility import M1SusceptibilityTrainer
from ml.training.m2_dynamic_risk import M2DynamicRiskTrainer
from ml.training.m3_cv_triage import M3CVTriageTrainer


class ModelRegistryLoader:
    def __init__(self, models_dir: str = "data/models"):
        self.models_dir = models_dir
        self._m1_model: Optional[M1SusceptibilityTrainer] = None
        self._m2_model: Optional[M2DynamicRiskTrainer] = None
        self._m3_model: Optional[M3CVTriageTrainer] = None

    def get_m1_model(self) -> M1SusceptibilityTrainer:
        if self._m1_model is None:
            m1_path = os.path.join(self.models_dir, "m1_susceptibility.pkl")
            if os.path.exists(m1_path):
                self._m1_model = M1SusceptibilityTrainer.load(m1_path)
            else:
                # Initialize untrained fallback with sensible defaults
                self._m1_model = M1SusceptibilityTrainer()
        return self._m1_model

    def get_m2_model(self) -> M2DynamicRiskTrainer:
        if self._m2_model is None:
            m2_path = os.path.join(self.models_dir, "m2_dynamic_risk.pkl")
            if os.path.exists(m2_path):
                self._m2_model = M2DynamicRiskTrainer.load(m2_path)
            else:
                self._m2_model = M2DynamicRiskTrainer()
        return self._m2_model

    def get_m3_model(self) -> M3CVTriageTrainer:
        if self._m3_model is None:
            m3_path = os.path.join(self.models_dir, "m3_cv_triage.pkl")
            if os.path.exists(m3_path):
                self._m3_model = M3CVTriageTrainer.load(m3_path)
            else:
                self._m3_model = M3CVTriageTrainer()
        return self._m3_model

    def predict_m1(self, X: np.ndarray) -> Tuple[np.ndarray, List[str]]:
        model = self.get_m1_model()
        if model.model is not None:
            return model.predict_susceptibility(X)
        # Fallback heuristic
        scores = np.clip(0.02 * X[:, 0] + 0.05 * X[:, 5] - 0.0001 * X[:, 8], 0.05, 0.95)
        classes = ["High" if s >= 0.6 else "Moderate" if s >= 0.3 else "Low" for s in scores]
        return scores, classes

    def predict_m2(self, X: np.ndarray) -> Tuple[np.ndarray, List[str], List[Optional[str]]]:
        model = self.get_m2_model()
        if model.model is not None:
            scores = model.predict_risk_score(X)
            tiers = model.classify_risk_tiers(scores)
            triggers = [model.determine_triggering_factor(x) for x in X]
            return scores, tiers, triggers
        # Fallback heuristic
        scores = np.clip(0.4 * X[:, 0] + 0.008 * X[:, 1] + 0.005 * X[:, 5], 0.02, 0.98)
        tiers = [
            "Evacuation" if s >= 0.8 else "Warning" if s >= 0.55 else "Watch" if s >= 0.3 else "Advisory"
            for s in scores
        ]
        triggers = ["rainfall" if x[1] >= 20 else None for x in X]
        return scores, tiers, triggers

    def predict_m3(self, X: np.ndarray) -> List[Dict[str, Any]]:
        model = self.get_m3_model()
        if model.model is not None:
            return model.predict_classification(X)
        # Fallback mock triage
        fallback_probs = {
            "crack": 0.88,
            "bulge": 0.06,
            "debris": 0.04,
            "rockfall": 0.01,
            "road_block": 0.01,
            "normal": 0.0,
        }
        return [
            {
                "classification": "crack",
                "confidence": 0.88,
                "class_probabilities": fallback_probs,
            }
            for _ in range(len(X))
        ]


_default_loader: Optional[ModelRegistryLoader] = None


def get_model_loader(models_dir: str = "data/models") -> ModelRegistryLoader:
    global _default_loader
    if _default_loader is None:
        _default_loader = ModelRegistryLoader(models_dir=models_dir)
    return _default_loader
