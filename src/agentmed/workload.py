from __future__ import annotations

from agentmed.workloads.kotaemon import SPEC

KOTAEMON_REPO = SPEC.repo
KOTAEMON_COMMIT = SPEC.commit
WORKLOAD = SPEC.path
DEFAULT_EXPECTED = SPEC.default_expected
DEFAULT_BADCASE = SPEC.default_badcase
DEFAULT_JUDGE = SPEC.default_judge
KOTAEMON_SNAPSHOT = {
    "repository": SPEC.repo,
    "commit": SPEC.commit,
    "workload": SPEC.path,
    "slug": SPEC.slug,
}
ATTRIBUTE_HYPOTHESIS = SPEC.attribute_hypothesis
