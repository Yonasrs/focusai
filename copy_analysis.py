# copy_analysis.py — Copy Intelligence Engine v3
# Analyzes ad copy for spelling, grammar, tone, persuasion quality, and claim strength.
# Runs as a parallel step alongside persona analysis — does NOT slow down the pipeline.

COPY_ANALYSIS_PROMPT = """You are a senior copywriter and direct-response advertising specialist.
Your job is to audit the copy in this advertisement with precision and no flattery.

You have access to:
1. The ad image (examine all visible text carefully)
2. Ad copy text if provided: {ad_copy}

Analyze every piece of visible and provided text across these 8 dimensions:

━━━ 1. SPELLING ━━━
Scan for typos, misspellings, and OCR-visible text errors in the image.
Check both provided copy AND text visible in the image.

━━━ 2. GRAMMAR ━━━
Check sentence structure, verb agreement, pronoun consistency, awkward phrasing.

━━━ 3. PUNCTUATION ━━━
Missing, excessive, or inconsistent punctuation. Ellipsis abuse. Missing periods.

━━━ 4. CAPITALIZATION ━━━
Inconsistent capitalization. Mid-sentence caps. Headline formatting inconsistencies.

━━━ 5. TONE CONSISTENCY ━━━
Does the copy maintain a coherent voice throughout?
Flag: premium brand using casual slang, or casual brand using stiff corporate language.
Flag: emotional headline paired with dry body copy.

━━━ 6. READABILITY ━━━
Is each line easy to process in under 2 seconds?
Flag: overly dense copy, confusing structure, buried CTA, unclear hierarchy.
Score 1-10 where 10 = instantly clear.

━━━ 7. PERSUASION QUALITY ━━━
Evaluate each of these signals (score each 1-10):
- Emotional strength: does it create desire, urgency, or connection?
- Specificity: does it use concrete details or vague generalities?
- CTA strength: is the call-to-action clear, compelling, and low-friction?
- Differentiation: does it say something competitors could NOT say?
- Urgency: is there a reason to act now?

━━━ 8. CLAIM QUALITY ━━━
Classify every major claim as one of:
- STRONG: measurable, specific, verifiable ("4.9/5 from 50K users")
- WEAK: vague, generic, unverifiable ("transform your life", "best ever")
- UNSUPPORTED: specific-sounding but no proof offered ("clinically proven")

CRITICAL RULES:
- If you find NO issues, say so explicitly — do not invent problems
- Every issue must quote the EXACT text from the ad
- Every fix must be a concrete rewrite, not advice like "be more specific"
- Rewrite suggestions must be full alternative copy lines, not tips

Respond ONLY with valid JSON (no markdown, no extra text):
{{
  "copy_clean": <true if zero spelling/grammar/punctuation errors, false otherwise>,
  "copy_quality_score": <1-10 overall copy quality>,
  "tone_consistency": "high/medium/low",
  "readability_score": <1-10>,
  "persuasion_score": <1-10>,
  "claim_quality": "weak/mixed/strong",
  "issues_found": [
    {{
      "type": "spelling|grammar|punctuation|capitalization|tone|readability|persuasion|claim",
      "text": "exact text from ad",
      "problem": "what is wrong and why it hurts the ad",
      "suggested_fix": "exact replacement text"
    }}
  ],
  "claims_audit": [
    {{
      "claim": "exact claim text",
      "classification": "strong|weak|unsupported",
      "reason": "why this classification"
    }}
  ],
  "strongest_copy_element": "the single best line or element and why it works",
  "weakest_copy_element": "the single worst line or element and why it fails",
  "persuasion_breakdown": {{
    "emotional_strength": <1-10>,
    "specificity": <1-10>,
    "cta_strength": <1-10>,
    "differentiation": <1-10>,
    "urgency": <1-10>
  }},
  "rewrite_suggestions": [
    {{
      "original": "existing copy line",
      "rewrite": "stronger alternative",
      "reason": "why the rewrite performs better"
    }}
  ]
}}"""


