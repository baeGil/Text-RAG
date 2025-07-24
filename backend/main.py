from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from .rag_pipeline import load_and_setup_rag, batch_vector_search
import json
from .config import SUMMARY_EVERY_N, REWRITE_HISTORY_M
from .rag_pipeline import llm
from .db import create_session, is_valid_session, save_chat, save_evaluation, get_eval_stats, delete_chat_history, delete_summary_for_session
# from .rag_pipeline import cache_key
import tempfile
import time
import uuid
import redis
from .config import REDIS_URL
import hashlib
import logging
import re
from datetime import datetime
import requests
app = FastAPI()

# CORS cho phép frontend truy cập từ bất kì domain nào
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Schemas pydantic model
# dữ liệu gửi lên khi người dùng chat
class ChatRequest(BaseModel):
    question: str
    session_id: str = None

# dữ liệu khi đánh gía câu trả lời
class EvalRequest(BaseModel):
    chat_id: str
    score: int
    comment: str = ""

# dùng cho batch query
class BatchQueryRequest(BaseModel):
    queries: list[str]
    session_id: str = None

# Quản lý pipeline theo session_id
session_rag_chains = {}

# Kết nối Redis
redis_client = redis.Redis.from_url(REDIS_URL)

def get_session_collection(session_id):
    key = f"session:{session_id}:collection"
    collection = redis_client.get(key)
    if collection:
        return collection.decode()
    # Nếu chưa có, tạo mới
    collection = f"session_{session_id}"
    redis_client.set(key, collection)
    return collection

def add_document_to_session(session_id, document_id, filename, size_mb):
    redis_client.rpush(f"session:{session_id}:documents", document_id)
    meta = {"filename": filename, 
            "session_id": session_id, 
            "size_mb": size_mb}
    redis_client.hset(f"document:{document_id}:meta", mapping=meta)

def remove_document_from_session(session_id, document_id):
    redis_client.lrem(f"session:{session_id}:documents", 0, document_id)
    redis_client.delete(f"document:{document_id}:meta")

def get_documents_of_session(session_id):
    doc_ids = redis_client.lrange(f"session:{session_id}:documents", 0, -1)
    docs = []
    for doc_id in doc_ids:
        doc_id_str = doc_id.decode()
        meta = redis_client.hgetall(f"document:{doc_id_str}:meta")
        meta = {k.decode(): v.decode() for k, v in meta.items()}
        meta["document_id"] = doc_id_str
        docs.append(meta)
    return docs

def get_llm_text(llm_result):
    if hasattr(llm_result, 'content'):
        return llm_result.content.strip()
    return str(llm_result).strip()

def save_chat_pair(session_id, question, answer, metrics=None):
    chat_pair = {
        "id": str(uuid.uuid4()),
        "question": question,
        "answer": answer,
        "created_at": datetime.now().isoformat(),
        # "metrics": metrics or {}
    }
    redis_client.rpush(f"chat:{session_id}:history", json.dumps(chat_pair))
    redis_client.expire(f"chat:{session_id}:history", 3600 * 24 * 7)
    return chat_pair["id"]


def update_chat_metrics(session_id, chat_id, metrics):
    key = f"chat:{session_id}:history"
    items = redis_client.lrange(key, 0, -1)
    for idx, item in enumerate(items):
        chat_pair = json.loads(item)
        if chat_pair.get("id") == chat_id:
            chat_pair["metrics"] = metrics
            redis_client.lset(key, idx, json.dumps(chat_pair))
            break


def get_chat_history_pairs(session_id):
    items = redis_client.lrange(f"chat:{session_id}:history", 0, -1)
    return [json.loads(item) for item in items]


def delete_chat_history(session_id):
    redis_client.delete(f"chat:{session_id}:history")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chat-debug")

@app.post("/session")
def create_new_session():
    """Tạo session mới cho user"""
    session_id = create_session()
    return {"session_id": session_id}

