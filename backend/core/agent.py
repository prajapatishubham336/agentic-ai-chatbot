
from langchain_groq import ChatGroq

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from langgraph.graph import StateGraph, START, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver

from core.config import GROQ_API_KEY, GROQ_MODEL
from core.tools import calculator, search_web
from core.rag import query_uploaded_pdfs


SYSTEM_PROMPT = """
You are an intelligent Agentic AI Assistant.

Your capabilities:

1. Answer general questions.
2. Perform calculations using calculator.
3. Search the web using Tavily when required.
4. Retrieve information from uploaded PDFs.
5. Explain technical concepts.
6. Help with Python, SQL, Machine Learning,
   Deep Learning, NLP, Generative AI and LLMs.

Rules:

- Give accurate and helpful answers.
- Explain answers clearly.
- Use tools when required.
- Never invent tool results.
- If PDF information is requested, use the PDF retrieval tool.
- Mention when information is not available.
- Respond in the language used by the user.
"""


def build_agent():

    if not GROQ_API_KEY:
        raise ValueError(
            "GROQ_API_KEY missing in backend .env file."
        )

    # Groq LLM with streaming enabled
    llm = ChatGroq(
        model=GROQ_MODEL,
        temperature=0.2,
        api_key=GROQ_API_KEY,
        streaming=True,
    )

    # Available agent tools
    tools = [
        calculator,
        search_web,
        query_uploaded_pdfs,
    ]

    llm_with_tools = llm.bind_tools(tools)

    # -----------------------------------------
    # ASYNC STREAMING ASSISTANT NODE
    # -----------------------------------------

    async def assistant(
        state: MessagesState,
        config: RunnableConfig,
    ):

        messages = [
            SystemMessage(content=SYSTEM_PROMPT)
        ] + state["messages"]

        response = None

        # Forward config so LangGraph can receive
        # the model's streaming callbacks.
        async for chunk in llm_with_tools.astream(
            messages,
            config=config,
        ):

            if response is None:
                response = chunk
            else:
                response = response + chunk

        if response is None:
            raise RuntimeError(
                "Groq returned an empty response."
            )

        return {
            "messages": [response]
        }

    # -----------------------------------------
    # LANGGRAPH WORKFLOW
    # -----------------------------------------

    builder = StateGraph(MessagesState)

    builder.add_node(
        "assistant",
        assistant,
    )

    builder.add_node(
        "tools",
        ToolNode(tools),
    )

    builder.add_edge(
        START,
        "assistant",
    )

    builder.add_conditional_edges(
        "assistant",
        tools_condition,
    )

    builder.add_edge(
        "tools",
        "assistant",
    )

    # In-memory LangGraph checkpoint.
    # SQLite separately stores permanent chat history.
    memory = MemorySaver()

    chatbot = builder.compile(
        checkpointer=memory,
    )

    return chatbot
