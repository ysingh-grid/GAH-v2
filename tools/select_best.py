def select_best_candidate(candidates):
    """Deterministically pick the best plan from PARALLEL strategy exploration.

    Given a list of candidate dicts (one per strategy child), each shaped like
    ``{"plan": <plan dict>, "verdict": "PASS"|..., "trust_tier": "certified"|"needs_review",
       "verification_token": <str>}``, return the single best ELIGIBLE candidate, or None.

    A candidate is ELIGIBLE only if it carries a plan dict AND a verification_token (proof it was
    really built + verified). Ranking, in order:
      1. geometry verdict PASS beats non-PASS,
      2. trust_tier 'certified' beats 'needs_review' (fidelity looked right),
      3. fewer build steps (simpler / more manufacturable) wins the tie.
    This is host-owned and pure (runs in the agent REPL as a native tool), so the choice is
    reproducible — the stochastic part (exploration) is bounded by a deterministic selection.
    """
    best = None
    best_key = None
    for c in (candidates or []):
        if not isinstance(c, dict):
            continue
        plan = c.get("plan")
        token = c.get("verification_token") or c.get("token")
        if not isinstance(plan, dict) or not token:
            continue
        verdict_ok = 1 if c.get("verdict") == "PASS" else 0
        tier = 2 if c.get("trust_tier") == "certified" else 1
        n_steps = len(plan.get("primitives_sequence") or [])
        key = (verdict_ok, tier, -n_steps)
        if best_key is None or key > best_key:
            best, best_key = c, key
    return best
