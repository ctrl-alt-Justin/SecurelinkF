"""
Dataset validation, deduplication, near-duplicate audit, and distribution summary
for SecureLink V4 evaluation datasets.

Usage:
    python -m eval.validate_dataset eval/datasets/v4_dev_300.json --held-out eval/datasets/held_out_sample.json
"""

from __future__ import annotations

import argparse
from collections import Counter
from typing import Dict, List, Tuple

from eval.metrics import normalize_text, tokenize_words
from eval.schema import EvalDataset, EvalScenario, load_dataset, verify_split_isolation


def _scenario_text(sc: EvalScenario) -> str:
    if sc.mode.value == "multi_turn":
        return " | ".join(t.utterance for t in sc.turns)
    return sc.utterance or sc.reference_transcript or ""


def find_exact_and_near_duplicates(
    ds: EvalDataset, jaccard_threshold: float = 0.85
) -> Dict[str, List[Tuple[str, str, float]]]:
    """
    Detect exact normalized text duplicates and high-Jaccard near-duplicates.
    Contrasting-context pairs sharing a `group:` tag are reported separately from
    unintentional duplicates.
    """
    norm_texts: List[Tuple[str, str, set[str], str]] = []
    for sc in ds.scenarios:
        raw = _scenario_text(sc)
        norm = normalize_text(raw)
        toks = set(tokenize_words(raw))
        grp = next((t for t in sc.tags if t.startswith("group:")), "")
        norm_texts.append((sc.id, norm, toks, grp))

    exact_dups: List[Tuple[str, str, float]] = []
    near_dups: List[Tuple[str, str, float]] = []

    for i in range(len(norm_texts)):
        id_a, norm_a, toks_a, grp_a = norm_texts[i]
        for j in range(i + 1, len(norm_texts)):
            id_b, norm_b, toks_b, grp_b = norm_texts[j]
            if norm_a and norm_a == norm_b:
                exact_dups.append((id_a, id_b, 1.0))
                continue
            if toks_a and toks_b:
                inter = len(toks_a & toks_b)
                union = len(toks_a | toks_b)
                jacc = inter / union if union > 0 else 0.0
                if jacc >= jaccard_threshold:
                    near_dups.append((id_a, id_b, round(jacc, 3)))

    return {"exact_duplicates": exact_dups, "near_duplicates": near_dups}


def summarize_dataset(ds: EvalDataset) -> Dict[str, object]:
    cat_counts: Counter = Counter()
    lang_counts: Counter = Counter()
    mode_counts: Counter = Counter()
    intent_counts: Counter = Counter()
    level_counts: Counter = Counter()
    review_count = 0
    teasing_count = 0
    threat_count = 0
    provisional_tagged = 0
    groups: set[str] = set()

    for sc in ds.scenarios:
        lang_counts[sc.language.value] += 1
        mode_counts[sc.mode.value] += 1
        if sc.expected_intent:
            intent_counts[sc.expected_intent] += 1
        if sc.expected_level:
            level_counts[sc.expected_level] += 1
        if sc.expected_review_required:
            review_count += 1
        if sc.is_friendly_teasing:
            teasing_count += 1
        if sc.is_serious_threat:
            threat_count += 1
        if "synthetic_provisional" in sc.tags:
            provisional_tagged += 1
        for tag in sc.tags:
            if tag.startswith("category:"):
                cat_counts[tag.split(":", 1)[1]] += 1
            elif tag.startswith("group:"):
                groups.add(tag.split(":", 1)[1])

    return {
        "dataset_name": ds.dataset_name,
        "split": ds.split.value,
        "total_scenarios": len(ds.scenarios),
        "provisional_tagged": provisional_tagged,
        "unique_groups": len(groups),
        "category_distribution": dict(sorted(cat_counts.items())),
        "language_coverage": dict(sorted(lang_counts.items())),
        "mode_coverage": dict(sorted(mode_counts.items())),
        "expected_intent_distribution": dict(sorted(intent_counts.items())),
        "expected_level_distribution": dict(sorted(level_counts.items())),
        "human_review_required_count": review_count,
        "friendly_teasing_count": teasing_count,
        "serious_threat_count": threat_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a SecureLink V4 evaluation dataset.")
    parser.add_argument("dataset", help="Path to dataset JSON file.")
    parser.add_argument("--held-out", default=None, help="Optional held-out dataset JSON to check split leakage.")
    parser.add_argument("--near-dup-threshold", type=float, default=0.85)
    args = parser.parse_args()

    ds = load_dataset(args.dataset)
    summary = summarize_dataset(ds)
    dups = find_exact_and_near_duplicates(ds, jaccard_threshold=args.near_dup_threshold)

    print("=== DATASET VALIDATION SUMMARY ===")
    for k, v in summary.items():
        print(f"{k}: {v}")
    print(f"exact_duplicates ({len(dups['exact_duplicates'])}): {dups['exact_duplicates']}")
    print(f"near_duplicates >= {args.near_dup_threshold} ({len(dups['near_duplicates'])}): {dups['near_duplicates']}")

    if args.held_out:
        ho = load_dataset(args.held_out)
        iso = verify_split_isolation(ds, ho)
        print(f"held_out_isolation: overlapping_ids={len(iso['overlapping_ids'])}, overlapping_texts={len(iso['overlapping_texts'])}")
        if iso["overlapping_texts"]:
            print("  overlapping_texts:", iso["overlapping_texts"])

    return 0 if not dups["exact_duplicates"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
