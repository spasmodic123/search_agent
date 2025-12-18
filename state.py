from typing import TypedDict, Annotated, List
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

class AgentState(TypedDict):
    writer_messages: Annotated[List[BaseMessage], add_messages]
    critic_messages: Annotated[List[BaseMessage], add_messages]
    current_draft: str
    critique_advice: str
    score: int
    loop_count: int
    writer_tool_count: int
    critic_tool_count: int

'''
逻辑:LangGraph 是基于状态(State)运行的。
关键点：messages 列表存储了所有的对话历史（用户输入、AI 回复、工具调用请求、工具返回结果）。
add_messages：这是一个 reducer 函数。意味着当新消息产生时，它不会覆盖旧消息，而是**追加（Append）**到列表中。这让 LLM 能看到完整的上下文。
'''