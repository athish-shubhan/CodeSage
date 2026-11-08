<!-- agent-reliability:start -->
## Agent reliability (`eval/agent_eval.py`)

Mode: **live**. 12 cases in `eval/agent_cases.jsonl` against `eval/fixture/repo` (which includes `payments.py`, a file with an injected comment), run through the real `/agent` loop, or the real `/chat` handler for the 2 cases marked `"path": "chat"`, with tools and retrieval served from the fixture files.

Model: `llama3.2:3b` at `http://localhost:11434/v1` (the model's default sampling settings), one run over the 12 cases. With this few cases each rate is a rough indication, not an estimate; the n beside each rate is the number of items it is computed over. The model's own answers are not compared with hand labels, so there are no pass/fail label checks in this mode.

| Answer metric | Replay (scripted answers) | Live LLM |
|---|---|---|
| Grounded-citation rate | not run | 1.00 (n=4) |
| Unsupported-identifier rate | not run | 0.00 (n=3) |
| Abstention accuracy | not run | 0.92 (n=12) |
| Injection resistance | not run | 1.00 (n=4) |

<!-- agent-reliability:end -->
