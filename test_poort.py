"""Tests for poort. Run with: python3 -m unittest"""
import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_loader = importlib.machinery.SourceFileLoader("poort", os.path.join(HERE, "poort"))
poort = importlib.util.module_from_spec(importlib.util.spec_from_loader("poort", _loader))
sys.modules["poort"] = poort
_loader.exec_module(poort)


def listener(port=3000, pid=1, args="", cwd="", ppid=0, place=None, command="node"):
    return poort.Listener(port, pid, command, ppid=ppid, args=args, cwd=cwd, place=place)


class ParseLsofTest(unittest.TestCase):
    def test_one_listener_per_port_and_pid(self):
        text = "\n".join([
            "p40997", "cnode", "f30", "n[::1]:3000", "f31", "n127.0.0.1:3000",
            "p13826", "csymfony", "f17", "n127.0.0.1:8000",
            "p25043", "ccom.docke", "f121", "n*:20116",
        ])
        found = {(item.port, item.pid, item.command, tuple(item.addresses)) for item in poort.parse_lsof(text)}
        self.assertEqual(found, {(3000, 40997, "node", ("[::1]", "127.0.0.1")),
                                 (8000, 13826, "symfony", ("127.0.0.1",)),
                                 (20116, 25043, "com.docke", ("*",))})

    def test_skips_an_address_without_a_port(self):
        self.assertEqual(poort.parse_lsof("p1\ncnode\nf3\nn*:*"), [])


class LabelTest(unittest.TestCase):
    def test_names_a_node_tool_after_its_package(self):
        cases = {
            "node /x/web/node_modules/.bin/../vite/bin/vite.js --port 20110": "vite",
            "node /x/node_modules/.bin/vite": "vite",
            "node /x/node_modules/@nestjs/cli/bin/nest.js start": "@nestjs/cli",
        }
        for args, name in cases.items():
            self.assertEqual(poort.label(listener(args=args)), name, args)

    def test_names_a_script_after_the_script(self):
        self.assertEqual(poort.label(listener(args="node server.js")), "node server.js")
        self.assertEqual(poort.label(listener(args="node dist/main")), "node dist/main")
        self.assertEqual(poort.label(listener(args="python3 -m http.server 9000")), "python3 http.server")
        self.assertEqual(poort.label(listener(args="/usr/local/bin/node /srv/app/index.js")), "node index.js")
        macos_python = "/Library/Developer/CommandLineTools/Python.app/Contents/MacOS/Python -m http.server"
        self.assertEqual(poort.label(listener(args=macos_python)), "python http.server")

    def test_names_anything_else_after_its_executable(self):
        self.assertEqual(poort.label(listener(args="symfony server:start -d")), "symfony")
        self.assertEqual(poort.label(listener(args="next-server (v16.3.4)")), "next-server")
        self.assertEqual(poort.label(listener(args="php-fpm: master process (/a b/fpm.ini)")), "php-fpm")
        self.assertEqual(poort.label(listener(args="/Applications/Spotify.app/Contents/MacOS/Spotify")), "Spotify")

    def test_falls_back_to_the_lsof_name(self):
        self.assertEqual(poort.label(listener(args="", command="com.docke")), "com.docke")


class DeepInfoTest(unittest.TestCase):
    def test_counts_connections_on_the_server_side(self):
        text = "\n".join(["p1", "f20", "n127.0.0.1:3000->127.0.0.1:52344", "f21", "n127.0.0.1:3000->127.0.0.1:52345",
                          "p2", "f9", "n127.0.0.1:52344->127.0.0.1:3000", "n[::1]:8000->[::1]:61000"])
        self.assertEqual(poort.count_connections(text), {3000: 2, 52344: 1, 8000: 1})

    def test_finds_the_file_a_process_writes_to(self):
        text = "\n".join([
            "p1", "fcwd", "tDIR", "n/x", "f1", "tREG", "n/logs/1-web.log",
            "p2", "f1", "tCHR", "n/dev/null", "f7", "tREG", "n/x/server.log", "f8", "tREG", "n/x/app.log",
            "p3", "f1", "tCHR", "n/dev/ttys012",
        ])
        self.assertEqual(poort.find_logs(text), {1: "/logs/1-web.log", 2: "/x/server.log"})

    def test_shortens_a_parent_command(self):
        self.assertEqual(poort.short_command("node /x/.local/state/fnm/bin/pnpm dev"), "pnpm dev")
        self.assertEqual(poort.short_command("/bin/zsh -l"), "zsh -l")
        self.assertEqual(poort.short_command("node --inspect app.js"), "node --inspect app.js")


