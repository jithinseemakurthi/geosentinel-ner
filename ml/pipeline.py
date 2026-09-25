"""
Unified ML Training Pipeline Orchestrator.
Trains and evaluates M1 (Susceptibility), M2 (Dynamic Risk), and M3 (CV Triage).
Exports model artifacts to data/models/ with detailed metric logs.
"""
import argparse
import json
import os
from typing import Any, Dict

from ml.synthetic_data import generate_m1_dataset, generate_m2_dataset, generate_m3_dataset
from ml.training.m1_susceptibility import evaluate_m1_model, train_m1_susceptibility_model
from ml.training.m2_dynamic_risk import evaluate_m2_model, train_m2_dynamic_risk_model
from ml.training.m3_cv_triage import evaluate_m3_model, train_m3_cv_triage_model


def run_training_pipeline(output_dir: str = "data/models", n_samples: int = 1000) -> Dict[str, Any]:
    """Execute complete end-to-end training for M1, M2, and M3."""
    os.makedirs(output_dir, exist_ok=True)
    summary: Dict[str, Any] = {"pipeline_status": "completed", "models": {}}

    print("--- [1/3] Training M1 Landslide Susceptibility Model ---")
    X1, y1, feat_m1 = generate_m1_dataset(n_samples=n_samples, random_state=42)
    split1 = int(0.8 * len(X1))
    X1_train, X1_test = X1[:split1], X1[split1:]
    y1_train, y1_test = y1[:split1], y1[split1:]

    m1_path = os.path.join(output_dir, "m1_susceptibility.pkl")
    m1_trainer = train_m1_susceptibility_model(X1_train, y1_train, feature_names=feat_m1, output_path=m1_path)
    m1_metrics = evaluate_m1_model(m1_trainer, X1_test, y1_test)
    m1_importances = m1_trainer.compute_feature_importance()
    summary["models"]["m1_susceptibility"] = {
        "metrics": m1_metrics,
        "top_features": sorted(m1_importances.items(), key=lambda x: x[1], reverse=True)[:5],
        "artifact_path": m1_path,
    }
    print(
        f"M1 Accuracy: {m1_metrics['accuracy']:.4f}, "
        f"ROC-AUC: {m1_metrics['roc_auc']:.4f}, F1: {m1_metrics['f1']:.4f}"
    )

    print("--- [2/3] Training M2 Dynamic Landslide Risk Model ---")
    X2, y2, feat_m2 = generate_m2_dataset(n_samples=n_samples, random_state=42)
    split2 = int(0.8 * len(X2))
    X2_train, X2_test = X2[:split2], X2[split2:]
    y2_train, y2_test = y2[:split2], y2[split2:]

    m2_path = os.path.join(output_dir, "m2_dynamic_risk.pkl")
    m2_trainer = train_m2_dynamic_risk_model(X2_train, y2_train, feature_names=feat_m2, output_path=m2_path)
    m2_metrics = evaluate_m2_model(m2_trainer, X2_test, y2_test)
    summary["models"]["m2_dynamic_risk"] = {
        "metrics": m2_metrics,
        "artifact_path": m2_path,
    }
    print(
        f"M2 Accuracy: {m2_metrics['accuracy']:.4f}, "
        f"ROC-AUC: {m2_metrics['roc_auc']:.4f}, Brier: {m2_metrics['brier_score']:.4f}"
    )

    print("--- [3/3] Training M3 Citizen Report CV Triage Model ---")
    X3, y3, classes_m3 = generate_m3_dataset(n_samples=min(n_samples, 600), random_state=42)
    split3 = int(0.8 * len(X3))
    X3_train, X3_test = X3[:split3], X3[split3:]
    y3_train, y3_test = y3[:split3], y3[split3:]

    m3_path = os.path.join(output_dir, "m3_cv_triage.pkl")
    m3_trainer = train_m3_cv_triage_model(X3_train, y3_train, output_path=m3_path)
    m3_metrics = evaluate_m3_model(m3_trainer, X3_test, y3_test)
    summary["models"]["m3_cv_triage"] = {
        "metrics": m3_metrics,
        "classes": classes_m3,
        "artifact_path": m3_path,
    }
    print(f"M3 Accuracy: {m3_metrics['accuracy']:.4f}, Macro-F1: {m3_metrics['macro_f1']:.4f}")

    summary_path = os.path.join(output_dir, "pipeline_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Pipeline finished! Summary saved to {summary_path}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GeoSentinel ML Training Pipeline")
    parser.add_argument("--output-dir", default="data/models", help="Directory to save trained models")
    parser.add_argument("--samples", type=int, default=1000, help="Number of synthetic samples")
    args = parser.parse_args()
    run_training_pipeline(output_dir=args.output_dir, n_samples=args.samples)
