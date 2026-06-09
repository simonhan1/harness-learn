"""Supervisor pattern: Quality assurance monitoring for AI-generated content.

This module implements a supervisor-worker pattern where:
1. Worker Agent: Receives a task and outputs a JSON-formatted analysis report
2. Supervisor Agent: Reviews Worker's output for quality assurance
   - Evaluation dimensions: accuracy (1-10), depth (1-10), format (1-10)
   - Output: {"passed": bool, "score": int, "feedback": str}
3. Iterative Refinement:
   - Pass (score >= 7): Return result
   - Fail: Provide feedback and retry (max 3 rounds)
   - Timeout (> 3 rounds): Force return with warning

Usage:
    from patterns.supervisor import supervisor

    result = supervisor("Analyze the impact of GPT-4 on AI industry")
    print(f"Status: {'Passed' if result['passed'] else 'Failed'}")
    print(f"Score: {result['final_score']}/30")
    print(f"Attempts: {result['attempts']}")
    if 'warning' in result:
        print(f"Warning: {result['warning']}")
"""

import json
import logging
import sys
from pathlib import Path

# Add parent directory to path for relative imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.model_client import create_client, LLMResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MAX_RETRIES = 3
PASS_SCORE_THRESHOLD = 7
MAX_TOTAL_SCORE = 30  # 10 + 10 + 10 (accuracy + depth + format)


# ---------------------------------------------------------------------------
# Worker Agent
# ---------------------------------------------------------------------------


def worker_agent(task: str) -> dict:
    """Worker Agent: Generate analysis report for the given task.

    Args:
        task: The task description/query to analyze.

    Returns:
        Dict containing the analysis report with the following keys:
            - title: Brief title of the analysis
            - summary: 1-3 sentence summary
            - key_points: List of 3-5 key insights
            - analysis: Detailed analysis text
            - references: Optional list of relevant sources/references

    Raises:
        RuntimeError: If LLM call fails after retries.
    """
    client = create_client()

    system_prompt = """You are an AI research analyst. Your task is to provide thorough, 
insightful analysis on given topics. Output your analysis as a JSON object with the following structure:
{
    "title": "Brief title of your analysis",
    "summary": "1-3 sentence summary of key findings",
    "key_points": ["point 1", "point 2", "point 3", ...],
    "analysis": "Detailed analysis covering the topic comprehensively",
    "references": ["reference 1", "reference 2", ...]
}

Ensure your output is valid JSON and covers the topic thoroughly."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Analyze: {task}"},
    ]

    logger.info("Worker Agent: Processing task: %s", task[:50])

    response = client.chat_with_retry(
        messages,
        temperature=0.7,
        max_tokens=2048,
        node_name="supervisor_worker",
    )

    # Parse the JSON response
    try:
        # Try to extract JSON from the response (in case there's surrounding text)
        content = response.content.strip()
        
        # Find JSON object boundaries
        start_idx = content.find("{")
        end_idx = content.rfind("}") + 1
        
        if start_idx == -1 or end_idx == 0:
            raise ValueError("No JSON object found in response")
        
        json_str = content[start_idx:end_idx]
        analysis = json.loads(json_str)
        
        logger.debug("Worker Agent: Successfully generated analysis")
        return analysis
        
    except json.JSONDecodeError as e:
        logger.error("Worker Agent: Failed to parse JSON response: %s", e)
        # Return a fallback structure
        return {
            "title": "Analysis Report",
            "summary": response.content[:200],
            "key_points": [response.content[:100]],
            "analysis": response.content,
            "references": [],
        }


# ---------------------------------------------------------------------------
# Supervisor Agent
# ---------------------------------------------------------------------------


def supervisor_agent(
    task: str,
    worker_output: dict,
    feedback: str | None = None,
) -> dict:
    """Supervisor Agent: Review Worker's output for quality assurance.

    Evaluates the Worker's analysis across three dimensions:
    - Accuracy (1-10): Is the information factually correct?
    - Depth (1-10): How thoroughly does it cover the topic?
    - Format (1-10): Is it well-structured and readable?

    Args:
        task: Original task description.
        worker_output: Worker Agent's output dict.
        feedback: Optional feedback from previous supervisor review.

    Returns:
        Dict with the following keys:
            - passed: bool indicating if score >= 7
            - accuracy_score: 1-10
            - depth_score: 1-10
            - format_score: 1-10
            - score: Total score (accuracy + depth + format)
            - feedback: Detailed feedback and improvement suggestions

    Raises:
        RuntimeError: If LLM call fails after retries.
    """
    client = create_client()

    # Build review context
    worker_output_str = json.dumps(worker_output, ensure_ascii=False, indent=2)
    
    feedback_context = ""
    if feedback:
        feedback_context = f"\n\nPrevious supervisor feedback to address:\n{feedback}"

    system_prompt = """You are a quality assurance expert. Review the Worker Agent's analysis output 
