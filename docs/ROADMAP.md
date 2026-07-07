# 项目路线图

这份路线图用于说明当前 demo 的边界，以及后续如何逐步演进成一个更完整的多 Agent 会议助手项目。

## 当前版本：Demo 闭环版

目标：先保证系统能跑通，能演示多 Agent 编排链路，能用于面试讲解。

已完成：

- FastAPI REST API
- WebSocket 接入口
- LangGraph Pipeline + Fan-out/Fan-in 编排
- 5 个 Agent 节点：
  - Transcription Agent
  - Summary Agent
  - Action Agent
  - Insight Agent
  - Follow-up Agent
- offline fallback 模式
- Docker Compose 本地运行环境
- PostgreSQL、Redis、ChromaDB 服务预留
- 教程、架构说明、面试讲解文档

当前边界：

- Transcription Agent 使用内置 demo transcript，没有接入真实音频转写。
- Summary、Action、Insight 默认走规则 fallback，没有强依赖 LLM API。
- ChromaDB 服务已启动，但会议内容还没有真正向量化入库。
- PostgreSQL、Redis 当前作为基础设施预留，还没有完整业务读写。

## Milestone 1：接入真实 LLM

目标：让纪要、待办、洞察由真实模型生成，同时保留 fallback 兜底。

计划：

- 支持 OpenAI-compatible API
- 支持 MiniMax API
- 为 Summary Agent 设计结构化 JSON Prompt
- 为 Action Agent 设计任务抽取 Prompt
- 为 Insight Agent 设计会议洞察 Prompt
- 增加 LLM 调用失败重试和超时控制
- 增加模型输出 JSON 解析和 schema 校验

验收标准：

- 设置 `LLM_PROVIDER=openai` 或 `LLM_PROVIDER=minimax` 后，demo 接口能调用真实模型。
- 模型异常时，系统自动回退到 offline fallback。

## Milestone 2：接入真实音频转写

目标：支持上传会议音频，并生成带说话人和时间戳的转写结果。

计划：

- 接入 WhisperX
- 恢复 Dockerfile 中的 ffmpeg 依赖
- 支持 wav、mp3、m4a 等常见音频格式
- 增加音频文件大小和格式校验
- 预留 pyannote speaker diarization 接口

验收标准：

- 上传音频文件后，`TranscriptionAgent` 能输出 `TranscriptResult`。
- 后续 Summary、Action、Insight 能基于真实转写继续执行。

## Milestone 3：会议内容向量化入库

目标：把会议转写、纪要、待办写入 ChromaDB，支持历史会议语义检索。

计划：

- 设计 meeting chunk 切分策略
- 增加 embedding client
- 将 transcript、summary、actions 写入 ChromaDB
- 提供历史会议搜索 API
- 支持基于历史会议上下文的问答

验收标准：

- demo 执行后，会议内容能写入 ChromaDB。
- 可以通过关键词或自然语言问题检索历史会议内容。

## Milestone 4：结构化持久化

目标：用 PostgreSQL 存储会议、转写、待办、报告状态。

计划：

- 设计会议表、转写片段表、待办表、报告表
- 接入 SQLAlchemy
- 保存每次 pipeline 执行结果
- 支持按会议 ID 查询历史结果

验收标准：

- 服务重启后，历史会议报告仍可查询。
- 待办事项可以按负责人、状态、截止时间筛选。

## Milestone 5：实时处理和 WebSocket 推送

目标：支持前端通过 WebSocket 接收会议处理进度和结果。

计划：

- 设计 WebSocket 消息协议
- 推送 recording、processing、transcript、summary、actions、completed 事件
- Redis 保存会话状态
- 支持断线重连后查询处理结果

验收标准：

- 客户端连接 WebSocket 后，能看到 pipeline 阶段进度。
- 处理完成后能收到完整结果。

## Milestone 6：前端演示页面

目标：提供一个直观的 Web 页面，方便面试演示。

计划：

- 创建会议
- 上传音频或运行 demo
- 展示会议转写
- 展示会议纪要
- 展示待办列表
- 展示发言统计和关键词

验收标准：

- 面试时可以不依赖 Swagger，通过页面完整演示项目。

## Milestone 7：外部系统集成

目标：把待办和会议纪要同步到实际协作工具。

计划：

- 飞书机器人发送会议纪要
- 飞书任务或多维表格同步待办
- Jira issue 创建
- 邮件发送会议报告

验收标准：

- Action Agent 抽取的任务可以同步到至少一个外部系统。
- Follow-up Agent 可以发送会议报告。

## 推荐面试表述

当前版本不是追求一次性堆满所有功能，而是先完成可运行的核心链路，再按工程优先级逐步增强：

1. 先跑通多 Agent 编排和接口闭环。
2. 再接真实 LLM，提升语义生成质量。
3. 再接真实音频转写，拓展输入能力。
4. 再做向量库和数据库持久化，提升长期可用性。
5. 最后接前端和外部系统，形成完整产品体验。

这样的路线能保证每个阶段都有可演示成果，也方便在面试中解释取舍和演进思路。
