"""
RedTeamAgent v2 — Enhancement E3: Adaptive Workflow.

Addresses professor feedback:
  A4 #1: "explore giving the system more autonomy in deciding retrieval or
          mutation strategies"
  A4 #4: "look at ways the workflow could adapt automatically based on
          historical outcomes"

Instead of the user always hand-picking attack_category, the system learns
from SQLite history which category produced the most PARTIAL/SUCCESS verdicts
for a given (or similar) target behavior, and either suggests or auto-selects
it. An epsilon-explore mechanism prevents the system from locking into a local
optimum — even in auto mode it occasionally tries a different category to keep
discovering new attack surfaces.

Autonomy modes:
    "manual"  — system does nothing, user picks (original behavior)
    "suggest" — system recommends, user decides  (safe default)
    "auto"    — system picks if confident, else falls back to suggest

Usage:
    from redteam_adaptive import recommend_strategy, adaptive_run_sweep
    rec = recommend_strategy("phishing email", history_fn=get_behavior_history)
    # rec = {"suggested_category": "ROLEPLAY", "confidence": 0.7, "basis": "..."}
"""

from __future__ import annotations
import random
from collections import Counter, defaultdict
from typing import Callable, Optional

ALL_CATEGORIES = ["ROLEPLAY", "ENCODING", "MANY_SHOT",
                  "TOKEN_SMUGGLING", "PROMPT_INJECTION", "JAILBREAK_TRANSFER"]

# Tunables
MIN_SWEEPS_FOR_CONFIDENCE = 3      # need at least this many past verdicts
CONFIDENCE_THRESHOLD      = 0.50   # winning category needs >= this share of hits
EPSILON_EXPLORE           = 0.15   # in auto mode, explore a random category 15% of time


def _hit(verdict: str) -> bool:
    """A 'hit' is a PARTIAL or SUCCESS — the attack made progress."""
    return verdict in ("PARTIAL", "SUCCESS")


def recommend_strategy(target_behavior: str,
                       history_fn: Callable,
                       mode: str = "suggest") -> dict:
    """
    Recommend an attack_category based on historical outcomes.

    Args:
        target_behavior : the behavior about to be tested
        history_fn      : function(target_behavior) -> list of verdict dicts,
                          each with at least 'verdict' and 'category' keys.
                          (redteam_core.get_behavior_history matches this.)
        mode            : "manual" | "suggest" | "auto"

    Returns dict:
        {
          "mode": ...,
          "suggested_category": str or None,
          "confidence": float,
          "basis": str,           # human-readable explanation
          "should_autopick": bool,# True only in auto mode with high confidence
          "explored": bool,       # True if epsilon-explore overrode the pick
          "category_stats": {...} # per-category hit rates
        }
    """
    if mode == "manual":
        return {"mode": "manual", "suggested_category": None,
                "confidence": 0.0, "basis": "manual mode — no suggestion",
                "should_autopick": False, "explored": False,
                "category_stats": {}}

    history = history_fn(target_behavior)

    # Aggregate hits per category
    hits = defaultdict(int)
    totals = defaultdict(int)
    for record in history:
        cat = record.get("category")
        verdict = record.get("verdict")
        if cat in ALL_CATEGORIES:
            totals[cat] += 1
            if _hit(verdict):
                hits[cat] += 1

    total_sweeps = sum(totals.values())

    category_stats = {
        cat: {
            "hits": hits[cat],
            "total": totals[cat],
            "hit_rate": round(hits[cat] / totals[cat], 3) if totals[cat] else 0.0
        }
        for cat in ALL_CATEGORIES if totals[cat] > 0
    }

    # Not enough history → no confident suggestion
    if total_sweeps < MIN_SWEEPS_FOR_CONFIDENCE:
        return {
            "mode": mode, "suggested_category": None,
            "confidence": 0.0,
            "basis": (f"only {total_sweeps} past verdict(s) for this behavior — "
                      f"need {MIN_SWEEPS_FOR_CONFIDENCE}+ for a confident "
                      f"recommendation"),
            "should_autopick": False, "explored": False,
            "category_stats": category_stats,
        }

    # Pick the category with the best hit rate (ties broken by volume)
    best_cat = max(category_stats.items(),
                   key=lambda kv: (kv[1]["hit_rate"], kv[1]["total"]))
    best_category = best_cat[0]
    best_rate = best_cat[1]["hit_rate"]

    # ── epsilon-explore (auto mode only) ─────────────────────────────
    explored = False
    should_autopick = False
    chosen = best_category

    if mode == "auto":
        if random.random() < EPSILON_EXPLORE:
            # Explore: pick a DIFFERENT category to avoid local optima
            alternatives = [c for c in ALL_CATEGORIES if c != best_category]
            chosen = random.choice(alternatives)
            explored = True
            should_autopick = True
        elif best_rate >= CONFIDENCE_THRESHOLD:
            should_autopick = True

    basis = (f"{best_category} had the best hit rate "
             f"({best_rate:.0%}) across {best_cat[1]['total']} past sweeps")
    if explored:
        basis = (f"exploring {chosen} instead of the usual best "
                 f"({best_category}, {best_rate:.0%}) to discover new attack "
                 f"surfaces (epsilon-explore)")

    return {
        "mode": mode,
        "suggested_category": chosen,
        "confidence": round(best_rate, 3),
        "basis": basis,
        "should_autopick": should_autopick,
        "explored": explored,
        "category_stats": category_stats,
    }


