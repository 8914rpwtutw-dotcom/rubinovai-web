from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class ChatRequest(BaseModel):
    message: str
    model: str

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    text = req.message.strip().lower()
    if "привет" in text:
        return {"reply": "Привет! Я RubinovAi."}
    return {"reply": f"Принял: {req.message}"}
