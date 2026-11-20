import json
import shutil

from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import FAISS

from langchain_huggingface import HuggingFaceEmbeddings

from langchain_text_splitters import RecursiveCharacterTextSplitter

from langchain_core.tools import tool

from core.config import (
    EMBEDDING_MODEL,
    DATA_DIR
)


BASE_DIR = Path(DATA_DIR)

UPLOAD_DIR = BASE_DIR / "uploads"
INDEX_DIR = BASE_DIR / "faiss_index"

META_FILE = BASE_DIR / "index_meta.json"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_embeddings = None
_vector_store = None


def get_embeddings():

    global _embeddings

    if _embeddings is None:

        _embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": "cpu"},
            encode_kwargs={
                "normalize_embeddings": True
            }
        )

    return _embeddings


def get_vector_store():

    global _vector_store

    if _vector_store is not None:
        return _vector_store

    index_file = INDEX_DIR / "index.faiss"

    if index_file.exists():

        _vector_store = FAISS.load_local(
            str(INDEX_DIR),
            get_embeddings(),
            allow_dangerous_deserialization=True
        )

    return _vector_store


def ingest_pdf(pdf_bytes, filename):

    global _vector_store

    safe_filename = Path(filename).name

    file_path = UPLOAD_DIR / safe_filename

    file_path.write_bytes(pdf_bytes)

    loader = PyPDFLoader(str(file_path))

    documents = loader.load()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )

    chunks = splitter.split_documents(documents)

    if not chunks:
        raise ValueError("No readable text found in PDF")

    vector_store = get_vector_store()

    if vector_store is None:

        vector_store = FAISS.from_documents(
            chunks,
            get_embeddings()
        )

    else:

        vector_store.add_documents(chunks)

    INDEX_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    vector_store.save_local(str(INDEX_DIR))

    _vector_store = vector_store

    metadata = {
        "documents": [safe_filename],
        "pages": len(documents),
        "chunks": len(chunks)
    }

    META_FILE.write_text(
        json.dumps(metadata, indent=4),
        encoding="utf-8"
    )

    return {
        "pages": len(documents),
        "chunks": len(chunks)
    }


def retrieve_context(query):

    vector_store = get_vector_store()

    if vector_store is None:
        return "No PDF document has been uploaded."

    documents = vector_store.similarity_search(
        query,
        k=4
    )

    if not documents:
        return "No relevant content found."

    results = []

    for document in documents:

        source = Path(
            document.metadata.get("source", "PDF")
        ).name

        page = document.metadata.get("page", "?")

        results.append(
            f"Source: {source}, Page: {page}\n"
            f"{document.page_content}"
        )

    return "\n\n".join(results)


@tool
def query_uploaded_pdfs(query: str) -> str:
    """
    Retrieve relevant information from uploaded PDF documents.
    """

    return retrieve_context(query)


def get_index_status():

    if not META_FILE.exists():
        return {
            "ready": False,
            "documents": 0,
            "chunks": 0
        }

    try:

        metadata = json.loads(
            META_FILE.read_text(encoding="utf-8")
        )

        return {
            "ready": (INDEX_DIR / "index.faiss").exists(),
            "documents": len(metadata.get("documents", [])),
            "chunks": metadata.get("chunks", 0)
        }

    except Exception:

        return {
            "ready": False,
            "documents": 0,
            "chunks": 0
        }


def clear_knowledge_base():

    global _vector_store

    _vector_store = None

    if INDEX_DIR.exists():
        shutil.rmtree(INDEX_DIR)

    if UPLOAD_DIR.exists():

        for file in UPLOAD_DIR.glob("*.pdf"):
            file.unlink()

    if META_FILE.exists():
        META_FILE.unlink()