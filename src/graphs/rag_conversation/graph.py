"""
RAG Conversation Graph

Linear LangGraph StateGraph: retrieve -> generate -> evaluate.
"""

import logging

from langgraph.graph import StateGraph, START, END

from constants import NodeNames
from graphs.rag_conversation.nodes import (
    retrieve_node,
    generate_node,
    evaluate_node,
)
from graphs.rag_conversation.state import RAGConversationState

logger = logging.getLogger(__name__)


def build_rag_conversation_graph() -> StateGraph:
    """
    Build the RAG conversation graph.

    Flow: START -> retrieve -> generate -> evaluate -> END

    Returns:
        Compiled StateGraph
    """
    graph = StateGraph(RAGConversationState)

    # Add nodes
    graph.add_node(NodeNames.RAGConversation.RETRIEVE, retrieve_node)
    graph.add_node(NodeNames.RAGConversation.GENERATE, generate_node)
    graph.add_node(NodeNames.RAGConversation.EVALUATE, evaluate_node)

    # Linear edges
    graph.add_edge(START, NodeNames.RAGConversation.RETRIEVE)
    graph.add_edge(NodeNames.RAGConversation.RETRIEVE, NodeNames.RAGConversation.GENERATE)
    graph.add_edge(NodeNames.RAGConversation.GENERATE, NodeNames.RAGConversation.EVALUATE)
    graph.add_edge(NodeNames.RAGConversation.EVALUATE, END)

    return graph.compile()


# Module-level compiled graph instance
rag_conversation_graph = build_rag_conversation_graph()
