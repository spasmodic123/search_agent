"""
FastAPI 服务入口
将 LangGraph Search Agent 包装为 REST API 服务
"""
import json
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from langchain_core.messages import SystemMessage, HumanMessage


# ============================================================
# Pydantic 数据模型
# ============================================================

class ResearchRequest(BaseModel):
    """研究请求模型"""
    topic: str = Field(..., description="研究主题", min_length=1)
    user_id: str = Field(..., description="用户ID", min_length=1)
    thread_id: str = Field(..., description="会话ID，用于隔离不同对话", min_length=1)


class ResearchResponse(BaseModel):
    """研究响应模型（同步端点使用）"""
    current_draft: str = Field(..., description="最终生成的草稿")
    status: str = Field(default="completed", description="任务状态")
    score: int = Field(default=0, description="Critic 评分")


class ErrorResponse(BaseModel):
    """错误响应模型"""
    error: str = Field(..., description="错误类型")
    message: str = Field(..., description="错误详情")
    thread_id: str | None = Field(default=None, description="相关的会话ID")


# ============================================================
# 自定义异常
# ============================================================

class LLMError(Exception):
    """LLM 调用相关错误"""
    def __init__(self, message: str, thread_id: str | None = None):
        self.message = message
        self.thread_id = thread_id
        super().__init__(self.message)


class ToolError(Exception):
    """工具执行相关错误"""
    def __init__(self, message: str, tool_name: str | None = None):
        self.message = message
        self.tool_name = tool_name
        super().__init__(self.message)


