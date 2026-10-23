"""C-17 Creativity & design: generate alternatives, check feasibility, score by an explicit rubric.

Options come from a design space (cartesian product of dimensions, bounded) and/or from
proposals (for example a model's JSON list). Every option is then judged the same way:
- constraints: named predicates; an option failing any is rejected with the names;
- rubric: criterion -> weight; each criterion has a scorer returning a number in [0, 1];
  a scorer that fails or returns anything else rejects the option (never a silent score);
- novelty (optional): share of dimensions that differ from a baseline option.
Ranking uses only rubric scores -- a proposer's own claims about quality are ignored.
"""
import itertools
import json

from maep.core import MAEPError


def _canonical(option):
    return json.dumps(option, sort_keys=True, ensure_ascii=False)


def novelty(baseline):
    def score(option):
        keys = set(baseline) | set(option)
        return sum(1 for k in keys if option.get(k) != baseline.get(k)) / len(keys) if keys else 0.0
    return score


class OptionGenerator:
    def __init__(self, *, max_combinations=500):
        self._max = max_combinations

    def candidates(self, dimensions=None, proposals=()):
        options, truncated = [], False
        if dimensions:
            if not isinstance(dimensions, dict) or not all(isinstance(v, list) and v for v in dimensions.values()):
                raise MAEPError("dimensions must map names to non-empty lists")
            names = sorted(dimensions)
            for combo in itertools.product(*(dimensions[n] for n in names)):
                if len(options) >= self._max:
                    truncated = True
                    break
                options.append(dict(zip(names, combo)))
        for proposal in proposals:
            if not isinstance(proposal, dict) or not proposal:
                raise MAEPError("each proposal must be a non-empty object")
            options.append({k: v for k, v in proposal.items() if k not in {"score", "rationale", "rank"}})
        unique = {}
        for option in options:
            unique.setdefault(_canonical(option), option)
        return list(unique.values()), truncated

    def evaluate(self, options, *, rubric, scorers, constraints=(), baseline=None, limit=10):
        if not isinstance(rubric, dict) or not rubric or any(
                isinstance(w, bool) or not isinstance(w, (int, float)) or w <= 0 for w in rubric.values()):
            raise MAEPError("rubric must map criteria to positive weights")
        scorers = dict(scorers)
        if baseline is not None and "novelty" in rubric:
            scorers.setdefault("novelty", novelty(baseline))
        missing = sorted(set(rubric) - set(scorers))
        if missing:
            raise MAEPError("no scorer for criteria: " + ", ".join(missing))
        total_weight = float(sum(rubric.values()))
        ranked, rejected = [], []
        for option in options:
            failed = [name for name, check in constraints if not self._holds(check, option)]
            if failed:
                rejected.append({"option": option, "reason": "constraints failed: " + ", ".join(failed)})
                continue
            scores, error = {}, None
            for criterion in sorted(rubric):
                try:
                    value = scorers[criterion](option)
                except Exception as exc:
                    error = f"scorer {criterion} raised {type(exc).__name__}"
                    break
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
                    error = f"scorer {criterion} returned {value!r}, not a number in [0, 1]"
                    break
                scores[criterion] = round(float(value), 4)
            if error:
                rejected.append({"option": option, "reason": error})
                continue
            total = round(sum(rubric[c] * scores[c] for c in rubric) / total_weight, 4)
            rationale = ", ".join(f"{c}={scores[c]}x{rubric[c]}" for c in sorted(rubric))
            ranked.append({"option": option, "scores": scores, "total": total, "rationale": rationale})
        ranked.sort(key=lambda r: (-r["total"], _canonical(r["option"])))
        for rank, item in enumerate(ranked, 1):
            item["rank"] = rank
        return {"options": ranked[:limit], "rejected": rejected, "evaluated": len(options),
                "feasible": len(ranked)}

    def generate(self, *, rubric, scorers, dimensions=None, proposals=(), constraints=(), baseline=None, limit=10):
        options, truncated = self.candidates(dimensions, proposals)
        result = self.evaluate(options, rubric=rubric, scorers=scorers, constraints=constraints,
                               baseline=baseline, limit=limit)
        result["truncated"] = truncated
        return result

    @staticmethod
    def _holds(check, option):
        try:
            return check(option) is True
        except Exception:
            return False


def proposals_from_model(router, brief, *, n=5, task_id=None):
    """Ask a model for up to n options as a JSON list of objects; anything unparseable yields []."""
    response = router.complete({"system": "Return only a JSON array of distinct option objects. "
                                          "Do not score or praise them.",
                                "messages": [{"role": "user", "content": f"Propose {n} options for: {brief}"}],
                                "max_tokens": 800}, kind="creative", task_id=task_id)
    text = response["text"]
    start, end = text.find("["), text.rfind("]")
    try:
        data = json.loads(text[start:end + 1]) if start >= 0 and end > start else []
    except ValueError:
        return []
    return [d for d in data if isinstance(d, dict) and d][:n]