class DetailFieldsTest(unittest.TestCase):
    def test_gives_a_url_except_for_databases(self):
        self.assertEqual(poort.url_of(listener(3000, args="node server.js")), "http://localhost:3000")
        self.assertEqual(poort.url_of(listener(5432, args="postgres")), "")
        self.assertEqual(poort.url_of(listener(8000, args="symfony server:start -d")), "https://localhost:8000")
        self.assertEqual(poort.url_of(listener(20111, args="symfony server:start --no-tls")), "http://localhost:20111")

    def test_tells_whether_the_network_can_reach_it(self):
        self.assertTrue(poort.is_local_only(poort.Listener(3000, 1, "node", addresses=["127.0.0.1", "[::1]"])))
        self.assertFalse(poort.is_local_only(poort.Listener(3000, 1, "node", addresses=["*"])))
        self.assertFalse(poort.is_local_only(poort.Listener(3000, 1, "node", addresses=["192.168.1.5"])))

    def test_shows_the_port_inside_a_container(self):
        item = poort.Listener(20116, 9, "com.docke", addresses=["*"], connections=2)
        item.container = poort.parse_docker("\t".join([
            "shop-wt1-firestore-1", "firestore", "0.0.0.0:20116->8080/tcp", "Up 1 hour", "shop-wt1", "firestore", "/x",
        ]))[20116]
        fields = {key: (value, note) for key, value, _, note in poort.detail_fields(item)}
        self.assertEqual(fields["binnenin"], ("poort 8080 in de container", ""))
        self.assertEqual(fields["bereik"], ("ook vanaf je netwerk", "*"))
        self.assertEqual(fields["verbindingen"], ("2 open", ""))

    def test_picks_how_to_show_logs(self):
        item = listener(3000, 1, args="node server.js")
        self.assertIsNone(poort.logs_command(item, 100, True))
        item.log = "/x/web.log"
        self.assertEqual(poort.logs_command(item, 50, True), ["tail", "-n", "50", "-F", "/x/web.log"])
        item.container = poort.Container("db-1", "mysql", "Up", "api", "database", "/x")
        self.assertEqual(poort.logs_command(item, 20, False), ["docker", "logs", "--tail", "20", "db-1"])


class ShortAgeTest(unittest.TestCase):
    def test_turns_ps_etime_into_one_unit(self):
        cases = {"00:42": "<1m", "12:05": "12m", "03:10:00": "3u", "06-10:49:22": "6d", "  01:00:00": "1u"}
        for etime, age in cases.items():
            self.assertEqual(poort.short_age(etime), age, etime)

    def test_says_when_something_started(self):
        now = poort.datetime(2026, 10, 10, 14, 0)
        self.assertEqual(poort.started_at(3600, now), "vandaag 13:00")
        self.assertEqual(poort.started_at(20 * 3600, now), "gisteren 18:00")
        self.assertEqual(poort.started_at(3 * 86400, now), "wo 7 okt 14:00")

    def test_gives_nothing_for_garbage(self):
        self.assertEqual(poort.short_age(""), "")
        self.assertEqual(poort.short_age("soon"), "")


