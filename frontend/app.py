import streamlit as st
import requests
import redis
import json
from datetime import datetime
import time
import os
from typing import List, Dict, Any

# Configuration
API_BASE_URL = "http://localhost:8000"  # Adjust this to your FastAPI server
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Initialize Redis client
@st.cache_resource
def init_redis():
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)

redis_client = init_redis()

# Load custom CSS
def load_css():
    try:
        with open("/Users/AIO2025/Project/Project 1.1/rag_app/frontend/style.css", "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        # Fallback CSS if file not found
        st.markdown("""
        <style>
        .sidebar-header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 1rem; margin: -1rem -1rem 1rem -1rem; }
        .chat-message { padding: 1rem; margin: 0.5rem 0; border-radius: 10px; }
        .user-message { background: #e3f2fd; margin-left: 2rem; }
        .bot-message { background: #f5f5f5; margin-right: 2rem; }
        .glass-effect { background: rgba(255, 255, 255, 0.1); backdrop-filter: blur(10px); border-radius: 15px; padding: 1rem; }
        </style>
        """, unsafe_allow_html=True)

# Enhanced session management functions
def sync_sessions_from_backend() -> List[Dict]:
    """Sync sessions from backend Redis structure with enhanced error handling"""
    try:
        sessions = []
        session_ids = set()
        
        # Safe function to get set members
        def safe_smembers(key):
            try:
                return redis_client.smembers(key) or set()
            except Exception:
                return set()
        
        # Safe function to get list items
        def safe_lrange(key):
            try:
                return redis_client.lrange(key, 0, -1) or []
            except Exception:
                return []
        
        # Safe function to get keys with pattern
        def safe_keys(pattern):
            try:
                return redis_client.keys(pattern) or []
            except Exception:
                return []
        
        # Check streamlit:sessions (set format)
        streamlit_sessions = safe_smembers("streamlit:sessions")
        if streamlit_sessions:
            session_ids.update(str(sid) for sid in streamlit_sessions)
        
        # Check streamlit:sessions_list (list format) - if backend uses this
        backend_sessions = safe_lrange("streamlit:sessions_list")
        if backend_sessions:
            session_ids.update(str(sid) for sid in backend_sessions)
        
        # Also check for direct session keys pattern
        all_keys = safe_keys("session:*")
        for key in all_keys:
            try:
                key_str = str(key)
                if not key_str.endswith(":documents") and not key_str.endswith(":collection") and not key_str.endswith(":meta"):
                    session_id = key_str.replace("session:", "")
                    if session_id:  # Make sure session_id is not empty
                        session_ids.add(session_id)
            except Exception:
                continue
        
        # Process each session with individual error handling
        for session_id in session_ids:
            try:
                if session_id:  # Ensure session_id is not empty
                    session_info = get_session_info(session_id)
                    if session_info and session_info.get("id"):
                        sessions.append(session_info)
            except Exception as e:
                st.warning(f"Error processing session {session_id}: {e}")
                continue
        
        return sorted(sessions, key=lambda x: x.get("created_at", ""), reverse=True)
        
    except Exception as e:
        st.error(f"Error syncing sessions from backend: {e}")
        return []

def get_session_info(session_id: str) -> Dict:
    """Get comprehensive session information from various Redis keys with enhanced error handling"""
    try:
        session_info = {}
        # Ensure we have required fields with safe defaults
        if not session_info.get("id"):
            session_info["id"] = str(session_id)
        
        if not session_info.get("name"):
            session_info["name"] = f"Session {str(session_id)[:8]}..."
        
        if not session_info.get("created_at"):
            session_info["created_at"] = datetime.now().isoformat()
        
        # Add document count and other metadata with error handling
        try:
            doc_count = get_session_document_count(session_id)
            session_info["document_count"] = doc_count
        except Exception as e:
            st.warning(f"Could not get document count for session {session_id}: {e}")
            session_info["document_count"] = 0
        
        # Check if session is active (has recent activity)
        session_info["status"] = "active" if session_info.get("document_count", 0) > 0 else "empty"
        
        return session_info
        
    except Exception as e:
        st.error(f"Error getting session info for {session_id}: {e}")
        # Return minimal session info instead of None
        return {
            "id": str(session_id),
            "name": f"Session {str(session_id)[:8]}...",
            "created_at": datetime.now().isoformat(),
            "document_count": 0,
            "status": "error"
        }

def get_session_document_count(session_id: str) -> int:
    """Get document count for a session with enhanced error handling"""
    try:
        # Check if the key exists and what type it is
        key = f"session:{session_id}:documents"
        key_type = redis_client.type(key)
        
        if key_type == "set":
            # Check documents from backend structure (set format)
            doc_ids = redis_client.smembers(key)
            return len(doc_ids) if doc_ids else 0
        elif key_type == "list":
            # Handle list format
            doc_ids = redis_client.lrange(key, 0, -1)
            return len(doc_ids) if doc_ids else 0
        elif key_type == "hash":
            # Handle hash format
            doc_data = redis_client.hgetall(key)
            return len(doc_data) if doc_data else 0
        else:
            # Key doesn't exist or unknown type
            return 0
            
    except Exception as e:
        st.warning(f"Error getting document count for session {session_id}: {e}")
        return 0

def create_new_session() -> str:
    """Create a new session via API and ensure it's cached properly"""
    try:
        response = requests.post(f"{API_BASE_URL}/session")
        if response.status_code == 200:
            session_id = response.json()["session_id"]
            # Cache session in both formats for compatibility
            cache_session_info(session_id)
            return session_id
        else:
            st.error("Failed to create new session")
            return None
    except Exception as e:
        st.error(f"Error creating session: {e}")
        return None

def cache_session_info(session_id: str):
    """Cache session information in Redis with both formats and enhanced error handling"""
    try:
        session_id_str = str(session_id)
        session_info = {
            "id": session_id_str,
            "session_id": session_id_str,  # For backend compatibility
            "created_at": datetime.now().isoformat(),
            "name": f"Session {session_id_str[:8]}...",
            "status": "active"
        }
        
        # Store in streamlit format with error handling
        try:
            redis_client.hset(f"streamlit:session:{session_id_str}", mapping=session_info)
            redis_client.sadd("streamlit:sessions", session_id_str)
        except Exception as e:
            st.warning(f"Could not cache streamlit session info: {e}")
        
        # Also ensure backend format exists
        try:
            redis_client.hset(f"session:{session_id_str}", mapping=session_info)
        except Exception as e:
            st.warning(f"Could not cache backend session info: {e}")
        
        # Add to both possible session lists with error handling
        try:
            redis_client.sadd("streamlit:sessions", session_id_str)
        except Exception:
            pass
        
        try:
            redis_client.lpush("streamlit:sessions_list", session_id_str)
        except Exception:
            pass
            
    except Exception as e:
        st.error(f"Error caching session info for {session_id}: {e}")

def get_cached_sessions() -> List[Dict]:
    """Get all cached sessions with enhanced sync"""
    return sync_sessions_from_backend()

def get_session_documents(session_id: str) -> List[Dict]:
    """Get documents for a session with enhanced backend sync"""
    try:
        # First try API
        response = requests.get(f"{API_BASE_URL}/list_docs", params={"session_id": session_id})
        if response.status_code == 200:
            api_docs = response.json().get("documents", [])
            if api_docs:
                return api_docs
        
        # Fallback: get from Redis directly
        documents = []
        doc_ids = redis_client.smembers(f"session:{session_id}:documents")
        
        for doc_id in doc_ids:
            doc_meta = redis_client.hgetall(f"document:{doc_id}:meta")
            if doc_meta:
                documents.append({
                    "document_id": doc_id,
                    "filename": doc_meta.get("filename", f"Document {doc_id[:8]}..."),
                    "size": doc_meta.get("size", "Unknown"),
                    "created_at": doc_meta.get("created_at", "Recently"),
                    "status": "processed"
                })
        
        return documents
        
    except Exception as e:
        st.error(f"Error fetching documents: {e}")
        return []

def get_session_history(session_id: str) -> List[Dict]:
    """Get chat history for a session"""
    try:
        response = requests.get(f"{API_BASE_URL}/history", params={"session_id": session_id})
        if response.status_code == 200:
            return response.json().get("history", [])
        return []
    except Exception as e:
        st.error(f"Error fetching history: {e}")
        return []

def upload_documents(session_id: str, files) -> bool:
    """Upload documents to a session"""
    try:
        files_data = []
        for file in files:
            files_data.append(("files", (file.name, file.getvalue(), file.type)))
        
        data = {"session_id": session_id}
        response = requests.post(
            f"{API_BASE_URL}/upload_doc",
            data=data,
            files=files_data
        )
        
        if response.status_code == 200:
            # Refresh session info after upload
            time.sleep(1)  # Give backend time to process
            return True
        else:
            st.error(f"Upload failed: {response.text}")
            return False
    except Exception as e:
        st.error(f"Error uploading documents: {e}")
        return False

def send_chat_message(session_id: str, question: str) -> Dict:
    """Send a chat message"""
    try:
        response = requests.post(
            f"{API_BASE_URL}/chat",
            json={"question": question, "session_id": session_id}
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"Chat failed: {response.text}")
            return {"answer": "Sorry, there was an error processing your message."}
    except Exception as e:
        st.error(f"Error sending message: {e}")
        return {"answer": "Sorry, there was an error processing your message."}

def delete_session_history(session_id: str) -> bool:
    """Delete session history"""
    try:
        response = requests.delete(f"{API_BASE_URL}/history", params={"session_id": session_id})
        return response.status_code == 200
    except Exception as e:
        st.error(f"Error deleting history: {e}")
        return False

def delete_session_completely(session_id: str) -> bool:
    """Delete session completely from both frontend and backend"""
    try:
        # Remove from streamlit cache
        redis_client.srem("streamlit:sessions", session_id)
        redis_client.delete(f"streamlit:session:{session_id}")
        
        # Remove from backend lists
        try:
            redis_client.lrem("streamlit:sessions_list", 0, session_id)
        except:
            pass
        
        # Optionally call backend API to clean up session data
        try:
            requests.delete(f"{API_BASE_URL}/session/{session_id}")
        except:
            pass
            
        return True
    except Exception as e:
        st.error(f"Error deleting session: {e}")
        return False

# Enhanced refresh function
def refresh_session_data():
    """Manually refresh session data from backend"""
    st.session_state.sessions = sync_sessions_from_backend()
    if st.session_state.current_session:
        # Refresh current session info
        session_info = get_session_info(st.session_state.current_session)
        if not session_info:
            st.session_state.current_session = None

# Collapsible sidebar component with enhanced session display
def render_collapsible_sidebar():
    """Render the enhanced collapsible sidebar"""
    # Initialize sidebar state
    if "sidebar_collapsed" not in st.session_state:
        st.session_state.sidebar_collapsed = False
    
    # Toggle button in main area
    col1, col2, col3 = st.columns([1, 10, 1])
    with col1:
        if st.button("☰" if st.session_state.sidebar_collapsed else "✕", 
                     key="sidebar_toggle", 
                     help="Toggle Sidebar",
                     use_container_width=True):
            st.session_state.sidebar_collapsed = not st.session_state.sidebar_collapsed
            st.rerun()
    
    # Refresh button
    with col3:
        if st.button("🔄", key="refresh_sessions", help="Refresh Sessions", use_container_width=True):
            refresh_session_data()
            st.rerun()
    
    # Sidebar content (only show when not collapsed)
    if not st.session_state.sidebar_collapsed:
        with st.sidebar:
            st.markdown('<div class="sidebar-header">', unsafe_allow_html=True)
            st.title("🤖 RAG ")
            st.markdown('</div>', unsafe_allow_html=True)
            
            # Control buttons row
            col1, col2 = st.columns(2)
            with col1:
                if st.button("➕", key="new_session_btn", use_container_width=True):
                    with st.spinner("Creating new session..."):
                        new_session_id = create_new_session()
                        if new_session_id:
                            st.session_state.current_session = new_session_id
                            refresh_session_data()
                            st.rerun()
            
            with col2:
                if st.button("🔄", key="refresh_sidebar", use_container_width=True):
                    refresh_session_data()
                    st.rerun()
            
            st.markdown("---")
            
            # Enhanced session list
            st.markdown('<div class="session-list">', unsafe_allow_html=True)
            st.subheader("Các phiên làm việc hiện có")
            
            # Auto-refresh sessions on each render
            current_sessions = sync_sessions_from_backend()
            st.session_state.sessions = current_sessions
            
            if not current_sessions:
                st.info("Không có phiên làm việc nào. Hãy tạo phiên đầu tiên!")
            else:
                for session in current_sessions:
                    session_id = session["id"]
                    session_name = session.get("name", f"Session {session_id[:8]}...")
                    doc_count = session.get("document_count", 0)
                    status = session.get("status", "unknown")
                    
                    # Check if this is the current session
                    is_current = st.session_state.current_session == session_id
                    
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        if st.button(
                            f"📂 {session_name}",
                            key=f"session_{session_id}",
                            use_container_width=True,
                            help=f"Session ID: {session_id}\nDocuments: {doc_count}\nStatus: {status}",
                            type="primary" if is_current else "secondary"
                        ):
                            st.session_state.current_session = session_id
                            st.rerun()

            st.markdown('</div>', unsafe_allow_html=True)
            
            # Performance metrics
            st.markdown("---")
            st.markdown('<div class="performance-metrics">', unsafe_allow_html=True)
            st.markdown("### 📊 Thống kê")
            
            col1, col2 = st.columns(2)
            with col1:
                total_sessions = len(current_sessions)
                st.metric("Số phiên", total_sessions)
            # with col2:
            #     total_docs = sum(s.get("document_count", 0) for s in current_sessions)
            #     st.metric("Documents", total_docs)
            
            st.markdown('</div>', unsafe_allow_html=True)

# Main application
def main():
    st.set_page_config(
        page_title="RAG Chat Pro",
        page_icon="🚀",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Load CSS
    load_css()
    
    # Initialize session state
    if "current_session" not in st.session_state:
        st.session_state.current_session = None
    if "sessions" not in st.session_state:
        st.session_state.sessions = []
    if "chat_input_key" not in st.session_state:
        st.session_state.chat_input_key = 0
    if "typing_indicator" not in st.session_state:
        st.session_state.typing_indicator = False
    if "last_refresh" not in st.session_state:
        st.session_state.last_refresh = 0
    
    # Auto-refresh every 30 seconds
    current_time = time.time()
    if current_time - st.session_state.last_refresh > 30:
        refresh_session_data()
        st.session_state.last_refresh = current_time
    
    # Render collapsible sidebar
    render_collapsible_sidebar()
    
    # Main content area with dynamic width based on sidebar state
    main_class = "main-collapsed" if st.session_state.get("sidebar_collapsed", False) else "main-expanded"
    st.markdown(f'<div class="main-content {main_class}">', unsafe_allow_html=True)
    
    if st.session_state.current_session:
        session_id = st.session_state.current_session
        session_info = get_session_info(session_id)
        chat_history_1 = get_session_history(session_id)
        documents_1 = get_session_documents(session_id)
        
        if not session_info:
            st.error("Session not found! Please select another session.")
            st.session_state.current_session = None
            st.rerun()
        
        # Enhanced header with breadcrumb
        st.markdown(f'''
        <div class="main-header gradient-bg">
            <div class="header-content">
                <div class="breadcrumb">
                    <span class="breadcrumb-item">🏠 Home</span>
                    <span class="breadcrumb-separator">></span>
                    <span class="breadcrumb-item active">💬 {session_info.get('name', 'Chat Session')}</span>
                </div>
                <h1 class="header-title">Session: {session_id[:12]}...</h1>
                <div class="header-stats">
                    <span class="stat-item">🔗 {session_info.get('status', 'active').title()}</span>
                    <span class="stat-item">💬 {len(chat_history_1)}</span>
                    <span class="stat-item">📄 {len(documents_1)}</span>
                </div>
            </div>
        </div>
        ''', unsafe_allow_html=True)
        
        # Enhanced tabs with icons
        tab1, tab2, tab3, tab4 = st.tabs(["💬 Hỏi đáp", "📄 Tài liệu", "📊 Phân tích", "⚙️ Cài đặt"])
        
        with tab1:      
            # Chat stats bar with real-time data
            chat_history = get_session_history(session_id)
            documents = get_session_documents(session_id)
            
            # Chat history with enhanced rendering
            if chat_history:
                for chat in chat_history:
                    with st.chat_message("user"):
                        st.write(chat["question"])
                    with st.chat_message("assistant"):
                        st.write(chat["answer"])
                        
                st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.markdown('''
                <div class="empty-state">
                    <div class="empty-icon">💭</div>
                    <h3>Bắt đầu cuộc trò chuyện</h3>
                    <p>Tải lên một vài tệp tin trước và bắt đầu!</p>
                </div>
                ''', unsafe_allow_html=True)
            
            # Enhanced chat input with suggestions
            st.markdown('<div class="chat-input-enhanced">', unsafe_allow_html=True)
            
            # Quick suggestions
            if not chat_history and documents:
                st.markdown('<div class="suggestions">', unsafe_allow_html=True)
                st.markdown("**💡 Gợi ý:**")
                
                suggestion_cols = st.columns(2)
                suggestions = [
                    "Tài liệu này là về vấn đề gì?",
                    "Tóm tắt tài liệu và liệt kê các điểm chính",
                ]
                
                for i, suggestion in enumerate(suggestions):
                    with suggestion_cols[i]:
                        if st.button(f"💬 {suggestion}", key=f"suggestion_{i}", use_container_width=True):
                            st.session_state[f"chat_input_{st.session_state.chat_input_key}"] = suggestion
                            st.rerun()
                
                st.markdown('</div>', unsafe_allow_html=True)
            
            # Main input area
            col1, col2 = st.columns([6, 1])
            
            with col1:
                user_input = st.text_input(
                    "Nhập câu hỏi của bạn...",
                    key=f"chat_input_{st.session_state.chat_input_key}",
                    placeholder="Hỏi gì đó 🔍",
                    label_visibility="collapsed",
                    disabled=len(documents) == 0
                )
            
            with col2:
                send_button = st.button(
                    "🚀", 
                    key="send_btn", 
                    use_container_width=True, 
                    help="Send Message",
                    disabled=len(documents) == 0
                )
            
            if len(documents) == 0:
                st.info("📄 Tải lên tệp tin trước!")
            
            # Handle message sending with typing indicator
            if send_button and user_input.strip() and len(documents) > 0:
                # Show typing indicator
                st.markdown('''
                <div class="typing-indicator">
                    <div class="typing-dots">
                        <span></span>
                        <span></span>
                        <span></span>
                    </div>
                    <span class="typing-text">Trợ lý đang soạn...</span>
                </div>
                ''', unsafe_allow_html=True)
                
                with st.spinner("Đang xử lý..."):
                    response = send_chat_message(session_id, user_input.strip())
                    if response:
                        st.session_state.chat_input_key += 1
                        st.rerun()
            
            # Action buttons
            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                if st.button("🔄 Regenerate", key="regenerate", help="Regenerate last response"):
                    st.info("Coming soon!")
            
            with col2:
                if st.button("📋 Export Chat", key="export", help="Export conversation"):
                    if chat_history:
                        # Create exportable format
                        export_data = {
                            "session_id": session_id,
                            "exported_at": datetime.now().isoformat(),
                            "messages": chat_history
                        }
                        st.download_button(
                            "📥 Download JSON",
                            data=json.dumps(export_data, indent=2),
                            file_name=f"chat_export_{session_id[:8]}.json",
                            mime="application/json"
                        )
                    else:
                        st.info("No chat history to export!")
            
            st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        with tab2:  
            # Document upload with drag & drop
            st.markdown('''
            <div class="upload-section">
                <h3>📤 Tải lên tập tin</h3>
                <p>Kéo và thả file hoặc nhấn Browse files</p>
            </div>
            ''', unsafe_allow_html=True)
            
            uploaded_files = st.file_uploader(
                "Choose files",
                accept_multiple_files=True,
                type=['pdf', 'txt', 'docx', 'md', 'csv'],
                key="file_uploader",
                help="Supports PDF, TXT, DOCX, MD, and CSV files"
            )
            
            if uploaded_files:
                # File preview
                st.markdown("### 📋 Xác nhận tải lên tập tin")
                for file in uploaded_files:
                    col1, col2, col3 = st.columns([3, 2, 1])
                    with col1:
                        st.text(f"📄 {file.name}")
                    with col2:
                        st.text(f"{file.size / 1024:.1f} KB")
                    with col3:
                        st.text(file.type.split('/')[-1].upper())
                
                if st.button("🚀 Tải lên toàn bộ", key="upload_btn", use_container_width=True):
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    for i, file in enumerate(uploaded_files):
                        status_text.text(f"Đang tải {file.name}...")
                        progress_bar.progress((i + 1) / len(uploaded_files))
                        time.sleep(0.1)  # Simulate processing time
                    
                    with st.spinner("Đang xử lý ..."):
                        success = upload_documents(session_id, uploaded_files)
                        if success:
                            st.success(f"✅ Tải lên thành công {len(uploaded_files)} tập tin!")
                            # Refresh session data to show new documents
                            refresh_session_data()
                            time.sleep(1)
                            st.rerun()
                    
                    progress_bar.empty()
                    status_text.empty()
            
            st.markdown("---")
            
            # Enhanced document list with real-time refresh
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown("### 📚 Danh sách tập tin")
            with col2:
                if st.button("🔄", key="refresh_docs", help="Refresh document list"):
                    st.rerun()
            
            documents = get_session_documents(session_id)
            
            if documents:
                for idx, doc in enumerate(documents):
                    st.markdown(f'''
                    <div class="document-card">
                        <div class="doc-header">
                            <span class="doc-icon">📄</span>
                            <span class="doc-name">{doc.get("filename", f"Document {idx + 1}")}</span>
                            <span class="doc-status">✅ {doc.get("status", "")}</span>
                        </div>
                        <div class="doc-details">
                            <span class="doc-size">Kích cỡ: {doc.get('size_mb', 'Unknown')} MB</span>
                        </div>
                    </div>
                    ''', unsafe_allow_html=True)
            else:
                st.markdown('''
                <div class="empty-state">
                    <div class="empty-icon">📁</div>
                    <h3>Chưa có tập tin nào được tải lên</h3>
                    <p>Tải lên tập tin đầu tiên để bắt đầu!</p>
                </div>
                ''', unsafe_allow_html=True)
            
            st.markdown('</div>', unsafe_allow_html=True)
        
        with tab3:
            # Analytics dashboard with real data
            st.markdown("### 📊 Thống kê phiên làm việc")
            
            # Real analytics data
            col1, col2, col3 = st.columns(3)
            
            with col1:
                total_messages = len(chat_history)
                st.markdown(f'''
                <div class="metric-card">
                    <div class="metric-icon">💬</div>
                    <div class="metric-value">{total_messages}</div>
                    <div class="metric-label">Tổng số truy vấn</div>
                    <div class="metric-label">tại phiên này</div>
                </div>
                ''', unsafe_allow_html=True)
            
            with col2:
                total_docs = len(documents)
                st.markdown(f'''
                <div class="metric-card">
                    <div class="metric-icon">📄</div>
                    <div class="metric-value">{total_docs}</div>
                    <div class="metric-label">Tài liệu</div>
                    <div class="metric-label">được tải lên</div>
                </div>
                ''', unsafe_allow_html=True)
            
            with col3:
                session_status = "Active" if total_docs > 0 else "Ready"
                st.markdown(f'''
                <div class="metric-card">
                    <div class="metric-icon">🎯</div>
                    <div class="metric-value">{session_status}</div>
                    <div class="metric-label">Trạng thái phiên</div>
                    <div class="metric-label">thời gian thực</div>
                </div>
                ''', unsafe_allow_html=True)
            
            # Chat history analysis
            if chat_history:
                st.markdown("---")
                st.markdown("### 📈 Thống kê truy vấn")
                
                # Simple metrics
                avg_question_length = sum(len(chat.get("question", "")) for chat in chat_history) / len(chat_history)
                avg_answer_length = sum(len(chat.get("answer", "")) for chat in chat_history) / len(chat_history)
                
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Độ dài trung bình truy vấn", f"{avg_question_length:.0f} ký tự")
                with col2:
                    st.metric("Độ dài trung bình phản hồi", f"{avg_answer_length:.0f} ký tự")
            
            st.markdown('</div>', unsafe_allow_html=True)
        
        with tab4:
            # Settings panel
            st.markdown("### ⚙️ Cài đặt phiên")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### 🔧 Thông tin phiên")
                st.text_input("ID", value=session_id, disabled=True)
                st.text_input("Tên", value=session_info.get("name", ""), key="session_name")
                st.selectbox("Trạng thái", ["hoạt động", "gián đoạn", "lưu trữ"], 
                           index=0 if session_info.get("status") == "active" else 1)
            
            st.markdown("#### 🔄 Quản lý phiên")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if st.button("💾 Lưu cài đặt", key="save_settings", use_container_width=True):
                    # Update session name if changed
                    new_name = st.session_state.get("session_name", "")
                    if new_name and new_name != session_info.get("name", ""):
                        session_info["name"] = new_name
                        redis_client.hset(f"streamlit:session:{session_id}", "name", new_name)
                        redis_client.hset(f"session:{session_id}", "name", new_name)
                        refresh_session_data()
                    st.success("Settings saved successfully!")
                    time.sleep(1)
                    st.rerun()
            
            with col2:
                if st.button("🔄 Khôi phục", key="reset_session", use_container_width=True):
                    if delete_session_history(session_id):
                        st.success("Session reset successfully!")
                        time.sleep(1)
                        st.rerun()
            
            with col3:
                if st.button("📤 Export Session", key="export_session", use_container_width=True):
                    # Export complete session data
                    export_data = {
                        "session_info": session_info,
                        "documents": documents,
                        "chat_history": chat_history,
                        "exported_at": datetime.now().isoformat()
                    }
                    st.download_button(
                        "📥 Download Session",
                        data=json.dumps(export_data, indent=2),
                        file_name=f"session_export_{session_id[:8]}.json",
                        mime="application/json"
                    )
            
            # Danger zone
            st.markdown("---")
            st.markdown("#### ⚠️ Cảnh Báo")
            st.warning("Thao tác này không thể thu hồi")
            
            if st.button("🗑️ Xoá phiên", key="delete_session_final", type="secondary"):
                if st.button("⚠️ Xác nhận", key="confirm_delete", type="secondary"):
                    with st.spinner("Đang xoá phiên..."):
                        if delete_session_completely(session_id):
                            st.success("Xoá phiên thành công!")
                            st.session_state.current_session = None
                            refresh_session_data()
                            time.sleep(2)
                            st.rerun()
            
            st.markdown('</div>', unsafe_allow_html=True)
    
    else:
        # Enhanced welcome screen with session discovery
        st.markdown('''
        <div class="welcome-container-enhanced">
            <div class="welcome-hero">
                <div class="hero-icon">🚀</div>
                <h1 class="hero-title">Demo RAG của Hnam</h1>
                <p class="hero-subtitle">Trải nghiệm hỏi đáp với văn bản</p>
            </div>
        ''', unsafe_allow_html=True)
        
        # Show available sessions if any exist
        available_sessions = sync_sessions_from_backend()
        if available_sessions:
            st.markdown('''
            <div class="session-discovery">
                <h2>🔍 Các phiên làm việc đã có sẵn</h2>
                <p>Đã tìm thấy một số phiên làm việc đang dở. Chọn một ở thanh bên và tiếp tục thôi nào</p>
            </div>
            ''', unsafe_allow_html=True)
        st.markdown('''
            <div class="features-grid">
                <div class="feature-card">
                    <h3>Tốc độ cao</h3>
                    <p>Hệ thống RAG tối ưu với Google Gemini Flash 2.5</p>
                </div>
                <div class="feature-card">
                    <h3>Rewrite Query & Follow up</h3>
                    <p>Nắm bắt nội dung cuộc trò chuyện với kỹ thuật Query Rewritting, tăng tốc truy vấn</p>
                </div>
                <div class="feature-card">
                    <h3>An toàn & Riêng tư</h3>
                    <p>Các phiên làm việc độc lập, cá nhân hoá cho một người dùng</p>
                </div>
                <div class="feature-card">
                    <h3>Cập nhật lịch sử trò chuyện</h3>
                    <p>Tự động tóm tắt hội thoại, giảm quá tải bộ nhớ</p>
                </div>
                <div class="feature-card">
                    <h3>Tối ưu hiệu năng</h3>
                    <p>Data caching với Redis, tải dữ liệu frontend và backend đều rất nhanh</p>
                </div>
            </div>
            <div class="cta-section">
                <h2>Sẵn sàng chưa?</h2>
                <p>Tạo phiên làm việc mới và bắt đầu thôi</p>
            </div>
        </div>
        ''', unsafe_allow_html=True)
    
    st.markdown('</div>', unsafe_allow_html=True)

    # Footer with connection status
    st.markdown("---")
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.text(f"🕒 Cập nhật lần cuối: {current_time}")
    with col3:
        if st.button("🔄 Force Refresh", key="force_refresh", help="Force refresh all data"):
            refresh_session_data()
            st.rerun()

if __name__ == "__main__":
    main()