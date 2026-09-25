"""
Unit and integration tests for GeoSentinel ML Training and Inference Pipelines (M1, M2, M3).
"""
import os
import shutil
import tempfile

import numpy as np
import pytest

from ml.features.m1_spatial_features import (
    compute_stream_power_index,
    compute_topographic_wetness_index,
    extract_spatial_features,
)
from ml.features.m2_temporal_features import (
    compute_antecedent_precipitation_index,
    compute_dynamic_features,
)
from ml.features.m3_image_features import ImageTransformPipeline
from ml.pipeline import run_training_pipeline
from ml.registry.model_loader import ModelRegistryLoader
from ml.synthetic_data import generate_m1_dataset, generate_m2_dataset, generate_m3_dataset
from ml.training.m1_susceptibility import (
    M1SusceptibilityTrainer,
    evaluate_m1_model,
    train_m1_susceptibility_model,
)
from ml.training.m2_dynamic_risk import (
    M2DynamicRiskTrainer,
    evaluate_m2_model,
    train_m2_dynamic_risk_model,
)
from ml.training.m3_cv_triage import (
    M3CVTriageTrainer,
    evaluate_m3_model,
    train_m3_cv_triage_model,
)


class TestSyntheticDataGenerators:
    def test_m1_dataset_shape(self):
        X, y, feats = generate_m1_dataset(n_samples=100)
        assert X.shape == (100, 11)
        assert y.shape == (100,)
        assert len(feats) == 11
        assert set(np.unique(y)).issubset({0, 1})

    def test_m2_dataset_shape(self):
        X, y, feats = generate_m2_dataset(n_samples=150)
        assert X.shape == (150, 10)
        assert y.shape == (150,)
        assert len(feats) == 10

    def test_m3_dataset_shape(self):
        X, y, classes = generate_m3_dataset(n_samples=80)
        assert X.shape == (80, 64)
        assert y.shape == (80,)
        assert len(classes) == 6


class TestFeatureEngineering:
    def test_topographic_wetness_index(self):
        area = np.array([100.0, 500.0, 1000.0])
        slope = np.array([15.0, 30.0, 45.0])
        twi = compute_topographic_wetness_index(area, slope)
        assert len(twi) == 3
        assert np.all(np.isfinite(twi))

    def test_stream_power_index(self):
        area = np.array([100.0, 500.0])
        slope = np.array([20.0, 35.0])
        spi = compute_stream_power_index(area, slope)
        assert len(spi) == 2
        assert spi[1] > spi[0]

    def test_extract_spatial_features(self):
        raw_zones = [
            {"slope_deg": 32.5, "elevation_m": 1200.0, "distance_to_road_m": 150.0},
            {"slope_deg": 18.0, "elevation_m": 450.0, "distance_to_road_m": 900.0},
        ]
        feats = extract_spatial_features(raw_zones)
        assert feats.shape == (2, 11)

    def test_antecedent_precipitation_index(self):
        rainfall_14d = [5.0, 10.0, 0.0, 12.0, 25.0, 30.0, 45.0, 10.0, 5.0, 0.0, 8.0, 20.0, 15.0, 40.0]
        api = compute_antecedent_precipitation_index(rainfall_14d, decay_factor=0.85, days=14)
        assert api > 0
        assert isinstance(api, float)

    def test_compute_dynamic_features(self):
        raw_items = [
            {"m1_susceptibility_score": 0.72, "forecast_rainfall_24h_mm": 85.0},
        ]
        feats = compute_dynamic_features(raw_items)
        assert feats.shape == (1, 10)
        assert feats[0, 0] == pytest.approx(0.72)

    def test_image_transform_pipeline(self):
        pipeline = ImageTransformPipeline()
        dummy_img = np.random.randint(0, 256, size=(224, 224, 3), dtype=np.uint8)
        chw = pipeline.preprocess(dummy_img)
        assert chw.shape == (3, 224, 224)
        assert np.all(np.isfinite(chw))


