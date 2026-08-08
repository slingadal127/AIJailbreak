"""
Dataset loaders for RedTeamAgent's attack library.

Loads adversarial-behavior datasets directly from HuggingFace and returns them
as plain Python dicts the rest of the framework can index into ChromaDB.

No files are stored in the repo — `datasets` caches to ~/.cache/huggingface/
on first call, then reuses that cache on every subsequent run.

Usage:
    from redteam_dataset_loader import load_attack_library
    library = load_attack_library(limit_per_source=25)
    # library is a list[dict]: [{id, category, target_type, source, prompt}, ...]
"""

from __future__ import annotations

from datasets import load_dataset

# Map each source's native taxonomy → our 6 attack categories.
CATEGORY_MAP: dict[str, str] = {
    # HarmBench semantic categories
    "chemical_biological": "PROMPT_INJECTION",
    "cybercrime_intrusion": "JAILBREAK_TRANSFER",
    "misinformation_disinformation": "ROLEPLAY",
    "harassment_bullying": "ROLEPLAY",
    "harmful": "ROLEPLAY",
    # JailbreakBench behaviors
    "Harassment/Discrimination": "ROLEPLAY",
    "Malware/Hacking": "JAILBREAK_TRANSFER",
    "Physical harm": "ROLEPLAY",
    "Fraud/Deception": "ROLEPLAY",
    "Disinformation": "ROLEPLAY",
    "Sexual/Adult content": "ROLEPLAY",
    "Privacy": "PROMPT_INJECTION",
    "Expert advice": "MANY_SHOT",
    "Government decision-making": "MANY_SHOT",
    "Economic harm": "MANY_SHOT",
}


def _norm_category(raw: str | None) -> str:
    if not raw:
        return "ROLEPLAY"
    return CATEGORY_MAP.get(raw, "ROLEPLAY")


def load_harmbench(limit: int | None = None) -> list[dict]:
    """Load HarmBench standard behaviors from HuggingFace (MIT)."""
    ds = load_dataset("walledai/HarmBench", "standard", split="train")
    if limit:
        ds = ds.select(range(min(limit, len(ds))))
    return [
        {
            "id": f"HB{i:04d}",
            "category": _norm_category(row.get("category")),
            "target_type": row.get("category", "harmful"),
            "source": "HarmBench",
            "text": row.get("behavior") or row.get("prompt") or "",
            "notes": f"HarmBench standard behavior · {row.get('category', 'harmful')}",
        }
        for i, row in enumerate(ds)
    ]


def load_jailbreakbench(limit: int | None = None) -> list[dict]:
    """Load JailbreakBench harmful behaviors from HuggingFace (MIT)."""
    ds = load_dataset("JailbreakBench/JBB-Behaviors", "behaviors", split="harmful")
    if limit:
        ds = ds.select(range(min(limit, len(ds))))
    return [
        {
            "id": f"JBB{i:04d}",
            "category": _norm_category(row.get("Category")),
            "target_type": row.get("Category", "harmful"),
            "source": "JailbreakBench",
            "text": row.get("Goal") or row.get("Behavior") or "",
            "notes": f"JailbreakBench harmful behavior · {row.get('Category', 'harmful')}",
        }
        for i, row in enumerate(ds)
    ]


def load_beavertails(limit: int | None = None) -> list[dict]:
    """Load BeaverTails 30k QA pairs from HuggingFace (CC-BY-NC-4.0).

    Only keeps rows flagged `is_safe == False` — the unsafe answers are the
    ones useful as adversarial seeds.
    """
    ds = load_dataset("PKU-Alignment/BeaverTails", split="30k_train")
    unsafe = ds.filter(lambda r: not r.get("is_safe", True))
    if limit:
        unsafe = unsafe.select(range(min(limit, len(unsafe))))
    return [
        {
            "id": f"BT{i:04d}",
            "category": "PROMPT_INJECTION",
            "target_type": "harmful_qa",
            "source": "BeaverTails",
            "text": row.get("prompt", ""),
            "notes": "BeaverTails unsafe QA pair (is_safe=False)",
        }
        for i, row in enumerate(unsafe)
    ]


def load_wildguard(limit: int | None = None) -> list[dict]:
    """Load WildGuard prompt-harm labeled set from HuggingFace (Apache-2.0)."""
    ds = load_dataset("allenai/wildguardmix", "wildguardtrain", split="train")
    harmful = ds.filter(lambda r: r.get("prompt_harm_label") == "harmful")
    if limit:
        harmful = harmful.select(range(min(limit, len(harmful))))
    return [
        {
            "id": f"WG{i:04d}",
            "category": _norm_category(row.get("subcategory")),
            "target_type": row.get("subcategory", "harmful"),
            "source": "WildGuard",
            "text": row.get("prompt", ""),
            "notes": f"WildGuard harmful prompt · {row.get('subcategory', 'harmful')}",
        }
        for i, row in enumerate(harmful)
    ]


def load_attack_library(limit_per_source: int = 100) -> list[dict]:
    """Load and merge all four datasets into a single attack library.

    Args:
        limit_per_source: max rows to draw from each source (keeps startup fast).

    Returns:
        list of dicts with keys: id, category, target_type, source, prompt.
    """
    library: list[dict] = []
    for loader in (load_harmbench, load_jailbreakbench, load_beavertails, load_wildguard):
        try:
            library.extend(loader(limit=limit_per_source))
        except Exception as e:
            # Non-fatal — if one source is unreachable, keep the others.
            print(f"[dataset_loader] {loader.__name__} failed: {type(e).__name__}: {e}")
    return library


if __name__ == "__main__":
    lib = load_attack_library(limit_per_source=25)
    print(f"\nLoaded {len(lib)} attack seeds")
    by_source: dict[str, int] = {}
    for item in lib:
        by_source[item["source"]] = by_source.get(item["source"], 0) + 1
    for src, n in by_source.items():
        print(f"  {src}: {n}")
    print("\nSample:")
    for item in lib[:3]:
        print(f"  [{item['source']} / {item['category']}] {item['text'][:80]}")
