from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_huggingface import HuggingFaceEmbeddings
from langchain.prompts import PromptTemplate
from langchain.chains import ConversationalRetrievalChain
from langchain_experimental.text_splitter import SemanticChunker
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_qdrant.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue, PayloadSchemaType
from .config import (
    GEMINI_API_KEY, GEMINI_MODEL, QDRANT_URL, QDRANT_COLLECTION_NAME, QDRANT_API_KEY,
    QDRANT_VECTOR_SIZE, QDRANT_BATCH_SIZE, CHUNK_SIZE, TOP_K, SEARCH_LIMIT
)
import hashlib
from typing import List
import uuid
from fastapi import HTTPException

# Prompt
BASE_PROMPT = """
You are a helpful assistant. Use the retrieved context to answer the question. 
The answer must be in LaTEX format for application. 
If you don't know, say you don't know. Be concise (max 3 sentences). Return only valid JSON:
{"context": "...", "answer": "..."}
"""

prompt = PromptTemplate.from_template(BASE_PROMPT)

# LLM & Embedding
llm = ChatGoogleGenerativeAI(model=GEMINI_MODEL, 
                             google_api_key=GEMINI_API_KEY)

embedding = HuggingFaceEmbeddings(
    model_name="bkai-foundation-models/vietnamese-bi-encoder"
    )

# kết nối Qdrant client
qdrant_client = QdrantClient(
    url=QDRANT_URL,
    api_key=QDRANT_API_KEY,
    )

# Semantic chunking
chunker = SemanticChunker(embeddings=embedding, min_chunk_size=CHUNK_SIZE)

def create_collection_if_not_exists(collection_name):
    """Tạo collection trên qdrant nếu chưa tồn tại và đảm bảo có index cho document_id"""
    try:
        qdrant_client.get_collection(collection_name)
    except Exception:
        qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=QDRANT_VECTOR_SIZE,
                distance=Distance.COSINE
            )
        )
    # Đảm bảo luôn có index cho document_id
    try:
        qdrant_client.create_payload_index(
            collection_name=collection_name,
            field_name="document_id",
            field_schema=PayloadSchemaType.KEYWORD
        )
    except Exception as e:
        print(f"[DEBUG] Index for document_id may already exist: {e}")

def batch_embed_documents(documents: List, batch_size: int = QDRANT_BATCH_SIZE):
    """Embed documents theo batch để tối ưu IO"""
    embeddings = []
    for i in range(0, len(documents), batch_size):
        batch = documents[i:i + batch_size]
        batch_texts = [doc.page_content for doc in batch]
        batch_embeddings = embedding.embed_documents(batch_texts)
        embeddings.extend(batch_embeddings)
    return embeddings

def ingest_documents_batch(documents):
    """Upload documents vào Qdrant với batch processing"""
    # Tạo collection nếu chưa có
    create_collection_if_not_exists(QDRANT_COLLECTION_NAME)

    # Semantic chunking
    docs = chunker.split_documents(documents)

    # Batch embedding
    embeddings = batch_embed_documents(docs)

    # Tạo points cho Qdrant
    points = []
    for i, (doc, embedding_vector) in enumerate(zip(docs, embeddings)):
        point = PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding_vector,
            payload={
                "text": doc.page_content,
                "metadata": doc.metadata,
                "chunk_id": i
            }
        )
        points.append(point)

    # Batch upload to Qdrant
    for i in range(0, len(points), QDRANT_BATCH_SIZE):
        batch_points = points[i:i + QDRANT_BATCH_SIZE]
        qdrant_client.upsert(
            collection_name=QDRANT_COLLECTION_NAME,
            points=batch_points
        )

    # Tạo Qdrant vector store cho LangChain
    vector_store = QdrantVectorStore(
        client=qdrant_client,
        collection_name=QDRANT_COLLECTION_NAME,
        embedding=embedding
    )

    return vector_store

def ingest_documents(documents):
    """Wrapper cho backward compatibility"""
    return ingest_documents_batch(documents)

def ingest_documents_to_collection(documents, collection_name, document_id):
    create_collection_if_not_exists(collection_name)
    docs = chunker.split_documents(documents)
    
    # DEBUG: Log document processing
    print(f"[DEBUG] Processing {len(documents)} documents into {len(docs)} chunks")
    for i, doc in enumerate(docs[:3]):  # Log first 3 chunks
        print(f"[DEBUG] Chunk {i}: content_length={len(doc.page_content)}, content_preview={doc.page_content[:100]}...")
    
    embeddings = batch_embed_documents(docs)
    points = []
    
    for i, (doc, embedding_vector) in enumerate(zip(docs, embeddings)):
        # FIX: Đảm bảo text không bị rỗng
        if not doc.page_content.strip():
            print(f"[WARNING] Empty content in chunk {i}, skipping")
            continue
            
        point = PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding_vector,
            payload={
                "text": doc.page_content.strip(),  # FIX: Strip whitespace
                "metadata": doc.metadata,
                "chunk_id": i,
                "document_id": document_id,
                # FIX: Thêm metadata để debug
                "content_length": len(doc.page_content),
                "source": doc.metadata.get("source", "unknown")
            }
        )
        points.append(point)
    
    print(f"[DEBUG] Created {len(points)} valid points for ingestion")
    
    # Batch upload to Qdrant
    for i in range(0, len(points), QDRANT_BATCH_SIZE):
        batch_points = points[i:i + QDRANT_BATCH_SIZE]
        try:
            qdrant_client.upsert(
                collection_name=collection_name,
                points=batch_points
            )
            print(f"[DEBUG] Uploaded batch {i//QDRANT_BATCH_SIZE + 1}: {len(batch_points)} points")
        except Exception as e:
            print(f"[ERROR] Failed to upload batch {i//QDRANT_BATCH_SIZE + 1}: {e}")

