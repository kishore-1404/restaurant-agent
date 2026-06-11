# scratch/test_flow.py
import asyncio
import os
import sys
import uuid
from dotenv import load_dotenv

# Ensure the project root is in PYTHONPATH
sys.path.append(os.getcwd())

load_dotenv()

from core.graph import graph
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from db.base import AsyncSessionFactory
from services.restaurant_service import RestaurantService
from services.order_service import OrderService
from services.menu_service import MenuService
from main import format_menu_for_prompt

async def run_test():
    session_id = str(uuid.uuid4())
    restaurant_id = 3 # Tokyo Bites
    
    print(f"Starting test flow for session {session_id}...")
    
    async with AsyncSessionFactory() as db:
        restaurant = await RestaurantService.get_by_id(db, restaurant_id)
        assert restaurant is not None
        menu = await MenuService.get_menu(db, restaurant_id)
        menu_text = format_menu_for_prompt(menu)
        order = await OrderService.create_order(db, restaurant_id, session_id)
        await db.commit()
        
        # Initial state: Peanut allergy customer
        state = {
            "messages": [],
            "restaurant_id": restaurant_id,
            "session_id": session_id,
            "language_code": "en",
            "customer_phone": "+1-555-0101", # Alex Chen (peanut allergy)
            "customer_name": "Alex Chen",
            "customer_profile": {
                "id": 1,
                "name": "Alex Chen",
                "phone": "+1-555-0101",
                "email": "alex@example.com",
                "language_code": "en",
                "dietary_restrictions": [],
                "allergens": ["peanuts"],
                "strict_allergens": ["peanuts"],
                "preferences": {}
            },
            "cart": [],
            "order_id": order.id,
            "stage": "greeting",
            "menu_text": menu_text,
            "active_promotions": [],
            "order_rules": [],
            "allergen_warnings_shown": [],
            "upsells_shown": [],
            "error_message": None,
        }
        
        config = {
            "configurable": {"thread_id": session_id},
        }
        
        # Turn 1: Greet customer
        print("\n--- USER: Hello ---")
        state["messages"] = [HumanMessage(content="Hello, I'd like to order.")]
        
        state_snapshot = await graph.ainvoke(state, config=config)
        last_msg = state_snapshot["messages"][-1]
        print(f"AGENT: {last_msg.content}")
        
        # Turn 2: Ask about safety
        print("\n--- USER: I have a peanut allergy. What is safe for me to eat? ---")
        input_data = {"messages": [HumanMessage(content="I have a peanut allergy. What is safe for me to eat?")]}
        
        state_snapshot = await graph.ainvoke(input_data, config=config)
        
        # Print entire trace of message exchange
        for msg in state_snapshot["messages"]:
            role = "AGENT" if isinstance(msg, AIMessage) else "USER" if isinstance(msg, HumanMessage) else "TOOL"
            print(f"{role}: {getattr(msg, 'content', '')[:300]}...")
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                print(f"  Tool calls: {msg.tool_calls}")

        # Turn 3: Try to add Spicy Tantanmen (which has peanuts)
        print("\n--- USER: Add Spicy Tantanmen to my order ---")
        input_data = {"messages": [HumanMessage(content="Add Spicy Tantanmen to my order")]}
        state_snapshot = await graph.ainvoke(input_data, config=config)
        
        for msg in state_snapshot["messages"][-3:]:
            role = "AGENT" if isinstance(msg, AIMessage) else "USER" if isinstance(msg, HumanMessage) else "TOOL"
            print(f"{role}: {getattr(msg, 'content', '')[:300]}...")
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                print(f"  Tool calls: {msg.tool_calls}")

if __name__ == "__main__":
    asyncio.run(run_test())