class TestM1SusceptibilityTraining:
    def test_m1_training_and_evaluation(self):
        X, y, feats = generate_m1_dataset(n_samples=200, random_state=42)
        trainer = train_m1_susceptibility_model(X[:150], y[:150], feature_names=feats)
        assert trainer.model is not None

        metrics = evaluate_m1_model(trainer, X[150:], y[150:])
        assert "accuracy" in metrics
        assert "roc_auc" in metrics
        assert metrics["accuracy"] >= 0.50

        probs, classes = trainer.predict_susceptibility(X[150:])
        assert len(probs) == 50
        assert len(classes) == 50
        assert all(c in ["Very High", "High", "Moderate", "Low", "Very Low"] for c in classes)

        shap_vals = trainer.explain_sample_shap(X[0])
        assert len(shap_vals) == 11
        assert "slope_deg" in shap_vals

    def test_m1_save_and_load(self):
        tmpdir = tempfile.mkdtemp()
        try:
            X, y, feats = generate_m1_dataset(n_samples=100, random_state=42)
            model_path = os.path.join(tmpdir, "m1_test.pkl")
            train_m1_susceptibility_model(X, y, feature_names=feats, output_path=model_path)
            assert os.path.exists(model_path)

            loaded = M1SusceptibilityTrainer.load(model_path)
            probs, classes = loaded.predict_susceptibility(X[:5])
            assert len(probs) == 5
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestM2DynamicRiskTraining:
    def test_m2_training_and_evaluation(self):
        X, y, feats = generate_m2_dataset(n_samples=250, random_state=42)
        trainer = train_m2_dynamic_risk_model(X[:200], y[:200], feature_names=feats)
        metrics = evaluate_m2_model(trainer, X[200:], y[200:])
        assert "accuracy" in metrics
        assert "brier_score" in metrics

        scores = trainer.predict_risk_score(X[200:])
        tiers = trainer.classify_risk_tiers(scores)
        assert len(tiers) == 50
        assert all(t in ["Advisory", "Watch", "Warning", "Evacuation"] for t in tiers)

        trigger = trainer.determine_triggering_factor(X[0])
        assert trigger is None or isinstance(trigger, str)

    def test_m2_save_and_load(self):
        tmpdir = tempfile.mkdtemp()
        try:
            X, y, feats = generate_m2_dataset(n_samples=100, random_state=42)
            model_path = os.path.join(tmpdir, "m2_test.pkl")
            train_m2_dynamic_risk_model(X, y, feature_names=feats, output_path=model_path)
            assert os.path.exists(model_path)

            loaded = M2DynamicRiskTrainer.load(model_path)
            scores = loaded.predict_risk_score(X[:5])
            assert len(scores) == 5
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestM3CVTriageTraining:
    def test_m3_training_and_evaluation(self):
        X, y, classes = generate_m3_dataset(n_samples=120, random_state=42)
        trainer = train_m3_cv_triage_model(X[:90], y[:90])
        metrics = evaluate_m3_model(trainer, X[90:], y[90:])
        assert "accuracy" in metrics
        assert "macro_f1" in metrics

        preds = trainer.predict_classification(X[90:])
        assert len(preds) == 30
        assert preds[0]["classification"] in classes
        assert "confidence" in preds[0]
        assert len(preds[0]["class_probabilities"]) == 6

    def test_m3_save_and_load(self):
        tmpdir = tempfile.mkdtemp()
        try:
            X, y, _ = generate_m3_dataset(n_samples=80, random_state=42)
            model_path = os.path.join(tmpdir, "m3_test.pkl")
            train_m3_cv_triage_model(X, y, output_path=model_path)
            assert os.path.exists(model_path)

            loaded = M3CVTriageTrainer.load(model_path)
            preds = loaded.predict_classification(X[:3])
            assert len(preds) == 3
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestModelRegistryLoader:
    def test_loader_inference_fallbacks(self):
        loader = ModelRegistryLoader(models_dir="/tmp/nonexistent_dir_for_test")

        # M1 fallback
        X1 = np.array([[35.0, 180.0, 800.0, 0.0, 0.0, 8.0, 1500.0, 400.0, 250.0, 1.0, 2.0]], dtype=np.float32)
        scores1, classes1 = loader.predict_m1(X1)
        assert len(scores1) == 1
        assert classes1[0] in ["High", "Moderate", "Low"]

        # M2 fallback
        X2 = np.array([[0.6, 50.0, 80.0, 100.0, 10.0, 30.0, 50.0, 80.0, 45.0, 5.0]], dtype=np.float32)
        scores2, tiers2, triggers2 = loader.predict_m2(X2)
        assert len(scores2) == 1
        assert tiers2[0] in ["Advisory", "Watch", "Warning", "Evacuation"]

        # M3 fallback
        X3 = np.random.normal(0, 1, size=(2, 64)).astype(np.float32)
        preds3 = loader.predict_m3(X3)
        assert len(preds3) == 2
        assert preds3[0]["classification"] == "crack"


class TestFullPipelineOrchestrator:
    def test_run_training_pipeline_end_to_end(self):
        tmpdir = tempfile.mkdtemp()
        try:
            summary = run_training_pipeline(output_dir=tmpdir, n_samples=120)
            assert summary["pipeline_status"] == "completed"
            assert "m1_susceptibility" in summary["models"]
            assert "m2_dynamic_risk" in summary["models"]
            assert "m3_cv_triage" in summary["models"]

            assert os.path.exists(os.path.join(tmpdir, "m1_susceptibility.pkl"))
            assert os.path.exists(os.path.join(tmpdir, "m2_dynamic_risk.pkl"))
            assert os.path.exists(os.path.join(tmpdir, "m3_cv_triage.pkl"))
            assert os.path.exists(os.path.join(tmpdir, "pipeline_summary.json"))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
