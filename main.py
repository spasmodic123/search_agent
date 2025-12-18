import sys
import re
import os
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, AIMessageChunk
from graph import app

def clean_filename(topic):
    """将 topic 转换为合法的文件名"""
    # 将非字母数字的字符替换为下划线，去掉多余下划线
    filename = re.sub(r'[^\w\s-]', '', topic).strip().lower()
    return re.sub(r'[-\s]+', '_', filename)


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <topic>")
        sys.exit(1)
    
    topic = " ".join(sys.argv[1:])
    
    print(f"--- Starting Search Agent for: {topic} ---")
    
    system_prompt = (
        "You are a smart research assistant. "
        "Your goal is to research the user's topic using the web search and visit_page tools. "
        "1. Use `search_web` to find relevant pages. "
        "2. Use `visit_page` to read detailed content from promising URLs. "
        "3. Synthesize information into a comprehensive Markdown report. "
        "The document should have a clear title, headings, and bullet points. "
        "请用中文回答"
    )
    
    first_input = {"writer_messages": [
        SystemMessage(content=system_prompt),
        HumanMessage(content=topic)
    ]}

    # 用于存储最后一条消息的内容,save as local markdown file
    final_content = ""
    

    # stream_mode="values"：
    # for event in app.stream(inputs, stream_mode="values", config={"recursion_limit": 50}):
    #     message = event["messages"][-1]
    #     message.pretty_print()

    #     # 实时更新 final_content，如果是 Writer 的消息且有内容，就记录下来
    #     if isinstance(message, AIMessage) and message.content and getattr(message, 'name', None) == 'writer':
    #         final_content = message.content


    # stream_mode="updates"：
    for event in app.stream(first_input, stream_mode="updates", config={"recursion_limit": 80}):
        for node_name, node_val in event.items():
            if "writer_messages" in node_val and node_val["writer_messages"]:
                message = node_val["writer_messages"][-1]
                message.pretty_print()
            elif "critic_messages" in node_val and node_val["critic_messages"]:
                message = node_val["critic_messages"][-1]
                message.pretty_print()
                
            # Update draft if present
            if "current_draft" in node_val and node_val["current_draft"]:
                final_content = node_val["current_draft"]
    

    # stream_mode="messages"
        # --- 状态追踪变量 ---
    # 用于缓存拼凑的消息： key=message_id, value=full_text_so_far
    # message_buffer = {} 
    # # 记录最后一条来自 writer 节点的消息 ID
    # last_writer_msg_id = None
    # # 记录当前正在输出的节点名称，用于打印 Header
    # current_node = None 
    
    # # 核心修改：使用 stream_mode="messages"
    # for msg_chunk, metadata in app.stream(inputs, stream_mode="messages", config={"recursion_limit": 50}):
        
    #     # metadata 包含了当前 Token 来自哪个节点，例如 {'langgraph_node': 'writer', ...}
    #     node_name = metadata.get("langgraph_node")

    #     # --- 1. 打印节点归属 Header (类似 pretty_print 的效果) ---
    #     if node_name != current_node:
    #         # 根据不同角色打印不同的标题
    #         header_icon = "🤖"
    #         role_name = node_name.upper()  
    #         if node_name == "writer":
    #             header_icon = "✍️✍️✍️✍️✍️✍️✍️"
    #             role_name = "WRITER (Thinking/Writing)"
    #         elif node_name == "critic":
    #             header_icon = "🕵️🕵️🕵️🕵️🕵️🕵️🕵️"
    #             role_name = "CRITIC (Reviewing)"
    #         elif node_name == "tools":
    #             header_icon = "🛠️🛠️🛠️🛠️🛠️🛠️🛠️"
    #             role_name = "TOOL OUTPUT"
    #         # 打印分隔线和角色名
    #         print(f"\n\n{header_icon} --- [ {role_name} ] ---\n")
    #         current_node = node_name
        
    #     # 1. 实时打印逻辑 (打字机效果)
    #     # 我们只打印有内容的 chunk，且为了美观，可以只打印 writer 和 critic 的发言
    #     # 情况 A: 文本内容 (Writer/Critic 的回复，或 Tool 的搜索结果)
    #     if msg_chunk.content:
    #         print(msg_chunk.content, end="", flush=True)
        
    #     # 情况 B: 工具调用请求 (Writer 正在构造参数去调用工具)
    #     # 这时 content 通常为空，但在 tool_call_chunks 里有数据
    #     if hasattr(msg_chunk, 'tool_call_chunks') and msg_chunk.tool_call_chunks:
    #         # 简单可视化：打印参数片段，让用户知道 Agent 正在尝试操作
    #         for chunk in msg_chunk.tool_call_chunks:
    #             # 打印工具名或参数片段（通常是 JSON 碎片）
    #             if chunk.get("name"):
    #                 print(f"\n[Call Tool: {chunk['name']}] args: ", end="", flush=True)
    #             if chunk.get("args"):
    #                 print(chunk["args"], end="", flush=True)
        
    #     # 2. 内容捕获逻辑 (为了保存文件)
    #     # 我们只关心 writer 生成的内容作为最终报告
    #     # 注意：writer 可能会多次发言（比如先说“我要搜索...”，最后才说“这是报告...”）
    #     # 我们通过不断更新 last_writer_msg_id，最终保留 writer 说的“最后一段话”
    #     if node_name == "writer" and isinstance(msg_chunk, AIMessageChunk):
    #         # 获取消息的唯一 ID (LangChain 会自动生成，或者流式中保持一致)
    #         msg_id = msg_chunk.id 
            
    #         # 如果没有 ID (极少数情况)，用 "temp" 代替，但这可能导致覆盖问题
    #         if not msg_id: 
    #             msg_id = "temp_writer_id"

    #         # 初始化或追加内容
    #         if msg_id not in message_buffer:
    #             message_buffer[msg_id] = ""
            
    #         # 只有当 chunk 有文本内容时才追加 (忽略 tool_call_chunks)
    #         if msg_chunk.content:
    #             message_buffer[msg_id] += msg_chunk.content
    #             # 标记这是 Writer 发出的最新一条文本消息
    #             last_writer_msg_id = msg_id

    # # --- 提取最终内容 ---
    # if last_writer_msg_id and last_writer_msg_id in message_buffer:
    #     final_content = message_buffer[last_writer_msg_id]
                

    print("\n\n--- Stream finished ---")
    # --- 保存文件逻辑 ---
    if final_content:
        # 1. 创建 output 文件夹（如果不存在）
        output_dir = "output"
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # 2. 生成文件名
        filename = f"{clean_filename(topic)}.md"
        filepath = os.path.join(output_dir, filename)
        
        # 3. 写入文件
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(final_content)
            print(f"\n✅ Document saved successfully to: {filepath}")
        except Exception as e:
            print(f"\n❌ Failed to save document: {e}")
    else:
        print("\n⚠️ No content was generated to save.")


