
import json
import sqlite3
import uuid

from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

from fastapi import (
    FastAPI,
    HTTPException,
    UploadFile,
    File,
)

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from langchain_core.messages import (
    HumanMessage,
    AIMessage,
)

load_dotenv()

from core.agent import build_agent


# ==================================================
# DATABASE CONFIGURATION
# ==================================================

# Project root:
# D:\MLOPS\agentic ai\chatbot.db

DB_PATH = (
    Path(__file__).resolve().parent.parent / "chatbot.db"
)


@contextmanager
def get_db():

    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
    )

    conn.row_factory = sqlite3.Row

    try:
        conn.execute("PRAGMA foreign_keys = ON")

        yield conn

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def init_db():

    with get_db() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_threads (
                thread_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(thread_id)
                    REFERENCES chat_threads(thread_id)
                    ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_messages_thread
            ON chat_messages(thread_id, id)
        """)


def save_message(thread_id: str, role: str, content: str):

    with get_db() as conn:

        if role == "user":

            conn.execute("""
                INSERT OR IGNORE INTO chat_threads
                (thread_id, title)
                VALUES (?, ?)
            """, (
                thread_id,
                content[:60],
            ))

        conn.execute("""
            INSERT INTO chat_messages
            (thread_id, role, content)
            VALUES (?, ?, ?)
        """, (
            thread_id,
            role,
            content,
        ))

        conn.execute("""
            UPDATE chat_threads
            SET updated_at = CURRENT_TIMESTAMP
            WHERE thread_id = ?
        """, (thread_id,))


def get_messages(thread_id: str):

    with get_db() as conn:

        rows = conn.execute("""
            SELECT role, content, created_at
            FROM chat_messages
            WHERE thread_id = ?
            ORDER BY id ASC
        """, (thread_id,)).fetchall()

    return [dict(row) for row in rows]


def get_previous_langchain_messages(thread_id: str):

    messages = []

    for item in get_messages(thread_id):

        if item["role"] == "user":

            messages.append(
                HumanMessage(content=item["content"])
            )

        elif item["role"] == "assistant":

            messages.append(
                AIMessage(content=item["content"])
            )

    return messages


# ==================================================
# AGENT INPUT / MEMORY
# ==================================================

def get_agent_input(
    thread_id: str,
    previous_messages: list,
    new_message: str,
):

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    try:

        snapshot = agent.get_state(config)

        existing_messages = (
            snapshot.values.get("messages", [])
            if snapshot and snapshot.values
            else []
        )

    except Exception as exc:

        print("Checkpoint read warning:", repr(exc))

        existing_messages = []

    # If graph memory already has this conversation,
    # send only the new message.
    if existing_messages:

        return {
            "messages": [
                HumanMessage(content=new_message)
            ]
        }

    # After backend restart, restore history from SQLite.
    return {
        "messages": previous_messages + [
            HumanMessage(content=new_message)
        ]
    }


# ==================================================
# RESPONSE HELPERS
# ==================================================

def extract_text(content):

    if isinstance(content, str):
        return content

    if isinstance(content, list):

        parts = []

        for item in content:

            if isinstance(item, str):
                parts.append(item)

            elif isinstance(item, dict):

                if item.get("type") == "text":
                    parts.append(item.get("text", ""))

        return "".join(parts)

    return ""


def sse_event(data: dict):

    return (
        "data: "
        + json.dumps(data, ensure_ascii=False)
        + "\n\n"
    )


def get_latest_ai_reply(result):

    messages = result.get("messages", [])

    for message in reversed(messages):

        if isinstance(message, AIMessage):

            reply = extract_text(message.content).strip()

            if reply:
                return reply

    return ""


# ==================================================
# INITIALIZE DATABASE
# ==================================================

init_db()


# ==================================================
# FASTAPI APPLICATION
# ==================================================

app = FastAPI(
    title="Agentic AI Chatbot - LangGraph",
    description=(
        "Agentic AI Chatbot with Groq streaming "
        "and SQLite conversation history"
    ),
    version="2.1.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================================================
# BUILD AGENT
# ==================================================

try:

    agent = build_agent()

    print("Agent initialized successfully.")

except Exception as exc:

    agent = None

    print(
        "Agent initialization failed:",
        repr(exc),
    )


# ==================================================
# REQUEST / RESPONSE MODELS
# ==================================================

class ChatRequest(BaseModel):

    message: str = Field(
        min_length=1,
        max_length=20000,
    )

    thread_id: str = Field(
        default_factory=lambda: str(uuid.uuid4())
    )


class ChatResponse(BaseModel):

    reply: str
    thread_id: str


# ==================================================
# ROOT AND HEALTH
# ==================================================

@app.get("/")
def root():

    return {
        "message": "Agentic AI Chatbot API is running",
        "database": str(DB_PATH),
    }


@app.get("/health")
def health():

    database_ok = DB_PATH.exists()

    return {
        "status": "ok" if agent is not None else "agent_error",
        "database": database_ok,
        "agent": agent is not None,
    }


# ==================================================
# CONVERSATION HISTORY API
# ==================================================

@app.get("/api/conversations")
def list_conversations():

    with get_db() as conn:

        rows = conn.execute("""
            SELECT
                thread_id,
                title,
                created_at,
                updated_at
            FROM chat_threads
            ORDER BY updated_at DESC
        """).fetchall()

    return {
        "conversations": [
            dict(row) for row in rows
        ]
    }


@app.get("/api/conversations/{thread_id}")
def get_conversation(thread_id: str):

    messages = get_messages(thread_id)

    if not messages:

        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    return {
        "thread_id": thread_id,
        "messages": messages,
    }


# ==================================================
# NORMAL CHAT API
# ==================================================

@app.post(
    "/api/chat",
    response_model=ChatResponse,
)
async def chat(request: ChatRequest):

    if agent is None:

        raise HTTPException(
            status_code=503,
            detail="Agent initialization failed. Check backend logs.",
        )

    try:

        previous_messages = get_previous_langchain_messages(
            request.thread_id
        )

        save_message(
            request.thread_id,
            "user",
            request.message,
        )

        input_state = get_agent_input(
            request.thread_id,
            previous_messages,
            request.message,
        )

        config = {
            "configurable": {
                "thread_id": request.thread_id
            }
        }

        # Graph contains an async assistant node,
        # so use ainvoke instead of invoke.
        result = await agent.ainvoke(
            input_state,
            config=config,
        )

        reply = get_latest_ai_reply(result)

        if not reply:

            raise HTTPException(
                status_code=502,
                detail="Groq returned no text response.",
            )

        save_message(
            request.thread_id,
            "assistant",
            reply,
        )

        return ChatResponse(
            reply=reply,
            thread_id=request.thread_id,
        )

    except HTTPException:
        raise

    except Exception as exc:

        print("CHAT ERROR:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail=f"Agent execution failed: {str(exc)}",
        )


# ==================================================
# REAL-TIME STREAMING CHAT API
# ==================================================

@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):

    if agent is None:

        raise HTTPException(
            status_code=503,
            detail="Agent initialization failed. Check backend logs.",
        )

    # Read old conversation before inserting new user message.
    previous_messages = get_previous_langchain_messages(
        request.thread_id
    )

    save_message(
        request.thread_id,
        "user",
        request.message,
    )

    input_state = get_agent_input(
        request.thread_id,
        previous_messages,
        request.message,
    )

    config = {
        "configurable": {
            "thread_id": request.thread_id
        }
    }

    async def generate():

        complete_reply = ""

        try:

            print(
                "Streaming started:",
                request.thread_id,
            )

            async for event in agent.astream_events(
                input_state,
                config=config,
                version="v2",
            ):

                event_name = event.get("event")

                if event_name != "on_chat_model_stream":
                    continue

                chunk = event.get(
                    "data", {}
                ).get("chunk")

                if chunk is None:
                    continue

                token = extract_text(
                    getattr(chunk, "content", "")
                )

                if not token:
                    continue

                complete_reply += token

                yield sse_event({
                    "type": "token",
                    "content": token,
                })

            # Save assistant response after successful completion.
            if complete_reply.strip():

                save_message(
                    request.thread_id,
                    "assistant",
                    complete_reply,
                )

                print(
                    "Streaming completed:",
                    request.thread_id,
                )

                yield sse_event({
                    "type": "done",
                    "thread_id": request.thread_id,
                })

            else:

                print(
                    "Streaming returned no text:",
                    request.thread_id,
                )

                yield sse_event({
                    "type": "error",
                    "message": (
                        "No text tokens received. "
                        "Check Groq API, model configuration "
                        "and LangGraph streaming."
                    ),
                })

        except Exception as exc:

            print(
                "STREAMING ERROR:",
                repr(exc),
            )

            yield sse_event({
                "type": "error",
                "message": str(exc),
            })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==================================================
# PDF UPLOAD API
# ==================================================

UPLOAD_DIR = (
    Path(__file__).resolve().parent
    / "data"
    / "uploads"
)

UPLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


@app.post("/api/knowledge/upload")
async def upload_pdf(file: UploadFile = File(...)):

    if (
        not file.filename
        or not file.filename.lower().endswith(".pdf")
    ):

        raise HTTPException(
            status_code=400,
            detail="Only PDF files are allowed.",
        )

    content = await file.read()

    if len(content) > 20 * 1024 * 1024:

        raise HTTPException(
            status_code=413,
            detail="PDF must be smaller than 20 MB.",
        )

    if not content.startswith(b"%PDF"):

        raise HTTPException(
            status_code=400,
            detail="Invalid PDF file.",
        )

    safe_name = f"{uuid.uuid4().hex}.pdf"

    destination = UPLOAD_DIR / safe_name

    destination.write_bytes(content)

    return {
        "status": "success",
        "message": (
            f"{file.filename} uploaded successfully. "
            "FAISS indexing is not connected yet."
        ),
        "filename": safe_name,
    }