def compute_confidence(persona_results: list) -> dict:
    """
    Compute analysis confidence from score spread across personas.
    No extra API calls needed — uses existing persona outputs.

    Logic:
    - Tight score spread (all personas within 2 pts) = HIGH confidence
    - Moderate spread (within 4 pts) = MEDIUM confidence
    - Wide spread (5+ pts difference) = LOW confidence

    This reflects real research methodology: high variance = low certainty.
    """
    if not persona_results:
        return {"confidence_level": "LOW", "reliability_score": 1,
                "confidence_reason": "No persona data available."}

    attention_scores = [r.get("attention_score", 5) for r in persona_results]
    trust_scores     = [r.get("trust_score", 5)     for r in persona_results]
    interest_scores  = [r.get("interest_score", 5)  for r in persona_results]

    attention_spread = max(attention_scores) - min(attention_scores)
    trust_spread     = max(trust_scores)     - min(trust_scores)
    interest_spread  = max(interest_scores)  - min(interest_scores)

    avg_spread = (attention_spread + trust_spread + interest_spread) / 3

    # Count stop-scroll agreement
    stop_votes = sum(1 for r in persona_results if r.get("would_stop_scrolling"))
    stop_majority = stop_votes >= 3  # majority agrees

    # Reliability score 1-10
    if avg_spread <= 2:
        reliability_score = 9
        confidence_level  = "HIGH"
        reason = (
            f"Personas produced highly consistent reactions "
            f"(avg score spread: {avg_spread:.1f} pts). "
            f"{'Majority agreed on scroll behavior.' if stop_majority else 'Minor disagreement on scroll behavior.'}"
        )
    elif avg_spread <= 4:
        reliability_score = 6
        confidence_level  = "MEDIUM"
        reason = (
            f"Personas showed moderate variation in scores "
            f"(avg spread: {avg_spread:.1f} pts), indicating the ad has mixed signals "
            f"that different audiences will interpret differently."
        )
    else:
        reliability_score = 3
        confidence_level  = "LOW"
        high_persona  = max(persona_results, key=lambda r: r.get("interest_score", 0))
        low_persona   = min(persona_results, key=lambda r: r.get("interest_score", 0))
        reason = (
            f"Persona reactions varied significantly (avg spread: {avg_spread:.1f} pts). "
            f"{high_persona['persona']['name']} and {low_persona['persona']['name']} "
            f"are at opposite ends — this ad is highly polarizing. "
            f"Results should be treated as directional, not definitive."
        )

    # Score breakdown for display
    score_breakdown = {
        "attention": {"min": min(attention_scores), "max": max(attention_scores), "spread": attention_spread},
        "trust":     {"min": min(trust_scores),     "max": max(trust_scores),     "spread": trust_spread},
        "interest":  {"min": min(interest_scores),  "max": max(interest_scores),  "spread": interest_spread},
    }

    return {
        "confidence_level":  confidence_level,
        "reliability_score": reliability_score,
        "confidence_reason": reason,
        "score_breakdown":   score_breakdown,
        "stop_scroll_votes": stop_votes,
        "avg_spread":        round(avg_spread, 1)
    }


# Per-persona trust rubric weights.
# Each persona applies these differently based on their bias.
TRUST_RUBRIC = {
    "base_factors": {
        "named_testimonial":     +3,
        "star_rating":           +2,
        "user_count":            +2,
        "app_screenshots":       +1,
        "no_credit_card":        +1,
        "money_back_guarantee":  +2,
        "security_badge":        +1,
        "generic_claim":         -2,
        "no_proof_visible":      -3,
        "hype_language":         -2,
        "unverifiable_claim":    -2,
    },
    "persona_multipliers": {
        # Jordan is hardest to convince — proof must be exceptional
        "skeptic":      {"star_rating": 0.5, "user_count": 0.5, "named_testimonial": 1.5, "no_proof_visible": 1.5},
        # Maya trusts if it feels authentic — less focused on hard data
        "emotional":    {"named_testimonial": 1.2, "generic_claim": 0.3, "no_proof_visible": 0.5},
        # David needs specificity — penalizes vague claims hardest
        "rational":     {"star_rating": 1.2, "user_count": 1.2, "generic_claim": 1.5, "no_proof_visible": 1.5},
        # Zoe cares little about proof — focused on vibe
        "trendy":       {"star_rating": 0.8, "no_proof_visible": 0.3, "hype_language": 0.2},
        # Robert needs value-proof — practical evidence matters most
        "conservative": {"money_back_guarantee": 1.5, "no_proof_visible": 1.2, "generic_claim": 1.3},
    }
}