def clean_rewrite_output(text):
    """Làm sạch output từ LLM rewrite để chỉ lấy câu hỏi đầu tiên"""
    lines = text.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Loại bỏ số thứ tự, bullet points
        line = re.sub(r'^\d+\.\s*', '', line)
        line = re.sub(r'^[-*]\s*', '', line)
        line = re.sub(r'^\*\*.*?\*\*\s*', '', line)  # Remove **bold text**
        
        # Loại bỏ phần trong ngoặc đơn ở cuối
        line = re.sub(r'\s*\([^)]+\)\s*$', '', line)
        
        line = line.strip()
        
        # Nếu là câu hỏi hợp lệ, trả về ngay
        if line and (line.endswith('?') or 'là ai' in line or 'là gì' in line):
            return line
    
    # Fallback: trả về dòng đầu tiên không rỗng
    for line in lines:
        line = line.strip()
        if line and not line.startswith('Dưới đây'):
            return line
    return text.strip()

def rewrite_query_with_history(question, history):
    """Dùng LLM rewrite truy vấn follow-up thành câu hỏi đầy đủ dựa trên m lịch sử gần nhất."""
    if not history:
        return question
    
    # Lấy m lịch sử gần nhất
    m = REWRITE_HISTORY_M
    selected_history = history[-m:] if len(history) >= m else history
    
    # FIX: Sửa logic check is_user
    chat_text = "\n".join([
        ("User: " if str(c.get('is_user')) == '1' else "Bot: ") + c.get('message', '') 
        for c in reversed(selected_history)
    ])
    
    # FIX: Cải thiện prompt để đảm bảo chỉ trả về 1 câu hỏi
    prompt = f"""
Giving the following chat history of conversation, rewrite the user question to reflect what the user is actually asking. Response in Vietnamese
Chat history:{chat_text}
User question: {question}
Your rewritten query:
"""
    logger.info(f"[REWRITE] Prompt: {prompt}")
    try:
        rewritten = llm.invoke(prompt)
        rewritten_text = get_llm_text(rewritten)
        logger.info(f"[REWRITE] LLM raw output: {rewritten_text}")
        
        cleaned = clean_rewrite_output(rewritten_text)
        logger.info(f"[REWRITE] Cleaned output: {cleaned}")
        
        # set_prompt_cache(prompt, cleaned)
        return cleaned
    except Exception as e:
        logger.error(f"[REWRITE] LLM error: {e}")
        return question

# Thống kê hiệu năng
stats = {"cache_hit": 0, "cache_miss": 0, "llm_calls": 0, "total_latency": 0, "num_chats": 0}

