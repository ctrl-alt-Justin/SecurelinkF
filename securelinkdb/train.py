"""
SecureLink TagalogBERT Fine-Tuning Pipeline (V4)
================================================
Clean, reproducible, CLI-runnable training pipeline supporting:
- Expanded Filipino/English/Taglish CSV datasets (`text`, `label` in 0..3)
- Input normalization, null/blank filtering, and exact deduplication
- Stratified train/validation splits
- Balanced class weights in CrossEntropyLoss for class imbalance
- Per-class F1, Macro-F1, Macro-Precision, Macro-Recall, and Accuracy metrics
- Export format directly compatible with `securelinkdb/server.py` and `ContextEngine`
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import torch
from datasets import Dataset
from sklearn.metrics import accuracy_score, precision_recall_fscore_support
from sklearn.model_selection import train_test_split
from sklearn.utils.class_weight import compute_class_weight
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
    set_seed,
)

NUM_LABELS = 4
ID2LABEL: Dict[int, str] = {0: "LABEL_0", 1: "LABEL_1", 2: "LABEL_2", 3: "LABEL_3"}
LABEL2ID: Dict[str, int] = {v: k for k, v in ID2LABEL.items()}


def load_and_prepare_dataset(
    csv_path: str | Path,
    val_size: float = 0.2,
    seed: int = 42,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load a training CSV (`text`, `label`), drop invalid rows, deduplicate exact
    `(text, label)` pairs, and return stratified `(train_df, val_df)` DataFrames.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Training dataset CSV not found: {path}")

    df = pd.read_csv(path)
    if "text" not in df.columns or "label" not in df.columns:
        raise ValueError("Dataset CSV must contain 'text' and 'label' columns.")

    df = df[["text", "label"]].dropna().copy()
    df["text"] = df["text"].astype(str).str.strip()
    df = df[df["text"] != ""]
    df["label"] = df["label"].astype(int)

    invalid_labels = sorted(set(df["label"].unique()) - set(range(NUM_LABELS)))
    if invalid_labels:
        raise ValueError(f"Unexpected labels {invalid_labels}; expected 0..{NUM_LABELS - 1}.")

    df = df.drop_duplicates(subset=["text", "label"]).reset_index(drop=True)
    class_counts = df["label"].value_counts()
    if (class_counts < 2).any():
        raise ValueError(f"Each present class needs >= 2 samples for stratified split: {class_counts.to_dict()}")

    n_total = len(df)
    n_classes = len(class_counts)
    n_val = max(n_classes, int(round(n_total * float(val_size))))
    if n_val >= n_total:
        raise ValueError(f"Dataset too small ({n_total} rows) for validation size {val_size}.")

    train_df, val_df = train_test_split(
        df,
        test_size=n_val,
        stratify=df["label"],
        random_state=int(seed),
    )
    return train_df.reset_index(drop=True), val_df.reset_index(drop=True)


def compute_balanced_class_weights(
    labels: Sequence[int],
    num_labels: int = NUM_LABELS,
) -> torch.Tensor:
    """Compute inverse-frequency balanced class weights as a float32 tensor."""
    y = np.asarray(list(labels), dtype=np.int64)
    present_classes = np.unique(y)
    weights = np.ones(num_labels, dtype=np.float32)
    if len(present_classes) > 0:
        computed = compute_class_weight("balanced", classes=present_classes, y=y)
        for cls_idx, w in zip(present_classes, computed):
            if 0 <= int(cls_idx) < num_labels:
                weights[int(cls_idx)] = float(w)
    return torch.tensor(weights, dtype=torch.float32)


def build_compute_metrics(num_labels: int = NUM_LABELS) -> Callable[[Any], Dict[str, float]]:
    """Return a HuggingFace Trainer `compute_metrics` callback with macro and per-class F1."""
    def compute_metrics(eval_pred: Any) -> Dict[str, float]:
        logits, labels = eval_pred
        preds = np.argmax(logits, axis=-1)
        acc = float(accuracy_score(labels, preds))
        macro_p, macro_r, macro_f1, _ = precision_recall_fscore_support(
            labels, preds, average="macro", zero_division=0
        )
        per_cls_p, per_cls_r, per_cls_f1, _ = precision_recall_fscore_support(
            labels, preds, labels=list(range(num_labels)), average=None, zero_division=0
        )
        metrics: Dict[str, float] = {
            "accuracy": round(acc, 4),
            "macro_precision": round(float(macro_p), 4),
            "macro_recall": round(float(macro_r), 4),
            "macro_f1": round(float(macro_f1), 4),
        }
        for i in range(num_labels):
            metrics[f"precision_class_{i}"] = round(float(per_cls_p[i]), 4)
            metrics[f"recall_class_{i}"] = round(float(per_cls_r[i]), 4)
            metrics[f"f1_class_{i}"] = round(float(per_cls_f1[i]), 4)
        return metrics

    return compute_metrics


class WeightedLossTrainer(Trainer):
    """HuggingFace Trainer applying balanced CrossEntropyLoss class weights."""

    def __init__(self, *args: Any, class_weights: Optional[torch.Tensor] = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.class_weights = class_weights

    def compute_loss(self, model, inputs, return_outputs: bool = False, **kwargs: Any):
        model_device = None
        if hasattr(model, "parameters"):
            try:
                model_device = next(model.parameters()).device
            except StopIteration:
                model_device = None
        labels = inputs.get("labels")
        if model_device is not None and labels is not None and hasattr(labels, "to"):
            labels = labels.to(model_device)
        model_inputs = {
            k: (v.to(model_device) if (model_device is not None and hasattr(v, "to")) else v)
            for k, v in inputs.items()
            if k != "labels"
        }
        outputs = model(**model_inputs)
        logits = outputs.get("logits") if isinstance(outputs, dict) else outputs.logits

        if self.class_weights is not None:
            loss_fct = torch.nn.CrossEntropyLoss(
                weight=self.class_weights.to(device=logits.device, dtype=torch.float32)
            )
        else:
            loss_fct = torch.nn.CrossEntropyLoss()
        loss = loss_fct(logits.float().view(-1, model.config.num_labels), labels.view(-1))
        return (loss, outputs) if return_outputs else loss


def train_classifier(
    csv_path: str | Path = "dataset.csv",
    model_name: str = "jcblaise/roberta-tagalog-base",
    output_dir: str | Path = "./securelink_final_model",
    checkpoint_dir: str | Path = "./securelink_tagalogbert",
    epochs: int = 5,
    batch_size: int = 8,
    learning_rate: float = 2e-5,
    val_size: float = 0.2,
    seed: int = 42,
    max_length: int = 128,
    fp16: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run stratified split, balanced-weight fine-tuning, evaluation, and compatible checkpoint export."""
    set_seed(int(seed))
    train_df, val_df = load_and_prepare_dataset(csv_path, val_size=val_size, seed=seed)
    class_weights = compute_balanced_class_weights(train_df["label"].tolist(), num_labels=NUM_LABELS)

    train_dist = train_df["label"].value_counts().sort_index().to_dict()
    val_dist = val_df["label"].value_counts().sort_index().to_dict()
    print(f"[SYS] Stratified split ready: train={len(train_df)} {train_dist}, val={len(val_df)} {val_dist}")
    print(f"[SYS] Balanced class weights: {[round(float(x), 4) for x in class_weights.tolist()]}")

    if dry_run:
        return {
            "dry_run": True,
            "train_size": len(train_df),
            "val_size": len(val_df),
            "train_distribution": {int(k): int(v) for k, v in train_dist.items()},
            "val_distribution": {int(k): int(v) for k, v in val_dist.items()},
            "class_weights": [round(float(x), 4) for x in class_weights.tolist()],
        }

    local_only = os.path.isdir(str(model_name))
    tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=local_only)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name,
        num_labels=NUM_LABELS,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
        ignore_mismatched_sizes=True,
        local_files_only=local_only,
    )

    def _tokenize(examples):
        return tokenizer(examples["text"], padding="max_length", truncation=True, max_length=int(max_length))

    tokenized_train = Dataset.from_pandas(train_df, preserve_index=False).map(_tokenize, batched=True)
    tokenized_eval = Dataset.from_pandas(val_df, preserve_index=False).map(_tokenize, batched=True)

    training_args = TrainingArguments(
        output_dir=str(checkpoint_dir),
        eval_strategy="epoch",
        save_strategy="epoch",
        learning_rate=float(learning_rate),
        per_device_train_batch_size=int(batch_size),
        per_device_eval_batch_size=int(batch_size),
        num_train_epochs=float(epochs),
        weight_decay=0.01,
        warmup_ratio=0.1,
        fp16=bool(fp16 and torch.cuda.is_available()),
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        greater_is_better=True,
        seed=int(seed),
        save_total_limit=2,
        report_to="none",
        logging_steps=10,
    )

    trainer = WeightedLossTrainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_train,
        eval_dataset=tokenized_eval,
        compute_metrics=build_compute_metrics(num_labels=NUM_LABELS),
        class_weights=class_weights,
    )

    trainer.train()
    eval_metrics = trainer.evaluate()
    print(f"[SYS] Validation metrics: {eval_metrics}")

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    trainer.model.save_pretrained(str(out_path))
    tokenizer.save_pretrained(str(out_path))
    print(f"[SYS] Exported compatible model + tokenizer to {out_path}")

    return {
        "dry_run": False,
        "train_size": len(train_df),
        "val_size": len(val_df),
        "class_weights": [round(float(x), 4) for x in class_weights.tolist()],
        "eval_metrics": eval_metrics,
        "output_dir": str(out_path),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Fine-tune SecureLink TagalogBERT Classifier (V4)")
    parser.add_argument("--csv", default="dataset.csv")
    parser.add_argument("--model-name", default="jcblaise/roberta-tagalog-base")
    parser.add_argument("--output-dir", default="./securelink_final_model")
    parser.add_argument("--checkpoint-dir", default="./securelink_tagalogbert")
    parser.add_argument("--epochs", type=float, default=5)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--val-size", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument("--fp16", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    train_classifier(
        csv_path=args.csv,
        model_name=args.model_name,
        output_dir=args.output_dir,
        checkpoint_dir=args.checkpoint_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        val_size=args.val_size,
        seed=args.seed,
        max_length=args.max_length,
        fp16=args.fp16,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
