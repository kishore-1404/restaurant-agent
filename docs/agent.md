# LangGraph Agentic Flow Guide

This document explains the AI conversation engine of our system, which is built on **LangGraph** (part of the LangChain ecosystem). It details how state is managed, how the agent makes decisions, and how tokens are streamed in real-time.

---

## 1. What is LangGraph and Why Do We Use It?

A simple chatbot usually works like this:
```
User Message ──> LLM ──> Response to User
```
This linear flow works well for basic Q&A, but fails when the AI needs to execute multi-step logic. For example:
1. User says: "Can I get a cheeseburger and search for any spicy side dishes?"
2. The AI needs to call `add_item_to_order` and *then* run `search_menu`.
3. It needs to look at the results of *both* tools, and then decide how to speak.

**LangGraph** solves this by letting us define a **StateGraph**: a collection of Python functions (called **Nodes**) connected by **Edges** (which can be conditional). This allows the application to loop, call tools, check conditions, and transition stages dynamically.

---

## 2. State Management — `OrderState`

Every transition in a LangGraph graph passes a single data object from node to node. In our application, this is `OrderState` (defined in [core/state.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/core/state.py)):

```python
class OrderState(TypedDict):
    messages: Annotated[list, add_messages]  # Chat history
    restaurant_id: int                       # Current tenant ID
    session_id: str                          # Session UUID
    customer_name: Optional[str]             # Customer's name
    cart: list[CartItem]                     # Current order items
    order_id: Optional[int]                  # Database order PK
    stage: str                               # Conversation stage
    menu_text: str                           # Formatted menu string
    error_message: Optional[str]             # Error tracking
```

### The `add_messages` Reducer
The `messages` key is wrapped in `Annotated[list, add_messages]`. The `add_messages` function is a **reducer**. It tells LangGraph: *"Instead of overwriting the messages list when a node returns a value, **append** new messages to it. If a message has the same ID, update it."* This is how conversation history is built up.

---

## 3. Nodes and Graph Layout

Our graph (configured in [core/graph.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/core/graph.py)) is structured as follows:

```
                  START
                    │
                    ▼
            ┌──────────────┐
            │   chatbot    │◄────────┐
            └──────┬───────┘         │
                   │                 │
                   ▼                 │
          should_use_tools?          │
             /           \           │
            /             \          │
    (Yes)  ▼               ▼ (No)    │
     ┌───────────┐   ┌──────────────┐│
     │   tools   │   │ update_stage ││
     └─────┬─────┘   └──────┬───────┘│
           │                │        │
           ▼                ▼        │
        (Repeat)           END ──────┘
```

### 3.1 `chatbot` Node ([core/nodes.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/core/nodes.py))
1. Fetches the restaurant's name and personality from the database.
2. Dynamically builds the system instructions using `build_system_prompt()`, injecting the menu, current cart, and current conversation stage.
3. Binds our list of tools (`ORDER_TOOLS`) to the LLM.
4. Invokes the LLM and appends the resulting AI message to the state.

### 3.2 `tools` Node (Custom Tool Executor)
Instead of using LangGraph's default pre-built tool executor, we wrote a custom `tool_executor` node:
*   It checks the last message in `state["messages"]` for any `tool_calls`.
*   It activates the PostgreSQL tenant context using `RestaurantService.set_tenant_context(db, restaurant_id)`.
*   It runs the actual Python code associated with the tool call (e.g. `add_item_to_order`, `remove_item_from_order`).
*   It queries the updated order items from PostgreSQL and overwrites the `cart` list in our `OrderState`.
*   It returns the result of the tool to the LLM as a `ToolMessage`.

### 3.3 `update_stage` Node
Examines the conversation history to advance the conversation flow stage (`"greeting" -> "ordering" -> "confirming" -> "done"`). This stage is used by `build_system_prompt()` to adjust the AI's prompts (e.g. if the stage is `"confirming"`, the AI will stop suggesting items and focus strictly on asking the user to confirm the order).

---

## 4. Conditional Edges

The router function `should_use_tools` looks at the last message returned by the LLM:
*   If the LLM decided it needs to run a database action, it attaches `tool_calls` to the message. The router returns `"tools"`, pushing execution into the custom database executor.
*   If the LLM just wanted to speak to the user, `tool_calls` is empty. The router returns `"end"`, routing to `update_stage` and ending the current execution turn.

---

## 5. Session Checkpointing — `MemorySaver`

To make the agent stateful across separate API calls, we compile the graph with a **checkpointer**:
```python
memory = MemorySaver()
graph = builder.compile(checkpointer=memory)
```
Whenever we invoke the graph, we pass a `thread_id` inside the configuration:
```python
config = {"configurable": {"thread_id": session_id}}
```
`MemorySaver` intercepts this, saving a snapshot of the entire `OrderState` to memory after every node execution. On the next user message, it loads the state corresponding to the `thread_id`, ensuring the AI remembers who it is talking to, their cart, and their conversation history.

---

## 6. Server-Sent Events (SSE) Streaming

To provide a premium user experience, we stream the AI's tokens as they generate, rather than making the user wait for the entire sentence to complete. This is managed in [api/routers/chat.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/api/routers/chat.py) using `graph.astream_events(..., version="v2")`.

The streaming endpoint yields structured Server-Sent Events:
1. **Tokens**: As the model thinks, it yields:
   ```
   data: {"token": "Hi"}
   data: {"token": " there!"}
   ```
2. **Tool Events**: When a tool executes, it streams the outcome:
   ```
   data: {"tool_result": "Added 1x Margherita Classica to your order."}
   ```
3. **Cart Sync**: When the graph finishes running, it streams the final cart contents and conversation stage:
   ```
   data: {"cart": [{"name": "Margherita Classica", "quantity": 1}], "stage": "ordering"}
   ```
4. **Done**: Indicates the stream is finished:
   ```
   data: [DONE]
   ```

The customer SPA frontend (`index.html`) listens to this stream, appends tokens to the chat bubble, and updates the sidebar cart in real-time.
