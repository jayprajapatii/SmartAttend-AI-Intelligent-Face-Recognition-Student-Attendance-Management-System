"""
scripts/train_mask_model.py

Trains the binary mask/no-mask classifier consumed by
core/mask_detection/mask_classifier.py, and saves it to
ml_models/mask_model.h5. Until this script has been run (and produced
a real .h5 file), mask_classifier.py automatically falls back to its
built-in heuristic - this script is what upgrades it to real
model-based detection.

Expects a dataset directory structured for Keras'
image_dataset_from_directory (standard ImageFolder-style layout):

    dataset/
        train/
            mask/       *.jpg
            no_mask/    *.jpg
        val/
            mask/       *.jpg
            no_mask/    *.jpg

A number of public mask-detection datasets on Kaggle/GitHub already
come in (or can be trivially reorganized into) this layout - this
script does not download or bundle any dataset itself.

Usage:
    python scripts/train_mask_model.py --data-dir /path/to/dataset --epochs 15
"""

import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train_mask_model")

IMAGE_SIZE = (224, 224)   # must match core/mask_detection/mask_classifier.py's MODEL_INPUT_SIZE
BATCH_SIZE = 32


def build_model():
    import tensorflow as tf

    base_model = tf.keras.applications.MobileNetV2(
        input_shape=(*IMAGE_SIZE, 3), include_top=False, weights="imagenet",
    )
    base_model.trainable = False  # transfer learning - freeze the pretrained backbone initially

    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(*IMAGE_SIZE, 3)),
        tf.keras.layers.Rescaling(1.0 / 255),
        base_model,
        tf.keras.layers.GlobalAveragePooling2D(),
        tf.keras.layers.Dense(64, activation="relu"),
        tf.keras.layers.Dropout(0.3),
        tf.keras.layers.Dense(1, activation="sigmoid"),  # 1 = mask, 0 = no mask (matches mask_classifier.py's assumption)
    ])

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-4),
        loss="binary_crossentropy",
        metrics=["accuracy"],
    )
    return model, base_model


def fine_tune(model, base_model, learning_rate=1e-5):
    """Unfreezes the last few layers of the backbone for a short fine-tuning pass."""
    import tensorflow as tf

    base_model.trainable = True
    for layer in base_model.layers[:-20]:
        layer.trainable = False

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate),
        loss="binary_crossentropy",
        metrics=["accuracy"],
    )
    return model


def main():
    parser = argparse.ArgumentParser(description="Train the mask detection model.")
    parser.add_argument("--data-dir", required=True, help="Path to dataset root (containing train/ and val/).")
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--fine-tune-epochs", type=int, default=5)
    parser.add_argument("--output", default="ml_models/mask_model.h5")
    args = parser.parse_args()

    import tensorflow as tf

    data_dir = Path(args.data_dir)
    train_dir = data_dir / "train"
    val_dir = data_dir / "val"

    if not train_dir.exists() or not val_dir.exists():
        raise FileNotFoundError(
            f"Expected '{train_dir}' and '{val_dir}' to exist, each containing 'mask/' and 'no_mask/' subfolders."
        )

    logger.info("Loading dataset from %s", data_dir)
    train_ds = tf.keras.utils.image_dataset_from_directory(
        train_dir, image_size=IMAGE_SIZE, batch_size=BATCH_SIZE, label_mode="binary",
    )
    val_ds = tf.keras.utils.image_dataset_from_directory(
        val_dir, image_size=IMAGE_SIZE, batch_size=BATCH_SIZE, label_mode="binary",
    )

    logger.info("Class mapping: %s (index 0) / %s (index 1)", train_ds.class_names[0], train_ds.class_names[1])
    if train_ds.class_names != ["mask", "no_mask"]:
        logger.warning(
            "Expected class folders named exactly 'mask' and 'no_mask' in that order for the "
            "sigmoid output to mean what mask_classifier.py assumes (1=mask). Found: %s. "
            "Verify the label mapping before trusting predictions.",
            train_ds.class_names,
        )

    train_ds = train_ds.prefetch(tf.data.AUTOTUNE)
    val_ds = val_ds.prefetch(tf.data.AUTOTUNE)

    model, base_model = build_model()

    logger.info("Training classification head (backbone frozen) for %d epochs...", args.epochs)
    model.fit(train_ds, validation_data=val_ds, epochs=args.epochs)

    if args.fine_tune_epochs > 0:
        logger.info("Fine-tuning top backbone layers for %d epochs...", args.fine_tune_epochs)
        model = fine_tune(model, base_model)
        model.fit(train_ds, validation_data=val_ds, epochs=args.fine_tune_epochs)

    val_loss, val_accuracy = model.evaluate(val_ds)
    logger.info("Final validation accuracy: %.2f%% (loss: %.4f)", val_accuracy * 100, val_loss)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(output_path)
    logger.info("Model saved to %s", output_path)


if __name__ == "__main__":
    main()