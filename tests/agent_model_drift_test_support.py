"""Production-shaped fixtures for agent-model-drift tests."""
from __future__ import annotations
import contextlib
import copy
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from agent_tools import agent_costs, agent_model_drift

REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX = REPO_ROOT / "home/common/agent-skills/model-matrix.json"

def digest(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
def coverage(state="full", eligible=0, paired=0, reasons=None):
    return {"state": state, "eligible_events": eligible, "paired_events": paired, "reasons": reasons or []}
def merge_coverage(*values):
    counts = Counter(); [counts.update({x["code"]: x["count"] for x in v["reasons"]}) for v in values]
    eligible, paired = sum(v["eligible_events"] for v in values), sum(v["paired_events"] for v in values)
    return coverage("full" if not counts else "partial" if paired else "none", eligible, paired, [{"code": k, "count": counts[k]} for k in sorted(counts)])
def unsupported_metric(): return {"value": None, "coverage": coverage("none", reasons=[{"code":"source_unsupported","count":1}]), "cohort_digest": None}
def telemetry(*, start="2026-09-20T10:00:00Z", end="2026-09-20T11:00:00Z", harness=None, routing_coverage=None, observations=None, source_only=None):
    metrics = {x: unsupported_metric() for x in ("spawn_attempts","capacity_rejections","waits","follow_ups","wait_input_tokens","covered_input_tokens","slot_capacity_seconds","claimed_slot_seconds")}
    route, source_only = routing_coverage or coverage(), copy.deepcopy(source_only or {})
    return {"schema_version":1,"producer":{"name":"agent-costs","version":1,"harness_versions":harness or {"claude":["2.1.0"]}},"event_window":{"start":start,"end":end},"source_coverage":{"routing":merge_coverage(route, *(x["routing"] for x in source_only.values())),"scheduling":{name:merge_coverage(metric["coverage"], *(x["scheduling"][name] for x in source_only.values())) for name,metric in metrics.items()},"source_only":source_only},"runs":[{"run_id":"claude:repo:98","routing":{"coverage":copy.deepcopy(route),"observations":observations or []},"scheduling":metrics}]}
def _producer_record(execution_telemetry, selected=("claude",)):
    group=agent_costs.new_group(); group["sessions"]=1
    groups={"claude":{"cost_basis":"list-price","groups":{("repo","98"):group}}}
    if "codex" in selected: groups["codex"]={"cost_basis":"subscription","groups":{}}
    window={"days":1,"cutoff_epoch":1,"file_mtime_selection":True,
            "whole_selected_file_usage":True,"strata":list(selected),
            "sources":{x:"/redacted" for x in selected}}
    value=agent_costs.build_record(groups,window,execution_telemetry=execution_telemetry)
    value["generated_at"]="2026-09-20T11:01:00Z"
    return value
def record_value(*, selected=("claude",), source_only=None, **kwargs):
    kwargs.setdefault("harness", {x:["2.1.0"] if x=="claude" else None for x in selected}); return _producer_record(telemetry(source_only=source_only, **kwargs), selected)
def seal_record(value):
    body=copy.deepcopy(value); generated=body.pop("generated_at", "2026-09-20T11:01:00Z"); body.pop("record_id",None); return dict(body, record_id=digest(body), generated_at=generated)
def legacy_record_value():
    value=record_value(); value.pop("execution_telemetry"); return seal_record(value)
def matrix_fixture(root):
    data=json.loads(MATRIX.read_text()); paths=[Path("home/common/agent-skills/model-matrix.json")]+[Path(x["path"]) for x in data["dispatch_sites"]]+[x.relative_to(REPO_ROOT) for x in (REPO_ROOT/"home/common/claude-code/agents").glob("*.md")]
    for path in sorted(set(paths)):
        target=root/path; target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(REPO_ROOT/path,target)
    return data
def baseline_value(matrix,matrix_digest,**updates):
    models=sorted({x["model"] for x in matrix["roles"].values()}); efforts=sorted({x["effort"] for x in matrix["roles"].values()})
    body={"schema_version":1,"kind":"agent-model-baseline","captured_at":"2026-09-20T09:00:00Z","valid_from":"2026-09-20T00:00:00Z","valid_before":"2026-09-21T00:00:00Z","matrix_digest":matrix_digest,"producer":{"name":"agent-costs","version":1,"telemetry_schema_version":1},"harness_versions":{"claude":["2.1.0"]},"model_catalog_version":"catalog-2026-09-20","dispatch_hosts":{x["id"]:"claude" for x in matrix["dispatch_sites"]},"catalog":{"claude":{"models":{x:{"allowed":[f"claude-{x}-5-20260901"],"prohibited":[]} for x in models},"efforts":{x:{"allowed":[x],"prohibited":[]} for x in efforts}}},"escalation_reason_codes":["capacity","source-unavailable"]}; body.update(updates); return dict(body,baseline_id=digest(body))
def seal_baseline(value):
    body=copy.deepcopy(value); body.pop("baseline_id",None); return dict(body,baseline_id=digest(body))
class DriftCliCase(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name); self.matrix_root=self.root/"matrix"; self.matrix=matrix_fixture(self.matrix_root); self.matrix_digest=digest(self.matrix)
    def write(self,name,value): path=self.root/name; path.write_text(json.dumps(value)); return path
    def run(self, record=None, baseline=None, now="2026-09-20T12:00:00Z"):
        # unittest owns TestCase.run(result); retain the brief's convenient CLI
        # seam when called without a result object.
        if record is not None and not isinstance(record, dict):
            return super().run(record)
        stdout,stderr=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr): code=agent_model_drift.main(["--record",str(self.write("record.json",record_value() if record is None else record)),"--baseline",str(self.write("baseline.json",baseline_value(self.matrix,self.matrix_digest) if baseline is None else baseline)),"--matrix-root",str(self.matrix_root),"--now",now])
        return code,stdout.getvalue(),stderr.getvalue()