and evaluate it across three dimensions. Output a JSON object with this structure:
{
    "accuracy_score": <1-10>,
    "depth_score": <1-10>,
    "format_score": <1-10>,
    "passed": <true/false>,
    "feedback": "Detailed feedback on strengths, weaknesses, and specific improvements needed"
}

Scoring guidelines:
- Accuracy (1-10): Factual correctness, reliability of information
- Depth (1-10): Thoroughness of analysis, coverage of important aspects
- Format (1-10): JSON validity, clarity, organization, readability

Pass threshold: Total score (sum of three dimensions) >= 21 (out of 30)
Fail threshold: Total score < 21

Provide constructive feedback that helps the Worker improve."""

    user_content = f"""Please review this analysis output:

Task: {task}

Worker Output:
{worker_output_str}{feedback_context}

Evaluate the output and provide quality scores + feedback."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    logger.info("Supervisor Agent: Reviewing worker output")

    response = client.chat_with_retry(
        messages,
        temperature=0.5,
        max_tokens=1024,
        node_name="supervisor_review",
    )

    # Parse the JSON response
    try:
        content = response.content.strip()
        
        # Find JSON object boundaries
        start_idx = content.find("{")
        end_idx = content.rfind("}") + 1
        
        if start_idx == -1 or end_idx == 0:
            raise ValueError("No JSON object found in response")
        
        json_str = content[start_idx:end_idx]
        review = json.loads(json_str)
        
        # Ensure all required fields are present
        accuracy = review.get("accuracy_score", 5)
        depth = review.get("depth_score", 5)
        format_score = review.get("format_score", 5)
        total_score = accuracy + depth + format_score
        
        result = {
            "accuracy_score": accuracy,
            "depth_score": depth,
            "format_score": format_score,
            "score": total_score,
            "passed": total_score >= (PASS_SCORE_THRESHOLD * 3),
            "feedback": review.get("feedback", "No feedback provided"),
        }
        
        logger.debug(
            "Supervisor Agent: Review complete - Score: %d/30, Passed: %s",
            total_score,
            result["passed"],
        )
        return result
        
    except (json.JSONDecodeError, KeyError) as e:
        logger.error("Supervisor Agent: Failed to parse review response: %s", e)
        # Return a default fail review
        return {
            "accuracy_score": 4,
            "depth_score": 4,
            "format_score": 4,
            "score": 12,
            "passed": False,
            "feedback": "Please improve the analysis: ensure factual accuracy, deeper coverage, and proper JSON formatting.",
        }


# ---------------------------------------------------------------------------
# Main Supervisor Function
# ---------------------------------------------------------------------------


