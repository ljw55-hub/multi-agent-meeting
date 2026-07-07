# 系统架构说明

## 总体架构

```text
Client
  -> FastAPI / WebSocket Gateway
  -> LangGraph Meeting Pipeline
     -> Transcription Agent
     -> Summary Agent
     -> Action Agent
     -> Insight Agent
     -> Follow-up Agent
  -> PostgreSQL / Redis / ChromaDB
```

## 分层说明

### 1. 接入层

接入层由 FastAPI 提供：

- REST API：用于创建会议、运行 demo、查询报告
- WebSocket：预留实时音频流接入和结果推送
- Swagger：提供接口调试页面

核心文件：

```text
src/main.py
src/api/routes.py
```

### 2. 编排层

编排层负责把多个 Agent 串成一个可执行流程。当前使用 LangGraph：

- `State`：会议处理过程中的共享状态
- `Node`：每个 Agent 是一个节点
- `Edge`：定义 Agent 的执行顺序

核心文件：

```text
src/graph/meeting_graph.py
```

### 3. Agent 层

当前实现 5 个 Agent：

- `TranscriptionAgent`：生成会议转写
- `SummaryAgent`：生成会议纪要
- `ActionAgent`：提取待办事项
- `InsightAgent`：生成会议洞察
- `FollowUpAgent`：汇总会后跟进结果

核心目录：

```text
src/agents/
```

### 4. 模型层

模型层使用 Pydantic 定义结构化数据：

- `TranscriptResult`
- `MeetingSummary`
- `ActionResult`
- `MeetingInsight`
- `FollowUpResult`

核心文件：

```text
src/models/schemas.py
```

### 5. 集成层

集成层负责外部能力适配。当前实现了 LLM 客户端：

- offline：规则 fallback
- openai：OpenAI-compatible JSON output
- minimax：MiniMax JSON output

核心文件：

```text
src/integrations/llm_client.py
```

## 为什么用 Pipeline + Fan-out/Fan-in

会议处理天然分为两个阶段：

1. 先转写，因为后续 Agent 都依赖文本。
2. 纪要、待办、洞察可以并行，因为三者互不依赖。
3. 最后 Follow-up 汇总三类结果，生成会后跟进信息。

这就是：

```text
Transcription
  -> Summary
  -> Action
  -> Insight
  -> Follow-up
```

更准确地说是：

```text
Transcription
  -> [Summary, Action, Insight]
  -> Follow-up
```

## 工程兜底设计

当前项目有两个兜底：

- 没有 LLM API Key 时，使用规则 fallback。
- 没有安装 LangGraph 时，使用手动 async pipeline fallback。

这样做的好处是 demo 不会因为外部服务、网络或依赖问题完全不可用。
