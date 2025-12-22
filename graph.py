import re
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
import openai
from dotenv import load_dotenv
import os

from state import AgentState
from tools import search_web, visit_page

# API 配置
BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')

# 加载环境变量
load_dotenv()

# 检查 API Key
if "DEEPSEEK_API_KEY" not in os.environ:
    print("WARNING: DEEPSEEK_API_KEY not found in environment. Please set it in .env file.")

# 初始化 LLM
llm = ChatOpenAI(model="deepseek-chat", temperature=1, base_url=BASE_URL, api_key=DEEPSEEK_API_KEY)
tools = [search_web, visit_page]
llm_with_tools = llm.bind_tools(tools)

# --- 提示词 (Prompts) ---
WRITER_SYSTEM_PROMPT = """你是一名智能研究助手。
你的目标是利用网络搜索和网页访问工具来研究用户的主题。
1. 使用 `search_web` 查找相关页面。
2. 使用 `visit_page` 阅读有价值的 URL 的详细内容。
3. 将信息整合成一份全面的 Markdown 报告。
4. 完成后，输出最终的 Markdown 格式报告。
5. 请务必用中文回答。
"""

CRITIC_SYSTEM_PROMPT = """你是一名严格的评论家。你需要审查 Writer 起草的报告。

**工作流程：**
1. **验证阶段**：
   - 首先检查草稿中的任何声明（例如新模型、近期事件、具体数字）。
   - 如果有任何不确定或未经证实的内容，**必须**使用 `search_web` 或 `visit_page` 工具进行验证。
   - 在此阶段，不要输出最终的评分 XML，直接调用工具即可。
   
2. **审查阶段**：
   - 验证完成后，根据 Writer 的草稿和你的验证结果进行评估。
   - 只有在验证完成**后**，才输出最终的评分和建议。

不要仅依赖内部训练数据来判断最近的信息。
请用中文回答！

Writer 的草稿如下所示。

**最终输出格式（验证完成后使用）：**
你的回复必须使用以下 XML 格式：

<advice>
[你的建设性批评意见以及具体的修改建议。如果草稿完美，请说 "No changes needed"。]
</advice>

<score>
[0 到 10 的整数。10 分代表完美。]
</score>

高分标准 (8-10):
- 无幻觉（事实经过验证）。
- 全面覆盖用户请求。
- 结构清晰且 Markdown 格式正确。
"""""

# --- 节点 (Nodes) ---

def writer_node(state: AgentState):
    """Writer 节点：负责执行搜索、访问网页和撰写草稿。"""
    current_messages = state.get("writer_messages", [])
    
    # 获取 Critic 的建议
    advice = state.get("critique_advice", "")
    loop_count = state.get("loop_count", 0)
    
    # 如果存在建议且是在后续循环中，尝试将其作为反馈加入到消息历史中
    if advice and loop_count > 0:
        # 检查是否已经添加过这条建议，避免重复添加
        # 这里的逻辑是简单的检查最后几条消息
        already_added = False
        for m in reversed(current_messages):
            if isinstance(m, HumanMessage) and advice in str(m.content):
                already_added = True
                break
        
        if not already_added:
             current_messages = list(current_messages) + [HumanMessage(content=f"Critic Feedback (Score: {state.get('score')}): {advice}")]

    # 强制停止工具调用：如果达到限制
    try:
        if state.get("writer_tool_count", 0) >= 6:
            # 注入系统通知，强迫 Writer 生成最终文本
            current_messages = list(current_messages) + [SystemMessage(content="系统通知：工具调用达到上限。请停止搜索，立即根据现有信息生成最终报告。")]
            # 使用不带工具绑定的 LLM，物理上禁止工具调用
            response = llm.invoke(current_messages)
        else:
            # 正常调用带工具的 LLM
            response = llm_with_tools.invoke(current_messages)

    except openai.BadRequestError as e:
        # 处理内容安全报错 (Content Exists Risk)
        if "Content Exists Risk" in str(e) or "invalid_request_error" in str(e):
            # 检查最后一条消息是否为工具输出，如果是，可能是搜索结果触发了风控
            if isinstance(current_messages[-1], ToolMessage):
                # 替换为安全提示
                safe_fallback_msg = ToolMessage(
                    tool_call_id=current_messages[-1].tool_call_id,
                    content="系统提示：搜索结果包含敏感内容被过滤。请尝试使用不同的关键词搜索，或忽略此条结果。"
                )
                current_messages[-1] = safe_fallback_msg
                # 重试
                response = llm_with_tools.invoke(current_messages)
            else:
                raise e
        else:
            raise e
        
    response.name = "writer"
    
    # 如果是文本回复（非纯工具调用），更新当前草稿内容
    draft = state.get("current_draft", "")
    if response.content and not response.tool_calls:
        draft = response.content
        
    return {
        "writer_messages": [response], # 增量追加消息
        "current_draft": draft
    }

