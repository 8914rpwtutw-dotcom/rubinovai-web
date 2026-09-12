import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Инициализируем клиент GenAI (ключ подтянется из переменных окружения Render)
client = genai.Client()

class ChatRequest(BaseModel):
    message: str
    model: str = "gemini-2.5-flash"  # актуальная быстрая модель

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    try:
        # Отправляем запрос к Gemini API
        response = client.models.generate_content(
            model=req.model,
            contents=req.message,
        )
        return {"reply": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
