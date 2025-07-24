import redis
import json
import uuid
from datetime import datetime
from .config import REDIS_URL, REDIS_DB, SESSION_EXPIRE_HOURS

# Redis client
redis_client = redis.from_url(REDIS_URL, db=REDIS_DB, decode_responses=True)

def create_session():
    """Tạo session mới (đơn giản, không cần auth)"""
    session_id = str(uuid.uuid4())
    redis_client.setex(f"session:{session_id}", SESSION_EXPIRE_HOURS * 3600, "active")
    return session_id

def is_valid_session(session_id):
    """Kiểm tra session có hợp lệ không"""
    return redis_client.exists(f"session:{session_id}")

def save_chat(session_id, message, is_user):
    """Lưu chat vào Redis"""
    chat_id = str(uuid.uuid4())
    chat_data = {
        "id": chat_id,
        "session_id": session_id,
        "message": message,
        "is_user": is_user,
        "created_at": datetime.now().isoformat()
    }
    # Lưu chat
    redis_client.hset(f"chat:{chat_id}", mapping=chat_data)
    # Thêm vào list chat của session
    redis_client.lpush(f"session_chats:{session_id}", chat_id)
    # Set expire cho session
    redis_client.expire(f"session:{session_id}", SESSION_EXPIRE_HOURS * 3600)
    redis_client.expire(f"session_chats:{session_id}", SESSION_EXPIRE_HOURS * 3600)
    return chat_data

def get_chat_history(session_id, limit=30):
    """Lấy lịch sử chat của session"""
    if not is_valid_session(session_id):
        return []
    
    chat_ids = redis_client.lrange(f"session_chats:{session_id}", 0, limit-1)
    chats = []
    for chat_id in chat_ids:
        chat_data = redis_client.hgetall(f"chat:{chat_id}")
        if chat_data:
            chats.append(chat_data)
    return chats

def get_cache(prompt_hash):
    """Lấy cache từ Redis"""
    cache_data = redis_client.get(f"cache:{prompt_hash}")
    if cache_data:
        return json.loads(cache_data)
    return None

def set_cache(prompt_hash, prompt, context, response):
    """Lưu cache vào Redis (expire sau 24h)"""
    cache_data = {
        "prompt": prompt,
        "context": context,
        "response": response,
        "created_at": datetime.now().isoformat()
    }
    redis_client.setex(f"cache:{prompt_hash}", 24*3600, json.dumps(cache_data))
    return cache_data

def save_evaluation(chat_id, score, comment=""):
    """Lưu đánh giá vào Redis"""
    eval_id = str(uuid.uuid4())
    eval_data = {
        "id": eval_id,
        "chat_id": chat_id,
        "score": score,
        "comment": comment,
        "created_at": datetime.now().isoformat()
    }
    redis_client.hset(f"eval:{eval_id}", mapping=eval_data)
    # Thêm vào list evaluation
    redis_client.lpush("evaluations", eval_id)
    return eval_data

def get_eval_stats():
    """Lấy thống kê đánh giá"""
    eval_ids = redis_client.lrange("evaluations", 0, -1)
    if not eval_ids:
        return {"num_eval": 0, "avg_score": 0}
    
    total_score = 0
    valid_evals = 0
    for eval_id in eval_ids:
        eval_data = redis_client.hgetall(f"eval:{eval_id}")
        if eval_data and eval_data.get("score"):
            total_score += int(eval_data["score"])
            valid_evals += 1
    
    avg_score = total_score / valid_evals if valid_evals > 0 else 0
    return {"num_eval": valid_evals, "avg_score": avg_score}

def delete_chat_history(session_id):
    key = f"chat:{session_id}:history"
    if redis_client.exists(key):
        redis_client.delete(key)

def delete_cache_for_session(session_id):
    # Xóa cache theo session (nếu cache key có lưu session_id)
    # Nếu cache key không lưu session_id, có thể bỏ qua hoặc implement thêm nếu cần
    pass

def delete_summary_for_session(session_id):
    key = f"summary:{session_id}"
    if redis_client.exists(key):
        redis_client.delete(key)

def cleanup_old_chats_from_session(session_id, num_chats_to_remove):
    """Xóa các chat cũ đã được summarize từ Redis"""
    try:
        # Lấy list chat IDs của session
        session_chat_key = f"session_chats:{session_id}"
        
        # Lấy các chat_id cũ nhất (từ cuối list vì lpush thêm vào đầu)
        old_chat_ids = redis_client.lrange(session_chat_key, -num_chats_to_remove, -1)
        
        # Xóa từng chat record
        deleted_count = 0
        for chat_id in old_chat_ids:
            if redis_client.delete(f"chat:{chat_id}"):
                deleted_count += 1
        
        # Xóa các chat_id khỏi session list (xóa từ cuối)
        for _ in range(min(num_chats_to_remove, len(old_chat_ids))):
            redis_client.rpop(session_chat_key)
            
        return deleted_count
        
    except Exception as e:
        print(f"[CLEANUP] Error cleaning up old chats: {e}")
        return 0