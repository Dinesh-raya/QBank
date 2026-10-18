"""Layered topic classification.

1. Transparent keyword/pattern rules for obvious cases (fast, deterministic).
2. Optional local-AI suggestion for questions the rules cannot place.
3. Manual correction in the UI (always available, always wins).

Rules return structured data validated against the taxonomy, never a free-text
paragraph, and never invent new topics. Confidence is expressed as a *method
label* (heuristic rule vs. model), never as a fabricated percentage.

Classification order follows the master prompt ("use the individual question's
task to determine its primary topic and use additional tags where appropriate"):

    1. rules over the question text together with its (non-chart) shared
       context, so the most specific rule wins; for chart/table contexts the
       stimulus is *not* consulted, and
    2. the context-type prior (a chart question with no distinguishing keyword
       becomes Data Interpretation),
    3. the optional local model.

The specific operation the question asks for (ratio / percentage / average)
stays the primary topic; the fact that it is chart- or table-based is recorded
as a ``data_interpretation`` tag rather than overwriting the topic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..taxonomy import Taxonomy
from . import local_model_adapter

# Comparators used to recognise inequality chains (letters, not digits).
_COMP = r"[<>\u2264\u2265\u2260]"
# Three letter elements chained by two comparators, e.g. "H < K <= P". Requiring
# a run of three avoids matching an isolated "F < G ... E > L" as could appear
# inside an alphanumeric character arrangement.
_INEQUALITY_CHAIN = rf"[A-Za-z]\s*{_COMP}\s*[A-Za-z]\s*{_COMP}\s*[A-Za-z]"

# (compiled pattern, subject, topic, subtopic)
_RULES: list[tuple[re.Pattern, str, str, Optional[str]]] = [
    # ---- Reasoning ----
    # A chain of letter elements joined by comparison operators is an
    # inequality question, e.g. "H < K <= P = R >= Y > M". This must be tested
    # before the syllogism rule, whose "Statement(s):/Conclusion" vocabulary it
    # shares.
    (re.compile(_INEQUALITY_CHAIN), "Reasoning Ability", "Inequality", None),
    (re.compile(r"(only a few|statements?\s*:|conclusion\s*(i|ii)\b)", re.I),
     "Reasoning Ability", "Syllogism", None),
    (re.compile(r"(conclusion\s+is\s+true|either conclusion|neither conclusion)", re.I),
     "Reasoning Ability", "Syllogism", None),
    (re.compile(r"(\b\d+\s*(?:th|nd|rd|st)?\s*(?:<|>|\u2264|\u2265|\u2260)\s*)", re.I),
     "Reasoning Ability", "Inequality", None),
    (re.compile(r"(floor|storeyed building|storey building|topmost floor)", re.I),
     "Reasoning Ability", "Floor Puzzle", None),
    (re.compile(r"(circular (table|arrangement)|around a circular)", re.I),
     "Reasoning Ability", "Circular Arrangement", None),
    (re.compile(r"(seating arrangement|sit(ting)? in a row|linear arrangement|facing (north|south))", re.I),
     "Reasoning Ability", "Seating Arrangement", None),
    (re.compile(r"(scheduled|days? of the (week|month)|months?|occasions?|consecutive|one after the other)", re.I),
     "Reasoning Ability", "Scheduling and Ordering Puzzles", None),
    (re.compile(r"(height|taller|shorter|shortest|tallest)\b", re.I),
     "Reasoning Ability", "Ranking and Height Arrangement", None),
    (re.compile(r"(coded as|code language|code for)", re.I),
     "Reasoning Ability", "Coding-Decoding", None),
    (re.compile(r"(meaningful (four|five|\d+) letter|make .* word using|word formation)", re.I),
     "Reasoning Ability", "Word Formation", None),
    (re.compile(r"(pairs? of letters|alphabetical order|as many letters between)", re.I),
     "Reasoning Ability", "Letter Pair and Alphabetical Order", None),
    (re.compile(r"(arrangement of symbol|symbol, letter and digit|letters, numbers and symbols|"
                r"vowels are deleted|consonants are there in the given arrangement)", re.I),
     "Reasoning Ability", "Symbol and Character Arrangement", None),
    (re.compile(r"(digit(s)?.*(arranged|subtracted|added)|arranged in descending order)", re.I),
     "Reasoning Ability", "Digit and Number Operations", None),
    (re.compile(r"(direction|km|north|south\b).*(distance|walk|turn)", re.I),
     "Reasoning Ability", "Direction and Distance", None),
    (re.compile(r"(blood relation|\bfather\b|\bmother\b|\bbrother\b|\bsister\b|\bson\b|\bdaughter\b)", re.I),
     "Reasoning Ability", "Blood Relations", None),
    (re.compile(r"(order and ranking|rank(ed)? .* (from|in) )", re.I),
     "Reasoning Ability", "Order and Ranking", None),
    (re.compile(r"(data sufficien)", re.I), "Reasoning Ability", "Data Sufficiency", None),
    (re.compile(r"(statement.*assumption|argument|course of action|logically follow)", re.I),
     "Reasoning Ability", "Logical Reasoning", None),

    # ---- Quantitative Aptitude ----
    (re.compile(r"(wrong number|series is given in which one number is wrong)", re.I),
     "Quantitative Aptitude", "Wrong Number Series", None),
    (re.compile(r"(\d+\s+){3,}\d+\s*$"), "Quantitative Aptitude", "Number Series", None),
    (re.compile(r"(depreciat)", re.I), "Quantitative Aptitude", "Depreciation", None),
    (re.compile(r"(compound interest|simple interest|\bc\.?i\.?\b|\bs\.?i\.?\b|interest)", re.I),
     "Quantitative Aptitude", "Simple and Compound Interest", None),
    (re.compile(r"(profit|loss|cost price|selling price|marked price|discount)", re.I),
     "Quantitative Aptitude", "Profit and Loss", None),
    (re.compile(r"(mixture|alligation|milk and water)", re.I),
     "Quantitative Aptitude", "Mixtures and Alligation", None),
    (re.compile(r"(men can (complete|do)|work in \d+ days|time and work|efficiency)", re.I),
     "Quantitative Aptitude", "Time and Work", None),
    (re.compile(r"(overtake|train[s]?\b.*(length|speed)|metres? long)", re.I),
     "Quantitative Aptitude", "Trains", None),
    (re.compile(r"(downstream|upstream|boat|stream)", re.I),
     "Quantitative Aptitude", "Boats and Streams", None),
    (re.compile(r"(average|mean)\b", re.I), "Quantitative Aptitude", "Average", None),
    (re.compile(r"(present age|ages of|years ago)", re.I), "Quantitative Aptitude", "Ages", None),
    (re.compile(r"(percentage|percent|%)", re.I), "Quantitative Aptitude", "Percentage", None),
    (re.compile(r"(ratio|proportion|: *\d)", re.I), "Quantitative Aptitude", "Ratio and Proportion", None),
    (re.compile(r"(radius|circumference|area of|perimeter|sq\.?\s*cm|volume|mensuration)", re.I),
     "Quantitative Aptitude", "Mensuration", None),
    (re.compile(r"(speed|kmph|km/h|distance|time would|travel)", re.I),
     "Quantitative Aptitude", "Speed, Time and Distance", None),
    (re.compile(r"(partnership|invest)", re.I), "Quantitative Aptitude", "Partnership", None),
    (re.compile(r"(probabilit)", re.I), "Quantitative Aptitude", "Probability", None),
    (re.compile(r"(permutation|combination|ways can|arranged in)", re.I),
     "Quantitative Aptitude", "Permutation and Combination", None),
    (re.compile(r"(simplif|what will come in the place of the question mark)", re.I),
     "Quantitative Aptitude", "Simplification", None),
    (re.compile(r"(approximate|approx)", re.I), "Quantitative Aptitude", "Approximation", None),
    (re.compile(r"(\u221a|sqrt|square root|\^|\bx\b.*=.*\?)", re.I),
     "Quantitative Aptitude", "Missing-Value Equations", None),
    (re.compile(r"(BODMAS|\d+\s*[+\u2212\u00d7\u00f7]\s*\d+.*=)", re.I),
     "Quantitative Aptitude", "Simplification", None),

    # ---- English ----
    (re.compile(r"(passage|read the following).*(answer the question)", re.I),
     "English Language", "Reading Comprehension", None),
    (re.compile(r"(cloze test)", re.I), "English Language", "Cloze Test", None),
    (re.compile(r"(error|incorrect|grammatically)", re.I), "English Language", "Error Detection", None),
    (re.compile(r"(sentence improvement|replace the bold)", re.I), "English Language", "Sentence Improvement", None),
    (re.compile(r"(fill in the blank|blanks?)", re.I), "English Language", "Fill in the Blanks", None),
    (re.compile(r"(para ?jumble|rearrange the sentences)", re.I), "English Language", "Para Jumbles", None),
    (re.compile(r"(synonym|antonym)", re.I), "English Language", "Synonyms and Antonyms", None),
    (re.compile(r"(idiom|phrase)", re.I), "English Language", "Idioms and Phrases", None),
]

# Context types that carry a chart/table stimulus. Rules are not run against
# these contexts' text (a stray word such as "months" must not turn a data
# question into a reasoning puzzle); the context-type prior is used instead.
_DATA_INTERPRETATION_TYPES = {
    "data_interpretation_graph",
    "data_interpretation_table",
    "data_interpretation_chart",
    "data_interpretation",
}

# context-type -> (subject, topic) prior (weaker than direct question rules)
_CONTEXT_PRIOR = {
    "floor_puzzle": ("Reasoning Ability", "Floor Puzzle"),
    "height_puzzle": ("Reasoning Ability", "Ranking and Height Arrangement"),
    "coding_language": ("Reasoning Ability", "Coding-Decoding"),
    "alphanumeric_sequence": ("Reasoning Ability", "Symbol and Character Arrangement"),
    "logical_statements": ("Reasoning Ability", "Syllogism"),
    "data_interpretation_graph": ("Quantitative Aptitude", "Data Interpretation"),
    "data_interpretation_table": ("Quantitative Aptitude", "Data Interpretation"),
    "data_interpretation_chart": ("Quantitative Aptitude", "Data Interpretation"),
    "reading_passage": ("English Language", "Reading Comprehension"),
}


@dataclass
class Classification:
    subject: str
    topic: str
    subtopic: Optional[str] = None
    method: str = "heuristic_keyword"
    confidence: Optional[float] = None
    confidence_kind: str = "heuristic"
    tags: list[str] = field(default_factory=list)
    reason: str = ""


class Classifier:
    def __init__(self, taxonomy: Optional[Taxonomy] = None, use_ai: bool = False):
        self.taxonomy = taxonomy or Taxonomy()
        self.use_ai = use_ai

    def classify(self, question_text: str, context_text: str = "",
                 context_type: Optional[str] = None) -> Classification:
        is_di = context_type in _DATA_INTERPRETATION_TYPES

        # 1) Rules over the question text plus its shared stimulus. For a
        #    chart/table the stimulus is withheld so a stray word in the chart
        #    caption cannot decide a data question's topic.
        if is_di:
            hit = self._match_rules(question_text)
            if hit is not None:
                pattern, subject, topic, subtopic = hit
                return self._build((subject, topic, subtopic), question_text, context_text,
                                   is_di, reason=f"matched rule for {topic}")
        else:
            combined = f"{question_text}\n{context_text}".strip()
            hit = self._match_rules(combined)
            if hit is not None:
                pattern, subject, topic, subtopic = hit
                from_question = bool(pattern.search(question_text))
                method = "heuristic_keyword" if from_question else "heuristic_context"
                reason = (f"matched rule for {topic}" if from_question
                          else f"matched rule for {topic} in shared context")
                return self._build((subject, topic, subtopic), question_text, context_text,
                                   is_di, reason=reason, method=method)

        # 2) context-type prior
        if context_type and context_type in _CONTEXT_PRIOR:
            subject, topic = _CONTEXT_PRIOR[context_type]
            return Classification(subject=subject, topic=topic, method="heuristic_context",
                                  confidence=None, confidence_kind="heuristic",
                                  tags=self._extra_tags(question_text, context_text, topic, is_di),
                                  reason="no question-level keyword; used shared context prior")

        # 3) optional local model
        if self.use_ai:
            allowed = self.taxonomy.subjects_with_topics()
            result = local_model_adapter.classify_with_model(question_text, context_text, allowed)
            if result and self._valid(result):
                return Classification(
                    subject=result["subject"], topic=result["topic"],
                    subtopic=result.get("subtopic"),
                    method="local_ai_model", confidence=None,
                    confidence_kind="model_self_reported",
                    tags=list(result.get("tags") or []),
                    reason=str(result.get("reason", ""))[:500],
                )

        return Classification(subject="Unclassified", topic="Unclassified",
                              method="none", confidence=None, confidence_kind="none",
                              reason="no rule matched")

    # -- helpers ---------------------------------------------------------
    def _match_rules(self, text: str):
        if not text:
            return None
        for pattern, subject, topic, subtopic in _RULES:
            if pattern.search(text):
                return (pattern, subject, topic, subtopic)
        return None

    def _build(self, hit, question_text: str, context_text: str,
               is_di: bool, *, reason: str,
               method: str = "heuristic_keyword") -> Classification:
        subject, topic, subtopic = hit
        return Classification(subject=subject, topic=topic, subtopic=subtopic,
                              method=method, confidence=None, confidence_kind="heuristic",
                              tags=self._extra_tags(question_text, context_text, topic, is_di),
                              reason=reason)

    def _valid(self, result: dict) -> bool:
        subj = result.get("subject")
        topic = result.get("topic")
        if not subj or not topic:
            return False
        return topic in self.taxonomy.topics(subj, active_only=False)

    def _extra_tags(self, question_text: str, context_text: str, topic: str,
                    is_di: bool) -> list[str]:
        tags: list[str] = []
        text = f"{question_text}\n{context_text}"
        if is_di or re.search(r"data interpretation|graph|table", text, re.I):
            if topic != "Data Interpretation":
                tags.append("data_interpretation")
        if re.search(r"ratio", text, re.I) and topic != "Ratio and Proportion":
            tags.append("ratio")
        if re.search(r"percent|%", text, re.I) and topic != "Percentage":
            tags.append("percentage")
        if re.search(r"average", text, re.I) and topic != "Average":
            tags.append("average")
        return tags
