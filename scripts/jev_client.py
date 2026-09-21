"""Minimal TypeSafe Jev HTTP client for this skill.

No third-party dependency is required.  The client is intentionally isolated so
any agent/skill runner that can execute Python can use the same Jev decision
layer without Codex or an MCP plugin.

Configuration:
  TYPESAFE_API_KEY       preferred for live calls
  <skill-root>/.env      fallback when TYPESAFE_API_KEY is not set
  TYPESAFE_BASE_URL      default: https://api.typesafe.ai
  TYPESAFE_DEFAULT_MODEL default: jev-latest
  JEV_TIMEOUT_SECONDS    default: 30
  JEV_MAX_RETRIES        default: 3
"""
from __future__ import annotations

import argparse
import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from urllib import error, request


def _read_local_env() -> Dict[str, str]:
    """Read a minimal KEY=VALUE .env file from the skill root without dependencies."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return {}
    values: Dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


class JevError(RuntimeError):
    """Base error for Jev integration."""


class JevUnavailable(JevError):
    """Raised when live Jev cannot be used, most commonly because no key exists."""


@dataclass
class JevConfig:
    api_key: str
    base_url: str = "https://api.typesafe.ai"
    model: str = "jev-latest"
    timeout: float = 30.0
    max_retries: int = 3

    @classmethod
    def from_env(cls) -> "JevConfig":
        local = _read_local_env()
        def setting(name: str, default: str) -> str:
            return os.environ.get(name, local.get(name, default))
        return cls(
            api_key=setting("TYPESAFE_API_KEY", "").strip(),
            base_url=setting("TYPESAFE_BASE_URL", "https://api.typesafe.ai").strip().rstrip("/"),
            model=setting("TYPESAFE_DEFAULT_MODEL", "jev-latest").strip() or "jev-latest",
            timeout=float(setting("JEV_TIMEOUT_SECONDS", "30")),
            max_retries=max(0, int(setting("JEV_MAX_RETRIES", "3"))),
        )


class JevClient:
    def __init__(self, config: Optional[JevConfig] = None):
        self.config = config or JevConfig.from_env()
        if not self.config.api_key:
            raise JevUnavailable(
                "未设置 TYPESAFE_API_KEY。Jev 为可选决策层；无 key 时请按原流程继续，"
                "不要伪造 Jev 输出。"
            )

    @property
    def endpoint(self) -> str:
        return f"{self.config.base_url}/v1/systemone"

    def system_one(self, state: Any, questions: Mapping[str, Mapping[str, Any]], model: Optional[str] = None) -> Dict[str, Any]:
        if not isinstance(questions, Mapping) or not questions:
            raise ValueError("questions 必须是非空映射")
        payload = {
            "state": state,
            "model": model or self.config.model,
            "questions": dict(questions),
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "company-top50-skill/2.3-jev",
        }
        last_error: Optional[BaseException] = None
        for attempt in range(self.config.max_retries + 1):
            req = request.Request(self.endpoint, data=body, headers=headers, method="POST")
            try:
                with request.urlopen(req, timeout=self.config.timeout) as resp:
                    raw = resp.read().decode("utf-8")
                    data = json.loads(raw)
                    if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
                        raise JevError("Jev 响应缺少 answers")
                    return data
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                last_error = JevError(f"Jev HTTP {exc.code}: {detail[:800]}")
                if exc.code not in (429, 529) and exc.code < 500:
                    raise last_error
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = 0.0
                else:
                    delay = min(8.0, 0.5 * (2 ** attempt)) + random.random() * 0.15
            except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = JevError(f"Jev 请求失败: {exc}")
                delay = min(8.0, 0.5 * (2 ** attempt)) + random.random() * 0.15
            if attempt >= self.config.max_retries:
                break
            time.sleep(delay)
        raise last_error or JevError("Jev 请求失败")


def answer_noul(answer: Mapping[str, Any]) -> float:
    """Return a Noul yes-probability, accepting current response aliases defensively."""
    for key in ("noul", "probability", "value"):
        value = answer.get(key)
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
    raise JevError(f"无法解析 Noul answer: {answer}")


def answer_choice(answer: Mapping[str, Any]) -> str:
    for key in ("choice", "value"):
        value = answer.get(key)
        if isinstance(value, str) and value:
            return value
    raise JevError(f"无法解析 Choice answer: {answer}")


def answer_confidence(answer: Mapping[str, Any]) -> Optional[float]:
    value = answer.get("confidence")
    return float(value) if isinstance(value, (int, float)) else None


def choice_probability(answer: Mapping[str, Any], choice: Optional[str] = None) -> Optional[float]:
    choice = choice or answer_choice(answer)
    probs = answer.get("probabilities")
    if isinstance(probs, Mapping) and isinstance(probs.get(choice), (int, float)):
        return float(probs[choice])
    return answer_confidence(answer)


def config_summary() -> Dict[str, Any]:
    cfg = JevConfig.from_env()
    return {
        "configured": bool(cfg.api_key),
        "base_url": cfg.base_url,
        "model": cfg.model,
        "timeout_seconds": cfg.timeout,
        "max_retries": cfg.max_retries,
        "api_key_source": (
            "TYPESAFE_API_KEY" if os.environ.get("TYPESAFE_API_KEY", "").strip()
            else ("<skill-root>/.env" if cfg.api_key else None)
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Jev connection helper")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("config", help="仅检查配置，不发起收费请求")
    smoke = sub.add_parser("smoke", help="发起一个最小 live 请求，验证 API key")
    smoke.add_argument("--text", default="This is a test record about a company opening a new factory.")
    args = ap.parse_args()
    if args.command == "config":
        print(json.dumps(config_summary(), ensure_ascii=False, indent=2))
        return
    client = JevClient()
    response = client.system_one(
        {"text": args.text},
        {"relevant": {"type": "noul", "instructions": "Does the text contain a concrete company fact?"}},
    )
    out = {
        "model": response.get("model"),
        "relevant_probability": answer_noul(response["answers"]["relevant"]),
        "usage": response.get("usage"),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