# ============================================================
# FastAPI 应用
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    在启动时初始化 LangGraph 实例，关闭时进行清理
    """
    # 启动时：导入并缓存 LangGraph 应用
    from graph import app as langgraph_app
    
    # 将 LangGraph 实例存储在 app.state 中
    app.state.langgraph_app = langgraph_app
    
    print("✅ LangGraph Search Agent 已初始化")
    
    yield
    
    # 关闭时：清理资源（如有必要）
    print("👋 正在关闭服务...")


app = FastAPI(
    title="Search Agent API",
    description="基于 LangGraph 的智能研究助手 API",
    version="1.0.0",
    lifespan=lifespan
)


# ============================================================
# 异常处理器
# ============================================================

@app.exception_handler(LLMError)
async def llm_error_handler(request: Request, exc: LLMError):
    """处理 LLM 相关错误"""
    return HTTPException(
        status_code=503,
        detail=ErrorResponse(
            error="llm_error",
            message=exc.message,
            thread_id=exc.thread_id
        ).model_dump()
    )


@app.exception_handler(ToolError)
async def tool_error_handler(request: Request, exc: ToolError):
    """处理工具执行错误"""
    return HTTPException(
        status_code=500,
        detail=ErrorResponse(
            error="tool_error",
            message=f"工具 {exc.tool_name} 执行失败: {exc.message}"
        ).model_dump()
    )


# ============================================================
# SSE 流式格式化
# ============================================================

def format_sse_event(node: str, content: str, event_type: str = "message") -> str:
    """
    将事件格式化为 SSE 格式
    
    Args:
        node: 节点名称 (writer, critic, tools_writer, etc.)
        content: 消息内容
        event_type: 事件类型
    
    Returns:
        SSE 格式字符串: data: {"node": "...", "content": "..."}\n\n
    """
    data = json.dumps({
        "node": node,
        "content": content,
        "type": event_type
    }, ensure_ascii=False)
    return f"data: {data}\n\n"


# ============================================================
# 系统提示词
# ============================================================

SYSTEM_PROMPT = """你是一名智能研究助手。
你的目标是利用网络搜索和网页访问工具来研究用户的主题。
1. 使用 `search_web` 查找相关页面。
2. 使用 `visit_page` 阅读有价值的 URL 的详细内容。
3. 将信息整合成一份全面的 Markdown 报告。
4. 完成后，输出最终的 Markdown 格式报告。
5. 请务必用中文回答。
"""


# ============================================================
# API 端点
# ============================================================

@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "healthy"}


@app.post("/api/research/stream")
async def research_stream(request: ResearchRequest):
    """
    流式研究端点 (SSE)
    
    实时流式输出 LangGraph 执行过程中的每个节点事件。
    
    使用示例:
    ```bash
    curl -X POST http://localhost:8000/api/research/stream \
      -H "Content-Type: application/json" \
      -H "Accept: text/event-stream" \
      -d '{"topic": "量子计算", "user_id": "user1", "thread_id": "thread1"}'
    ```
    """
    
    async def event_generator() -> AsyncGenerator[str, None]:
        """生成 SSE 事件流"""
        langgraph_app = app.state.langgraph_app
        
        # 构建初始输入
        initial_input = {
            "writer_messages": [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=request.topic)
            ]
        }
        
        # 配置 thread_id 以隔离会话状态
        config = {
            "configurable": {
                "thread_id": request.thread_id
            },
            "recursion_limit": 80
        }
        
        try:
            # 发送开始事件
            yield format_sse_event("system", f"开始研究: {request.topic}", "start")
            
            # 使用 stream_mode="updates" 流式处理
            for event in langgraph_app.stream(initial_input, stream_mode="updates", config=config):
                for node_name, node_val in event.items():
                    # 处理 Writer 消息
                    if "writer_messages" in node_val and node_val["writer_messages"]:
                        message = node_val["writer_messages"][-1]
                        content = ""
                        
                        # 提取消息内容
                        if hasattr(message, 'content') and message.content:
                            content = str(message.content)
                        
                        # 检查是否有工具调用
                        if hasattr(message, 'tool_calls') and message.tool_calls:
                            tool_info = [tc.get('name', 'unknown') for tc in message.tool_calls]
                            content = f"调用工具: {', '.join(tool_info)}"
                        
                        if content:
                            yield format_sse_event(node_name, content)
                    
                    # 处理 Critic 消息
                    elif "critic_messages" in node_val and node_val["critic_messages"]:
                        message = node_val["critic_messages"][-1]
                        content = ""
                        
                        if hasattr(message, 'content') and message.content:
                            content = str(message.content)
                        
                        if hasattr(message, 'tool_calls') and message.tool_calls:
                            tool_info = [tc.get('name', 'unknown') for tc in message.tool_calls]
                            content = f"验证工具: {', '.join(tool_info)}"
                        
                        if content:
                            yield format_sse_event(node_name, content)
                    
                    # 处理草稿更新
                    if "current_draft" in node_val and node_val["current_draft"]:
                        yield format_sse_event("draft_update", node_val["current_draft"], "draft")
                    
                    # 处理评分更新
                    if "score" in node_val:
                        yield format_sse_event("score", str(node_val["score"]), "score")
                
                # 让出控制权，避免阻塞
                await asyncio.sleep(0)
            
            # 发送完成事件
            yield format_sse_event("system", "研究完成", "complete")
            
        except Exception as e:
            # 发送错误事件
            yield format_sse_event("error", str(e), "error")
            raise
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/api/research/sync", response_model=ResearchResponse)
async def research_sync(request: ResearchRequest):
    """
    同步研究端点
    
    阻塞式执行研究任务，返回最终草稿。
    适用于不需要实时反馈的场景。
    
    注意: 此端点可能需要较长时间才能返回（取决于研究复杂度）。
    
    使用示例:
    ```bash
    curl -X POST http://localhost:8000/api/research/sync \
      -H "Content-Type: application/json" \
      -d '{"topic": "人工智能发展趋势", "user_id": "user1", "thread_id": "thread2"}'
    ```
    """
    langgraph_app = app.state.langgraph_app
    
    # 构建初始输入
    initial_input = {
        "writer_messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=request.topic)
        ]
    }
    
    # 配置 thread_id
    config = {
        "configurable": {
            "thread_id": request.thread_id
        },
        "recursion_limit": 80
    }
    
    try:
        # 使用 invoke 同步执行
        final_state = langgraph_app.invoke(initial_input, config=config)
        
        return ResearchResponse(
            current_draft=final_state.get("current_draft", ""),
            status="completed",
            score=final_state.get("score", 0)
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error="execution_error",
                message=str(e),
                thread_id=request.thread_id
            ).model_dump()
        )


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
