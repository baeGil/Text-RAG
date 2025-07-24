# 🧠 RAG Chatbot with some optimization techniques

---

## 📂 Project Structure

```
├── backend/               # Backend logic
|   ├── API_Test_Guide.md  
│   ├── config.py          # Variables config
│   ├── db.py              # Interact with db
│   ├── main.py            # Main fastAPI file
│   └── rag_pipeline.py    # RAG 
│
├── frontend/              # Frontend logic
│   ├── app.py             # Main streamlit file
│   └── style.css
│
├── .env.example           # Env variables
├── requirements.txt       # Python dependencies
└── README.md              
```

---

## 🚀 Features

- ✅ Simple, responsive Streamlit UI.
- ✅ Conversational memory, metadata stored in Redis.
- ✅ Qdrant vector store for fast retriever with HNSW algorithm.
- ✅ Support multiple documents upload.
- ✅ Chat history persistence across sessions.
- ✅ Follow-up technique for better query.
- ✅ Semantic chunking for better retriever.
- ✅ Summarize chat history to reduce memory usage.
- ✅ Caching data so it consist even when we restart the page web.

---

## 🛠️ Installation

1. **Clone the repository:**

```bash
git clone https://github.com/baeGil/Text-rag.git
cd Text-rag
```

2. **Create virtual environment (optional but recommended):**

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. **Install dependencies:**

```bash
pip install -r requirements.txt
```

4. **Set up `.env` file:**

```bash
cp .env.example .env
# Edit with your credentials for Gemini, Qdrant
```

---

## ▶️ Running the App

### 1. Start the backend server:
From the root directory, run the following command
```bash
cd backend
uvicorn main:app --reload
```

### 2. Launch the Streamlit frontend:
Split the terminal, run the following command
```bash
cd frontend
streamlit run app.py
```

---

## 🧪 API Testing

See `backend/API_Test_Guide.md` for detailed instructions and sample payloads.

---

## 🧠 Technologies Used

- [LangChain](https://www.langchain.com/)
- [Google Gemini](https://ai.google.dev/)
- [Qdrant](https://qdrant.tech/)
- [Redis](https://redis.io/)
- [Streamlit](https://streamlit.io/)
- [FastAPI](https://fastapi.tiangolo.com/)
---

## 📷 Demo

![Farmers Market Finder Demo](Demo.gif)

---

## 🤝 Contributing

Contributions are welcome!  
Please open an issue or submit a pull request.

---

## ✨ Acknowledgements

Special thanks to `Chip Huyen`, `AIO2025 Community` for helping me to build and optimize the pipeline.