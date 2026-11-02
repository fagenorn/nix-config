# Acceptance record — issue #278

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] nohup x &, (setsid x), env nohup x, $(disown) and sh -c 'nohup x' exit 2 with the refusal naming the background mode — measured: tests/test_claude_permission_guard.py adversarial rows | code | `test_detaching_words_are_refused_globally` via `CLAUDE_SETTINGS_PATH=<just show-claude-settings output> python3 -m unittest tests/test_claude_permission_guard.py` | Ran 41 tests, OK | f0189e5 | darwin, settings built from that commit | met |
| AC2 | [code] echo "nohup", grep nohup log, a heredoc body, a comment and a & b & wait pass — measured: the same table | code | `test_detaching_word_mentions_pass`, same run | Ran 41 tests, OK | f0189e5 | same run | met |
| AC3 | [code] nohup git push origin main is still refused, now for detaching — measured: the same table | code | `test_detaching_refusal_precedes_the_push_grammar`, same run | Ran 41 tests, OK | f0189e5 | same run | met |
| AC4 | [code] The guard still imports nothing from agent_tools and the guard suite is green — measured: just build and the guard suite | code | `just build` (in final verification), the guard suite run above, and `grep -nE '^\s*(from|import)\s+agent_tools' home/common/claude-code/lifecycle_guard.py` | build exit 0; suite OK; grep finds nothing | f0189e5 | same run | met |
