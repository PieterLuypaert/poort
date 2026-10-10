# poort

Which TCP ports are listening, and which project each one belongs to: every port sits under its git checkout (repo, branch, path), worktrees apart from the main checkout. Docker ports are named after their container and join the checkout of their compose project; a stack that `wt` started joins its worktree.

```sh
poort                     # the live view: pick, open, follow, restart or stop with a key
poort lijst               # the grouped list, printed once (also what a pipe gets)
poort lijst shop           # only what matches shop: repo, branch, folder, tool or container
poort lijst -a            # desktop apps and helper processes too
poort 3000                # one port in detail: url, reach, pid, parent, output, restart plan
poort kill 3000 8000      # free those ports
poort kill wt1            # stop a whole project or stack, after asking (-j skips the question)
poort herstart 3000       # stop it and start it again the way it was started
poort herstart wt1        # the same for a whole project or stack, after asking
poort open 3000/admin     # open http://localhost:3000/admin
poort logs 3000           # follow docker logs, or the file the process writes to
poort vrij 3000 -n 3      # the first three free ports from 3000
poort wacht 3000          # wait until something listens on 3000 (exits 1 after --timeout)
poort --json              # everything as JSON, for scripts
```

In the live view: arrows or the mouse pick a port, `o` or enter opens it, `l` follows its logs (ctrl-c comes back), `c` copies the url, `r` restarts it, `k` stops it, `R` and `K` do that for its whole project, `/` filters, `a` shows apps, `q` quits. It refreshes itself every two seconds.

A restart climbs from the server through the tools that run it (pnpm, npm, turbo, nodemon) to the command that started it, stops that with everything under it and runs it again in its folder, in the background, its output appended to the file the server wrote to (or `~/.cache/poort`). A container gets `docker restart`; a server that `wt` started keeps its pid file up to date, so `wt down` still stops it.

Needs macOS or Linux with `python3` and `lsof`; Docker is optional.

```sh
ln -s "$PWD/poort" ~/.local/bin/poort
python3 -m unittest   # tests
```
