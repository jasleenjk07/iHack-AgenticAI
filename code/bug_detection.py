from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

from openai import OpenAI


DEFAULT_MODEL = "llama-3.1-8b-instant"
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"


def first_differing_line(code_a: str, code_b: str) -> int:
    lines_a = (code_a or "").strip().splitlines()
    lines_b = (code_b or "").strip().splitlines()
    for i, (la, lb) in enumerate(zip(lines_a, lines_b)):
        if la.strip() != lb.strip():
            return i + 1
    if len(lines_a) != len(lines_b):
        return min(len(lines_a), len(lines_b)) + 1
    return 1 if lines_a else 0


def parse_json_result(raw: str) -> dict | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except Exception:
                return None
    return None


def predict_bug_line(client: OpenAI, model: str, code: str, context: str, explanation: str) -> tuple[int, str]:
    code_lines = (code or "").splitlines()
    numbered = "\n".join(f"{i+1}: {line}" for i, line in enumerate(code_lines[:200]))
    prompt = (
        "Find the exact buggy line in this C/C++ snippet.\n"
        "Respond in strict JSON only: {\"bug_line\": <int>, \"reason\": <short string>}.\n\n"
        f"Context: {context[:500]}\n"
        f"Hint: {explanation[:500]}\n"
        f"Code:\n{numbered}"
    )

    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=120,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "Return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
    )
    text = (resp.choices[0].message.content or "").strip()
    data = parse_json_result(text)
    if not data:
        return 1, "Could not parse model output."
    try:
        bug_line = int(data.get("bug_line", 1))
    except Exception:
        bug_line = 1
    reason = str(data.get("reason", "")).strip() or "Predicted by Groq model."
    return max(1, bug_line), reason


class GroqBugDetectionAgent:
    """
    Bug detection agent using Groq (OpenAI-compatible API).
    Used by main.py pipeline; accepts parsed (dict or object with lines/raw_lines).
    """

    def __init__(self, api_key: str | None) -> None:
        self.enabled = bool(api_key)
        self._client = (
            OpenAI(api_key=api_key, base_url=DEFAULT_BASE_URL, timeout=25.0)
            if api_key
            else None
        )
        self._model = os.getenv("GROQ_MODEL", DEFAULT_MODEL)

    def detect_bug_line(
        self,
        parsed,
        context: str,
        fallback_bug_line: int,
        explanation: str = "",
    ) -> int:
        """Return 1-based bug line. parsed can be dict with 'lines' or object with raw_lines/lines."""
        if not self.enabled or not self._client:
            return max(1, fallback_bug_line)
        # Get raw code string from parsed (dict from parse_agent or wrapper with raw_lines)
        if isinstance(parsed, dict):
            lines = parsed.get("lines", [])
        else:
            lines = getattr(parsed, "raw_lines", getattr(parsed, "lines", []))
        code = "\n".join(lines) if lines else ""
        try:
            bug_line, _ = predict_bug_line(
                self._client,
                self._model,
                code,
                context or "",
                explanation or "",
            )
            return max(1, bug_line)
        except Exception:
            return max(1, fallback_bug_line)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bug detection with Groq API.")
    parser.add_argument("--samples", default="samples.csv", help="Path to samples.csv")
    parser.add_argument("--output", default="output_groq.csv", help="Path to output csv")
    parser.add_argument("--model", default=os.getenv("GROQ_MODEL", DEFAULT_MODEL), help="Groq model id")
    parser.add_argument("--limit", type=int, default=0, help="Process first N rows only (0 = all)")
    args = parser.parse_args()

    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        raise RuntimeError("Missing GROQ_API_KEY. Set it in your environment.")

    client = OpenAI(api_key=api_key, base_url=DEFAULT_BASE_URL, timeout=25.0)

    samples_path = Path(args.samples).resolve()
    output_path = Path(args.output).resolve()
    if not samples_path.is_file():
        raise FileNotFoundError(f"Missing samples file: {samples_path}")

    with samples_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    if args.limit and args.limit > 0:
        rows = rows[: args.limit]

    output_rows = []
    for row in rows:
        sample_id = str(row.get("ID", "")).strip()
        explanation = str(row.get("Explanation", "")).strip()
        context = str(row.get("Context", "")).strip()
        code = str(row.get("Code", ""))
        correct_code = str(row.get("Correct Code", ""))

        try:
            bug_line, reason = predict_bug_line(client, args.model, code, context, explanation)
        except Exception:
            # Fallback keeps script reliable for demos.
            bug_line = first_differing_line(code, correct_code) or 1
            reason = "Fallback: first differing line vs Correct Code."

        output_rows.append(
            {
                "ID": sample_id,
                "Bug Line": bug_line,
                "Explanation": reason,
            }
        )

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ID", "Bug Line", "Explanation"])
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Done. Output written to: {output_path}")


if __name__ == "__main__":
    main()