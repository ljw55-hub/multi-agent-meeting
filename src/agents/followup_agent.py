from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from ..integrations.email_client import EmailClient
from ..integrations.feishu_client import FeishuClient
from ..models import ActionResult, FollowUpResult, MeetingInsight, MeetingStatus, MeetingSummary

logger = logging.getLogger(__name__)


class FollowUpAgent:
    """Final fan-in node that publishes meeting follow-up artifacts."""

    def __init__(
        self,
        email: EmailClient | None = None,
        feishu: FeishuClient | None = None,
    ) -> None:
        self.email = email or EmailClient()
        self.feishu = feishu or FeishuClient()

    async def process(self, state: dict) -> dict:
        meeting_id = state["meeting_id"]
        summary: MeetingSummary | None = state.get("summary")
        actions: ActionResult | None = state.get("actions")
        insights: MeetingInsight | None = state.get("insights")

        report_url, report_error = self._write_report(meeting_id, summary, actions, insights)
        if report_error:
            state["errors"] = state.get("errors", []) + [report_error]

        title = summary.title if summary else f"Meeting {meeting_id}"
        summary_md = _format_summary(summary)
        actions_md = _format_actions(actions)
        insights_md = _format_insights(insights)
        recipients = _email_recipients(summary.participants if summary else [])

        summary_sent = False
        if self.email.is_enabled and recipients:
            summary_sent = await self.email.send_meeting_report(
                title=title,
                recipients=recipients,
                summary_md=summary_md,
                actions_md=actions_md,
                insights_md=insights_md,
            )

        feishu_sent = False
        if self.feishu.webhook_url:
            feishu_sent = await self.feishu.send_meeting_summary(
                title=title,
                summary_md=summary_md,
                actions_md=actions_md,
                insights_md=insights_md,
            )

        state["followup"] = FollowUpResult(
            meeting_id=meeting_id,
            summary_sent=summary_sent or feishu_sent,
            recipients=recipients,
            jira_issues_created=[item.jira_issue_key for item in actions.action_items if item.jira_issue_key]
            if actions
            else [],
            feishu_tasks_created=[item.feishu_task_id for item in actions.action_items if item.feishu_task_id]
            if actions
            else [],
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
    ) -> tuple[str, str | None]:
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)
        path = reports_dir / f"{meeting_id}.md"

        lines = [
            f"# Meeting Report - {meeting_id}",
            "",
            f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
            "",
            "## Summary",
            "",
            _format_summary(summary),
            "",
            "## Action Items",
            "",
            _format_actions(actions),
            "",
            "## Insights",
            "",
            _format_insights(insights),
            "",
        ]

        try:
            path.write_text("\n".join(lines), encoding="utf-8")
        except OSError as exc:
            message = f"failed to write meeting report {path}: {exc}"
            logger.warning(message)
            return "", message
        return f"/reports/{path.name}", None


def _format_summary(summary: MeetingSummary | None) -> str:
    if not summary:
        return "No summary generated."

    lines = [f"### {summary.title}", ""]
    if summary.participants:
        lines.extend([f"Participants: {', '.join(summary.participants)}", ""])
    for topic in summary.topics:
        lines.extend([f"#### {topic.title}", ""])
        lines.extend(f"- {point}" for point in topic.discussion_points)
        if topic.conclusion:
            lines.append(f"- Conclusion: {topic.conclusion}")
        lines.append("")
    if summary.decisions:
        lines.extend(["#### Decisions", ""])
        lines.extend(f"- {decision}" for decision in summary.decisions)
    if summary.next_steps:
        lines.extend(["", "#### Next Steps", ""])
        lines.extend(f"- {step}" for step in summary.next_steps)
    return "\n".join(lines).strip()


def _format_actions(actions: ActionResult | None) -> str:
    if not actions or not actions.action_items:
        return "No action items generated."

    lines = []
    for item in actions.action_items:
        sync_parts = []
        if item.jira_issue_key:
            sync_parts.append(f"Jira: {item.jira_issue_key}")
        if item.feishu_task_id:
            sync_parts.append(f"Feishu: {item.feishu_task_id}")
        sync_suffix = f" ({'; '.join(sync_parts)})" if sync_parts else ""
        lines.append(
            f"- [{item.priority.value}] {item.assignee}: {item.task}"
            f" | deadline: {item.deadline or 'N/A'}{sync_suffix}"
        )
    return "\n".join(lines)


def _format_insights(insights: MeetingInsight | None) -> str:
    if not insights:
        return "No insights generated."

    lines = [
        f"- Sentiment: {insights.overall_sentiment} ({insights.sentiment_score})",
        f"- Efficiency score: {insights.efficiency_score}/10",
    ]
    if insights.keywords:
        lines.append(f"- Keywords: {', '.join(insights.keywords)}")
    if insights.highlights:
        lines.append("- Highlights:")
        lines.extend(f"  - {highlight}" for highlight in insights.highlights)
    if insights.speaker_stats:
        lines.append("- Speaker statistics:")
        lines.extend(
            f"  - {stat.speaker}: {stat.percentage:.1f}% ({stat.duration_s:.1f}s)"
            for stat in insights.speaker_stats
        )
    return "\n".join(lines)


def _email_recipients(participants: list[str]) -> list[str]:
    return [participant for participant in participants if "@" in participant]
