"""Agent-based monitoring tasks - autonomous investigation and monitoring."""
import datetime
import logging
from typing import Optional

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc

from app.models import Article, Classification, AgentTask
from app.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

logger = logging.getLogger(__name__)


# Pre-built agent task templates
AGENT_TEMPLATES = {
    "monitor_topic": {
        "name": "主题监测",
        "description": "持续监测特定主题的新动态并生成摘要",
        "instructions": """你是一个专业的AI+Crypto行业监测Agent。请完成以下任务：
1. 分析所有与目标主题相关的最新文章
2. 提取关键事实和重要变化
3. 判断是否有需要立即关注的信号
4. 生成简洁的监测报告（中文）

输出格式:
- 新动态数量
- 最重要的3个发现
- 趋势判断（升温/平稳/降温）
- 风险提示（如有）
- 建议下一步关注点
""",
    },
    "investigate_entity": {
        "name": "实体调查",
        "description": "深入调查特定公司/项目/人物的最新进展",
        "instructions": """你是一个专业的尽调分析Agent。请完成以下调查：
1. 收集目标实体的所有最新信息
2. 分析其近期活动模式
3. 识别潜在的积极信号和风险信号
4. 评估信息的可靠性

输出格式:
- 调查对象概况
- 近期关键事件（按时间排序）
- 积极信号
- 风险信号
- 信息可靠性评估
- 总体判断和建议
""",
    },
    "verify_narrative": {
        "name": "叙事验证",
        "description": "验证某个流行叙事/说法的真实性",
        "instructions": """你是一个专业的事实核查Agent。请验证以下叙事：
1. 识别叙事中的核心声明
2. 寻找支持和反对的证据
3. 评估信息来源的可信度
4. 给出验证结论

输出格式:
- 核心声明提取
- 支持证据（来源+内容）
- 反对证据（来源+内容）
- 来源可信度评估
- 验证结论（已证实/部分证实/未证实/虚假）
- 置信度（0-100%）
""",
    },
    "risk_assessment": {
        "name": "风险评估",
        "description": "对特定项目或领域进行系统性风险评估",
        "instructions": """你是一个专业的风险评估Agent。请完成以下评估：
1. 收集目标的所有风险相关信息
2. 分类风险类型（监管/技术/市场/团队/竞争）
3. 评估每类风险的概率和影响
4. 给出整体风险等级

输出格式:
- 风险概况
- 监管风险: [等级] - [说明]
- 技术风险: [等级] - [说明]
- 市场风险: [等级] - [说明]
- 团队风险: [等级] - [说明]
- 竞争风险: [等级] - [说明]
- 整体风险等级: [低/中/高/极高]
- 关键风险触发点
- 风险缓解建议
""",
    },
}


