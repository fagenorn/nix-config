You check whether issue {{run.issue}} of {{run.repo}} still applies before it is delivered. Change nothing.
The issue, with its comments:
{{preflight.issue_text}}
Read the code at origin/{{preflight.integration_branch}}, already fetched, with read-only git commands and the file tools.
If the issue no longer applies (already fixed or obsolete), answer verdict no-longer-applies and give in evidence the facts that show it, in a few lines a reader of the issue can check: the files, the symbols and the commit.
Otherwise answer verdict applies, with evidence empty.
In details, in a few lines, say what still applies, where (files and symbols) and what already exists.
