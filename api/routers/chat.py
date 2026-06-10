from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from core.graph import graph
from api.dependencies import get_db_and_restaurant
import json
import uuid

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str = None


@router.post("/stream")
async def chat_stream(request: ChatRequest, context=Depends(get_db_and_restaurant)):
    """
    Stream LLM tokens as Server-Sent Events.
    The terminal client receives tokens in real-time as the LLM generates them.
    """
    session_id = request.session_id or str(uuid.uuid4())
    db, restaurant = context

    async def generate():
        from monitoring.hooks import MonitorCallback
        from sqlalchemy import select
        from db.models import Order
        from services.order_service import OrderService
        from services.menu_service import MenuService
        from main import format_menu_for_prompt

        config = {
            "configurable": {"thread_id": session_id},
            "callbacks": [MonitorCallback(session_id=session_id)],
        }

        state_snapshot = await graph.aget_state(config)
        if not state_snapshot.values:
            # Check if an order already exists for this session in the database
            res = await db.execute(select(Order).where(Order.session_id == session_id))
            order = res.scalar_one_or_none()
            if not order:
                order = await OrderService.create_order(db, restaurant.id, session_id)
                await db.commit()

            menu = await MenuService.get_menu(db, restaurant.id)
            menu_text = format_menu_for_prompt(menu)

            inputs = {
                "messages": [{"role": "user", "content": request.message}],
                "restaurant_id": restaurant.id,
                "session_id": session_id,
                "customer_name": None,
                "cart": [],
                "order_id": order.id,
                "stage": "greeting",
                "menu_text": menu_text,
                "error_message": None,
            }
        else:
            inputs = {
                "messages": [{"role": "user", "content": request.message}],
            }

        async for event in graph.astream_events(inputs, config=config, version="v2"):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    yield f"data: {json.dumps({'token': chunk.content})}\n\n"
            elif event["event"] == "on_tool_end":
                yield f"data: {json.dumps({'tool_result': event['data']['output']})}\n\n"

        # Fetch final state snapshot from the checkpointer
        state_snapshot = await graph.aget_state(config)
        result = state_snapshot.values
        cart = result.get("cart", [])
        stage = result.get("stage", "greeting")
        yield f"data: {json.dumps({'cart': cart, 'stage': stage})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/config")
async def chat_config():
    from llm.factory import llm_provider

    return {"provider": llm_provider.get_provider_name()}
