from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agents import run_agent
from liquid import place_order as liquid_place_order
from polymarket_clob import place_order as poly_place_order

app = FastAPI(title="Polymarket Agent Chat")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AgentRequest(BaseModel):
    prompt: str


class LiquidOrder(BaseModel):
    symbol: str
    side: str
    size: float
    leverage: int = 1


class PolymarketOrder(BaseModel):
    token_id: str
    amount_usd: float
    price_limit: float = 0.99


class ExecuteRequest(BaseModel):
    liquid_orders: list[LiquidOrder] = []
    polymarket_orders: list[PolymarketOrder] = []


@app.post("/agent")
async def agent_endpoint(req: AgentRequest):
    result = await run_agent(req.prompt)
    return result


@app.post("/execute")
async def execute_endpoint(req: ExecuteRequest):
    results = []
    for o in req.liquid_orders:
        try:
            r = await liquid_place_order(o.symbol, o.side, o.size, o.leverage)
            results.append({"venue": "liquid", "symbol": o.symbol, "side": o.side, **r})
        except Exception as e:
            results.append({"venue": "liquid", "symbol": o.symbol, "side": o.side, "error": str(e)})
    for o in req.polymarket_orders:
        try:
            r = await poly_place_order(o.token_id, o.amount_usd, o.price_limit)
            results.append({"venue": "polymarket", "token_id": o.token_id[:16] + "...", **r})
        except Exception as e:
            results.append({"venue": "polymarket", "token_id": o.token_id[:16] + "...", "error": str(e)})
    return {"results": results}