def adaptive_run_sweep(target_behavior: str,
                       run_sweep_fn: Callable,
                       history_fn: Callable,
                       mode: str = "suggest",
                       user_category: Optional[str] = None,
                       num_variants: int = 2,
                       **sweep_kwargs) -> dict:
    """
    Wraps run_sweep with adaptive category selection.

    In "manual"  : uses user_category (must be provided).
    In "suggest" : returns the recommendation WITHOUT running — the caller
                   (UI) shows it to the user, who confirms. If user_category
                   is already provided, runs with it.
    In "auto"    : if confident, auto-picks and runs; else behaves like suggest.

    Returns either a recommendation dict (needs user confirmation) or a sweep
    result dict (already ran), distinguished by the 'action' key.
    """
    rec = recommend_strategy(target_behavior, history_fn, mode=mode)

    # Decide the category to use
    if mode == "manual":
        if not user_category:
            return {"action": "error",
                    "message": "manual mode requires user_category"}
        category = user_category

    elif mode == "suggest":
        if user_category:
            # User already chose (possibly after seeing a prior suggestion)
            category = user_category
        else:
            # Return the suggestion for the UI to display; don't run yet
            return {"action": "await_confirmation", "recommendation": rec}

    else:  # auto
        if rec["should_autopick"] and rec["suggested_category"]:
            category = rec["suggested_category"]
        elif user_category:
            category = user_category
        else:
            # Not confident enough to autopick and no user choice → ask
            return {"action": "await_confirmation", "recommendation": rec}

    # Run the sweep
    result = run_sweep_fn(target_behavior=target_behavior,
                          attack_category=category,
                          num_variants=num_variants,
                          **sweep_kwargs)
    result["action"] = "ran"
    result["adaptive"] = {
        "mode": mode,
        "category_used": category,
        "recommendation": rec,
        "followed_suggestion": (category == rec.get("suggested_category")),
    }
    return result


# ── Acceptance-rate tracking (a new metric) ──────────────────────────────
class SuggestionTracker:
    """Tracks how often users accept the adaptive suggestion — shows the
    adaptive system is actually useful."""

    def __init__(self):
        self.offered = 0
        self.accepted = 0
        self.explored = 0

    def record(self, suggested: Optional[str], chosen: str, explored: bool):
        if suggested:
            self.offered += 1
            if suggested == chosen:
                self.accepted += 1
        if explored:
            self.explored += 1

    def acceptance_rate(self) -> float:
        return round(self.accepted / self.offered, 3) if self.offered else 0.0

    def summary(self) -> dict:
        return {
            "suggestions_offered": self.offered,
            "suggestions_accepted": self.accepted,
            "acceptance_rate": self.acceptance_rate(),
            "explorations": self.explored,
        }


