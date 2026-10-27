"""
The tickets tool, a repo's tickets kept as one YAML file per GitHub issue in its docs/tickets/, read from GitHub.

Run it through kdf-tickets.sh beside this folder, which refuses a reviewer and finds cicd's venv interpreter, against a
worktree of the repo named by --root. This release holds the read side alone, check, fmt, plan, pull, find, prompt,
scan and ages, and nothing in it writes an issue or a board.
"""
