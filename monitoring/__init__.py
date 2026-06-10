"""
monitoring/

Developer monitoring system for the restaurant AI platform.

Quick start
-----------
1. Mount the dashboard in api/main.py:

    from monitoring.dashboard import mount_dashboard
    mount_dashboard(app)

2. Instrument the DB engine in db/base.py:

    from monitoring.hooks import setup_db_hooks
    setup_db_hooks(engine)

3. Wrap Redis client in redis_client.py:

    from monitoring.hooks import InstrumentedRedis
    # Replace: self.client = aioredis.Redis(...)
    # With:    self.client = InstrumentedRedis(aioredis.Redis(...))

4. Add LangChain callback in core/graph.py:

    from monitoring.hooks import MonitorCallback

    config = {
        "configurable": {"thread_id": session_id},
        "callbacks": [MonitorCallback(session_id=session_id)],
    }

5. Emit agent state snapshots from nodes.py:

    from monitoring.hooks import emit_agent_state
    emit_agent_state(state, state["session_id"], node_name="chatbot_node")

6. Open http://localhost:8000/monitor in your browser.
"""

from monitoring.events import bus, Event, EK, EventBus
from monitoring.hooks import (
    setup_db_hooks,
    InstrumentedRedis,
    MonitorCallback,
    emit_agent_state,
    emit_order_event,
)

__all__ = [
    "bus",
    "Event",
    "EK",
    "EventBus",
    "setup_db_hooks",
    "InstrumentedRedis",
    "MonitorCallback",
    "emit_agent_state",
    "emit_order_event",
]
