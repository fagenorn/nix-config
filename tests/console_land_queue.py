"""A stand-in forge for the console screenshots' land queue."""
from agent_tools.console import movement


def land_queue_reader(waiting: tuple[int, ...]):
    """A `pull_reader` over `movement.read_pulls` and two stand-in forge calls: the pull request of
    another issue holds the land lock of `main`; the one of the issues of `waiting` is registered
    behind it."""
    def pull(number: int, issues: tuple[int, ...], oid: str) -> dict:
        return {"number": number, "headRefName": f"work-{number}", "baseRefName": "main",
                "headRefOid": oid, "isCrossRepository": False,
                "body": " ".join(f"#{issue}" for issue in issues), "commits": {"nodes": []}}

    holder, mine = "8" * 40, "7" * 40
    pulls = {"data": {"repository": {"pullRequests": {"nodes": [
        pull(7, waiting, mine), pull(8, (99,), holder)]}}}}
    refs = [{"ref": ref, "object": {"sha": sha, "type": "commit"}} for ref, sha in (
        ("refs/agent-locks/land/main", holder),
        ("refs/agent-locks/land-wait/main/1000-7-1060", mine))]

    def answer(argv):
        return pulls if argv[1] == "graphql" else refs

    return lambda slug, pattern, *, cancelled: movement.read_pulls(slug, pattern, call=answer, cancelled=cancelled)
