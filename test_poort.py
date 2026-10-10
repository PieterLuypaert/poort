"""Tests for poort. Run with: python3 -m unittest"""
import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
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
        found = {(item.port, item.pid, item.command) for item in poort.parse_lsof(text)}
        self.assertEqual(found, {(3000, 40997, "node"), (8000, 13826, "symfony"), (20116, 25043, "com.docke")})

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


class ShortAgeTest(unittest.TestCase):
    def test_turns_ps_etime_into_one_unit(self):
        cases = {"00:42": "<1m", "12:05": "12m", "03:10:00": "3u", "06-10:49:22": "6d", "  01:00:00": "1u"}
        for etime, age in cases.items():
            self.assertEqual(poort.short_age(etime), age, etime)

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


class RenderTest(unittest.TestCase):
    def test_shows_a_worktree_and_an_orphan(self):
        main = poort.Place("shop", "apps/web", "main", False)
        tree = poort.Place("shop", "apps/web", "fix/thing", True)
        rows = [
            listener(3000, 1, args="node x/node_modules/.bin/vite", cwd=HOME_DIR, place=main),
            listener(20110, 2, args="node x/node_modules/.bin/vite", cwd=HOME_DIR, place=tree),
            listener(3417, 3, args="node server.js", cwd="/nowhere/at/all"),
        ]
        lines = [line.split() for line in poort.render_rows(rows, poort.Paint(False), 120)]
        self.assertEqual(lines[0][:4], ["3000", "vite", "shop/apps/web", "main"])
        self.assertEqual(lines[1][:5], ["20110", "vite", "shop/apps/web", "wt", "fix/thing"])
        self.assertEqual(lines[2][:6], ["3417", "node", "server.js", "/nowhere/at/all", "map", "is"])


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
        self.assertEqual(poort.render_rows([item], poort.Paint(False), 120)[0].split(),
                         ["3306", "database", "docker", "api", "mysql:8.4", "6d"])


class DetailTest(unittest.TestCase):
    def test_shows_where_a_process_runs_from(self):
        item = listener(3000, 40997, ppid=40983, args="node server.js", cwd=HOME_DIR + "/shop",
                        place=poort.Place("shop", "", "fix/cart", True))
        item.elapsed = "01:00:00"
        text = "\n".join(poort.render_detail(item, poort.Paint(False)))
        for expected in ["3000  node server.js", "pid        40997  ouder 40983", "map        ~/shop",
                         "branch     fix/cart  worktree", "draait     1u", "stoppen: poort 3000 --kill"]:
            self.assertIn(expected, text)

    def test_says_a_free_port_is_free(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = poort.show_ports([3999], [], kill=False, paint=poort.Paint(False))
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
        self.assertEqual(poort.place_of(os.path.join(self.repo, "apps", "web")),
                         poort.Place("shop", "apps/web", "main", False))

    def test_places_a_worktree_under_its_repo(self):
        self.assertEqual(poort.place_of(self.tree), poort.Place("shop", "", "fix/cart", True))

    def test_has_no_place_outside_git(self):
        self.assertIsNone(poort.place_of(self.tmp.name))
        self.assertIsNone(poort.place_of("/"))


if __name__ == "__main__":
    unittest.main()