def supervisor(task: str, max_retries: int = DEFAULT_MAX_RETRIES) -> dict:
    """Supervisor monitoring pattern: Iteratively review and refine Worker output.

    Workflow:
    1. Worker Agent generates analysis for the task
    2. Supervisor Agent reviews the output
    3. If score >= 7 per dimension, return result
    4. Otherwise, provide feedback to Worker and retry (max 3 times)
    5. After max retries, return with warning

    Args:
        task: The task description/query to analyze.
        max_retries: Maximum number of retry attempts (default: 3).

    Returns:
        Dict with the following keys:
            - output: Final analysis output from Worker
            - passed: bool indicating final status
            - attempts: Number of attempts made
            - final_score: Total score from final review (out of 30)
            - accuracy_score: Final accuracy score (out of 10)
            - depth_score: Final depth score (out of 10)
            - format_score: Final format score (out of 10)
            - warning: (optional) Warning message if max retries exceeded

    Raises:
        RuntimeError: If Worker or Supervisor agent fails unexpectedly.
    """
    logger.info("Supervisor: Starting supervision cycle for task: %s", task[:50])

    attempt = 0
    worker_output = None
    review_result = None
    feedback = None

    while attempt < max_retries:
        attempt += 1
        logger.info("Supervisor: Attempt %d/%d", attempt, max_retries)

        try:
            # Step 1: Worker Agent generates analysis
            logger.debug("Supervisor: Invoking Worker Agent (attempt %d)", attempt)
            worker_output = worker_agent(task)
            
            # Step 2: Supervisor Agent reviews the output
            logger.debug("Supervisor: Invoking Supervisor Agent (attempt %d)", attempt)
            review_result = supervisor_agent(task, worker_output, feedback)

            # Step 3: Check if review passed
            if review_result["passed"]:
                logger.info(
                    "Supervisor: Review passed on attempt %d with score %d/30",
                    attempt,
                    review_result["score"],
                )
                return {
                    "output": worker_output,
                    "passed": True,
                    "attempts": attempt,
                    "final_score": review_result["score"],
                    "accuracy_score": review_result["accuracy_score"],
                    "depth_score": review_result["depth_score"],
                    "format_score": review_result["format_score"],
                }

            # Step 4: Review failed, extract feedback for retry
            feedback = review_result.get("feedback", "Please improve the analysis.")
            logger.warning(
                "Supervisor: Review failed on attempt %d with score %d/30. Feedback: %s",
                attempt,
                review_result["score"],
                feedback[:100],
            )

        except RuntimeError as e:
            logger.error("Supervisor: Agent call failed on attempt %d: %s", attempt, e)
            if attempt >= max_retries:
                raise

    # Step 5: Max retries exceeded
    logger.warning("Supervisor: Max retries (%d) exceeded", max_retries)

    if worker_output is None:
        raise RuntimeError("Worker Agent failed to produce output after all retries")

    warning_msg = (
        f"Maximum retries ({max_retries}) exceeded. "
        f"Final score: {review_result['score']}/30. "
        f"Please review the output manually."
    )

    return {
        "output": worker_output,
        "passed": False,
        "attempts": attempt,
        "final_score": review_result["score"],
        "accuracy_score": review_result["accuracy_score"],
        "depth_score": review_result["depth_score"],
        "format_score": review_result["format_score"],
        "warning": warning_msg,
    }


# ---------------------------------------------------------------------------
# Test Entry Point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    print("=" * 80)
    print("Supervisor Pattern Test - Quality Assurance Monitoring")
    print("=" * 80)

    test_tasks = [
        "Analyze the impact of transformer models on natural language processing",
        "What are the key differences between supervised and unsupervised learning?",
        "Explain how prompt engineering improves LLM performance",
    ]

    for i, test_task in enumerate(test_tasks, 1):
        print(f"\n[Test {i}] Task: {test_task}")
        print("-" * 80)

        try:
            result = supervisor(test_task, max_retries=3)

            status = "PASSED" if result['passed'] else "FAILED"
            print(f"Status: {status}")
            print(f"Attempts: {result['attempts']}")
            print(f"Final Score: {result['final_score']}/30")
            print(f"  - Accuracy:  {result['accuracy_score']}/10")
            print(f"  - Depth:     {result['depth_score']}/10")
            print(f"  - Format:    {result['format_score']}/10")

            if "warning" in result:
                print(f"\nWARNING: {result['warning']}")

            # Show output preview
            output = result["output"]
            if isinstance(output, dict):
                print(f"\nOutput Preview:")
                print(f"  Title: {output.get('title', 'N/A')}")
                summary = output.get("summary", "N/A")
                if len(summary) > 100:
                    summary = summary[:100] + "..."
                print(f"  Summary: {summary}")

        except Exception as e:
            print(f"[Error] {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 80)
    print("Test completed!")
    print("=" * 80)
