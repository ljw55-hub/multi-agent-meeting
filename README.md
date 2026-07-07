# Multi-Agent HY Meeting Assistant

一个可演示、可继续扩展、适合放到 GitHub 的多 Agent 智能会议助手。项目参考 `multi-agent-meeting-assistant-guide-zh` 和原始 `python` 代码，但这里重新整理成更干净的学习版工程，重点是你能讲清楚架构、节点职责和落地路径。

## 功能闭环

- FastAPI REST API 和 WebSocket 接入层
- LangGraph Pipeline + Fan-out/Fan-in 编排
- 5 个 Agent 节点：
  - `TranscriptionAgent`：音频转写入口，当前提供 demo transcript，后续可接 WhisperX
  - `SummaryAgent`：生成结构化会议纪要
  - `ActionAgent`：抽取负责人、任务、截止时间、优先级
  - `InsightAgent`：统计发言占比、关键词、会议亮点和效率评分
  - `FollowUpAgent`：汇总结果并生成会后报告路径
- 离线 fallback 模式：没有 OpenAI/MiniMax Key 时也能跑完整 demo
- Docker Compose 本地环境：API + PostgreSQL + Redis + ChromaDB

## 快速启动

```bash
docker compose up -d --build
```

然后访问：

- API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health

运行 demo：

```bash
curl -X POST http://localhost:8000/api/v1/meeting/demo/demo
```

如果 Docker Hub 网络拉取 `python:3.11-slim` 超时，等网络恢复后重试同一条命令即可。

## API 示例

创建会议：

```bash
curl -X POST http://localhost:8000/api/v1/meeting/start ^
  -H "Content-Type: application/json" ^
  -d "{\"title\":\"Q3预算评审会\",\"participants\":[\"张总\",\"李明\",\"王芳\",\"赵伟\"],\"language\":\"zh\"}"
```

运行指定会议 demo：

```bash
curl -X POST http://localhost:8000/api/v1/meeting/{meeting_id}/demo
```

查询完整报告：

```bash
curl http://localhost:8000/api/v1/meeting/{meeting_id}/report
```

## 环境变量

复制 `.env.example` 为 `.env`，按需填写：

```bash
LLM_PROVIDER=offline
OPENAI_API_KEY=
MINIMAX_API_KEY=
MINIMAX_GROUP_ID=
```

`LLM_PROVIDER=offline` 时会使用规则 fallback，适合面试演示和本地开发。需要接真实模型时改为 `openai` 或 `minimax` 并填写 Key。

## 面试讲法

- LangGraph 负责把会议处理流程显式建模为状态图：转写先执行，纪要/待办/洞察并行执行，最后由跟进 Agent 汇总。
- 每个 Agent 只写自己负责的状态字段，便于排错、观测和替换。
- 规则逻辑负责确定性计算，例如发言统计；LLM 负责语义理解，例如纪要、待办和洞察。
- fallback 模式保证系统在没有模型 Key、外部 API 异常时仍能完成主流程，这体现工程可用性。
