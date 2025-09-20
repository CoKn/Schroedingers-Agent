# LLM/Adapters/Outbound/_base_mcp_client.py
from contextlib import AsyncExitStack
import anyio
from anyio.abc import TaskGroup, AsyncResource
from Agent.Ports.Outbound.mcp_interface import MCPClient
from mcp import ClientSession


class _BaseMCPClient(MCPClient):
    """
    Transport-agnostic MCP client.
    One long-lived service task owns the whole transport/session lifecycle, so
    the AnyIO cancel-scope rule (“exit in the same task”) is never violated.
    """

    _runner_cm: AsyncResource | None = None   # context manager that produced _tg
    _tg: TaskGroup | None = None       # real TaskGroup instance
    _session: ClientSession | None = None

    # Public helper so callers (adapter, FastAPI) can grab the live session
    @property
    def session(self) -> ClientSession | None:
        return self._session

    # Internal service task: open transport, wrap in ClientSession, init
    async def _service(self, transport_cm, ready: anyio.Event):
        async with AsyncExitStack() as stack:
            # 1) open raw transport   (stdio / http)
            r, w, *_ = await stack.enter_async_context(transport_cm)
            # 2) wrap into MCP session
            self._session = await stack.enter_async_context(ClientSession(r, w))
            await self._session.initialize()
            ready.set()                           # handshake complete
            await anyio.Event().wait()            # stay alive until .disconnect()

    # Called by concrete adapters
    async def connect_transport(self, transport_cm):
        if self._tg:                              # already connected
            return

        ready = anyio.Event()
        self._runner_cm = anyio.create_task_group()
        self._tg = await self._runner_cm.__aenter__()
        self._tg.start_soon(self._service, transport_cm, ready)
        await ready.wait()                        # block caller until ready

    async def disconnect(self):
        if self._tg:
            self._tg.cancel_scope.cancel()        # stops _service
            await self._runner_cm.__aexit__(None, None, None)
            self._tg = self._runner_cm = self._session = None
