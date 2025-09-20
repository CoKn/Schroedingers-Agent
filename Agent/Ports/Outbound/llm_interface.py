from abc import abstractmethod, ABC

class LLM(ABC):
    @abstractmethod
    def call(self, prompt):
        ...