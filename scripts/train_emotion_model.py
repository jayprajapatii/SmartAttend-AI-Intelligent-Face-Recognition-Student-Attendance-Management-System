"""
scripts/train_emotion_model.py

Trains the emotion classifier consumed by
core/emotion_recognition/emotion_classifier.py, and saves it to
ml_models/emotion_model.h5. Until this script has been run (and
produced a real .h5 file), emotion_classifier.py falls back to its
smile-cascade heuristic (Happy/Neutral only) - this script upgrades
it to full Happy/Neutral/Sad/Angry/Surprised coverage.

Expects data in the classic FER2013 CSV format (48x48 grayscale
pixels as a space-separated string per row, with an integer emotion
label and a Usage column marking Training/PublicTest/PrivateTest):

    emotion,pixels,Usage
    0,"70 80 82 ...",Training
    ...

FER2013's 7 label indices (0-6) are: angry, disgust, fear, happy,
sad, surprise, neutral - matching
core/emotion_recognition/emotion_classifier.py's EMOTION_MODEL_LABELS
mapping exactly, so no relabeling is needed if you're using this
dataset format. If your dataset uses a different label order, update
EMOTION_MODEL_LABELS in emotion_classifier.py to match.

This script does not download or bundle the dataset itself - fer2013.csv
is a well-known public dataset, obtain it separately.

Usage:
    python scripts/train_emotion_model.py --csv-path /path/to/fer2013.csv --epochs 30
"""

import argparse
import logging
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train_emotion_model")

IMAGE_SIZE = (48, 48)   # must match core/emotion_recognition/emotion_classifier.py's MODEL_INPUT_SIZE
NUM_CLASSES = 7          # angry, disgust, fear, happy, sad, surprise, neutral


def load_fer2013(csv_path: Path):
    import pandas as pd

    logger.info("Loading FER2013 CSV from %s", csv_path)
    df = pd.read_csv(csv_path)

    def parse_pixels(pixel_string):
        return np.array(pixel_string.split(), dtype="float32").reshape(*IMAGE_SIZE, 1) / 255.0

    train_df = df[df["Usage"] == "Training"]
    val_df = df[df["Usage"] == "PublicTest"]
    test_df = df[df["Usage"] == "PrivateTest"]

    def to_arrays(subset_df):
        X = np.stack(subset_df["pixels"].apply(parse_pixels).values)
        y = subset_df["emotion"].values
        return X, y

    X_train, y_train = to_arrays(train_df)
    X_val, y_val = to_arrays(val_df)
    X_test, y_test = to_arrays(test_df)

    logger.info(
        "Loaded %d training, %d validation, %d test samples.",
        len(X_train), len(X_val), len(X_test),
    )
    return (X_train, y_train), (X_val, y_val), (X_test, y_test)


def build_model():
    import tensorflow as tf
    models = tf.keras.models
    layers = tf.keras.layers

    model = models.Sequential([
        layers.Input(shape=(*IMAGE_SIZE, 1)),

        layers.Conv2D(32, (3, 3), activation="relu", padding="same"),
        layers.BatchNormalization(),
        layers.Conv2D(32, (3, 3), activation="relu", padding="same"),
        layers.BatchNormalization(),
        layers.MaxPooling2D((2, 2)),
        layers.Dropout(0.25),

        layers.Conv2D(64, (3, 3), activation="relu", padding="same"),
        layers.BatchNormalization(),
        layers.Conv2D(64, (3, 3), activation="relu", padding="same"),
        layers.BatchNormalization(),
        layers.MaxPooling2D((2, 2)),
        layers.Dropout(0.25),

        layers.Conv2D(128, (3, 3), activation="relu", padding="same"),
        layers.BatchNormalization(),
        layers.MaxPooling2D((2, 2)),
        layers.Dropout(0.25),

        layers.Flatten(),
        layers.Dense(256, activation="relu"),
        layers.BatchNormalization(),
        layers.Dropout(0.5),
        layers.Dense(NUM_CLASSES, activation="softmax"),
    ])

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model


def main():
    parser = argparse.ArgumentParser(description="Train the emotion recognition model.")
    parser.add_argument("--csv-path", required=True, help="Path to fer2013.csv")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--output", default="ml_models/emotion_model.h5")
    args = parser.parse_args()

    import tensorflow as tf

    (X_train, y_train), (X_val, y_val), (X_test, y_test) = load_fer2013(Path(args.csv_path))

    model = build_model()

    callbacks = [
        tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=5, restore_best_weights=True),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=3),
    ]

    logger.info("Training for up to %d epochs (early stopping enabled)...", args.epochs)
    model.fit(
        X_train, y_train,
        validation_data=(X_val, y_val),
        epochs=args.epochs,
        batch_size=args.batch_size,
        callbacks=callbacks,
    )

    test_loss, test_accuracy = model.evaluate(X_test, y_test)
    logger.info("Final test accuracy: %.2f%% (loss: %.4f)", test_accuracy * 100, test_loss)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(output_path)
    logger.info("Model saved to %s", output_path)
    logger.info(
        "Label order is (0=angry, 1=disgust, 2=fear, 3=happy, 4=sad, 5=surprise, 6=neutral), "
        "matching emotion_classifier.py's default EMOTION_MODEL_LABELS - no changes needed there."
    )


if __name__ == "__main__":
    main()