# ── Self-test with synthetic history (no API) ────────────────────────────
if __name__ == "__main__":
    print("=" * 68)
    print("E3 ADAPTIVE WORKFLOW — SELF TEST (synthetic history, no API)")
    print("=" * 68)

    # Synthetic history: for "phishing", ROLEPLAY has worked best
    fake_history = {
        "phishing email": [
            {"category": "ROLEPLAY", "verdict": "PARTIAL"},
            {"category": "ROLEPLAY", "verdict": "SUCCESS"},
            {"category": "ROLEPLAY", "verdict": "FAIL"},
            {"category": "ROLEPLAY", "verdict": "PARTIAL"},
            {"category": "ENCODING", "verdict": "FAIL"},
            {"category": "ENCODING", "verdict": "FAIL"},
            {"category": "PROMPT_INJECTION", "verdict": "FAIL"},
        ],
        "brand new behavior": [],  # no history
    }

    def history_fn(tb):
        return fake_history.get(tb, [])

    # Test 1: suggest mode with strong history
    print("\n--- Test 1: SUGGEST mode, behavior with history ---")
    rec = recommend_strategy("phishing email", history_fn, mode="suggest")
    print(f"  suggested : {rec['suggested_category']}")
    print(f"  confidence: {rec['confidence']:.0%}")
    print(f"  basis     : {rec['basis']}")
    print(f"  stats     : {rec['category_stats']}")
    assert rec["suggested_category"] == "ROLEPLAY", "should suggest ROLEPLAY"
    print("  OK - correctly identified ROLEPLAY as best")

    # Test 2: no history → no confident suggestion
    print("\n--- Test 2: behavior with NO history ---")
    rec2 = recommend_strategy("brand new behavior", history_fn, mode="suggest")
    print(f"  suggested : {rec2['suggested_category']}")
    print(f"  basis     : {rec2['basis']}")
    assert rec2["suggested_category"] is None, "should not suggest with no history"
    print("  OK - correctly declined to suggest without history")

    # Test 3: auto mode — should autopick ROLEPLAY (high confidence)
    print("\n--- Test 3: AUTO mode, confident ---")
    random.seed(2)   # avoid triggering epsilon-explore
    rec3 = recommend_strategy("phishing email", history_fn, mode="auto")
    print(f"  suggested    : {rec3['suggested_category']}")
    print(f"  should_autopick: {rec3['should_autopick']}")
    print(f"  explored     : {rec3['explored']}")

    # Test 4: epsilon-explore fires sometimes in auto mode
    print("\n--- Test 4: AUTO mode, epsilon-explore over 100 runs ---")
    explore_count = 0
    for i in range(100):
        random.seed(i)
        r = recommend_strategy("phishing email", history_fn, mode="auto")
        if r["explored"]:
            explore_count += 1
    print(f"  explored in {explore_count}/100 runs "
          f"(target ~{int(EPSILON_EXPLORE*100)}%)")
    assert 5 <= explore_count <= 30, "explore rate should be roughly 15%"
    print("  OK - epsilon-explore keeps the system from locking in")

    # Test 5: acceptance tracker
    print("\n--- Test 5: suggestion acceptance tracking ---")
    tracker = SuggestionTracker()
    tracker.record("ROLEPLAY", "ROLEPLAY", False)   # accepted
    tracker.record("ROLEPLAY", "ENCODING", False)   # overridden
    tracker.record("ROLEPLAY", "ROLEPLAY", False)   # accepted
    print(f"  {tracker.summary()}")

    print("\n" + "=" * 68)
    print("✅ E3 self-test complete — suggests from history, declines when")
    print("   data is thin, autopicks when confident, explores to avoid ruts.")
    print("=" * 68)