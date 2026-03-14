"""
Content Generators

Contains generators for creating newsletter content from preprocessed discussions:
- base: Base class defining the generator interface
- newsletter_generator: Generic newsletter generator using format plugins
- factory: Factory for creating appropriate generator instances

Use ContentGeneratorFactory.create() which returns a NewsletterContentGenerator
configured for the specified format.
"""

from core.generation.generators.base import ContentGeneratorInterface
from core.generation.generators.factory import ContentGeneratorFactory
from core.generation.generators.newsletter_generator import NewsletterContentGenerator

__all__ = [
    "ContentGeneratorInterface",
    "ContentGeneratorFactory",
    "NewsletterContentGenerator",
]