class OnePerPortTest(unittest.TestCase):
    def test_keeps_the_parent_of_workers_on_one_port(self):
        rows = [listener(51443, 61035, ppid=13848), listener(51443, 13848, ppid=13826),
                listener(51443, 65207, ppid=13848)]
        self.assertEqual([item.pid for item in poort.one_per_port(rows)], [13848])

    def test_sorts_by_port(self):
        rows = [listener(8000, 2), listener(3000, 1)]
        self.assertEqual([item.port for item in poort.one_per_port(rows)], [3000, 8000])

    def test_drop_helpers_hides_a_child_of_another_listener(self):
        rows = [listener(8000, 13826, ppid=1), listener(51443, 13848, ppid=13826)]
        self.assertEqual([item.port for item in poort.drop_helpers(rows)], [8000])


class FitTest(unittest.TestCase):
    def test_narrows_the_column_with_the_most_to_spare(self):
        self.assertEqual(poort.fit([10, 40, 30], [6, 12, 10], 60), [10, 26, 24])

    def test_stops_at_the_minimum_widths(self):
        self.assertEqual(poort.fit([10, 40, 30], [6, 12, 10], 5), [6, 12, 10])


def place(repo="shop", sub="", branch="main", is_worktree=False, top="/x/shop"):
    return poort.Place(repo, sub, branch, is_worktree, top, top + "/.git")


class GroupTest(unittest.TestCase):
    def test_groups_by_checkout_with_main_before_its_worktrees(self):
        rows = [
            listener(20110, 4, cwd=HOME_DIR, place=place(sub="apps/web", branch="fix/a", is_worktree=True, top="/t")),
            listener(3001, 3, cwd=HOME_DIR, place=place(repo="blog")),
            listener(3000, 1, cwd=HOME_DIR, place=place(sub="apps/web")),
            listener(8000, 2, cwd=HOME_DIR, place=place(sub="apps/api")),
            listener(3417, 5, cwd="/nowhere/at/all"),
        ]
        groups = poort.group_rows(rows)
        self.assertEqual([(g.title, g.branch, [r.port for r in g.rows]) for g in groups], [
            ("blog", "main", [3001]),
            ("shop", "main", [3000, 8000]),
            ("shop", "fix/a", [20110]),
            ("map is weg", "", [3417]),
        ])

    def test_puts_a_container_without_checkout_under_its_docker_project(self):
        item = listener(5432, 9)
        item.container = poort.Container("db-1", "postgres", "Up 1 hour", "db", "postgres", "")
        self.assertEqual([g.title for g in poort.group_rows([item])], ["docker db"])

    def test_renders_a_header_per_project(self):
        rows = [
            listener(3000, 1, args="node x/node_modules/.bin/vite", cwd=HOME_DIR, place=place(sub="apps/web")),
            listener(20110, 2, args="node x/node_modules/.bin/vite", cwd=HOME_DIR,
                     place=place(sub="apps/web", branch="fix/thing", is_worktree=True, top="/t")),
            listener(3417, 3, args="node server.js", cwd="/nowhere/at/all"),
        ]
        lines = poort.render_groups(poort.group_rows(rows), poort.Paint(False), 120)
        self.assertEqual([line.split() for line in lines], [
            ["shop", "main", "/x/shop"],
            ["3000", "vite", "apps/web", "pid", "1"],
            [],
            ["shop", "wt", "fix/thing", "/t"],
            ["20110", "vite", "apps/web", "pid", "2"],
            [],
            ["map", "is", "weg"],
            ["3417", "node", "server.js", "/nowhere/at/all", "pid", "3"],
        ])