def create_agent_task(
    db: Session,
    name: str,
    task_type: str,
    target: str,
    instructions: str = None,
    schedule: str = None,
    template: str = None,
) -> AgentTask:
    """Create a new agent monitoring task."""
    # Use template if specified
    if template and template in AGENT_TEMPLATES:
        tmpl = AGENT_TEMPLATES[template]
        if not instructions:
            instructions = tmpl["instructions"]
        if not name:
            name = f"{tmpl['name']}: {target}"

    task = AgentTask(
        name=name,
        description=f"Agent task: {task_type} for {target}",
        task_type=task_type,
        target=target,
        instructions=instructions or "",
        schedule=schedule,
        status="active",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def execute_agent_task(db: Session, task_id: int) -> dict:
    """Execute an agent task and return results."""
    task = db.query(AgentTask).filter(AgentTask.id == task_id).first()
    if not task:
        return {"error": "Task not found"}

    if task.status == "paused":
        return {"error": "Task is paused"}

    logger.info(f"Executing agent task: {task.name} (type: {task.task_type})")

    # Gather relevant data based on task type and target
    context = _gather_task_context(db, task)

    # Execute with LLM if available
    if OPENAI_API_KEY:
        result = _execute_with_llm(task, context)
    else:
        result = _execute_rule_based(task, context)

    # Update task
    task.last_run_at = datetime.datetime.utcnow()
    task.last_result = result.get("report", "")
    task.run_count += 1
    db.commit()

    return result


def _gather_task_context(db: Session, task: AgentTask) -> dict:
    """Gather relevant articles and data for the task."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=7)

    # Search by target keyword
    articles = db.query(Article).options(
        joinedload(Article.classification),
        joinedload(Article.score),
        joinedload(Article.source),
    ).filter(
        Article.fetched_at >= since,
    ).order_by(desc(Article.published_at)).limit(200).all()

    target_lower = task.target.lower()
    relevant = []
    for article in articles:
        text = f"{article.title} {article.raw_content or ''}".lower()
        tags = article.classification.tags if article.classification and article.classification.tags else []
        entities = [e.get("name", "").lower() for e in (article.classification.entities or [])] if article.classification else []

        if (target_lower in text or
            target_lower in [t.lower() for t in tags] or
            target_lower in entities):
            relevant.append(article)

    return {
        "target": task.target,
        "task_type": task.task_type,
        "articles": relevant[:30],
        "total_found": len(relevant),
    }


def _execute_with_llm(task: AgentTask, context: dict) -> dict:
    """Execute task using LLM."""
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    # Prepare article summaries
    article_summaries = []
    for a in context["articles"][:20]:
        source_name = a.source.name if a.source else "Unknown"
        score = a.score.total_score if a.score else 0
        content_type = a.classification.content_type if a.classification else "unknown"
        article_summaries.append(
            f"- [{content_type}] {a.title} (来源: {source_name}, 评分: {score:.2f}, 时间: {a.published_at})"
        )

    prompt = f"""任务: {task.name}
类型: {task.task_type}
目标: {task.target}
相关文章数: {context['total_found']}

相关文章列表:
{chr(10).join(article_summaries)}

---

{task.instructions or '请根据以上信息生成分析报告。'}
"""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "你是一个专业的AI+Crypto/Web3行业分析Agent，擅长系统性地分析信息并给出有洞察力的结论。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=1500,
        )
        report = response.choices[0].message.content
        return {
            "status": "success",
            "report": report,
            "articles_analyzed": len(context["articles"]),
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Agent LLM execution error: {e}")
        return _execute_rule_based(task, context)


def _execute_rule_based(task: AgentTask, context: dict) -> dict:
    """Fallback rule-based execution."""
    articles = context["articles"]

    if not articles:
        return {
            "status": "no_data",
            "report": f"未找到与 '{task.target}' 相关的近期文章。",
            "articles_analyzed": 0,
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }

    # Generate simple report
    report_lines = [
        f"# Agent 监测报告: {task.target}",
        f"时间: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
        f"相关文章: {len(articles)} 篇",
        "",
        "## 最新动态",
    ]

    for i, a in enumerate(articles[:10], 1):
        score = a.score.total_score if a.score else 0
        report_lines.append(f"{i}. {a.title} (评分: {score:.2f})")

    # Tag analysis
    from collections import Counter
    tag_counter = Counter()
    for a in articles:
        if a.classification and a.classification.tags:
            for tag in a.classification.tags:
                tag_counter[tag] += 1

    report_lines.append("\n## 相关主题")
    for tag, count in tag_counter.most_common(10):
        report_lines.append(f"- {tag}: {count}次")

    # Risk indicators
    high_risk = [a for a in articles if a.classification and a.classification.regulation_risk > 0.5]
    high_hype = [a for a in articles if a.classification and a.classification.hype_risk > 0.5]

    report_lines.append(f"\n## 风险指标")
    report_lines.append(f"- 高监管风险文章: {len(high_risk)}篇")
    report_lines.append(f"- 高炒作风险文章: {len(high_hype)}篇")

    report_lines.append("\n---")
    report_lines.append("*注: 配置 OPENAI_API_KEY 可获得 AI 深度分析报告*")

    return {
        "status": "success",
        "report": "\n".join(report_lines),
        "articles_analyzed": len(articles),
        "timestamp": datetime.datetime.utcnow().isoformat(),
    }


def list_agent_tasks(db: Session, status: str = None) -> list:
    """List all agent tasks."""
    query = db.query(AgentTask)
    if status:
        query = query.filter(AgentTask.status == status)
    return query.order_by(desc(AgentTask.created_at)).all()


def pause_agent_task(db: Session, task_id: int) -> bool:
    """Pause an agent task."""
    task = db.query(AgentTask).filter(AgentTask.id == task_id).first()
    if task:
        task.status = "paused"
        db.commit()
        return True
    return False


def resume_agent_task(db: Session, task_id: int) -> bool:
    """Resume a paused task."""
    task = db.query(AgentTask).filter(AgentTask.id == task_id).first()
    if task:
        task.status = "active"
        db.commit()
        return True
    return False


def delete_agent_task(db: Session, task_id: int) -> bool:
    """Delete an agent task."""
    task = db.query(AgentTask).filter(AgentTask.id == task_id).first()
    if task:
        db.delete(task)
        db.commit()
        return True
    return False


def get_agent_templates() -> list[dict]:
    """Get available agent task templates."""
    return [
        {"id": key, "name": val["name"], "description": val["description"]}
        for key, val in AGENT_TEMPLATES.items()
    ]
