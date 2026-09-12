import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from google import genai

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

client = genai.Client()

class ChatRequest(BaseModel):
    message: str
    model: str = "gemini-2.5-flash"

# Красивый веб-интерфейс чата на главной странице
@app.get("/", response_class=HTMLResponse)
async def get_chat_ui():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>RubinovAi Chat</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
            .chat-container { width: 100%; max-width: 600px; height: 80vh; background: #1e293b; border-radius: 12px; display: flex; flex-direction: column; box-shadow: 0 10px 25px rgba(0,0,0,0.3); overflow: hidden; }
            .chat-header { background: #334155; padding: 16px; font-weight: bold; text-align: center; font-size: 1.1rem; }
            .chat-messages { flex: 1; padding: 16px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }
            .message { padding: 10px 14px; border-radius: 8px; max-width: 80%; line-height: 1.4; word-break: break-word; }
            .user { background: #3b82f6; align-self: flex-end; color: white; }
            .ai { background: #475569; align-self: flex-start; color: #f1f5f9; }
            .chat-input-area { display: flex; padding: 12px; background: #334155; gap: 8px; }
            input { flex: 1; padding: 10px 14px; border-radius: 6px; border: none; background: #1e293b; color: white; font-size: 1rem; outline: none; }
            button { padding: 10px 20px; background: #3b82f6; color: white; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; transition: background 0.2s; }
            button:hover { background: #2563eb; }
        </style>
    </head>
    <body>
        <div class="chat-container">
            <div class="chat-header">RubinovAi Assistant</div>
            <div id="messages" class="chat-messages"></div>
            <div class="chat-input-area">
                <input type="text" id="messageInput" placeholder="Введите сообщение..." onkeydown="if(event.key==='Enter') sendMessage()">
                <button onclick="sendMessage()">Отправить</button>
            </div>
        </div>
        <script>
            async function sendMessage() {
                const input = document.getElementById('messageInput');
                const messagesDiv = document.getElementById('messages');
                const text = input.value.trim();
                if (!text) return;

                messagesDiv.innerHTML += `<div class="message user">${text}</div>`;
                input.value = '';
                messagesDiv.scrollTop = messagesDiv.scrollHeight;

                try {
                    const response = await fetch('/api/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ message: text, model: "gemini-2.5-flash" })
                    });
                    const data = await response.json();
                    messagesDiv.innerHTML += `<div class="message ai">${data.reply || data.detail || 'Ошибка ответа'}</div>`;
                } catch (err) {
                    messagesDiv.innerHTML += `<div class="message ai">Ошибка соединения с сервером.</div>`;
                }
                messagesDiv.scrollTop = messagesDiv.scrollHeight;
            }
        </script>
    </body>
    </html>
    """

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    try:
        response = client.models.generate_content(
            model=req.model,
            contents=req.message,
        )
        return {"reply": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
