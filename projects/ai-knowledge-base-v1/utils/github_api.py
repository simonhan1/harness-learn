import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import TypedDict

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
RATE_LIMIT_INTERVAL = 1.0


class RepoInfo(TypedDict):
    """Typed structure for GitHub repository basic information."""

    full_name: str
    stars: int
    forks: int
    description: str
    url: str
    language: str


def _make_request(url: str, token: str | None) -> dict:
    """Send a GET request to GitHub API with optional authentication.

    Args:
        url: The GitHub API endpoint URL.
        token: GitHub personal access token, or None.

    Returns:
        Parsed JSON response as a dict.

    Raises:
        ConnectionError: If the network request fails.
        ValueError: If the HTTP status is not 200.
    """
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.getcode()
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        status = e.code
        body = e.read().decode("utf-8")
    except urllib.error.URLError as e:
        raise ConnectionError(f"Failed to connect to GitHub API: {e.reason}") from e

    if status == 403:
        raise ValueError("GitHub API rate limit exceeded. Set GITHUB_TOKEN env var to increase limit.")
    if status == 404:
        raise ValueError("Repository not found. Check that the owner and repo name are correct.")
    if status != 200:
        raise ValueError(f"GitHub API returned HTTP {status}: {body}")

    return json.loads(body)


def get_repo_info(owner: str, repo: str) -> RepoInfo:
    """Fetch basic information about a GitHub repository.

    Authenticated requests have a higher rate limit (5000/h vs 60/h).
    Set the ``GITHUB_TOKEN`` environment variable to use authentication.

    Args:
        owner: Repository owner (user or organization name).
        repo: Repository name.

    Returns:
        A ``RepoInfo`` dict with keys: full_name, stars, forks,
        description, url, language.

    Raises:
        ValueError: If the repository is not found or the rate limit is exceeded.
        ConnectionError: If the GitHub API is unreachable.

    Example:
        >>> info = get_repo_info("microsoft", "vscode")
        >>> info["stars"]
        168000
    """
    token = os.getenv("GITHUB_TOKEN")
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"

    if token:
        logger.debug("Fetching repo info for %s/%s (authenticated)", owner, repo)
    else:
        logger.info(
            "Fetching repo info for %s/%s (unauthenticated — rate limit 60 req/h). "
            "Set GITHUB_TOKEN env var for 5000 req/h.",
            owner, repo,
        )

    try:
        data = _make_request(url, token)
        logger.debug("Successfully fetched repo info for %s/%s", owner, repo)
    except (ValueError, ConnectionError):
        logger.exception("Failed to fetch repo info for %s/%s", owner, repo)
        raise

    time.sleep(RATE_LIMIT_INTERVAL)

    return RepoInfo(
        full_name=data.get("full_name", ""),
        stars=data.get("stargazers_count", 0),
        forks=data.get("forks_count", 0),
        description=data.get("description") or "",
        url=data.get("html_url", ""),
        language=data.get("language") or "",
    )


def get_trending_repos(language: str = "python", since: str = "daily") -> list[dict]:
    """Fetch trending repositories via GitHub's search API.

    Note: This uses the GitHub Search API, not the trending page.
    Results are sorted by stars, updated within the given time window.

    Args:
        language: Programming language filter. Defaults to "python".
        since: Time window filter ("daily", "weekly", "monthly"). Defaults to "daily".

    Returns:
        List of raw repository dicts from the search API.

    Raises:
        ValueError: If the search API returns an error.
        ConnectionError: If the GitHub API is unreachable.
    """
    token = os.getenv("GITHUB_TOKEN")

    days_map = {"daily": 1, "weekly": 7, "monthly": 30}
    delta = timedelta(days=days_map.get(since, 1))
    since_date = (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%d")
    qualifier = f"created:>={since_date}"
    query = f"language:{language} {qualifier}"
    encoded_query = urllib.parse.quote(query)
    url = f"{GITHUB_API_BASE}/search/repositories?q={encoded_query}&sort=stars&order=desc&per_page=30"

    logger.debug("Searching trending repos: %s", query)

    try:
        data = _make_request(url, token)
        items = data.get("items", [])
        logger.info("Found %d trending repos for language=%s since=%s", len(items), language, since)
        return items
    except (ValueError, ConnectionError):
        logger.exception("Failed to fetch trending repos")
        raise
