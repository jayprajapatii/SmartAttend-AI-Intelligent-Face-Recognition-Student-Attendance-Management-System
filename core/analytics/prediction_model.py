"""
core/analytics/prediction_model.py

"Attendance Prediction (AI)" feature: scores each student's risk of
falling into chronic low attendance.

Honest scope note: without real historical outcome labels (e.g. actual
academic probation / dropout records tied to past attendance patterns),
there's no ground truth to train a supervised model against yet. So
this ships with:

    1. A transparent rule-based risk scorer (default, always available)
       combining current attendance %, recent trend direction, and
       consecutive-absence streaks into a Low/Medium/High risk label.
       This is deterministic and explainable - useful today.

    2. Optional scikit-learn model scaffolding: if you later obtain
       labeled outcome data (student_id -> was_actually_at_risk),
       call train() to fit a real classifier on the same engineered
       features, and predictions will automatically switch to using
       it. Until trained, predict() transparently uses the rule-based
       scorer - this mirrors the fallback pattern used throughout
       core/ (e.g. mask_classifier.py, emotion_classifier.py).

Usage:
    from core.analytics.prediction_model import risk_predictor

    risk_list = risk_predictor.predict_all(start_date, end_date)
    for r in risk_list:
        print(r.student_id, r.risk_level, r.risk_score, r.reasons)

    # Once you have labeled outcomes:
    # risk_predictor.train(labeled_examples, start_date, end_date)
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from database.models.attendance_model import AttendanceModel
from database.models.student_model import StudentModel

logger = logging.getLogger("SmartAttendAI.core.analytics.prediction_model")

try:
    from sklearn.ensemble import RandomForestClassifier
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.info("scikit-learn not installed - model-based prediction unavailable; using rule-based scorer only.")

# Rule-based thresholds
HIGH_RISK_PERCENTAGE = 60.0
MEDIUM_RISK_PERCENTAGE = 75.0
CONSECUTIVE_ABSENCE_HIGH_RISK = 3

FEATURE_NAMES = ["attendance_percentage", "trend_slope", "consecutive_absences", "total_sessions"]


@dataclass
class StudentRiskResult:
    student_id: int
    student_name: str
    roll_number: str
    attendance_percentage: float
    risk_level: str          # "Low" | "Medium" | "High"
    risk_score: float        # 0-1, higher = more at risk
    reasons: list = field(default_factory=list)
    method: str = "rule_based"  # "rule_based" | "model"


class AttendanceRiskPredictor:
    """
    Scores each student's risk of chronic low attendance. Uses a
    trained scikit-learn model if one has been fit via train(),
    otherwise falls back to a transparent rule-based scorer.
    """

    def __init__(self):
        self._model = None
        self._feature_means = None
        self._feature_stds = None

    @property
    def is_model_trained(self) -> bool:
        return self._model is not None

    # ------------------------------------------------------------
    # Feature engineering (shared by both rule-based and model paths)
    # ------------------------------------------------------------
    def _build_features(self, student_id: int, start_date: str, end_date: str) -> dict:
        try:
            percentage = AttendanceModel.get_student_attendance_percentage(student_id, start_date, end_date)
            records = AttendanceModel.get_by_student(student_id, start_date, end_date)
        except Exception as exc:
            logger.error("Failed to build features for student_id=%s: %s", student_id, exc)
            return {
                "attendance_percentage": 0.0, "trend_slope": 0.0,
                "consecutive_absences": 0, "total_sessions": 0,
            }

        consecutive_absences = self._count_recent_consecutive_absences(records)
        trend_slope = self._simple_trend_slope(records)

        return {
            "attendance_percentage": percentage,
            "trend_slope": trend_slope,
            "consecutive_absences": consecutive_absences,
            "total_sessions": len(records),
        }

    @staticmethod
    def _count_recent_consecutive_absences(records: list) -> int:
        """Records are assumed sorted most-recent-first (matches AttendanceModel.get_by_student ordering)."""
        streak = 0
        for r in records:
            if r["attendance_status"] == "Absent":
                streak += 1
            else:
                break
        return streak

    @staticmethod
    def _simple_trend_slope(records: list) -> float:
        """Positive = improving recently, negative = declining recently. Crude 2-point (recent-half vs older-half) proxy."""
        if len(records) < 4:
            return 0.0

        midpoint = len(records) // 2
        recent_half = records[:midpoint]
        older_half = records[midpoint:]

        def present_rate(chunk):
            if not chunk:
                return 0.0
            present = sum(1 for r in chunk if r["attendance_status"] in ("Present", "Late"))
            return present / len(chunk)

        return round(present_rate(recent_half) - present_rate(older_half), 3)

    # ------------------------------------------------------------
    # Rule-based scoring (always available, fully explainable)
    # ------------------------------------------------------------
    def _rule_based_score(self, features: dict) -> tuple:
        """Returns (risk_level, risk_score, reasons)."""
        reasons = []
        score = 0.0

        pct = features["attendance_percentage"]
        if pct < HIGH_RISK_PERCENTAGE:
            score += 0.5
            reasons.append(f"Attendance at {pct}%, below the {HIGH_RISK_PERCENTAGE:.0f}% high-risk threshold.")
        elif pct < MEDIUM_RISK_PERCENTAGE:
            score += 0.25
            reasons.append(f"Attendance at {pct}%, below the {MEDIUM_RISK_PERCENTAGE:.0f}% target.")

        if features["consecutive_absences"] >= CONSECUTIVE_ABSENCE_HIGH_RISK:
            score += 0.3
            reasons.append(f"{features['consecutive_absences']} consecutive absences.")

        if features["trend_slope"] < -0.15:
            score += 0.2
            reasons.append("Attendance trending downward recently.")
        elif features["trend_slope"] > 0.15:
            score -= 0.1
            reasons.append("Attendance trending upward recently.")

        score = max(0.0, min(1.0, score))

        if score >= 0.6:
            risk_level = "High"
        elif score >= 0.3:
            risk_level = "Medium"
        else:
            risk_level = "Low"

        if not reasons:
            reasons.append("No significant risk factors detected.")

        return risk_level, round(score, 2), reasons

    # ------------------------------------------------------------
    # Model-based scoring (optional, once train() has been called)
    # ------------------------------------------------------------
    def _model_based_score(self, features: dict) -> tuple:
        vector = np.array([[features[name] for name in FEATURE_NAMES]])
        vector = (vector - self._feature_means) / self._feature_stds

        proba = self._model.predict_proba(vector)[0]
        # Assumes binary classifier where class index 1 = "at risk"
        risk_score = float(proba[1]) if len(proba) > 1 else float(proba[0])

        if risk_score >= 0.6:
            risk_level = "High"
        elif risk_score >= 0.3:
            risk_level = "Medium"
        else:
            risk_level = "Low"

        reasons = [f"Model-predicted risk probability: {risk_score:.0%}."]
        return risk_level, round(risk_score, 2), reasons

    # ------------------------------------------------------------
    # Public prediction API
    # ------------------------------------------------------------
    def predict_student(self, student_id: int, start_date: str, end_date: str) -> StudentRiskResult:
        student = StudentModel.get_by_id(student_id) or {}
        features = self._build_features(student_id, start_date, end_date)

        if self.is_model_trained:
            risk_level, risk_score, reasons = self._model_based_score(features)
            method = "model"
        else:
            risk_level, risk_score, reasons = self._rule_based_score(features)
            method = "rule_based"

        return StudentRiskResult(
            student_id=student_id,
            student_name=student.get("full_name", "Unknown"),
            roll_number=student.get("roll_number", "-"),
            attendance_percentage=features["attendance_percentage"],
            risk_level=risk_level,
            risk_score=risk_score,
            reasons=reasons,
            method=method,
        )

    def predict_all(self, start_date: str = None, end_date: str = None, active_only: bool = True) -> list:
        """Scores every active student over the given range (defaults to the last 30 days)."""
        if not end_date:
            end_date = date.today().isoformat()
        if not start_date:
            start_date = (date.today() - timedelta(days=30)).isoformat()

        try:
            students = StudentModel.get_all(active_only=active_only)
        except Exception as exc:
            logger.error("Failed to load students for risk prediction: %s", exc)
            return []

        results = [
            self.predict_student(s["student_id"], start_date, end_date)
            for s in students
        ]
        return sorted(results, key=lambda r: r.risk_score, reverse=True)

    # ------------------------------------------------------------
    # Optional: train a real model once labeled outcome data exists
    # ------------------------------------------------------------
    def train(self, labeled_examples: list, start_date: str, end_date: str):
        """
        labeled_examples: list of (student_id, was_at_risk: bool) pairs,
        e.g. sourced from actual academic-probation or dropout records
        correlated with this same date range.

        Once trained, predict_student()/predict_all() automatically
        switch from the rule-based scorer to this model.
        """
        if not SKLEARN_AVAILABLE:
            raise RuntimeError("scikit-learn is not installed. Run: pip install scikit-learn")

        if len(labeled_examples) < 20:
            logger.warning(
                "Training with only %d labeled examples - model quality will likely be poor "
                "with this little data. Consider sticking with the rule-based scorer until more "
                "labeled outcomes are available.",
                len(labeled_examples),
            )

        X, y = [], []
        for student_id, was_at_risk in labeled_examples:
            features = self._build_features(student_id, start_date, end_date)
            X.append([features[name] for name in FEATURE_NAMES])
            y.append(1 if was_at_risk else 0)

        X = np.array(X)
        y = np.array(y)

        self._feature_means = X.mean(axis=0)
        self._feature_stds = np.where(X.std(axis=0) == 0, 1.0, X.std(axis=0))
        X_normalized = (X - self._feature_means) / self._feature_stds

        model = RandomForestClassifier(n_estimators=100, max_depth=4, random_state=42)
        model.fit(X_normalized, y)
        self._model = model

        logger.info("Risk prediction model trained on %d labeled examples.", len(labeled_examples))

    def reset_model(self):
        """Reverts to the rule-based scorer (e.g. if the trained model needs to be discarded)."""
        self._model = None
        self._feature_means = None
        self._feature_stds = None

    def load_from_pickle(self, filepath: str) -> bool:
        """
        Loads a model previously trained and saved by
        scripts/train_attendance_predictor.py. Call this once at app
        startup (e.g. from main.py) if ml_models/attendance_predictor.pkl
        exists, so predictions use the trained model instead of the
        rule-based fallback. Returns True on success.
        """
        import pickle
        from pathlib import Path

        path = Path(filepath)
        if not path.exists():
            logger.info("No trained risk model found at %s - using rule-based scorer.", path)
            return False

        try:
            with open(path, "rb") as f:
                state = pickle.load(f)
            self._model = state["model"]
            self._feature_means = state["feature_means"]
            self._feature_stds = state["feature_stds"]
            logger.info("Loaded trained attendance risk model from %s.", path)
            return True
        except Exception as exc:
            logger.error("Failed to load trained risk model from %s: %s", path, exc)
            return False


# Singleton instance - import this everywhere instead of instantiating directly
risk_predictor = AttendanceRiskPredictor()