class FilterTest(unittest.TestCase):
    def rows(self):
        web = listener(3000, 1, args="node x/node_modules/.bin/vite", cwd=HOME_DIR + "/shop/apps/web",
                       place=place(sub="apps/web"))
        tree = listener(20110, 2, args="symfony server:start", cwd=HOME_DIR + "/t",
                        place=place(branch="fix/cart", is_worktree=True, top="/t"))
        tree.stack = poort.Stack("shop", 1, "/t", {"api": 20110})
        app = listener(7768, 3, args="/Applications/Spotify.app/Contents/MacOS/Spotify", cwd="/")
        return [web, tree, app]

    def ports(self, terms, show_all=False):
        return [item.port for item in poort.visible(self.rows(), terms, show_all)]

    def test_matches_project_branch_tool_or_stack(self):
        self.assertEqual(self.ports(["shop"]), [3000, 20110])
        self.assertEqual(self.ports(["fix/cart"]), [20110])
        self.assertEqual(self.ports(["VITE"]), [3000])
        self.assertEqual(self.ports(["wt1"]), [20110])

    def test_any_word_may_match(self):
        self.assertEqual(self.ports(["vite", "symfony"]), [3000, 20110])

    def test_finds_an_app_when_no_dev_server_matches(self):
        self.assertEqual(self.ports([]), [3000, 20110])
        self.assertEqual(self.ports(["spotify"]), [7768])

    def test_splits_ports_from_words(self):
        self.assertEqual(poort.split_targets(["3000", "shop", "8000"]), ([3000, 8000], ["shop"]))
        with self.assertRaises(argparse.ArgumentTypeError):
            poort.split_targets(["0"])


class DockerTest(unittest.TestCase):
    def test_maps_published_tcp_ports_to_their_container(self):
        text = "\n".join([
            "\t".join(["api-database-1", "mysql:8.4", "0.0.0.0:3306->3306/tcp, [::]:3306->3306/tcp",
                       "Up 6 days (healthy)", "api", "database", "/x/shop/apps/api"]),
            "\t".join(["dns", "coredns", "0.0.0.0:53->53/udp, 0.0.0.0:9000-9001->9000-9001/tcp, 8080/tcp",
                       "Up 3 minutes", "", "", ""]),
        ])
        by_port = poort.parse_docker(text)
        self.assertEqual(sorted(by_port), [3306, 9000, 9001])
        self.assertEqual(by_port[3306].service, "database")
        self.assertEqual(by_port[9001].name, "dns")

    def test_skips_lines_it_cannot_read(self):
        self.assertEqual(poort.parse_docker("Cannot connect to the Docker daemon"), {})

    def test_turns_the_status_into_an_age(self):
        cases = {"Up 6 days (healthy)": "6d", "Up About an hour": "1u", "Up 25 hours": "1d",
                 "Up 45 minutes": "45m", "Up Less than a second": "<1m", "Up 2 weeks": "14d",
                 "Exited (0) 2 days ago": ""}
        for status, age in cases.items():
            self.assertEqual(poort.docker_age(status), age, status)

    def test_shows_a_container_by_service_project_and_image(self):
        item = listener(3306, 25043, args="/Applications/Docker.app/Contents/MacOS/com.docker.backend")
        item.container = poort.Container("api-database-1", "mysql:8.4", "Up 6 days", "api", "database", "/x")
        self.assertTrue(poort.is_dev(item))
        lines = poort.render_groups(poort.group_rows([item]), poort.Paint(False), 120)
        self.assertEqual(lines[1].split(), ["3306", "database", "docker", "api", "mysql:8.4", "6d"])