@app.post("/chat")
async def chat(req: ChatRequest):
    start = time.time()
    if not req.session_id or not is_valid_session(req.session_id):
        req.session_id = create_session()
    collection_name = get_session_collection(req.session_id)
    try:
        from .rag_pipeline import get_retriever_for_collection
        retriever = get_retriever_for_collection(collection_name)
    except HTTPException as e:
        return {"answer": "Vui lòng upload tài liệu trước khi đặt câu hỏi.", "session_id": req.session_id, "latency": 0}
    prev_pairs = get_chat_history_pairs(req.session_id)[-REWRITE_HISTORY_M:]
    prev_chats = [
        {"is_user": "1", "message": pair["question"]} for pair in prev_pairs
    ] + [
        {"is_user": "0", "message": pair["answer"]} for pair in prev_pairs
    ]
    logger.info(f"[CHAT] Prev chats: {prev_chats}")
    full_question = rewrite_query_with_history(req.question, prev_chats)
    logger.info(f"[CHAT] Full question after rewrite: {full_question}")
    try:
        docs = retriever.invoke(full_question)
        logger.info(f"[CHAT] Retrieved {len(docs)} documents")
        for i, doc in enumerate(docs):
            logger.info(f"[CHAT] Doc {i}: content_length={len(doc.page_content)}, metadata={doc.metadata}")
        valid_docs = [doc for doc in docs if doc.page_content.strip()]
        logger.info(f"[CHAT] Valid docs after filtering: {len(valid_docs)}")
    except Exception as e:
        logger.error(f"[CHAT] Retriever error: {e}")
        valid_docs = []
    if not valid_docs:
        logger.warning("[CHAT] No valid documents found")
        context = ""
    else:
        context = "\n".join([doc.page_content for doc in valid_docs])
    logger.info(f"[CHAT] Context length: {len(context)}")
    if not context.strip():
        answer_prompt = f"""Câu hỏi: {full_question}

Không có tài liệu nào liên quan được tìm thấy trong cơ sở dữ liệu. 
Hãy trả lời dựa trên kiến thức chung của bạn một cách ngắn gọn (tối đa 3 câu).

Trả lời:"""
    else:
        answer_prompt = f"""Tài liệu tham khảo: {context}

Câu hỏi: {full_question}

Hãy trả lời câu hỏi dựa trên tài liệu tham khảo trên. Nếu tài liệu không chứa thông tin cần thiết, hãy nói rõ điều đó.

Trả lời:"""
    logger.info(f"[CHAT] Answer prompt: {answer_prompt}")
    # cached_answer = get_prompt_cache(answer_prompt)
    stats["num_chats"] += 1
    chat_count_key = f"chat:{req.session_id}:count"
    chat_count = redis_client.incr(chat_count_key)
    stats["cache_miss"] += 1
    from .rag_pipeline import llm
    stats["llm_calls"] += 1
    try:
        answer_raw = llm.invoke(answer_prompt)
        answer = get_llm_text(answer_raw)
        logger.info(f"[CHAT] LLM answer: {answer}")
    except Exception as e:
        logger.error(f"[CHAT] LLM error: {e}")
        answer = "Không thể trả lời câu hỏi này."

    chat_id = save_chat_pair(req.session_id, req.question, answer)  # , metrics)
    latency = time.time() - start
    stats["total_latency"] += latency
    chat_history = get_chat_history_pairs(req.session_id)
    if len(chat_history) >= SUMMARY_EVERY_N:
        chat_text = "\n".join([
            f"User: {pair['question']}\nBot: {pair['answer']}" for pair in chat_history
        ])
        summary_prompt = f"Tóm tắt ngắn gọn đoạn hội thoại sau (dưới 3 câu):\n{chat_text}"
        logger.info(f"[SUMMARY] Prompt: {summary_prompt}")

        try:
            from .rag_pipeline import llm
            summary_raw = llm.invoke(summary_prompt)
            summary_text = get_llm_text(summary_raw)
            logger.info(f"[SUMMARY] LLM output: {summary_text}")
            # set_prompt_cache(summary_prompt, summary_text)
        except Exception as e:
            logger.error(f"[SUMMARY] LLM error: {e}")
            summary_text = "Không thể tóm tắt."
        delete_chat_history(req.session_id)
        save_chat_pair(req.session_id, "Tóm tắt hội thoại", summary_text)
        logger.info(f"[SUMMARY] Chat history reset, only summary kept.")
    return {"answer": answer, 
            "latency": latency, "session_id": req.session_id, 
            "chat_id": chat_id
            }  # , "metrics": metrics

