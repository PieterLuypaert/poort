# poort

A terminal tool that shows which ports are listening on your machine, grouped per project and branch, and lets you open, follow, restart or stop them with a key. Docker containers and git worktrees each land under the project they belong to. The interface is in Dutch.

```sh
mkdir -p ~/.local/bin
curl -fsSL https://raw.githubusercontent.com/PieterLuypaert/poort/main/poort -o ~/.local/bin/poort
chmod +x ~/.local/bin/poort
```

Needs `python3` and `lsof` (macOS has both); Docker is optional. Run `poort`, or `poort -h` for every command.