def critic_node(state: AgentState):
    """Critic 节点：负责审查草稿。"""
    current_messages = state.get("critic_messages", [])
    draft = state.get("current_draft", "")
    
    # --- 构建 Critic 的上下文 ---
    # 1. 系统提示词
    messages_to_send = [SystemMessage(content=CRITIC_SYSTEM_PROMPT)]
    
    # 2. 历史消息
    messages_to_send += list(current_messages)

    # 如果是新 loop 开始（tool_count 刚被重置）
    if state.get("critic_tool_count", 0) == 0 and state.get("loop_count", 0) > 0:
        # 注入"重置提示"
        messages_to_send.append(SystemMessage(content="注意：工具使用次数已重置为0，你可以继续验证事实。"))
    
    # 3. 注入草稿
    # 仅在 Critic 开始新一轮审查（tool_count == 0）时注入草稿
    if state.get("critic_tool_count", 0) == 0:
        input_msg = HumanMessage(content=f"这是 Writer 的最新草稿，请审查：\n\n{draft}\n\n请开始审查并验证事实。")
        messages_to_send.append(input_msg)
        
    # 强制停止工具调用：如果达到限制
    if state.get("critic_tool_count", 0) >= 6:
        messages_to_send.append(SystemMessage(content="系统通知：工具调用达到上限。请停止搜索，立即给出评分和建议。"))
        response = llm.invoke(messages_to_send)
    else:
        response = llm_with_tools.invoke(messages_to_send)
        
    response.name = "critic"
    
    # 解析分数和建议 (Regex)
    score = 0
    advice = ""
    if response.content and not response.tool_calls:
        score_match = re.search(r'<score>\s*(\d+)\s*</score>', response.content)
        advice_match = re.search(r'<advice>(.*?)</advice>', response.content, re.DOTALL)
        
        if score_match:
            try:
                score = int(score_match.group(1))
            except:
                pass
        
        print(f"\n\n\nDEBUG: Parsed score: {score}")  #  这个debug信息会在Ai Message之前打印出来，因为代码运行到这一行，已经有critic response了，但是没有return
        
        if advice_match:
            advice = advice_match.group(1).strip()
            
    # 返回更新的状态
    msgs_to_return = []
    # 如果我们这轮注入了“请审查草稿”的消息，也需要保存到历史记录中
    if state.get("critic_tool_count", 0) == 0:
         msgs_to_return.append(HumanMessage(content=f"这是 Writer 的最新草稿，请审查：\n\n{draft}\n\n请开始审查并验证事实。"))
    
    msgs_to_return.append(response)

    return {
        "critic_messages": msgs_to_return,
        "score": score,
        "critique_advice": advice
    }


# --- 路由逻辑 (Routing) & 工具节点 ---

def writer_router(state: AgentState):
    """Writer 的路由：决定是去调用工具还是转交给 Critic。"""
    last_message = state["writer_messages"][-1]
    
    # 只有当有工具调用请求时，才去 tools_writer
    if last_message.tool_calls:
        return "tools_writer" 

    # DeepSeek 有时会输出原始 tokens 而没有被解析为 tool_calls
    content = str(last_message.content)
    if "<｜DSML｜function_calls>" in content:
        return "tools_writer"
        
    # 否则（生成了文本），转交给 Critic
    return "critic"

def critic_router(state: AgentState):
    """Critic 的路由：决定是调用工具还是结束/打回给 Writer。"""
    last_message = state["critic_messages"][-1]
    
    # 1. 优先检查结构化工具调用
    if last_message.tool_calls:
        return "tools_critic" 
    
    # 2. 检查是否有“假”工具调用（Raw XML leakage）
    # DeepSeek 有时会输出原始 tokens 而没有被解析为 tool_calls
    content = str(last_message.content)
    if "<｜DSML｜function_calls>" in content:
        return "tools_critic"
    
    # 检查分数和循环次数
    score = state.get("score", 0)
    loop = state.get("loop_count", 0)
    
    # 如果分数 >= 8 或者 已经尝试了 2 次（0, 1），则结束
    if score >= 8 or loop >= 2: 
        return END
    else:
        return "increment_loop" # 回到 Writer 修改

