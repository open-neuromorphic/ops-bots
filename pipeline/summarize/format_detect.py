import re


def detect_ec_transcript_format(text: str) -> str:
    """
    Analyzes the content of a static transcript note to determine its structure.
    Returns: 'pre_summarized', 'bolded_asr', or 'raw_asr'.
    """
    # Look for standard structural headers that denote a human or AI has already processed it
    if "ALIGNED" in text and re.search(r"^##?\s*(?:Decisions|Action Items|Summary)", text, re.M | re.I):
        return "pre_summarized"

    # Look for bolded speaker names (a lighter level of formatting)
    if re.search(r"^\*\*.+?:\*\*", text, re.M) or re.search(r"^###\s", text, re.M):
        return "bolded_asr"

    return "raw_asr"


def assign_priority_bucket(source_key: str, format_type: str = "unknown") -> int:
    """
    Returns the routing priority tier based on source identity and format.
    1 = Immutable Reference (Diff only, handled outside digests)
    2 = Operational State (FAST model, flatten to bullets/tables)
    3 = Strategic State (STRONG model, deep extraction)
    """
    priority_3_sources = {"leadership", "ec_transcript", "tech-contributors"}

    if source_key in priority_3_sources:
        if format_type == "pre_summarized":
            # If it's already summarized, bump it down to FAST tier to lightly format it
            return 2
        return 3

    return 2  # Default to FAST tier for operational channels like #event-coordination