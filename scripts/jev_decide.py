"""Jev decision layer for search/evidence triage.

This script NEVER performs web search and NEVER writes findings/raw records.
It converts already-observed search results or evidence passages into advisory
probabilistic decisions that a skill runner can use to reduce expensive reading.

Subcommands:
  screen-search   Search result snippets -> open/skip priorities.
  route-evidence  Evidence passages -> relevant metric/face probabilities.
  judge-band      Evidence for one formal metric -> candidate rubric band.
  verify-claims   Claim + evidence -> support/contradiction probabilities.

All outputs are review artifacts.  They are not evidence and must never be
cited as a source or injected into raw/batch*.json as if Jev had browsed a page.
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple
from urllib.parse import urlparse

from common import read, rules, write
from jev_client import JevClient, JevError, answer_choice, answer_confidence, answer_noul, choice_probability


def _records(path: str) -> List[Dict[str, Any]]:
    data = read(path)
    if isinstance(data, dict):
        for key in ("results", "records", "items", "passages", "claims"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        raise ValueError(f"{path}: 需要 JSON 数组，或含 results/records/items/passages/claims 数组的对象")
    out = []
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: 第{i+1}项必须是对象")
        r = dict(row)
        r.setdefault("id", f"R{i+1:04d}")
        out.append(r)
    return out


def _source_hint(url: str) -> str:
    try:
        host = (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return "unknown"
    if not host:
        return "unknown"
    if host.endswith(".gov.cn") or host == "gov.cn":
        return "government-domain"
    if host.endswith("sse.com.cn") or host.endswith("szse.cn") or host.endswith("hkexnews.hk"):
        return "exchange-domain"
    return "other-domain"


def _chunks(seq: Sequence[Dict[str, Any]], n: int) -> Iterable[Sequence[Dict[str, Any]]]:
    for i in range(0, len(seq), n):
        yield seq[i:i+n]


def screen_search_records(
    client: Any,
    records: Sequence[Dict[str, Any]],
    *,
    company: str,
    company_id: str = "",
    industry: str = "",
    region: str = "",
    keep_threshold: float = 0.68,
    entity_threshold: float = 0.60,
    batch_size: int = 32,
) -> Dict[str, Any]:
    if not company.strip():
        raise ValueError("screen-search 必须提供 --company")
    if not records:
        return {"records": [], "usage": [], "summary": {"input": 0, "kept": 0}}
    decisions, usages = [], []
    for batch_no, batch in enumerate(_chunks(list(records), max(1, min(batch_size, 80))), 1):
        candidates = []
        for idx, row in enumerate(batch):
            candidates.append({
                "index": idx,
                "id": row["id"],
                "title": row.get("title", ""),
                "snippet": row.get("snippet") or row.get("excerpt") or row.get("text") or "",
                "url": row.get("url", ""),
                "source_hint": _source_hint(row.get("url", "")),
                "query": row.get("query", ""),
            })
        state = {
            "target_company": company,
            "target_company_id": company_id,
            "industry": industry,
            "region": region,
            "task": "Screen web-search results before expensive page opening. Prefer concrete, target-specific evidence; reject homonyms, directories, generic SEO pages and duplicates.",
            "candidates": candidates,
        }
        questions: Dict[str, Dict[str, Any]] = {}
        for i in range(len(candidates)):
            questions[f"entity_{i}"] = {
                "type": "noul",
                "instructions": f"Does candidates[{i}] refer to the target company/entity rather than a namesake or unrelated entity?",
            }
            questions[f"open_{i}"] = {
                "type": "noul",
                "instructions": f"Should a researcher open candidates[{i}] because it is likely to contain concrete, auditable evidence useful for evaluating the target company?",
            }
            questions[f"primary_{i}"] = {
                "type": "noul",
                "instructions": f"Is candidates[{i}] likely to be a primary/official or otherwise authoritative source rather than a low-value aggregation page?",
            }
        response = client.system_one(state, questions)
        usages.append(response.get("usage"))
        answers = response["answers"]
        for i, row in enumerate(batch):
            entity_p = answer_noul(answers[f"entity_{i}"])
            open_p = answer_noul(answers[f"open_{i}"])
            primary_p = answer_noul(answers[f"primary_{i}"])
            # Do not let "official-looking" trump entity mismatch. Open probability is the main signal.
            priority = round(entity_p * (0.80 * open_p + 0.20 * primary_p), 6)
            keep = entity_p >= entity_threshold and open_p >= keep_threshold
            decisions.append(dict(row, jev={
                "entity_probability": round(entity_p, 6),
                "open_probability": round(open_p, 6),
                "primary_probability": round(primary_p, 6),
                "priority": priority,
                "keep": keep,
                "batch": batch_no,
            }))
    decisions.sort(key=lambda x: (-x["jev"]["keep"], -x["jev"]["priority"], x["id"]))
    return {
        "records": decisions,
        "usage": usages,
        "summary": {
            "input": len(records),
            "kept": sum(bool(x["jev"]["keep"]) for x in decisions),
            "keep_threshold": keep_threshold,
            "entity_threshold": entity_threshold,
        },
    }


def _labels_from_file(path: str) -> List[Dict[str, str]]:
    data = read(path)
    if isinstance(data, dict) and isinstance(data.get("labels"), list):
        data = data["labels"]
    elif isinstance(data, dict):
        data = [{"id": k, "description": v if isinstance(v, str) else ""} for k, v in data.items()]
    if not isinstance(data, list) or not data:
        raise ValueError("labels 文件须为非空数组、{labels:[...]} 或 id->description 映射")
    labels = []
    for i, x in enumerate(data):
        if isinstance(x, str):
            labels.append({"id": x, "description": x})
        elif isinstance(x, dict) and str(x.get("id", "")).strip():
            labels.append({"id": str(x["id"]).strip(), "description": str(x.get("description") or x.get("label") or x["id"]).strip()})
        else:
            raise ValueError(f"labels 第{i+1}项格式无效")
    if len({x['id'] for x in labels}) != len(labels):
        raise ValueError("labels id 重复")
    if len(labels) > 255:
        raise ValueError("labels 超过255；请拆分")
    return labels


def formal_metric_labels() -> List[Dict[str, str]]:
    _, items, _ = rules()
    return [{"id": i["id"], "description": f"{i['label']}。可用来源线索：{'、'.join(i.get('sources', []))}"} for i in items]


def route_one_passage(client: Any, row: Dict[str, Any], labels: Sequence[Dict[str, str]], company: str) -> Dict[str, Any]:
    text = row.get("text") or row.get("excerpt") or row.get("snippet") or ""
    if not str(text).strip():
        raise ValueError(f"passage {row['id']} 缺少 text/excerpt/snippet")
    state = {
        "target_company": company,
        "source_url": row.get("url", ""),
        "title": row.get("title", ""),
        "passage": text,
        "instruction_context": "Judge only what this passage directly supports. A passage may match multiple labels. Do not infer facts absent from the passage.",
    }
    questions = {
        f"label_{i}": {
            "type": "noul",
            "instructions": f"Does the passage contain concrete evidence directly relevant to this evaluation face/metric: {lab['id']} — {lab['description']}?",
        }
        for i, lab in enumerate(labels)
    }
    questions["target_entity"] = {
        "type": "noul",
        "instructions": "Does this passage actually describe the target company/entity rather than another company or a generic industry statement?",
    }
    response = client.system_one(state, questions)
    answers = response["answers"]
    probs = {lab["id"]: round(answer_noul(answers[f"label_{i}"]), 6) for i, lab in enumerate(labels)}
    return {
        **row,
        "jev": {
            "target_entity_probability": round(answer_noul(answers["target_entity"]), 6),
            "label_probabilities": probs,
        },
        "_usage": response.get("usage"),
    }


def route_evidence_records(client: Any, records: Sequence[Dict[str, Any]], labels: Sequence[Dict[str, str]], company: str, threshold: float, max_concurrency: int) -> Dict[str, Any]:
    out: List[Dict[str, Any]] = []
    with futures.ThreadPoolExecutor(max_workers=max(1, max_concurrency)) as ex:
        jobs = [ex.submit(route_one_passage, client, r, labels, company) for r in records]
        for job in jobs:
            out.append(job.result())
    usages = []
    for r in out:
        usages.append(r.pop("_usage", None))
        probs = r["jev"]["label_probabilities"]
        r["jev"]["matches"] = [k for k, v in sorted(probs.items(), key=lambda kv: -kv[1]) if v >= threshold]
        r["jev"]["threshold"] = threshold
    out.sort(key=lambda x: x["id"])
    return {"records": out, "usage": usages, "summary": {"input": len(records), "labels": len(labels), "threshold": threshold}}


def judge_band_one(client: Any, row: Dict[str, Any], item: Mapping[str, Any]) -> Dict[str, Any]:
    evidence = row.get("evidence") or row.get("excerpt") or row.get("text") or ""
    fact = row.get("fact") or ""
    if not str(evidence).strip() and not str(fact).strip():
        raise ValueError(f"record {row['id']} 缺少 evidence/fact")
    criteria = {band: f"Rubric label worth {score}/{item['max']} points" for band, score in item["bands"]}
    criteria["__INSUFFICIENT__"] = "The supplied evidence is insufficient, ambiguous, mismatched in entity/time/scope, or does not justify any rubric band."
    state = {
        "metric_id": item["id"],
        "metric_label": item["label"],
        "target_company": row.get("company_name", ""),
        "period": row.get("period", ""),
        "fact": fact,
        "evidence": evidence,
        "source_title": row.get("title", ""),
        "source_url": row.get("url", ""),
    }
    response = client.system_one(state, {
        "band": {
            "type": "choice",
            "instructions": "Choose the single rubric band directly supported by the supplied evidence. Do not reward missing information; choose __INSUFFICIENT__ when the evidence cannot support a band.",
            "criteria": criteria,
        }
    })
    ans = response["answers"]["band"]
    choice = answer_choice(ans)
    return {
        **row,
        "jev": {
            "metric_id": item["id"],
            "band_choice": choice,
            "band_probability": choice_probability(ans, choice),
            "confidence": answer_confidence(ans),
            "advisory_only": True,
        },
        "_usage": response.get("usage"),
    }


def judge_band_records(client: Any, records: Sequence[Dict[str, Any]], metric_id: str, max_concurrency: int) -> Dict[str, Any]:
    _, items, _ = rules(); imap = {i["id"]: i for i in items}
    if metric_id not in imap:
        raise ValueError(f"未知正式指标 {metric_id}")
    out = []
    with futures.ThreadPoolExecutor(max_workers=max(1, max_concurrency)) as ex:
        jobs = [ex.submit(judge_band_one, client, r, imap[metric_id]) for r in records]
        for job in jobs:
            out.append(job.result())
    usage = [r.pop("_usage", None) for r in out]
    out.sort(key=lambda x: x["id"])
    return {"records": out, "usage": usage, "summary": {"input": len(records), "metric_id": metric_id}}


def verify_claim_one(client: Any, row: Dict[str, Any]) -> Dict[str, Any]:
    claim = row.get("claim") or row.get("fact") or ""
    evidence = row.get("evidence") or row.get("excerpt") or row.get("text") or ""
    if not str(claim).strip() or not str(evidence).strip():
        raise ValueError(f"record {row['id']} 需要 claim/fact 和 evidence/excerpt/text")
    state = {"claim": claim, "evidence": evidence, "source_url": row.get("url", ""), "period": row.get("period", "")}
    response = client.system_one(state, {
        "supports": {"type": "noul", "instructions": "Does the evidence directly support the claim as written, including entity, time and scope?"},
        "contradicts": {"type": "noul", "instructions": "Does the evidence directly contradict the claim as written?"},
    })
    return {
        **row,
        "jev": {
            "support_probability": round(answer_noul(response["answers"]["supports"]), 6),
            "contradiction_probability": round(answer_noul(response["answers"]["contradicts"]), 6),
            "advisory_only": True,
        },
        "_usage": response.get("usage"),
    }


def verify_claim_records(client: Any, records: Sequence[Dict[str, Any]], max_concurrency: int) -> Dict[str, Any]:
    out = []
    with futures.ThreadPoolExecutor(max_workers=max(1, max_concurrency)) as ex:
        jobs = [ex.submit(verify_claim_one, client, r) for r in records]
        for job in jobs:
            out.append(job.result())
    usage = [r.pop("_usage", None) for r in out]
    out.sort(key=lambda x: x["id"])
    return {"records": out, "usage": usage, "summary": {"input": len(records)}}


class _FakeClient:
    """Only for --dry-run schema checks; never presented as model output."""
    def system_one(self, state: Any, questions: Mapping[str, Mapping[str, Any]], model: str | None = None) -> Dict[str, Any]:
        answers = {}
        for key, q in questions.items():
            if q.get("type") == "choice":
                first = next(iter(q.get("criteria", {"__INSUFFICIENT__": None})))
                answers[key] = {"type": "choice", "choice": first, "confidence": 0.0, "probabilities": {first: 0.0}}
            else:
                answers[key] = {"type": "noul", "noul": 0.0}
        return {"model": "dry-run", "answers": answers, "usage": {"dry_run": True}}


def main() -> None:
    ap = argparse.ArgumentParser(description="Jev-assisted search/evidence triage")
    ap.add_argument("--dry-run", action="store_true", help="仅验证输入输出结构，不调用Jev，不得把结果当模型判断")
    sub = ap.add_subparsers(dest="command", required=True)

    s = sub.add_parser("screen-search", help="搜索结果snippet批量初筛")
    s.add_argument("--input", required=True); s.add_argument("--output", required=True)
    s.add_argument("--company", required=True); s.add_argument("--company-id", default="")
    s.add_argument("--industry", default=""); s.add_argument("--region", default="")
    s.add_argument("--keep-threshold", type=float, default=0.68)
    s.add_argument("--entity-threshold", type=float, default=0.60)
    s.add_argument("--batch-size", type=int, default=32)

    s = sub.add_parser("route-evidence", help="passage路由到粗采面或23维正式指标")
    s.add_argument("--input", required=True); s.add_argument("--output", required=True)
    s.add_argument("--company", required=True)
    group = s.add_mutually_exclusive_group(required=False)
    group.add_argument("--labels", help="自定义面/标签JSON；粗采45面应从这里传入，不能让Jev自行发明")
    group.add_argument("--formal-metrics", action="store_true", help="使用现有23维正式评分指标（默认）")
    s.add_argument("--threshold", type=float, default=0.70)
    s.add_argument("--max-concurrency", type=int, default=8)

    s = sub.add_parser("judge-band", help="针对一个正式指标给出档位建议")
    s.add_argument("--input", required=True); s.add_argument("--output", required=True)
    s.add_argument("--metric", required=True); s.add_argument("--max-concurrency", type=int, default=8)

    s = sub.add_parser("verify-claims", help="claim-evidence语义复核")
    s.add_argument("--input", required=True); s.add_argument("--output", required=True)
    s.add_argument("--max-concurrency", type=int, default=8)

    args = ap.parse_args()
    client = _FakeClient() if args.dry_run else JevClient()
    rows = _records(args.input)

    if args.command == "screen-search":
        result = screen_search_records(client, rows, company=args.company, company_id=args.company_id,
            industry=args.industry, region=args.region, keep_threshold=args.keep_threshold,
            entity_threshold=args.entity_threshold, batch_size=args.batch_size)
    elif args.command == "route-evidence":
        labels = _labels_from_file(args.labels) if args.labels else formal_metric_labels()
        result = route_evidence_records(client, rows, labels, args.company, args.threshold, args.max_concurrency)
        result["labels"] = labels
    elif args.command == "judge-band":
        result = judge_band_records(client, rows, args.metric, args.max_concurrency)
    else:
        result = verify_claim_records(client, rows, args.max_concurrency)
    result["dry_run"] = bool(args.dry_run)
    write(args.output, result)
    print(json.dumps(result.get("summary", {}), ensure_ascii=False))


if __name__ == "__main__":
    main()