def delete_document_vectors(collection_name, document_id):
    # Xóa tất cả vector có payload document_id trong collection_name
    qdrant_client.delete(
        collection_name=collection_name,
        points_selector=Filter(
            must=[
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=document_id)
                )
            ]
        )
    )

def get_retriever_for_collection(collection_name):
    try:
        collection_info = qdrant_client.get_collection(collection_name)
        print(f"[DEBUG] Collection {collection_name} exists with {collection_info.points_count} points")
    except UnexpectedResponse:
        raise HTTPException(
            status_code=400,
            detail=f"Collection `{collection_name}` không tồn tại. Hãy upload dữ liệu trước."
        )

    vector_store = QdrantVectorStore(
        client=qdrant_client,
        collection_name=collection_name,
        embedding=embedding
    )
    
    # FIX: Tạo custom retriever với debug
    class DebugRetriever:
        def __init__(self, vector_store, k=TOP_K):
            self.vector_store = vector_store
            self.k = k
        
        def invoke(self, query):
            print(f"[DEBUG] Retrieving for query: {query}")
            try:
                # Thử search trực tiếp với Qdrant client trước
                query_vector = embedding.embed_query(query)
                search_results = qdrant_client.search(
                    collection_name=collection_name,
                    query_vector=query_vector,
                    limit=self.k,
                    with_payload=True
                )
                
                print(f"[DEBUG] Direct Qdrant search returned {len(search_results)} results")
                for i, result in enumerate(search_results):
                    payload = result.payload
                    print(f"[DEBUG] Result {i}: score={result.score}, text_length={len(payload.get('text', ''))}")
                    print(f"[DEBUG] Result {i} text preview: {payload.get('text', '')[:100]}...")
                
                # Chuyển đổi sang LangChain Document format
                from langchain.docstore.document import Document
                docs = []
                for result in search_results:
                    doc = Document(
                        page_content=result.payload.get('text', ''),
                        metadata=result.payload.get('metadata', {})
                    )
                    docs.append(doc)
                
                return docs
                
            except Exception as e:
                print(f"[ERROR] Retrieval failed: {e}")
                return []
    
    return DebugRetriever(vector_store)

# Prompt/response caching (simple hash-based)
def cache_key(prompt, context):
    return hashlib.sha256((prompt + context).encode()).hexdigest()

# RAG chain
retriever = None
rag_chain = None

def setup_rag(vector_store):
    global retriever, rag_chain
    retriever = vector_store.as_retriever(
        search_kwargs={
            "k": TOP_K,
            "limit": SEARCH_LIMIT
        }
    )
    rag_chain = ConversationalRetrievalChain.from_llm(
        llm=llm,
        retriever=retriever,
        condense_question_prompt=prompt,
        return_source_documents=True
    )
    return rag_chain

def load_and_setup_rag(doc_paths, collection_name, document_ids):
    """Ingest nhiều tài liệu vào collection, trả về retriever cho collection đó"""
    for doc_path, document_id in zip(doc_paths, document_ids):
        if doc_path.endswith(".pdf"):
            loader = PyPDFLoader(doc_path)
        else:
            loader = TextLoader(doc_path)
        documents = loader.load()
        ingest_documents_to_collection(documents, collection_name, document_id)
    return get_retriever_for_collection(collection_name)

# Batch query optimization
# async def batch_vector_search(queries: List[str], batch_size: int = 5):
#     """Thực hiện batch vector search để tối ưu IO"""
#     results = []
#     for i in range(0, len(queries), batch_size):
#         batch_queries = queries[i:i + batch_size]
#         # Embed batch queries
#         batch_embeddings = embedding.embed_documents(batch_queries)

#         # Batch search
#         batch_results = []
#         for query_embedding in batch_embeddings:
#             search_result = qdrant_client.search(
#                 collection_name=QDRANT_COLLECTION_NAME,
#                 query_vector=query_embedding,
#                 limit=TOP_K
#             )
#             batch_results.append(search_result)

#         results.extend(batch_results)

#     return results

# batch vector search
async def batch_vector_search(queries: List[str], batch_size: int = 5):
    """Thực hiện batch vector search để tối ưu IO"""
    results = []
    for i in range(0, len(queries), batch_size):
        batch_queries = queries[i:i + batch_size]
        # Embed batch queries
        batch_embeddings = embedding.embed_documents(batch_queries)

        # Batch search
        batch_results = []
        for query_embedding in batch_embeddings:
            search_result = qdrant_client.search(
                collection_name=QDRANT_COLLECTION_NAME,  # FIX: Cần dynamic collection name
                query_vector=query_embedding,
                limit=TOP_K,
                with_payload=True  # FIX: Đảm bảo lấy payload
            )
            batch_results.append(search_result)

        results.extend(batch_results)

    return results