@app.post("/batch_query")
async def batch_query(req: BatchQueryRequest):
    """Batch query để tối ưu IO cho nhiều câu hỏi cùng lúc"""
    start = time.time()
    
    # Tạo session mới nếu chưa có
    if not req.session_id or not is_valid_session(req.session_id):
        req.session_id = create_session()
    
    # Thực hiện batch vector search
    try:
        batch_results = await batch_vector_search(req.queries)
        
        # Xử lý kết quả và tạo câu trả lời
        answers = []
        for i, (query, search_result) in enumerate(zip(req.queries, batch_results)):
            # Lưu câu hỏi
            save_chat(req.session_id, query, 1)
            
            # Tạo context từ search results
            context = "\n".join([result.payload.get("text", "") for result in search_result])
            
            # Gọi LLM để trả lời
            prompt = f"Context: {context}\nQuestion: {query}\nAnswer:"
            try:
                answer = llm.invoke(prompt)
            except Exception:
                answer = "Không thể trả lời câu hỏi này."
            
            answers.append(answer)
            
            # Lưu câu trả lời
            save_chat(req.session_id, answer, 0)
        
        latency = time.time() - start
        stats["num_chats"] += len(req.queries)
        stats["llm_calls"] += len(req.queries)
        stats["total_latency"] += latency
        
        return {
            "answers": answers, 
            "latency": latency, 
            "session_id": req.session_id,
            "batch_size": len(req.queries)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch query failed: {str(e)}")

@app.post("/upload_doc")
async def upload_doc(
    session_id: str = Form(...), 
    files: list[UploadFile] = File(...)
):
    start = time.time()
    if not is_valid_session(session_id):
        raise HTTPException(status_code=400, detail="Session không hợp lệ. Hãy tạo session trước khi upload file.")
    collection_name = get_session_collection(session_id)
    doc_paths = []
    document_ids = []
    file_infos = []
    for file in files:
        file_start = time.time()
        document_id = str(uuid.uuid4())
        content = await file.read()
        size_mb = round(len(content) / (1024 * 1024), 2)
        with tempfile.NamedTemporaryFile(delete=False, suffix="_" + file.filename) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        doc_paths.append(tmp_path)
        document_ids.append(document_id)
        add_document_to_session(session_id, document_id, file.filename, size_mb)
        file_infos.append({
            "filename": file.filename,
            "size_mb": size_mb,
            "upload_time": round(time.time() - file_start, 3)
        })
    try:
        retriever = load_and_setup_rag(doc_paths, collection_name, document_ids)
    except Exception as e:
        return HTTPException(status_code=500, detail=f"Upload thất bại: {e}")
    latency = round(time.time() - start, 3)
    return {
        "success": True,
        "files": file_infos,
        "total_files": len(files),
        "total_latency": latency
    }

@app.get("/list_docs")
def list_docs(session_id: str):
    start = time.time()
    if not is_valid_session(session_id):
        raise HTTPException(status_code=400, detail="Session không hợp lệ.")
    docs = get_documents_of_session(session_id)
    if not docs:
        logger.warning(f"[LIST_DOCS] No documents found for session {session_id}")
        return {"documents": [], "latency": round(time.time() - start, 3)}
    latency = time.time() - start
    return {"documents": docs, "latency": latency}

@app.delete("/delete_doc")
def delete_doc(session_id: str, document_id: str):
    start = time.time()
    if not is_valid_session(session_id):
        raise HTTPException(status_code=400, detail="Session không hợp lệ.")
    collection_name = get_session_collection(session_id)
    # Xóa vector trong Qdrant
    from .rag_pipeline import delete_document_vectors
    delete_document_vectors(collection_name, document_id)
    # Xóa metadata
    remove_document_from_session(session_id, document_id)
    latency = time.time() - start
    return {"success": True, "deleted": document_id, "latency": latency}

@app.get("/history")
def history(session_id: str):
    start = time.time()
    if not is_valid_session(session_id):
        return {"history": [], "latency": 0}
    chats = get_chat_history_pairs(session_id)
    latency = time.time() - start
    return {"history": chats, "latency": latency}

@app.delete("/history")
def delete_history(session_id: str):
    start = time.time() - start
    if not is_valid_session(session_id):
        raise HTTPException(status_code=400, detail="Session không hợp lệ.")
    delete_chat_history(session_id)
    delete_summary_for_session(session_id)
    # Có thể xóa cache liên quan nếu cần
    latency = time.time() - start
    return {"success": True, "deleted_history": session_id, "latency": latency}

@app.get("/summary")
def summary(session_id: str):
    start = time.time()
    if not is_valid_session(session_id):
        return {"summary": "Session không hợp lệ.", "latency": 0}
    
    # Lấy summary từ Redis
    summary_key = f"summary:{session_id}"
    cached_summary = redis_client.get(summary_key)
    if cached_summary:
        latency = time.time() - start
        return {"summary": cached_summary.decode(), "latency": latency}

    chats = get_chat_history_pairs(session_id)
    if not chats:
        latency = time.time() - start
        return {"summary": "Chưa có lịch sử chat.", "latency": latency}
    
    # Lấy nội dung chat gần nhất
    chat_text = "\n".join([
        f"User: {pair['question']}\nBot: {pair['answer']}" for pair in chats
    ])
    
    # Tóm tắt bằng Gemini
    prompt = f"Tóm tắt ngắn gọn đoạn hội thoại sau (dưới 3 câu):\n{chat_text}"
    try:
        from .rag_pipeline import llm
        summary_raw = llm.invoke(prompt)
        summary_text = get_llm_text(summary_raw)
        redis_client.set(summary_key, summary_text)
    except Exception:
        summary_text = "Không thể tóm tắt."
    latency = time.time() - start
    return {"summary": summary_text, "latency": latency}