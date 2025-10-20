from enum import Enum, auto

class AgentState(Enum):
    INIT = auto()
    PLANNING = auto()
    EXECUTING = auto()
    SUMMARISING = auto()
    DONE = auto()
    ERROR = auto()

