# Changelog

## v1.6.1
- Propagate force_refresh_extraction parameter to Beeper extractor for cache bypass support.

## v1.6.0
- RAG newsletter conversation: chat with past newsletters using retrieval-augmented generation.

## v1.5.1
- Merge English Substack rendering support into main.

## v1.5.0
- English newsletter rendering support: generate and render newsletters in English with Substack-compatible HTML output.

## v1.4.0
- RAG podcast conversation: ingest podcast transcripts, chunk, embed, and enable conversational Q&A over podcast content.

## v1.3.0
- Custom SLM: enhanced Ollama-based message pre-filtering with custom classifier configuration.

## v1.2.0
- Translation cache for avoiding redundant translation API calls. Poll message extraction and rendering support.

## v1.1.1
- Updated README: image extraction pipeline documentation, reply correlation section, reduced hardcoded model references.
- Updated pipeline animation and static diagram to include Extract Images and Associate Images stages.

## v1.1.0
  - Image analysis pipeline: extract, decrypt, and describe images from WhatsApp messages using vision models.
  - Images are now associated with their discussions and included as context in the relevant llm calls.
  - Expanded SLM classifier configuration options, as preparation for an upcoming fine-tuned SLM enhancement.  

## v1.0.0
  - Squashed first public release.