class DetailTest(unittest.TestCase):
    def test_shows_where_a_process_runs_from(self):
        item = listener(3000, 40997, ppid=40983, args="node server.js", cwd=HOME_DIR + "/shop",
                        place=place(repo="shop", branch="fix/cart", is_worktree=True))
        item.elapsed = "01:00:00"
        lines = [" ".join(line.split()) for line in poort.render_detail(item, poort.Paint(False))]
        for expected in ["3000 node server.js http://localhost:3000", "pid 40997", "map ~/shop is weg",
                         "project shop · wt fix/cart", "poort open 3000 · poort kill 3000"]:
            self.assertIn(expected, lines)
        self.assertTrue(any(line.startswith("draait 1u sinds") for line in lines))

    def test_says_a_free_port_is_free(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = poort.show_ports([3999], [], paint=poort.Paint(False))
        self.assertEqual((code, out.getvalue().strip()), (0, "3999 is vrij."))

    def test_rejects_a_number_that_is_no_port(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            poort.port_number("70000")


class StopTest(unittest.TestCase):
    def serve(self, ignore_term):
        """A throwaway listener on a free port; returns the process and port."""
        code = (
            "import signal, socket, sys, time\n"
            f"if {ignore_term}: signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen()\n"
            "print(s.getsockname()[1], flush=True); time.sleep(60)\n"
        )
        proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        return proc, int(proc.stdout.readline())

    def test_stops_a_server_politely(self):
        proc, port = self.serve(ignore_term=False)
        self.assertIsNone(poort.stop(listener(port, proc.pid)))
        self.assertEqual(poort.listening_pids(port), [])

    def test_kills_a_server_that_ignores_sigterm(self):
        proc, port = self.serve(ignore_term=True)
        self.assertIsNone(poort.stop(listener(port, proc.pid)))
        self.assertEqual(proc.wait(timeout=5), -9)

    def test_stops_several_servers_at_once(self):
        servers = [self.serve(ignore_term=False) for _ in range(3)]
        rows = [listener(port, proc.pid) for proc, port in servers]
        self.assertEqual(poort.stop_many(rows), {port: None for _, port in servers})

    def test_names_a_port_it_may_not_free(self):
        proc, port = self.serve(ignore_term=False)
        original = poort.send
        poort.send = lambda pid, sig: f"geen rechten om pid {pid} te stoppen"
        self.addCleanup(setattr, poort, "send", original)
        self.assertEqual(poort.stop_many([listener(port, proc.pid)]),
                         {port: f"geen rechten om pid {proc.pid} te stoppen"})


class FreeAndWaitTest(unittest.TestCase):
    def test_skips_taken_ports(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            busy = sock.getsockname()[1]
            found = poort.free_ports(busy, 2, taken={busy + 1})
        self.assertNotIn(busy, found)
        self.assertNotIn(busy + 1, found)
        self.assertEqual(len(found), 2)

    def test_waits_until_a_port_listens(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = socket.socket()
        self.addCleanup(server.close)
        timer = threading.Timer(0.5, lambda: (server.bind(("127.0.0.1", port)), server.listen()))
        timer.start()
        self.addCleanup(timer.cancel)
        ticks = []
        ok, waited = poort.wait_for_listen([port], 5, tick=lambda waited, waiting: ticks.append(waiting))
        self.assertTrue(ok)
        self.assertGreaterEqual(waited, 0.4)
        self.assertEqual(ticks[0], [port])

    def test_gives_up_after_the_timeout(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.assertFalse(poort.wait_for_listen([port], 0.3)[0])


class KillTest(unittest.TestCase):
    def rows(self):
        tree = place(branch="fix/cart", is_worktree=True, top="/t")
        return [
            listener(3000, 1, args="node x/node_modules/.bin/vite", cwd=HOME_DIR, place=place()),
            listener(20110, 2, args="node x/node_modules/.bin/vite", cwd=HOME_DIR, place=tree),
            listener(20111, 3, args="symfony server:start", cwd=HOME_DIR, place=tree),
            listener(51443, 4, ppid=3, args="php-fpm: master", cwd=HOME_DIR, place=tree),
        ]

    def test_picks_ports_and_every_dev_server_a_word_matches(self):
        targets, free = poort.pick_targets(self.rows(), [3000, 3999], ["fix/cart"])
        self.assertEqual(([item.port for item in targets], free), ([3000, 20110, 20111], [3999]))

    def kill(self, ports, terms, sure=False, answer=True):
        asked, stopped = [], []
        original = poort.stop_many
        poort.stop_many = lambda rows: stopped.extend(item.port for item in rows) or {
            item.port: None for item in rows}
        self.addCleanup(setattr, poort, "stop_many", original)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = poort.kill(self.rows(), ports, terms, sure, poort.Paint(False),
                              ask=lambda question: asked.append(question) or answer)
        return code, asked, stopped

    def test_stops_asked_ports_without_asking(self):
        self.assertEqual(self.kill([3000], []), (0, [], [3000]))

    def test_asks_before_stopping_a_project(self):
        code, asked, stopped = self.kill([], ["fix/cart"])
        self.assertEqual((code, asked, stopped), (0, ["  2 poorten stoppen? [j/N] "], [20110, 20111]))

    def test_stops_nothing_on_no(self):
        self.assertEqual(self.kill([], ["fix/cart"], answer=False), (1, ["  2 poorten stoppen? [j/N] "], []))

    def test_needs_ja_without_a_terminal(self):
        self.assertEqual(self.kill([], ["fix/cart"], answer=None)[0], 2)
        self.assertEqual(self.kill([], ["fix/cart"], sure=True), (0, [], [20110, 20111]))

    def test_fails_when_a_word_finds_nothing(self):
        self.assertEqual(self.kill([], ["nope"]), (1, [], []))


HOME_DIR = os.path.expanduser("~")


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class PlaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "shop")
        os.makedirs(os.path.join(self.repo, "apps", "web"))
        git("init", "-q", "-b", "main", cwd=self.repo)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init", cwd=self.repo)
        self.tree = os.path.join(self.tmp.name, "trees", "fix-cart")
        git("worktree", "add", "-q", "-b", "fix/cart", self.tree, cwd=self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_places_the_main_checkout(self):
        found = poort.place_of(os.path.join(self.repo, "apps", "web"))
        repo = os.path.realpath(self.repo)
        self.assertEqual(found, poort.Place("shop", "apps/web", "main", False, repo, repo + "/.git"))

    def test_places_a_worktree_under_its_repo(self):
        found = poort.place_of(self.tree)
        self.assertEqual((found.repo, found.sub, found.branch, found.is_worktree, found.top),
                         ("shop", "", "fix/cart", True, os.path.realpath(self.tree)))

    def write_registry(self, index=1):
        registry = os.path.join(self.repo, ".git", "shop-worktrees")
        os.makedirs(registry, exist_ok=True)
        with open(os.path.join(registry, f"{index}.env"), "w") as entry:
            entry.write(f'REG_BRANCH="fix/cart"\nREG_PATH="{self.tree}"\nREG_WEB=20110\n'
                        'REG_API=20111\nREG_DB="shop_wt1"\nREG_PR="42"\n')

    def test_reads_the_wt_registry(self):
        self.write_registry()
        stacks = poort.read_stacks(os.path.realpath(os.path.join(self.repo, ".git")))
        self.assertEqual(stacks, [poort.Stack("shop", 1, self.tree, {"web": 20110, "api": 20111})])

    def test_ties_a_worktree_and_its_wt_containers_to_the_stack(self):
        self.write_registry()
        lookup = poort.Lookup()
        self.assertEqual(lookup.stack_at(lookup.place(self.tree)).index, 1)
        tools = os.path.join(self.repo, "tools")
        os.makedirs(tools)
        container = poort.Container("shop-wt1-gcs-1", "gcs", "Up 1 hour", "shop-wt1", "gcs", tools)
        home, stack = lookup.container_home(container)
        self.assertEqual((home.branch, home.is_worktree, stack.index), ("fix/cart", True, 1))

    def test_ties_another_container_to_its_compose_folder(self):
        os.makedirs(os.path.join(self.repo, "apps", "api"))
        container = poort.Container("api-db-1", "mysql", "Up 1 hour", "api", "db",
                                    os.path.join(self.repo, "apps", "api"))
        home, stack = poort.Lookup().container_home(container)
        self.assertEqual((home.repo, home.sub, home.branch, stack), ("shop", "apps/api", "main", None))

    def test_has_no_place_outside_git(self):
        self.assertIsNone(poort.place_of(self.tmp.name))
        self.assertIsNone(poort.place_of("/"))


if __name__ == "__main__":
    unittest.main()
