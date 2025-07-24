# API Test Guide for RAG Backend

You can use `curl`, `Postman` or `SwaggerUI` for API testing.

---

## 1. `/session`
**Purpose:** Create a new session

### Request
- **Method:** POST
- **Endpoint:** `/session`

### curl Example
```bash
curl -X POST http://localhost:8000/session
```

### Expected Response
```json
{"session_id": "<SESSION_ID>"}
```

---

## 2. `/upload_doc`
**Purpose:** Upload one or more files for a specific session

### Request
- **Method:** POST
- **Endpoint:** `/upload_doc`
- **Content-Type:** `multipart/form-data`
- **Body:**
    - Field `session_id` (type: text)
    - Field `files` (type: file, **multiple files**)

### curl Example (for files)
```bash
curl -X POST http://localhost:8000/upload_doc \
  -F "session_id=<SESSION_ID>" \
  -F "files=@file1.pdf" \
  -F "files=@file2.pdf"
```

### Postman Example
- Method POST, URL: `http://localhost:8000/upload_doc`
- Tab Body > form-data:
    - key: `session_id` (type: Text)
    - key: `files` (type: File)

### Expected Response
```json
{
  "success": true,
  "files": [
    {
      "filename": "ankhe.pdf",
      "size_mb": 1.84,
      "upload_time": 0.004
    }
  ],
  "total_files": 1,
  "total_latency": 4.129
}
```

**Note:** Must create a session before uploading files

---

## 3. `/list_docs`
**Purpose:** See a list of session files

### Request
- **Method:** GET
- **Endpoint:** `/list_docs?session_id=<SESSION_ID>`

### curl Example
```bash
curl "http://localhost:8000/list_docs?session_id=<SESSION_ID>"
```

### Expected Response
```json
{
  "documents": [
    {
      "filename": "ankhe.pdf",
      "session_id": "<SESSION_ID>",
      "size_mb": "1.84",
      "document_id": "<DOC_ID"
    }
  ],
  "latency": 0.0015420913696289062
}
```

---

## 4. `/delete_doc`
**Purpose:** Delete files from session, automatically remove them from Redis, Qdrant

### Request
- **Method:** DELETE
- **Endpoint:** `/delete_doc?session_id=<SESSION_ID>&document_id=<DOCUMENT_ID>`

### curl Example
```bash
curl -X DELETE "http://localhost:8000/delete_doc?session_id=<SESSION_ID>&document_id=<DOCUMENT_ID>"
```

### Expected Response
```json
{
  "success": true, 
  "deleted": "<DOCUMENT_ID>"
}
```

---

## 5. `/chat`
**Purpose:** Main RAG pipeline API

### Request
- **Method:** POST
- **Endpoint:** `/chat`
- **Body (JSON):**
```json
{
  "question": "Tóm tắt truyện Tấm Cám?",
  "session_id": "<SESSION_ID>"
}
```

### curl Example
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Tóm tắt truyện Tấm Cám?", "session_id": "<SESSION_ID>"}'
```

### Expected Response
```json
{
  "answer": "<RESPONSE>",
  "latency": 17.245036125183105,
  "session_id": "<SESSION_ID>",
  "chat_id": "<CHAT_ID>"
}
```

**Note:**
- Return error 400 if no documents found in the session

---

## 6. `/history`
**Purpose:** Return the chat history of the session

### Request
- **Method:** GET
- **Endpoint:** `/history?session_id=<SESSION_ID>`

### curl Example
```bash
curl "http://localhost:8000/history?session_id=<SESSION_ID>"
```

### Expected Response
```json
{
  "history": [
    {
      "id": "<CHAT_ID>",
      "question": "Tấm là ai ?",
      "answer": "<RESPONSE>",
      "created_at": "<TIME>"
    },
    {
      "id": "<CHAT_ID",
      "question": "Tấm là ai thế ?",
      "answer": "<RESPONSE>",
      "created_at": "<TIME>"
    }
  ],
  "latency": 0.003737926483154297
}
```

---

## 7. `/history`
**Purpose:** Delete the chat history of the session

### Request
- **Method:** DELETE
- **Endpoint:** `/history?session_id=<SESSION_ID>`

### curl Example
```bash
curl -X DELETE "http://localhost:8000/history?session_id=<SESSION_ID>"
```

### Expected Response
```json
{
  "success": true, 
  "deleted_history": "<SESSION_ID>"
}
```