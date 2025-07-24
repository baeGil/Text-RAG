import os
from dotenv import load_dotenv

load_dotenv()

# LLM config
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"
# GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"

# Vector DB config (Qdrant)
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME")
QDRANT_VECTOR_SIZE = int(os.getenv("QDRANT_VECTOR_SIZE", 768))  # embedding size
QDRANT_BATCH_SIZE = int(os.getenv("QDRANT_BATCH_SIZE", 64))  # Batch size for ingestion

# Redis config
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_DB = int(os.getenv("REDIS_DB", 0))

# Chunking config
CHUNK_SIZE = 1024

# Chat summary config
SUMMARY_EVERY_N = int(os.getenv("SUMMARY_EVERY_N", 10))  # Số lượt chat để tự động summarize

# Session config (đơn giản, không cần auth)
SESSION_EXPIRE_HOURS = int(os.getenv("SESSION_EXPIRE_HOURS", 24))

# Vector search config
TOP_K = int(os.getenv("TOP_K", 3))  # Số lượng chunk trả về khi truy vấn
SEARCH_LIMIT = int(os.getenv("SEARCH_LIMIT", 10)) # số lượng vector để search đồng thời

REWRITE_HISTORY_M = int(os.getenv("REWRITE_HISTORY_M", 3))  # Số lịch sử dùng để rewrite query