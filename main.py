from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import uvicorn
import os

from scorer import analyze_token

app = FastAPI(title="BITFA Signal Scorer", version="0.1.0")

class AnalyzeRequest(BaseModel):
    symbol: Optional[str] = None
    address: Optional[str] = None

@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "BITFA Signal Scorer is running",
        "usage": "POST /analyze with {\"symbol\": \"TICKER\"} or {\"address\": \"0x...\"}"
    }

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    if not req.symbol and not req.address:
        return {"error": "symbol or address is required", "score": 0}
    
    result = analyze_token(symbol=req.symbol, address=req.address)
    return result

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
