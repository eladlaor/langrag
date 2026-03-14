from core.ingestion.preprocessors.base import DataPreprocessorInterface
from core.ingestion.preprocessors.whatsapp import WhatsAppPreprocessor
from constants import DataSources, ALL_KNOWN_CHAT_NAMES


class DataProcessorFactory:
    """
    Factory for creating data preprocessors based on data source type and chat name.

    All WhatsApp community chats use the same WhatsAppPreprocessor since they have
    identical preprocessing logic. Chat names are derived from ALL_KNOWN_CHAT_NAMES
    in constants.py (the single source of truth).
    """

    # All WhatsApp chats use the same preprocessor — auto-generated from constants
    STRATEGIES: dict[str, dict[str, type]] = {DataSources.WHATSAPP_GROUP_CHAT_MESSAGES: {chat_name: WhatsAppPreprocessor for chat_name in ALL_KNOWN_CHAT_NAMES}}

    @classmethod
    def create(cls, data_source_type: str, chat_name: str, **kwargs) -> DataPreprocessorInterface:
        """
        Create a preprocessor for the given data source type and chat name.

        Args:
            data_source_type: Type of data source (e.g., "whatsapp_group_chat_messages")
            chat_name: Name of the chat to preprocess
            **kwargs: Additional arguments passed to the preprocessor

        Returns:
            DataPreprocessorInterface instance

        Raises:
            ValueError: If data source type or chat name is not supported
        """
        try:
            preprocessor_class = cls.STRATEGIES[data_source_type][chat_name]
            return preprocessor_class(chat_name=chat_name, **kwargs)
        except KeyError:
            raise ValueError(f"Data source type '{data_source_type}' or chat name '{chat_name}' " f"not found in supported strategies: {list(cls.STRATEGIES.keys())}")
