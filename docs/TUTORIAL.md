# 从零运行教程

这份教程用于把 demo 跑起来，并理解每一步背后的系统设计。当前版本是“可演示闭环版”：没有真实音频和 LLM API Key 也能跑完整多 Agent 流程。

## 1. 环境准备

需要安装：

- Docker Desktop
- Docker Compose

检查命令：

```bash
docker --version
docker compose version
```

## 2. 启动服务

在项目根目录执行：

```bash
docker compose up -d --build
```

启动后会有 4 个容器：

- `multi-agent-hy-api`：FastAPI 后端
- `multi-agent-hy-postgres`：关系数据库，预留会议元数据和任务存储
- `multi-agent-hy-redis`：缓存和任务状态服务
- `multi-agent-hy-chromadb`：向量数据库，预留历史会议检索

检查状态：

```bash
docker compose ps
```

## 3. 访问接口文档

浏览器打开：

```text
http://localhost:8000/docs
```

健康检查：

```text
http://localhost:8000/health
```

预期返回：

```json
{"status":"ok"}
```

## 4. 运行会议 Demo

在 Swagger 页面找到：

```text
POST /api/v1/meeting/demo/{meeting_id}
```

点击 `Try it out`，`meeting_id` 填：

```text
demo
```

点击 `Execute`。

也可以用命令：

```bash
curl -X POST http://localhost:8000/api/v1/meeting/demo/demo
```

## 5. Demo 执行链路

当前 demo 会模拟一段会议转写，然后执行完整 Agent Pipeline：

```text
Transcription Agent
  -> Summary Agent
  -> Action Agent
  -> Insight Agent
  -> Follow-up Agent
```

实际编排是：

```text
Start
  -> Transcription
  -> Summary / Action / Insight 并行
  -> Follow-up 汇总
  -> End
```

## 6. 返回结果怎么看

接口返回 JSON 中的关键字段：

- `transcript`：会议转写，包含 speaker、text、start、end
- `summary`：结构化会议纪要，包含议题、决策、下一步
- `actions`：待办事项，包含负责人、任务、截止时间、优先级
- `insights`：会议洞察，包含发言统计、关键词、亮点、建议
- `followup`：会后跟进结果，包含提醒数量和报告地址

## 7. 接入真实 LLM

默认 `.env` 使用：

```env
LLM_PROVIDER=offline
```

这表示系统使用规则 fallback，不调用外部模型。

如果要接 OpenAI：

```env
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=你的Key
```

如果要接 MiniMax：

```env
LLM_PROVIDER=minimax
MINIMAX_API_KEY=你的Key
MINIMAX_GROUP_ID=你的GroupId
```

改完后重启：

```bash
docker compose up -d --build
```

## 8. 常见问题

### Docker Hub 拉取超时

当前 Dockerfile 默认使用国内镜像源：

```dockerfile
ARG PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.11-slim
```

如果你在海外环境，可以改成：

```dockerfile
ARG PYTHON_IMAGE=python:3.11-slim
```

### PowerShell 显示中文乱码

接口本身返回的是 UTF-8。PowerShell 有时会把中文显示成乱码，建议优先用浏览器访问 Swagger。

### 为什么现在没有真实音频转写

当前版本先保证多 Agent 编排闭环。真实音频转写需要接入 WhisperX、ffmpeg、模型权重和可能的 GPU 环境，适合放到下一阶段。
