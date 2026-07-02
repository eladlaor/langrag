"""Translated-newsletter response contract.

A TRANSLATED newsletter has the SAME structured shape as the ENRICHED newsletter
dict: identical keys and structure, every URL preserved verbatim, and only the
human-readable text field values rendered in the target language. Because the
shape is identical, the translated dict is renderable by the exact same format
plugins (``render_markdown`` / ``render_html`` and ``json.dump``) that produce
the enriched outputs.

That shape is FORMAT-SPECIFIC — the LangTalks format uses
``LlmResponseLangTalksNewsletterContent`` (primary/secondary discussions +
worth-mentioning), while the MCP Israel format uses
``LlmResponseMcpIsraelNewsletterContent`` (categorical prose sections). Rather
than duplicate both shapes here (which would drift from the source-of-truth
generation schemas), the structured-translation operation reuses each format's
own ``get_response_schema()`` as the structured-output schema. This module names
that contract and provides the resolver so callers and the graph-wiring phase
reference one canonical symbol.
"""

from pydantic import BaseModel

from custom_types.field_keys import ContentResultKeys, NewsletterStructureKeys
from custom_types.newsletter_formats import get_format

# A translated newsletter is, by contract, the same Pydantic shape the format
# emits at generation/enrichment time. Named alias for call sites and typing.
TranslatedNewsletterContent = BaseModel


def resolve_translated_newsletter_dict(translation_result: object) -> dict:
    """Resolve the translated newsletter dict from a structured-translate result.

    The structured-translate op returns the translated newsletter dict directly
    (same shape as the enriched dict). Some callers wrap it under
    ``ContentResultKeys.TRANSLATED_NEWSLETTER``; accept either shape. Fail-fast on
    anything that is not a usable newsletter dict.

    This is the single shared resolver used by BOTH the per-chat and consolidated
    final-newsletter nodes, so the two pipelines stay byte-identical in how they
    unwrap the structured-translate result.

    Args:
        translation_result: The raw result returned by the structured translate op.

    Returns:
        The translated newsletter dict.

    Raises:
        RuntimeError: If the result is empty or exposes no resolvable dict.
    """
    if not isinstance(translation_result, dict) or not translation_result:
        raise RuntimeError(f"Structured translation returned an empty or non-dict result: {type(translation_result)}")

    # A raw newsletter dict carries the newsletter structure directly.
    if NewsletterStructureKeys.PRIMARY_DISCUSSION in translation_result:
        return translation_result

    # Otherwise expect the dict wrapped under the translated-newsletter key.
    wrapped = translation_result.get(ContentResultKeys.TRANSLATED_NEWSLETTER)
    if isinstance(wrapped, dict) and wrapped:
        return wrapped

    raise RuntimeError(f"Structured translation result has no resolvable newsletter dict (keys={list(translation_result.keys())})")


def merge_enrichment_only_keys(translated_dict: dict, enriched_dict: dict) -> dict:
    """Re-attach enrichment-only top-level keys the strict-schema translate drops.

    The structured translate returns a dict pinned to the format's GENERATION
    schema, so enrichment-only top-level keys the enriched dict carried
    (``link_enrichment_metadata``, ``links_inserted``, ``metadata``) are absent
    from the translated dict. English runs keep them (they render the enriched
    dict directly); this restores parity for non-English runs so the final JSON
    is structurally identical regardless of target language.

    Translated text fields are preserved (translated keys win); only keys ABSENT
    from the translated dict are copied over from the enriched dict.

    Args:
        translated_dict: The translated (schema-pinned) newsletter dict.
        enriched_dict: The pre-translation enriched newsletter dict.

    Returns:
        The translated dict with the dropped enrichment-only keys re-attached.
    """
    for key in ENRICHMENT_ONLY_TOP_LEVEL_KEYS:
        if key not in translated_dict and key in enriched_dict:
            translated_dict[key] = enriched_dict[key]
    return translated_dict


# Top-level keys the enrichment stage adds to the newsletter dict but the strict
# generation schema does not model, so a schema-pinned structured translate omits
# them. Named here so both pipelines re-attach exactly the same set.
ENRICHMENT_ONLY_TOP_LEVEL_KEYS = (
    NewsletterStructureKeys.LINK_ENRICHMENT_METADATA,
    NewsletterStructureKeys.LINKS_INSERTED,
    NewsletterStructureKeys.METADATA,
)


def get_translated_newsletter_schema(summary_format: str) -> type[BaseModel]:
    """Resolve the response schema for a structured newsletter translation.

    The translated dict must validate to the SAME shape as the enriched
    newsletter for the given format, so this returns that format's own
    generation response schema.

    Args:
        summary_format: The format identifier (e.g. ``"langtalks_format"``).

    Returns:
        The Pydantic model type describing the translated newsletter dict.

    Raises:
        Exception: If the format cannot be resolved or exposes no schema.
    """
    try:
        newsletter_format = get_format(summary_format)
        return newsletter_format.get_response_schema()
    except Exception as e:
        error_message = f"Error resolving translated-newsletter schema for format '{summary_format}' in get_translated_newsletter_schema: {e}"
        raise Exception(error_message) from e