if __name__ == "__main__":
    main()


'''
Step 1: 启动与系统提示 (main.py)
程序开始，构建初始输入：
    SystemMessage: "你是研究助理...请搜索并总结..." (设定了 Agent 的人设和目标)。
    HumanMessage: "The future of quantum computing"。
调用 app.stream(inputs) 开始图的执行。
Step 2: 第一轮思考 (进入 graph.py 的 agent 节点)
    Input: System Prompt + User Query。
    LLM 处理: LLM 发现自己不知道量子计算的最新未来，且这需要外部知识。
    LLM Output: 返回一个 AIMessage，内容为空，但包含 tool_calls: name='search_web', args={'query': 'future of quantum computing'}。
    Edge 判断: tools_condition 检测到 tool_calls，将流向指引到 tools 节点。
Step 3: 执行工具 (进入 graph.py 的 tools 节点)
    Input: 上一步的 AIMessage (包含调用指令)。
    Action: ToolNode 解析指令，真正执行 search_web("future of quantum computing")。
    DDGS: 访问 DuckDuckGo，抓取 Top 5 结果。
    Output: 生成一个 ToolMessage，内容是搜索到的 JSON 字符串/文本。
    Edge: 强制流回 agent 节点。
Step 4: 第二轮思考 (回到 agent 节点)
Input (此时的状态):
    [0] SystemMessage
    [1] HumanMessage (User input)
    [2] AIMessage (I want to search...)
    [3] ToolMessage (Here are the search results...)
LLM 处理: LLM 阅读了 [3] 中的搜索结果。
    情况 A: 信息不够 -> LLM 再次生成 tool_calls (搜索另一个关键词)，循环回 Step 3。
    情况 B: 信息足够 -> LLM 开始根据 Prompt 的要求（撰写 Markdown 文档）进行综合。
LLM Output: 返回一个 AIMessage，内容是最终的 Markdown 总结文章。不包含 tool_calls。
Edge 判断: tools_condition 发现没有工具调用，路由到 END。
Step 5: 输出结果 (main.py)
    app.stream 也是一个生成器。在上述每一个 Step 完成时，main.py 中的循环都会收到更新的 event。
'''