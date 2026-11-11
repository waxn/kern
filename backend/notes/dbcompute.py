"""Values of database properties, including computed ones (rollups, formulas)."""
import statistics
from collections import defaultdict

from .formula import Evaluator, FormulaError, compile_formula, to_date, to_json, to_str
from .models import Document, PropertyDef, PropertyValue


def raw_values(doc_ids) -> dict:
    out = defaultdict(dict)
    for doc_id, def_id, value in PropertyValue.objects.filter(document_id__in=doc_ids).values_list(
        "document_id", "definition_id", "value"
    ):
        out[doc_id][str(def_id)] = value
    return out


def _option_names(d: PropertyDef, value):
    names = {o.get("id"): o.get("name", "") for o in d.options or []}
    if isinstance(value, list):
        return [names[v] for v in value if v in names]
    return names.get(value)


def _rollup(fn: str, values: list):
    present = [v for v in values if v not in (None, "", [])]
    flat = []
    for v in present:
        flat.extend(v if isinstance(v, list) else [v])
    nums = [float(v) for v in flat if isinstance(v, (int, float)) and not isinstance(v, bool)]
    n = len(values)
    if fn == "count":
        return float(n)
    if fn == "count_values":
        return float(len(flat))
    if fn == "count_unique":
        return float(len({to_str(v) for v in flat}))
    if fn == "count_empty":
        return float(n - len(present))
    if fn == "count_not_empty":
        return float(len(present))
    if fn == "percent_empty":
        return round(100 * (n - len(present)) / n, 1) if n else None
    if fn == "percent_not_empty":
        return round(100 * len(present) / n, 1) if n else None
    if fn == "sum":
        return sum(nums)
    if fn == "average":
        return sum(nums) / len(nums) if nums else None
    if fn == "median":
        return statistics.median(nums) if nums else None
    if fn == "min":
        return min(nums) if nums else None
    if fn == "max":
        return max(nums) if nums else None
    if fn == "range":
        return max(nums) - min(nums) if nums else None
    if fn == "checked":
        return float(sum(1 for v in values if v is True))
    if fn == "unchecked":
        return float(sum(1 for v in values if v is not True))
    if fn == "percent_checked":
        return round(100 * sum(1 for v in values if v is True) / n, 1) if n else None
    if fn in ("earliest", "latest"):
        dates = [d for d in (to_date(v) for v in flat if isinstance(v, str)) if d]
        if not dates:
            return None
        return (min(dates) if fn == "earliest" else max(dates)).isoformat()
    return flat  # "show": the related values as a list


def compute(docs: list[Document], defs: list[PropertyDef], depth: int = 0) -> dict:
    """Return {doc_id: {prop_id: value}} with computed properties filled in."""
    ids = [d.id for d in docs]
    raw = raw_values(ids)
    by_id = {d.id: d for d in docs}
    defs_by_id = {str(d.id): d for d in defs}
    out: dict = {}

    rollups = [d for d in defs if d.type == "rollup"]
    rollup_values: dict = defaultdict(dict)
    for r in rollups:
        cfg = r.config or {}
        rel = defs_by_id.get(cfg.get("relation") or "")
        if not rel or rel.type != "relation":
            continue
        related_ids = set()
        for did in ids:
            related_ids.update(raw[did].get(str(rel.id)) or [])
        related = list(
            Document.objects.filter(id__in=related_ids, trashed_at__isnull=True)
        )
        target_id = cfg.get("target") or "title"
        target = None if target_id == "title" else PropertyDef.objects.filter(id=target_id).first()
        if target_id != "title" and target is None:
            continue
        if target and target.type in PropertyDef.COMPUTED:
            if depth >= 2:
                continue
            sub = compute(related, [target], depth + 1)
            tvals = {k: v.get(str(target.id)) for k, v in sub.items()}
        elif target:
            rv = raw_values([d.id for d in related])
            tvals = {}
            for d in related:
                v = rv[d.id].get(str(target.id))
                if target.type in ("select", "status", "multi_select"):
                    v = _option_names(target, v)
                tvals[d.id] = v
        else:
            tvals = {d.id: d.title for d in related}
        alive = {str(d.id): d.id for d in related}
        for did in ids:
            refs = [alive[x] for x in (raw[did].get(str(rel.id)) or []) if x in alive]
            rollup_values[did][str(r.id)] = _rollup(cfg.get("fn") or "show", [tvals.get(x) for x in refs])

    titles_needed = set()
    for d in defs:
        if d.type == "relation":
            for did in ids:
                titles_needed.update(raw[did].get(str(d.id)) or [])
    titles = dict(
        Document.objects.filter(id__in=titles_needed, trashed_at__isnull=True).values_list("id", "title")
    )
    titles = {str(k): v for k, v in titles.items()}

    by_name = {d.name.lower(): d for d in defs}
    formulas = [d for d in defs if d.type == "formula"]

    for did in ids:
        doc = by_id[did]
        vals = dict(raw[did])
        for d in defs:
            if d.type == "created_time":
                vals[str(d.id)] = doc.created_at.isoformat()
            elif d.type == "last_edited_time":
                vals[str(d.id)] = doc.updated_at.isoformat()
            elif d.type == "rollup":
                vals[str(d.id)] = rollup_values[did].get(str(d.id))
            elif d.type == "relation":
                vals[str(d.id)] = [x for x in vals.get(str(d.id)) or [] if x in titles]

        cache: dict = {}
        active: set = set()

        def lookup(name, did=did, doc=doc, vals=vals, cache=cache, active=active):
            key = name.lower()
            if key in ("title", "name") and key not in by_name:
                return doc.title
            d = by_name.get(key)
            if d is None:
                if key == "title":
                    return doc.title
                raise FormulaError(f"No property named “{name}”")
            v = vals.get(str(d.id))
            if d.type == "formula":
                if key in cache:
                    return cache[key]
                if key in active:
                    raise FormulaError("Formula refers to itself")
                active.add(key)
                try:
                    cache[key] = eval_formula(d, lookup)
                finally:
                    active.discard(key)
                return cache[key]
            if d.type in ("select", "status", "multi_select"):
                return _option_names(d, v) if v is not None else ([] if d.type == "multi_select" else None)
            if d.type == "relation":
                return [titles.get(x, "") for x in v or []]
            if d.type in ("date", "created_time", "last_edited_time"):
                return to_date(v) if v else None
            if d.type == "boolean":
                return bool(v)
            if d.type in ("number", "rating"):
                return float(v) if v is not None else None
            return v

        for f in formulas:
            try:
                vals[str(f.id)] = to_json(lookup(f.name))
            except FormulaError as e:
                vals[str(f.id)] = {"error": str(e)}
            except RecursionError:
                vals[str(f.id)] = {"error": "Formula is too deeply nested"}
        out[did] = vals
    return out


def eval_formula(d: PropertyDef, lookup):
    expr = (d.config or {}).get("expr") or ""
    if not expr.strip():
        return None
    return Evaluator(lookup).run(compile_formula(expr))
