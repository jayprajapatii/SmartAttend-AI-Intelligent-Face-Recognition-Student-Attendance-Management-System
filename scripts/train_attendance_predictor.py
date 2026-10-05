"""
scripts/train_attendance_predictor.py

Trains the low-attendance risk model used by
core/analytics/prediction_model.py, and saves it to
ml_models/attendance_predictor.pkl. Until this script has been run,
AttendanceRiskPredictor uses its built-in transparent rule-based
scorer - this script upgrades it to a real trained classifier, IF you
have actual labeled outcomes to train on.

Requires labeled outcome data: for each (student_id, date_range) you
want to include, whether that student actually turned out to be "at
risk" by some real institutional definition (put on academic
probation, dropped a course, flagged by an advisor, etc.). This
script does not fabricate labels - garbage in, garbage out applies
especially hard here, since a model trained on made-up labels would
be actively misleading, arguably worse than the honest rule-based
fallback it would replace.

Expected input: a CSV with columns `student_id,start_date,end_date,was_at_risk`
    student_id,start_date,end_date,was_at_risk
    101,2026-01-01,2026-01-31,1
    102,2026-01-01,2026-01-31,0
    ...

Usage:
    python scripts/train_attendance_predictor.py --labels-csv labels.csv
"""

import argparse
import csv
import logging
import pickle
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train_attendance_predictor")


def load_labels(csv_path: Path) -> dict:
    """
    Returns {(start_date, end_date): [(student_id, was_at_risk), ...]},
    since AttendanceRiskPredictor.train() needs one consistent date
    range per call (features are computed per range) - this groups
    labeled examples by their range so each group can be trained
    together, or you can just use a single range for all your data.
    """
    grouped = defaultdict(list)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required_columns = {"student_id", "start_date", "end_date", "was_at_risk"}
        if not required_columns.issubset(reader.fieldnames or []):
            raise ValueError(f"CSV must have columns: {required_columns}. Found: {reader.fieldnames}")

        for row in reader:
            key = (row["start_date"], row["end_date"])
            grouped[key].append((
                int(row["student_id"]),
                bool(int(row["was_at_risk"])),
            ))

    total = sum(len(examples) for examples in grouped.values())
    logger.info("Loaded %d labeled examples across %d distinct date range(s).", total, len(grouped))
    return grouped


def main():
    parser = argparse.ArgumentParser(description="Train the attendance risk prediction model.")
    parser.add_argument("--labels-csv", required=True, help="CSV of student_id,start_date,end_date,was_at_risk")
    parser.add_argument("--output", default="ml_models/attendance_predictor.pkl")
    args = parser.parse_args()

    # Imported here (not top-level) so this script's --help works even
    # without the full app's DB connection configured.
    from core.analytics.prediction_model import risk_predictor, SKLEARN_AVAILABLE

    if not SKLEARN_AVAILABLE:
        raise RuntimeError("scikit-learn is not installed. Run: pip install scikit-learn")

    grouped_labels = load_labels(Path(args.labels_csv))

    if len(grouped_labels) > 1:
        logger.warning(
            "Labels span %d different date ranges. AttendanceRiskPredictor.train() fits "
            "one model per call using one date range for feature computation - training "
            "on the largest group only. Consider re-running with a single consistent range "
            "for cleaner results.",
            len(grouped_labels),
        )

    (start_date, end_date), examples = max(grouped_labels.items(), key=lambda kv: len(kv[1]))
    logger.info("Training on %d examples from range %s to %s.", len(examples), start_date, end_date)

    risk_predictor.train(examples, start_date, end_date)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as f:
        pickle.dump({
            "model": risk_predictor._model,
            "feature_means": risk_predictor._feature_means,
            "feature_stds": risk_predictor._feature_stds,
        }, f)

    logger.info("Trained model saved to %s", output_path)
    logger.info(
        "To use this trained model, call risk_predictor.load_from_pickle('%s') once at app "
        "startup (e.g. from main.py) - predictions will then use the trained model instead "
        "of the rule-based fallback.",
        output_path,
    )


if __name__ == "__main__":
    main()