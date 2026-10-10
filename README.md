# poort

Which TCP ports are listening, and which project each one belongs to: every port sits under its git checkout (repo, branch, path), worktrees apart from the main checkout. Docker ports are named after their container and join the checkout of their compose project; a stack that `wt` started joins its worktree.

```sh
poort                     # your dev servers, grouped per project
poort shop                 # only what matches shop: repo, branch, folder, tool or container
poort -a                  # desktop apps and helper processes too
poort 3000                # one port in detail: url, reach, pid, parent, output, connections
poort kill 3000 8000      # free those ports
poort kill wt1            # stop a whole project or stack, after asking (-j skips the question)
poort open 3000/admin     # open http://localhost:3000/admin
poort logs 3000           # follow docker logs, or the file the process writes to
poort vrij 3000 -n 3      # the first three free ports from 3000
poort wacht 3000          # wait until something listens on 3000 (exits 1 after --timeout)
poort live                # interactive, refreshes itself
poort --json              # everything as JSON, for scripts
```

In `poort live`: arrows or the mouse pick a port, `o` or enter opens it, `l` follows its logs (ctrl-c comes back), `c` copies the url, `k` stops it, `K` stops its whole project, `/` filters, `a` shows apps, `q` quits.

Needs macOS or Linux with `python3` and `lsof`; Docker is optional.

```sh
ln -s "$PWD/poort" ~/.local/bin/poort
python3 -m unittest   # tests
```
