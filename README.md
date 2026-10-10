# poort

Which TCP ports are listening, and what is behind each one: the process or Docker container, the repo, folder and branch it runs from, and how long it has been up.

```sh
poort              # your dev servers, one line per port
poort -a           # every listening port, desktop apps too
poort 3000         # one port in detail
poort 3000 --kill  # free it: stop the process or its container
```

Needs macOS or Linux with `python3` and `lsof`; Docker is optional.

```sh
ln -s "$PWD/poort" ~/.local/bin/poort
python3 -m unittest   # tests
```
