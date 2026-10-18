"""Typography and layout formatting for competitive exam question stems.

Formats run-on text from multi-column exam PDFs (e.g. Syllogisms, Inequalities,
Input-Output steps) into clean, readable text with preserved line breaks and indentation.
"""
from __future__ import annotations

import re


def format_stem_typography(text: str) -> str:
    """Format question stem text with proper indentation and line breaks for Statements and Conclusions."""
    if not text:
        return ""

    s = text.strip()

    # Check if text contains Statements / Statement or Conclusions / Conclusion
    has_stmt = bool(re.search(r"\bStatements?\s*[:.-]", s, re.IGNORECASE))
    has_concl = bool(re.search(r"\bConclusions?\s*(?:[I|V|X]+|\d+)?\s*[:.-]", s, re.IGNORECASE))

    if not (has_stmt or has_concl):
        return s

    # 1. Isolate Conclusions block
    concl_match = re.search(r"\b(Conclusions?\s*(?:[I|V|X]+|\d+)?\s*[:.-].*)", s, re.IGNORECASE | re.DOTALL)
    concls_text = ""
    stmts_text = s
    if concl_match:
        concls_text = concl_match.group(1).strip()
        stmts_text = s[:concl_match.start()].strip()

    # 2. In stmts_text, isolate preamble and Statements:
    stmt_match = re.search(r"\b(Statements?\s*[:.-])\s*(.*)", stmts_text, re.IGNORECASE | re.DOTALL)
    preamble = ""
    stmt_header = ""
    stmt_body = stmts_text
    if stmt_match:
        preamble = stmts_text[:stmt_match.start()].strip()
        stmt_header = stmt_match.group(1).strip()
        # Capitalize nicely (e.g. "Statements:")
        if stmt_header.lower().startswith("statements"):
            stmt_header = "Statements:"
        elif stmt_header.lower().startswith("statement"):
            stmt_header = "Statement:"
        stmt_body = stmt_match.group(2).strip()

    out_lines: list[str] = []
    if preamble:
        out_lines.append(preamble)
        out_lines.append("")

    if stmt_header:
        out_lines.append(stmt_header)
        # Check if stmt_body contains Syllogism quantifiers
        # e.g. "Only a few Lakes are Rivers Some Rivers are Puddles No Puddle is a Pond"
        quant_pat = r"(?<!^)(?<!\bOnly\s)(?<!\bA\s)\b(Only a few|Some|All|No|Few|None|Only)\b"
        tokens = re.split(quant_pat, stmt_body)
        if len(tokens) > 1:
            i = 0
            while i < len(tokens):
                t = tokens[i].strip()
                if not t:
                    i += 1
                    continue
                if t in ("Only a few", "Some", "All", "No", "Few", "None", "Only"):
                    next_t = tokens[i + 1].strip() if i + 1 < len(tokens) else ""
                    out_lines.append(f"  • {t} {next_t}".rstrip())
                    i += 2
                else:
                    out_lines.append(f"  • {t}")
                    i += 1
        else:
            out_lines.append(f"  {stmt_body}")
    elif stmt_body:
        out_lines.append(stmt_body)

    if concls_text:
        out_lines.append("\nConclusions:")
        # Parse individual conclusions: "Conclusion I: Some ... Conclusion II: ..." or "I. ... II. ..."
        c_parts = re.split(
            r"(?:Conclusion\s*([I|V|X]+|\d+)\s*[:.-]|(?:\b|^)([I|V|X]+|\d+)\s*[:.-])",
            concls_text,
            flags=re.IGNORECASE,
        )

        items: list[tuple[str, str]] = []
        i = 1
        while i < len(c_parts):
            num = c_parts[i] or (c_parts[i + 1] if i + 1 < len(c_parts) else "")
            idx_next = i + 1
            while idx_next < len(c_parts) and not (c_parts[idx_next] and len(c_parts[idx_next].strip()) > 3):
                idx_next += 1
            body = c_parts[idx_next].strip() if idx_next < len(c_parts) else ""
            body = re.sub(r"Conclusion\s*[I|V|X|\d]+.*", "", body, flags=re.IGNORECASE).strip()
            if num and body:
                items.append((num.upper(), body))
            i = idx_next + 1

        if items:
            for num, body in items:
                out_lines.append(f"  {num}. {body}")
        else:
            cleaned_c = re.sub(r"^Conclusions?\s*[:.-]\s*", "", concls_text, flags=re.IGNORECASE)
            out_lines.append(f"  {cleaned_c}")

    return "\n".join(out_lines)
