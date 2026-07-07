from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..models import ActionResult, FollowUpResult, MeetingInsight, MeetingStatus, MeetingSummary


class FollowUpAgent:
    async def process(self, state: dict) -> dict:
        meeting_id = state["meeting_id"]
        summary: MeetingSummary | None = state.get("summary")
        actions: ActionResult | None = state.get("actions")
        insights: MeetingInsight | None = state.get("insights")

        report_url = self._write_report(meeting_id, summary, actions, insights)
        state["followup"] = FollowUpResult(
            meeting_id=meeting_id,
            recipients=summary.participants if summary else [],
            reminders_scheduled=len(actions.action_items) if actions else 0,
            report_url=report_url,
            stored_in_vector_db=False,
        )
        state["status"] = MeetingStatus.COMPLETED.value
        return state

    @staticmethod
    def _write_report(
        meeting_id: str,
        summary: MeetingSummary | None,
        actions: ActionResult | None,
        insights: MeetingInsight | None,
    ) -> str:
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)
        path = reports_dir / f"{meeting_id}.md"

        lines = [
            f"# 会议报告 - {meeting_id}",
            "",
            f"生成时间: {datetime.now().isoformat(timespec='seconds')}",
            "",
            "## 会议纪要",
            "",
        ]
        if summary:
            lines.extend([f"### {summary.title}", "", f"参会人: {', '.join(summary.participants)}", ""])
            for topic in summary.topics:
                lines.extend([f"#### {topic.title}", ""])
                lines.extend(f"- {point}" for point in topic.discussion_points)
                if topic.conclusion:
                    lines.append(f"- 结论: {topic.conclusion}")
                lines.append("")
            lines.extend(["### 决策", ""])
            lines.extend(f"- {item}" for item in summary.decisions)

        lines.extend(["", "## 待办事项", ""])
        if actions:
            for item in actions.action_items:
                lines.append(f"- {item.assignee}: {item.task} | {item.deadline} | {item.priority.value}")

        lines.extend(["", "## 会议洞察", ""])
        if insights:
            lines.append(f"- 整体情绪: {insights.overall_sentiment} ({insights.sentiment_score})")
            lines.append(f"- 效率评分: {insights.efficiency_score}/10")
            lines.append(f"- 关键词: {', '.join(insights.keywords)}")
            lines.extend(f"- {item}" for item in insights.highlights)

        try:
            path.write_text("\n".join(lines), encoding="utf-8")
        except OSError:
            pass
        return f"/reports/{path.name}"
