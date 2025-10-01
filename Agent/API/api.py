# LLM/API/api.py
import os
import dotenv
import uvicorn
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, APIRouter, Query
from pydantic import BaseModel
from contextlib import asynccontextmanager
import asyncio
import logging

from Agent.API.deps import verify_token, auth_ws
from Agent.Adapters.Outbound.azure_openai_adapter import AzureOpenAIAdapter
from Agent.Adapters.Outbound.openai_adapter import OpenAIAdapter
from Agent.Adapters.Outbound.mcp_adapter import MCPAdapter
from Agent.Domain.agent_service import AgentService
from Agent.Domain.agent_lifecycle import AgentSession

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

dotenv.load_dotenv()


provider = os.getenv("LLM_PROVIDER")

if provider == "OPENAI":
    llm_client = OpenAIAdapter(
        api_key=os.getenv("OPENAI_API_KEY"),
        deployment_name=os.getenv("LLM_MODEL")
    )

elif provider == "AZURE_OPENAI":
    llm_client = AzureOpenAIAdapter(
        endpoint=os.getenv("AZURE_ENDPOINT"),
        api_key=os.getenv("AZURE_API_KEY"), 
        deployment_name=os.getenv("LLM_MODEL"),
        api_version=os.getenv("AZURE_API_VERSION"),
    )
else:
    raise ValueError("LLM_PROVIDER environment variable is required")


mcp_client = MCPAdapter(llm=llm_client)

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await mcp_client.startup_mcp()
        app.state.mcp_ready = True
    except (asyncio.TimeoutError, Exception):
        app.state.mcp_ready = False
    
    yield
    await mcp_client.disconnect_all()

app = FastAPI(lifespan=lifespan)
protected = APIRouter(dependencies=[Depends(verify_token)])

class PromptRequest(BaseModel):
    prompt: str


# endpoints
@protected.post("/call")
async def call_llm(req: PromptRequest):
    # Note: you could also call through mcp if you wrap azure_client as a tool
    result: str = llm_client.call(
        prompt=req.prompt,
        system_prompt="You are a helpful assistant."
    )
    return {"result": result, "trace": None}

@app.websocket("/ws/call")
async def call_llm_with_ws(websocket: WebSocket, _: None = Depends(auth_ws)):
    await websocket.accept()
    try:
        # Receive the prompt from the client
        prompt = await websocket.receive_text()
        
        # Stream the response using the new streaming method
        async for chunk in llm_client.call_stream(
            prompt=prompt,
            system_prompt="You are a helpful assistant."
        ):
            if isinstance(chunk, dict):
                await websocket.send_json(chunk)
            else:
                await websocket.send_text(chunk)
        
        await websocket.close()
        
    except WebSocketDisconnect:
        logger.info("WebSocket connection closed by the client.")
    except Exception as e:
        logger.error(f"Error during WebSocket communication: {e}", exc_info=True)
        await websocket.send_json({"error": str(e)})
        await websocket.close()


@protected.post("/call_mcp")
async def call_llm_with_mcp(req: PromptRequest):
    # Check if MCP is ready
    if not getattr(app.state, 'mcp_ready', False):
        raise HTTPException(status_code=503, detail="MCP services not available")
    
    try:
        # Use the global MCP client that was initialized at startup
        result, trace = await asyncio.wait_for(
            mcp_client.process_query(prompt=req.prompt, summary=True), 
            timeout=60.0
        )
        return {"result": result, "trace": trace}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=500, detail="Operation timed out")
    except Exception as e:
        logger.error(f"MCP operation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    

@app.websocket("/ws/call_mcp")
async def call_llm_with_mcp_ws(websocket: WebSocket, _: None = Depends(auth_ws)):
    await websocket.accept()
    try:
        if not app.state.mcp_ready:
            await websocket.send_json({"error": "MCP services not available"})
            return await websocket.close()

        while True:
            query = await websocket.receive_text()
            final, trace = await asyncio.wait_for(
                mcp_client.process_query(prompt=query, websocket=websocket, summary=True, trace=True),
                timeout=60.0
            )
            await websocket.send_json({
                "result": final,
                "trace": trace
            })
            return await websocket.close()

    except WebSocketDisconnect:
        logger.info("WebSocket connection closed by the client.")
    except asyncio.TimeoutError:
        await websocket.send_json({"error": "Operation timed out"})
        await websocket.close()
    except Exception as e:
        logger.error(f"Error during WebSocket communication: {e}", exc_info=True)
        await websocket.send_json({"error": str(e)})
        await websocket.close()



@protected.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "mcp_ready": getattr(app.state, 'mcp_ready', False)
    }

# list tools
@protected.get("/tools")
async def list_tools():
    return mcp_client.get_tools_json()


@protected.post("/agent")
async def agent_run(req: PromptRequest):
    if not getattr(app.state, 'mcp_ready', False):
        raise HTTPException(status_code=503, detail="MCP services not available")

    try:
        service = AgentService(llm=llm_client, mcp=mcp_client)
        session = AgentSession(user_prompt=req.prompt, max_steps=5)
        result, trace = await asyncio.wait_for(service.loop_run(session), timeout=90.0)
        return {"result": result, "trace": trace}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=500, detail="Operation timed out")
    except Exception as e:
        logger.error(f"Agent run failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
    
app.include_router(protected)


if __name__ == "__main__":
    uvicorn.run("Agent.API.api:app", host="0.0.0.0", port=8080, reload=True)