def writer_tools_node(state: AgentState):
    """Writer 的工具执行节点。"""
    last_msg = state["writer_messages"][-1]
    
    # 限制检查 (Fail-safe)
    if state.get("writer_tool_count", 0) >= 6:
        error_msgs = []
        if last_msg.tool_calls:
            print("DEBUG: writer_tool_count limit reached with valid tool_calls. Returning Error ToolMessage.")
            for tool_call in last_msg.tool_calls:
                error_msgs.append(ToolMessage(
                    tool_call_id=tool_call['id'],
                    content="错误：本轮工具调用次数已达上限。请停止搜索并撰写报告。"
                ))
        else:
             # 如果没有 tool_calls 但进来了（可能是 Raw XML case），也返回错误
             print("DEBUG: writer_tool_count limit reached AND Raw XML format detected. Returning Error SystemMessage.")
             return {
                 "writer_messages": [SystemMessage(content="系统通知：工具调用次数上限已达。此前调用格式可能有误。请停止尝试，直接撰写报告。")]
             }
             
        return {
            "writer_messages": error_msgs
        }
    
    #这是处理 Raw XML 错误的核心逻辑
    if not last_msg.tool_calls:
        # 如果路由到了这里但没有 tool_calls，说明 Router 认为是 Raw XML 错误
        print("DEBUG: writer_tools_node detected Raw XML format. Sending System Warning.")
        return {
            "writer_messages": [SystemMessage(content="系统严重警告：检测到你输出了无效的工具调用格式（Raw XML）。这会导致工具无法执行。请**立刻**停止生成报告，并使用正确的 Tool/Function Calling 格式重新发起调用！")]
        }
    
    tool_node = ToolNode(tools)
    result = tool_node.invoke({"messages": [last_msg]})
    
    return {
        "writer_messages": result["messages"],
        "writer_tool_count": state.get("writer_tool_count", 0) + 1
    }

def critic_tools_node(state: AgentState):
    """Critic 的工具执行节点。"""
    last_msg = state["critic_messages"][-1]
    
    if state.get("critic_tool_count", 0) >= 6:
        error_msgs = []
        if last_msg.tool_calls:
            print("DEBUG: critic_tool_count limit reached with valid tool_calls. Returning Error ToolMessage.")
            for tool_call in last_msg.tool_calls:
                error_msgs.append(ToolMessage(
                    tool_call_id=tool_call['id'],
                    content="错误：本轮工具调用次数已达上限。请停止搜索并给出修改建议。"
                ))
        else:
             # 如果没有 tool_calls 但进来了（可能是 Raw XML case），也返回错误
             print("DEBUG: critic_tool_count limit reached AND Raw XML format detected. Returning Error SystemMessage.")
             return {
                 "critic_messages": [SystemMessage(content="系统通知：工具调用次数上限已达。此前调用格式可能有误。请停止尝试，直接给出修改建议。")]
             }
             
        return {
            "critic_messages": error_msgs
        }
    
    #这是处理 Raw XML 错误的核心逻辑
    if not last_msg.tool_calls:
        # 如果路由到了这里但没有 tool_calls，说明 Router 认为是 Raw XML 错误
        print("DEBUG: critic_tools_node detected Raw XML format. Sending System Warning.")
        return {
            "critic_messages": [SystemMessage(content="系统严重警告：检测到你输出了无效的工具调用格式（Raw XML）。这会导致工具无法执行。请使用正确的 Tool/Function Calling 格式重新发起调用！")]
        }

    tool_node = ToolNode(tools)

    result = tool_node.invoke({"messages": [last_msg]})
    
    return {
        "critic_messages": result["messages"],
        "critic_tool_count": state.get("critic_tool_count", 0) + 1
    }
    
def increment_loop(state: AgentState):
    """增加循环计数，并重置工具计数器以便下一轮使用。"""
    return {
        "loop_count": state.get("loop_count", 0) + 1,
        "writer_tool_count": 0,
        "critic_tool_count": 0
    }

def reset_critic_tools(state: AgentState):
    """在 Writer -> Critic 转换时，重置 Critic 的工具计数器。"""
    return {"critic_tool_count": 0} 

# --- 图构建 (Graph Construction) ---
workflow = StateGraph(AgentState)

workflow.add_node("writer", writer_node)
workflow.add_node("critic", critic_node)
workflow.add_node("tools_writer", writer_tools_node)
workflow.add_node("tools_critic", critic_tools_node)
workflow.add_node("increment_loop", increment_loop)
workflow.add_node("reset_critic", reset_critic_tools) 

workflow.set_entry_point("writer")

# Writer 分支
workflow.add_conditional_edges(
    "writer",
    writer_router,
    {"tools_writer": "tools_writer", "critic": "reset_critic"} 
)

# 中间节点连接
workflow.add_edge("reset_critic", "critic")
workflow.add_edge("tools_writer", "writer")

# Critic 分支
workflow.add_conditional_edges(
    "critic",
    critic_router,
    {
        "tools_critic": "tools_critic", 
        "increment_loop": "increment_loop",
        END: END
    }
)

workflow.add_edge("tools_critic", "critic")
workflow.add_edge("increment_loop", "writer")

# 创建内存检查点，支持多会话
memory = MemorySaver()
app = workflow.compile(checkpointer=memory)
