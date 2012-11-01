## -*- coding: utf-8 -*-
##
## runners.py
##
## Author:   Toke Høiland-Jørgensen (toke@toke.dk)
## Date:     16 oktober 2012
## Copyright (c) 2012, Toke Høiland-Jørgensen
##
## This program is free software: you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation, either version 3 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program.  If not, see <http://www.gnu.org/licenses/>.

import threading, time, shlex, subprocess, re, time, sys

from datetime import datetime

class ProcessRunner(threading.Thread):
    """Default process runner for any process."""

    def __init__(self, binary, options, delay, config, *args, **kwargs):
        threading.Thread.__init__(self,*args, **kwargs)
        self.binary = binary
        self.options = options
        self.delay = delay
        self.config = config
        self.result = None

    def run(self):
        """Runs the configured job. If a delay is set, wait for that many
        seconds, then open the subprocess, wait for it to finish, and collect
        the last word of the output (whitespace-separated)."""

        if self.delay:
            time.sleep(self.delay)
        args = [self.binary] + shlex.split(self.options)
        prog = subprocess.Popen(args,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE,
                         universal_newlines=True)
        out,err=prog.communicate()
        if prog.returncode:
            sys.stderr.write("Warning: Program exited non-zero.\nCommand: %s\n" % " ".join(args))
            sys.stderr.write("Program output:")
            sys.stderr.write("  " + "\n  ".join(err.splitlines()) + "\n")
            sys.stderr.write("  " + "\n  ".join(out.splitlines()) + "\n")
            self.result = None
        else:
            self.result = self.parse(out)

    def parse(self, output):
        """Default parser returns the last (whitespace-separated) word of
        output."""

        return output.split()[-1].strip()

DefaultRunner = ProcessRunner

class NetperfDemoRunner(ProcessRunner):
    """Runner for netperf demo mode."""

    def parse(self, output):
        """Parses the interim result lines and returns a list of (time,value)
        pairs."""

        result = []
        lines = output.split("\n")
        for line in lines:
            if line.startswith("Interim"):
                parts = line.split()
                result.append([float(parts[9]), float(parts[2])])

        return result

class PingRunner(ProcessRunner):
    """Runner for ping/ping6 in timestamped (-D) mode."""

    pingline_regex = re.compile(r'^\[([0-9]+\.[0-9]+)\].*time=([0-9]+(?:\.[0-9]+)?) ms$')

    def parse(self, output):
        result = []
        lines = output.split("\n")
        for line in lines:
            match = self.pingline_regex.match(line)
            if match:
                result.append([float(match.group(1)), float(match.group(2))])

        return result

class IperfCsvRunner(ProcessRunner):
    """Runner for iperf csv output (-y C), possibly with unix timestamp patch."""

    def parse(self, output):
        result = []
        lines = output.strip().split("\n")
        for line in lines[:-1]: # The last line is an average over the whole test
            parts = line.split(",")
            if len(parts) < 8:
                continue

            timestamp = parts[0]
            bandwidth = parts[8]

            # If iperf is patched to emit sub-second resolution unix timestamps,
            # there'll be a dot as the decimal marker; in this case, just parse
            # the time as a float. Otherwise, assume that iperf is unpatched
            # (and so emits YMDHMS timestamps).
            #
            # The patch for iperf (v2.0.5) is in the misc/ directory.
            if "." in timestamp:
                result.append([float(timestamp), float(bandwidth)])
            else:
                dt = datetime.strptime(timestamp, "%Y%m%d%H%M%S")
                result.append([time.mktime(dt.timetuple()), float(bandwidth)])

        return result

class TcRunner(ProcessRunner):
    """Runner for iterated `tc -s qdisc`. Expects iterations to be separated by
    '\n---\n and a timestamp to be present in the form 'Time: xxxxxx.xxx' (e.g.
    the output of `date '+Time: %s.%N'`)."""

    time_re = re.compile(r"^Time: (?P<timestamp>\d+\.\d+)", re.MULTILINE)
    qdisc_res = [
        re.compile(r"Sent (?P<sent_bytes>\d+) bytes (?P<sent_pkts>\d+) pkt "
                   r"\(dropped (?P<dropped>\d+), "
                   r"overlimits (?P<overlimits>\d+) "
                   r"requeues (?P<requeues>\d+)\)"),
        re.compile(r"backlog (?P<backlog_bytes>\d+)b "
                   r"(?P<backlog_pkts>\d+)p "
                   r"requeues (?P<backlog_requeues>\d+)"),
        re.compile(r"maxpacket (?P<maxpacket>\d+) "
                   r"drop_overlimit (?P<drop_overlimit>\d+) "
                   r"new_flow_count (?P<new_flow_count>\d+) "
                   r"ecn_mark (?P<ecn_mark>\d+)"),
        re.compile(r"new_flows_len (?P<new_flows_len>\d+) "
                   r"old_flows_len (?P<old_flows_len>\d+)")
        ]


    def parse(self, output):
        result = []
        parts = output.split("\n---\n")
        for part in parts:
            matches = {}
            timestamp = self.time_re.search(part)
            if timestamp is not None:
                timestamp = float(timestamp.group('timestamp'))

            for r in self.qdisc_res:
                m = r.search(part)
                if m is not None:
                    matches.update(m.groupdict())
            key = self.config.get('tc_parameter', 'sent_bytes')
            if timestamp and key in matches:
                result.append([timestamp, float(matches[key])])
        return result