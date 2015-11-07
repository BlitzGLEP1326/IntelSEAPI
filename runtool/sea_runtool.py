﻿#   Intel(R) Single Event API
#
#   This file is provided under the BSD 3-Clause license.
#   Copyright (c) 2015, Intel Corporation
#   All rights reserved.
#
#   Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#       Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
#       Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
#       Neither the name of the Intel Corporation nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission.
#
#   THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
#   IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
#   HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
#********************************************************************************************************************************************************************************************************************************************************************************************

import os
import sys
import cgi #for escaping XML
import struct
from glob import glob

from subprocess import Popen, PIPE

#FIXME: if you have end and don't have begin, count that begin is the time of trace begin

class DummyWith(): #for conditional with statements
    def __enter__(self):
        return self
    def __exit__(self, type, value, traceback):
        return False

def parse_args(args):
    import argparse
    parser = argparse.ArgumentParser(epilog="After this command line add ! followed by command line of your program")
    format_choices = ["gt", "mfc", "mfp", "qt", "fd", "btf"]
    if sys.platform == 'win32':
        format_choices.append("etw")
    elif sys.platform == 'darwin':
        format_choices.append("xcode")
    elif sys.platform == 'linux':
        format_choices.append("kernelshark")
    parser.add_argument("-f", "--format", choices=format_choices, nargs='*')
    parser.add_argument("-o", "--output")
    parser.add_argument("-b", "--bindir")
    parser.add_argument("-i", "--input")
    parser.add_argument("-t", "--trace")
    parser.add_argument("-d", "--dir")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-c", "--cuts", nargs='*')
    parser.add_argument("-s", "--sync")
    parser.add_argument("--dry", action="store_true")

    if "!" in args:
        separator = args.index("!")
        parsed_args = parser.parse_args(args[:separator])
        victim = args[separator + 1:]
        victim[-1] = victim[-1].strip() #removal of trailing '\r' - when launched from .sh
        return (parsed_args, victim)
    else: #nothing to launch, transformation mode
        args[-1] = args[-1].strip() #removal of trailing '\r' - when launched from .sh
        parsed_args = parser.parse_args(args)
        if parsed_args.input:
            if not parsed_args.output:
                parsed_args.output = parsed_args.input
            return (parsed_args, None)
        print "--input argument is required for transformation mode."
        parser.print_help()
        sys.exit(-1)

def main():
    (args, victim) = parse_args(sys.argv[1:]) #skipping the script name
    if victim:
        launch(args, victim)
    else:
        if args.input.endswith(".xml"):
            transform_etw_xml(args)
        else:
            transform(args)

def os_lib_ext():
    if sys.platform == 'win32':
        return '.dll'
    elif sys.platform == 'darwin':
        return '.dylib'
    elif 'linux' in sys.platform:
        return '.so'
    assert(not "Unsupported platform")

def echo(what, where):
    try:
        with open(where, "w") as file:
            file.write(what)
            return True
    except:
        return False

class FTrace:
    def __init__(self, args):
        self.args = args
        self.file = args.output + ".ftrace"
        echo("0", "/sys/kernel/debug/tracing/tracing_on")
        echo("", "/sys/kernel/debug/tracing/trace") #cleansing ring buffer (we need it's header only)
        Popen("cat /sys/kernel/debug/tracing/trace > " + self.file, shell=True).wait()
        self.proc = Popen("cat /sys/kernel/debug/tracing/trace_pipe >> " + self.file, shell=True)
        echo("1", "/sys/kernel/debug/tracing/tracing_on")
    def stop(self):
        echo("0", "/sys/kernel/debug/tracing/tracing_on")
        self.proc.terminate()
        return self.file

def start_ftrace(args):
    if not echo("nop", "/sys/kernel/debug/tracing/current_tracer"):
        print "Warning: failed to access ftrace subsystem"
        return False
    echo("*:*", "/sys/kernel/debug/tracing/set_event") #enabling all events
    return FTrace(args)

def launch(args, victim):
    env={}
    script_dir = os.path.abspath(args.bindir) if args.bindir else os.path.dirname(os.path.realpath(__file__))
    paths = []
    macosx = sys.platform == 'darwin'
    for bits in (['32', '64'] if not macosx else ['']):
        search = os.path.sep.join([script_dir, "*IntelSEAPI" + bits + os_lib_ext()])
        files = glob(search)
        if not len(files):
            print "Error: didn't find any files for:", search
            sys.exit(-1)
        paths.append(files[0])
    if macosx:
        env["DYLD_INSERT_LIBRARIES"] = paths[0]
    else:
        env["INTEL_LIBITTNOTIFY32"] = paths[0]
        env["INTEL_LIBITTNOTIFY64"] = paths[1]
    env["INTEL_SEA_FEATURES"] = str(args.format) if args.format else ""

    if args.output:
        env["INTEL_SEA_SAVE_TO"] = args.output

    if (args.dry):
        for key, val in env.iteritems():
            if val:
                print key + "=" + val
        return

    new_env = dict(os.environ)
    new_env.update(env)
    env = new_env

    if 'kernelshark' in args.format:
        victim = 'trace-cmd record -e IntelSEAPI/* ' + victim

    ftrace = start_ftrace(args) if ('gt' in args.format and 'linux' in sys.platform and args.output) else False

    proc = Popen(victim, env=env, shell=False, cwd=args.dir)
    proc.wait()
    if ftrace:
        args.trace = ftrace.stop()
    if args.output:
        args.input = "%s-%d" % (args.output, proc.pid)
        transform(args)

def extract_cut(filename):
    return (filename.split("!")[1].split("-")[0]) if ('!' in filename) else None

def default_tree():
    return {"strings":{}, "domains": {}, "threads":{}, "modules":{}, "ring_buffer": False, "cuts":set()}

def sea_reader(folder): #reads the structure of .sea format folder into dictionary
    tree = default_tree()
    pos = folder.rfind("-") #pid of the process is encoded right in the name of the folder
    tree["pid"] = int(folder[pos+1:])
    folder = folder.replace("\\", "/").rstrip("/")
    toplevel = os.walk(folder).next()
    for filename in toplevel[2]:
        with open("/".join([folder, filename]), "r") as file:
            if filename.endswith(".str"): #each string_handle_create writes separate file, name is the handle, content is the value
                tree["strings"][int(filename.replace(".str", ""))] = file.readline()
            elif filename.endswith(".tid"): #named thread makes record: name is the handle and content is the value
                tree["threads"][filename.replace(".tid", "")] = file.readline()
            elif filename.endswith(".mdl"): #registered modules - for symbol resolving
                tree["modules"][int(filename.replace(".mdl", ""))] = file.readline()
    for domain in toplevel[1]:#data from every domain gets recorded into separate folder which is named after the domain name
        tree["domains"][domain] = {"files":[]}
        for file in os.walk("/".join([folder, domain])).next()[2]: #each thread of this domain has separate file with data
            if not file.endswith(".sea"):
                print "Warning: weird file found:", file
                continue
            filename = file[:-4]

            tree["ring_buffer"] = tree["ring_buffer"] or ('-' in filename)
            tid = int(filename.split("!")[0].split("-")[0])
            tree["cuts"].add(extract_cut(filename))

            tree["domains"][domain]["files"].append((tid, "/".join([folder, domain, file])))
        def time_sort(item):
            with open(item[1], "rb") as file:
                tuple = read_chunk_header(file)
                return tuple[0]
        tree["domains"][domain]["files"].sort(key=time_sort)
    return tree

g_progress_interceptor = None

class Progress:
    def __init__(self, total, steps, message = ""):
        self.total = total
        self.steps = steps
        self.shown_steps = 0
        self.message = message
        print message, "[",

    def __enter__(self):
        return self

    def tick(self, current):
        if g_progress_interceptor:
            g_progress_interceptor(self.message, current, self.total)
        self.show_progress(int(self.steps * current / self.total))

    def show_progress(self, show_steps):
        if self.shown_steps < show_steps:
            for i in range(show_steps - self.shown_steps):
                print ".",
            self.shown_steps = show_steps

    def __exit__(self, type, value, traceback):
        if g_progress_interceptor:
            g_progress_interceptor(self.message, self.total, self.total)
        self.show_progress(self.steps)
        print "]"

    @staticmethod
    def set_interceptor(interceptor):
        global g_progress_interceptor
        g_progress_interceptor = interceptor


def read_chunk_header(file):
    chunk = file.read(10) #header of the record, see STinyRecord in Recorder.cpp
    if chunk == '':
        return (0,0,0)
    return struct.unpack('Qbb', chunk)

def transform(args):
    tree = sea_reader(args.input) #parse the structure
    if args.cuts and args.cuts == ['all']:
        return transform2(args, tree)
    else:
        result = []
        output = args.output[:] #deep copy
        for current_cut in tree['cuts']:
            if args.cuts and current_cut not in args.cuts:
                continue
            args.output = (output + "!" + current_cut) if current_cut else output
            print "Cut #", current_cut if current_cut else "<None>"
            def skip_fn(path):
                filename = os.path.split(path)[1]
                if current_cut: #read only those having this cut name in filename
                    if current_cut != extract_cut(filename[:-4]):
                        return True
                else: #reading those haveing not cut name in filename
                    if "!" in filename:
                        return True
                return False
            result += transform2(args, tree, skip_fn)
        args.output = output
        return result

TaskTypes = [
    "task_begin", "task_end",
    "task_begin_overlapped", "task_end_overlapped",
    "metadata_str_add",
    "marker",
    "counter",
    "frame_begin", "frame_end",
    "object_new", "object_snapshot", "object_delete",
    "relation"
]

class Callbacks:
    callbacks = [] #while parsing we might have one to many 'listeners' - output format writers
    def __init__(self, args, tree):
        if "qt" in args.format:
            self.callbacks.append(QTProfiler(args, tree))
        if "gt" in args.format:
            self.callbacks.append(GoogleTrace(args, tree))
        if "fd" in args.format:
            self.callbacks.append(FrameDebugger(args, tree))
        if "btf" in args.format:
            self.callbacks.append(BestTraceFormat(args, tree))

    def is_empty(self):
        return 0 == len(self.callbacks)

    def __enter__(self):
        [callback.__enter__() for callback in self.callbacks]
        return self

    def __exit__(self, type, value, traceback):
        [callback.__exit__(type, value, traceback) for callback in self.callbacks] #emulating 'with' statement
        return False

    def on_event(self, type, data):
        #copy here as handler can change the data for own good - this shall not affect other handlers
        [callback(type, data.copy()) for callback in self.callbacks]

    def get_result(self):
        return [callback.get_target() for callback in self.callbacks]

def transform2(args, tree, skip_fn = None):

    with Callbacks(args, tree) as callbacks:
        if callbacks.is_empty():
            return callbacks.get_result()

        count = 0
        for domain, content in tree["domains"].iteritems(): #go thru domains
            for tid, path in content["files"]: #go thru per thread files

                if skip_fn and skip_fn(path): #for "cut" support
                    continue

                if args.verbose:
                    print path
                    progress = DummyWith()
                else:
                    progress = Progress(os.path.getsize(path), 10, path)

                with progress:
                    with open(path, "rb") as file:
                        while True: #records iteration
                            call = {"tid": tid, "pid": tree["pid"], "domain": domain}

                            tuple = read_chunk_header(file)
                            if tuple == (0,0,0): #mem mapping wasn't trimed on close, zero padding goes further
                                break
                            call["time"] = tuple[0]
                            type = tuple[1]

                            assert(type < len(TaskTypes)); #sanity check
                            flags = tuple[2]
                            assert(flags < 0x80); #sanity check
                            if flags & 0x1: #has id
                                chunk = file.read(3*8)
                                call["id"] = struct.unpack('QQQ', chunk)[0]
                            if flags & 0x2: #has parent
                                chunk = file.read(3*8)
                                call["parent"] = struct.unpack('QQQ', chunk)[0]
                            if flags & 0x4: #has string
                                chunk = file.read(8)
                                str_id = struct.unpack('Q', chunk)[0] #string handle
                                call["str"] = tree["strings"][str_id]
                            if flags & 0x8: #has tid, that differs from the calling thread (virtual tracks)
                                chunk = file.read(8)
                                call["tid"] = struct.unpack('Q', chunk)[0]

                            if tree["threads"].has_key(str(call["tid"])):
                                call["thread_name"] = tree["threads"][str(call["tid"])]
                            else:
                                call["thread_name"] = hex(call["tid"])

                            if flags & 0x10: #has data
                                chunk = file.read(8)
                                length = struct.unpack('Q', chunk)[0]
                                call["data"] = file.read(length)
                            if flags & 0x20: #has delta
                                chunk = file.read(8)
                                call["delta"] = struct.unpack('d', chunk)[0]

                            if flags & 0x40: #has pointer
                                chunk = file.read(8)
                                ptr = struct.unpack('Q', chunk)[0]
                                if not resolve_pointer(args, tree, ptr, call):
                                    call["pointer"] = ptr

                            if args.verbose:
                                print "%d\t%s\t%s" % (count, TaskTypes[type], call)
                            elif count % 10 == 0:
                                progress.tick(file.tell())

                            callbacks.on_event(TaskTypes[type], call)
                            count += 1

    return callbacks.get_result()


def get_module_by_ptr(tree, ptr):
    keys = list(tree['modules'].iterkeys())
    keys.sort() #looking for first bigger the address, previous is the module we search for
    item = keys[0]
    for key in keys[1:]:
        if key > ptr:
            break;
        item = key
    assert(item < ptr)
    return (ptr - item, tree['modules'][item])

def resolve_pointer(args, tree, ptr, call, cache = {}):
    if not cache.has_key(ptr):
        (addr, path) = get_module_by_ptr(tree, ptr)
        if not os.path.exists(path):
            return False
        if sys.platform == 'win32':
            script_dir = os.path.abspath(args.bindir) if args.bindir else os.path.dirname(os.path.realpath(__file__))
            executable = os.path.sep.join([script_dir, 'TestIntelSEAPI32.exe'])
            cmd = "%s %s:%d" % (executable, path, addr)
        elif sys.platform == 'darwin':
            cmd = ""
        elif 'linux' in sys.platform:
            cmd = "addr2line %s -e %s -i -p -f -C" % (to_hex(ptr), path)
        else:
            assert(not "Unsupported platform!")

        env=dict(os.environ)
        if env.has_key("INTEL_SEA_VERBOSE"):
            del env["INTEL_SEA_VERBOSE"]
        proc = Popen(cmd, shell=True, stdout=PIPE, stderr=PIPE, env=env)

        cache[ptr], err = proc.communicate()
        assert(not err)
    lines = cache[ptr].splitlines()
    if not lines:
        return False
    if sys.platform == 'win32':
        if len(lines) == 1:
            call['str'] = lines[0]
        elif len(lines) == 2:
            call['str'] = lines[1]
            (call['__file__'], call['__line__']) = lines[0].rstrip(")").rsplit("(", 1)
    else:
        (call['str'], fileline) = lines[0].split(" at ")
        (call['__file__'], call['__line__']) = fileline.strip().split(":")
    return True

def attachme():
    print "Attach me!"
    while not sys.gettrace():
        pass
    import time
    time.sleep(1)


class TaskCombiner:

    no_begin = [] #for the ring buffer case when we get task end but no task begin
    time_bounds = [2**64, 0] #left and right time bounds

    def __enter__(self):
        return self
    def __exit__(self, type, value, traceback):
        self.handle_leftovers()
        self.finish()
        return False

    def __init__(self, tree):
        self.tree = tree
        self.domains = {}
        self.events = []
        self.event_map = {}

    def global_metadata(self, data):
        pass

    def relation(self, data, head, tail):
        pass

    def handle_leftovers(self):
        for end in self.no_begin:
            begin = end.copy()
            begin['time'] = self.time_bounds[0]
            self.complete_task("task", begin, end)
        for domain, threads in self.domains.iteritems():
            for tid, records in threads.iteritems():
                for id, per_id_records in records['byid'].iteritems():
                    for begin in per_id_records:
                        end = begin.copy()
                        end['time'] = self.time_bounds[1]
                        self.complete_task("task", begin, end)
                for begin in records['stack']:
                    end = begin.copy()
                    end['time'] = self.time_bounds[1]
                    self.complete_task("task", begin, end)

    def __call__(self, fn, data):
        domain = self.domains.setdefault(data['domain'], {})
        thread = domain.setdefault(data['tid'], {'byid':{}, 'stack':[]})

        def get_tasks(id):
            if not id:
                return thread['stack']
            return thread['byid'].setdefault(id, [])

        def get_task(id):
            if id:
                tasks = get_tasks(id)
                if not tasks: #they can be stacked
                    tasks = get_tasks(None)
                    if not tasks or not tasks[-1].has_key('id') or tasks[-1]['id'] != id:
                        return None
            else:
                tasks = get_tasks(None)
            if tasks:
                return tasks[-1]
            else:
                return None

        def find_task(id):
            for _, thread_stacks in domain.iteritems(): #look in all threads
                if thread_stacks['byid'].has_key(id) and len(thread_stacks['byid'][id]):
                    return thread_stacks['byid'][id][-1]
                else:
                    for item in thread_stacks['stack']:
                        if item.has_key('id') and item['id'] == id:
                            return item

        if fn == "task_begin" or fn == "task_begin_overlapped":
            self.time_bounds[0] = min(self.time_bounds[0], data['time'])
            get_tasks(None if fn == "task_begin" else data['id']).append(data)
        elif fn == "task_end" or fn == "task_end_overlapped":
            self.time_bounds[1] = max(self.time_bounds[1], data['time'])
            tasks = get_tasks(None if fn == "task_end" else data['id'])
            if len(tasks):
                item = tasks.pop()
                self.complete_task("task", item, data)
            else:
                assert(self.tree["ring_buffer"] or self.tree['cuts'])
                self.no_begin.append(data)
        elif fn == "frame_begin":
            get_tasks(data['id'] if data.has_key('id') else None).append(data)
        elif fn == "frame_end":
            frames = get_tasks(data['id'] if data.has_key('id') else None)
            if len(frames):
                item = frames.pop()
                self.complete_task("frame", item, data)
            else:
                assert(self.tree["ring_buffer"] or self.tree['cuts'])
        elif fn=="metadata_str_add":
            task = get_task(data['id'] if data.has_key('id') else None)
            if task:
                args = task.setdefault('args', {})
                args[data['str']] = data['data']
            else:#global metadata
                self.global_metadata(data)
        elif fn == "object_snapshot":
            if data.has_key('args'):
                args = data['args'].copy()
            else:
                args = {'snapshot':{}}
            if data.has_key('data'):
                state = data['data']
                for pair in state.split(","):
                    (key, value) = tuple(pair.split("="))
                    args['snapshot'][key] = value
            data['args'] = args
            self.complete_task(fn, data, data)
        elif fn in ["marker", "counter", "object_new", "object_delete"]:
            if fn == "marker" and data['data'] == 'task':
                markers = get_tasks("marker_" + (data['id'] if data.has_key('id') else ""))
                if markers:
                    item = markers.pop()
                    self.complete_task("task", item, data)
                markers.append(data)
            else:
                self.complete_task(fn, data, data)
        elif fn == "relation":
            self.relation(
                data,
                get_task(data['id'] if data.has_key('id') else None),
                get_task(data['parent']) or find_task(data['parent'])
            )
        else:
            assert(not "Unsupported type:" + fn)

def to_hex(value):
    return "0x" + hex(value).rstrip('L').replace("0x", "").upper()

class GoogleTrace(TaskCombiner):
    def __init__(self, args, tree):
        TaskCombiner.__init__(self, tree)
        self.args = args
        self.file = open(self.get_target(), "w")
        self.target_scale_start = 0
        self.source_scale_start = 0
        self.ratio = 1 / 1000.

        self.file.write('{')
        if args.trace:
            self.handle_ftrace(args.trace)
        elif args.sync:
            self.apply_time_sync(args.sync)
        self.file.write('\n"traceEvents": [\n')

        for key, value in tree["threads"].iteritems():
            self.file.write(
                '{"name": "thread_name", "ph":"M", "pid":%d, "tid":%s, "args": {"name":"%s"}},\n' % (tree['pid'], key, value)
            )

    def get_target(self):
        return self.args.output + ".json"

    def convert_time(self, time):
        return (time - self.source_scale_start) * self.ratio + self.target_scale_start

    @staticmethod
    def read_ftrace_lines(trace, time_sync):
        write_chrome_time_sync = True
        with open(trace) as file:
            with Progress(os.path.getsize(trace), 10, "Loading ftrace") as progress:
                for line in file:
                    if 'IntelSEAPI_Time_Sync' in line:
                        parts = line.split()
                        time_sync.append((float(parts[-4].strip(":")), int(parts[-1]))) #target (ftrace), source (nanosecs)
                        if write_chrome_time_sync: #chrome time sync, pure zero doesn't work, so we shift on very little value
                            yield "%strace_event_clock_sync: parent_ts=%s\n" % (line.split("IntelSEAPI_Time_Sync")[0], line.split(":")[-4].split()[-1])
                            write_chrome_time_sync = False #one per trace is enough
                    else:
                        yield line
                    progress.tick(file.tell())

    def handle_ftrace(self, trace):
        time_sync = []
        self.file.write('\n"systemTraceEvents": "')

        for line in read_ftrace_lines(trace):
            self.file.write(line.strip("\r\n").replace('\\', '\\\\').replace('"', r'\"') + r"\n")
        self.file.write('",\n')
        self.apply_time_sync(time_sync)

    def apply_time_sync(self, time_sync):
        Target = 0
        Source = 1
        #looking for closest time points to calculate start points
        diffs = []
        for i in range(1, len(time_sync)):
            diff = (time_sync[i][Target] - time_sync[i-1][Target], time_sync[i][Source] - time_sync[i-1][Source])
            diffs.append((diff, i))
        diffs.sort()
        (diff, index) = diffs[0] #it's the width between two closest measurements

        #source measurement is the fisrt, target is second
        #Target time is always after the source, due to workflow
        #one measurement is begin -> begin and another is end -> end
        #if nothing interferes begin -> begin measurement should take same time as end -> end

        #run 1: most ballanced case - everything is even
        #S   /b  |  |  I  /e
        #T          /b  I  |  |  /e

        #run 2: takes more time after Target measurement
        #S   /b  |  |  I  /e
        #T      /b  I  |  |  /e

        #run 3: takes more time before Targer measurement
        #S   /b  |  |  I  /e
        #T              /b  I  |  |  /e

        #From these runs obvious that in all cases the closest points (I) of global timeline are:
        #   Quater to end of Source and Quater after begin of Target
        self.source_scale_start = time_sync[index - 1][Source] + int(diff[Source] * 0.75) #to keep the precision
        self.target_scale_start = (time_sync[index - 1][Target] + (diff[Target] * 0.25)) * 1000000. #multiplying by 1000000. to have time is microseconds (ftrace/target time was in seconds)

        print "Timelines correlation precision is +- %f us" % (diff[Target] / 2. * 1000000.)

        #taking farest time points to calculate frequencies
        diff = (time_sync[-1][Target] - time_sync[0][Target], time_sync[-1][Source] - time_sync[0][Source])
        self.ratio = 1000000. * diff[Target] / diff[Source] # when you multiply Source value with this ratio you get Target units, multiplying by 1000000. to have time is microseconds (ftrace/target time was in seconds)


    def global_metadata(self, data):
        if data['str'] == "__process__":
            self.file.write(
                '{"name": "process_name", "ph":"M", "pid":%d, "tid":%s, "args": {"name":"%s"}},\n' % (data['pid'], data['tid'], data['data'].replace("\\", "\\\\"))
            )
            if not self.tree['threads'].has_key(str(data['tid'])):
                self.file.write(
                    '{"name": "thread_name", "ph":"M", "pid":%d, "tid":%s, "args": {"name":"%s"}},\n' % (data['pid'], data['tid'], "<main>")
                )

    def relation(self, data, head, tail):
        if not head or not tail:
            return
        items = sorted([head, tail], key=lambda item: item['time']) #we can't draw lines in backward direction, so we sort them by time
        template = '{"ph":"%s", "name": "relation", "pid":%d, "tid":%s, "ts":%.3f, "id":%s, "args":{"name": "%s"}, "cat":"%s"},\n'
        if not data.has_key('str'):
            data['str'] = "unknown"
        self.file.write(template % ("s", data['pid'], items[0]['tid'], self.convert_time(items[0]['time']), data['parent'], data['str'], data['domain']))
        self.file.write(template % ("f", data['pid'], items[1]['tid'], self.convert_time(items[1]['time']), data['parent'], data['str'], data['domain']))

    def format_value(self, arg): #this function must add quotes if value is string, and not number/float, do this recursively for dictionary
        if type(arg) == type({}):
            return "{" + ", ".join(['"%s":%s' % (key, self.format_value(value)) for key, value in arg.iteritems()]) + "}"
        if ('isdigit' in dir(arg)) and arg.isdigit():
            return arg
        try:
            val = float(arg)
            if val.is_integer():
                return int(val)
            else:
                return val
        except:
            return '"%s"' % str(arg).replace("\\", "\\\\")

    def complete_task(self, type, begin, end):
        #TODO:
        #obj tracking: g_TraceEventFormat.WriteEvent(CTraceEventFormat::ObjectNew, std::string(objtype) + ":" + objname, CTraceEventFormat::CArgs(), &rf, kind, &id);

        res = []
        phase = {'task':'X', 'counter':'C', 'marker':'i', 'object_new':'N', 'object_snapshot':'O', 'object_delete':'D', 'frame':'X'}
        assert(phase.has_key(type))
        res.append('{"ph":"%s"' % (phase[type]))
        res.append(', "pid":%(pid)d, "tid":%(tid)d' % begin)
        res.append(', "ts":%.3f' % (self.convert_time(begin['time'])))

        if "marker" == type:
            name = begin['str']
            markers = {
                "unknown":"t",
                "global":"g",
                "track_group":"p",
                "track":"t",
                "task":"t",
                "marker":"t"
            }
            res.append(', "s":"%s"' % (markers[begin['data']]))
        elif "object_" in type:
            if begin.has_key('str'):
                name = begin['str']
            else:
                name = ""
        elif "frame" == type:
            if begin.has_key('str'):
                name = type + ":" + begin['str']
            else:
                name = type + ":" + begin['domain']
        else:
            if type not in ["counter", "task"]:
                name = type + ":"
            else:
                name = ""

            if begin.has_key('parent'):
                name += to_hex(begin['parent']) + "->"
            if begin.has_key('str'):
                name += begin['str'] + ":"
            if begin.has_key('pointer'):
                name += "func<"+ to_hex(begin['pointer']) + ">:"
            if begin.has_key('id'):
                name += "(" + to_hex(begin['id']) + ")"
            else:
                name = name.rstrip(":")

        assert(name or "object_" in type)
        res.append(', "name":"%s"' % (name))
        res.append(', "cat":"%s"' % (begin['domain']))

        if begin.has_key('id'):
            res.append(', "id":%s' % (begin['id']))
        if type in ['task', 'frame']:
            res.append(', "dur":%.3f' % (self.convert_time(end['time']) - self.convert_time(begin['time'])))
        args = {}
        if begin.has_key('args'):
            args = begin['args'].copy()
        if end.has_key('args'):
            args.update(end['args'])
        if begin.has_key('__file__'):
            args["__file__"] = begin["__file__"]
            args["__line__"] = begin["__line__"]
        if 'counter' == type:
            args[name] = begin['delta']
        if args:
            res.append(', "args":')
            res.append(self.format_value(args))
            res.append(' ');
        res.append('}, ');
        self.file.write("".join(res + ['\n']))

    def finish(self):
        self.file.write("{}]}")
        self.file.close()

    @staticmethod
    def join_traces(traces, output):
        import zipfile
        with zipfile.ZipFile(output + ".zip", 'w') as zip:
            for file in traces:
                zip.write(file, os.path.basename(file))
        return output + ".zip"


class QTProfiler(TaskCombiner): #https://github.com/danimo/qt-creator/blob/master/src/plugins/qmlprofiler/qmlprofilertracefile.cpp https://github.com/danimo/qt-creator/blob/master/src/plugins/qmlprofiler/qv8profilerdatamodel.cpp
    def __init__(self, args, tree):
        TaskCombiner.__init__(self, tree)
        self.args = args
        self.file_name = self.get_target()
        self.file = open(self.file_name, "w")
        self.notes = []
        self.start_time = None
        self.end_time = None

    def get_target(self):
        return self.args.output + ".qtd"

    def set_times(self, start, end):
        if self.start_time is None:
            self.start_time = start
        else:
            self.start_time = min(start, self.start_time)
        if self.end_time is None:
            self.end_time = end
        else:
            self.end_time = max(end, self.end_time)

    def complete_task(self, type, begin, end):
        if begin.has_key('str'):
            name = begin['str']
        elif begin.has_key('pointer'):
            name = "func<"+ to_hex(begin['pointer']) + ">"
        else:
            name = "<unknown>"

        details = (type + ":") if type != 'task' else ""
        if begin.has_key('parent'):
            details += to_hex(begin['parent']) + "->"
        details += name + ":"
        if begin.has_key('id'):
            details += "(" + to_hex(begin['id']) + ")"
        else:
            details = details.rstrip(":")

        if type == 'counter' or type == 'marker':
            kind = 'Painting'
        elif type == 'frame' or 'object_' in type:
            kind = 'Creating'
        else:
            kind = 'Javascript'

        record = (
            begin['__file__'].replace("\\", "/") if begin.has_key('__file__') else "",
            begin['__line__'] if begin.has_key('__line__') else "0",
            kind,
            "%s | %s | %s" % (details, begin['thread_name'], begin['domain']),
            name
        )
        record = tuple([cgi.escape(item) for item in record])

        if self.event_map.has_key(record):
            index = self.event_map[record]
        else:
            index = len(self.events)
            self.events.append(record)
            self.event_map[record] = index
        start_time = round(begin['time'] / 1000) #sad but it's limiter to milliseconds only
        end_time = round(end['time'] / 1000)
        dur = end_time - start_time
        if not dur or dur < 0: #QT Creator doesn't show notes on objects with zero duration
            dur = 1
        tag = '<range startTime="%d" duration="%d" eventIndex="%d"/>\n' % (start_time, dur, index)

        args = {}
        if type == "counter":
            args['delta'] = begin['delta']
        if begin.has_key('args'):
            args = begin['args']
            if end.has_key('args'):
                args.update(end['args'])
        if args:
            self.notes.append((start_time, dur, index, args))

        self.set_times(start_time, end_time)
        self.file.write(tag)

    def write_header(self):
        #at this moment print is redirected to output file
        print '<?xml version="1.0" encoding="UTF-8"?>'
        print '<trace version="1.02" traceStart="%d" traceEnd="%d">' % (self.start_time, self.end_time)
        print '<eventData totalTime="%d">' % (self.end_time - self.start_time)
        counter = 0
        for event in self.events:
            print '<event index="%d"><filename>%s</filename><line>%s</line><type>%s</type><details>%s</details><displayname>%s</displayname></event>'\
                % (counter, event[0], event[1], event[2], event[3], event[4])
            counter += 1
        print '</eventData><profilerDataModel>'

    def write_footer(self, file):
        file.write('</profilerDataModel><noteData>\n')
        for note in self.notes:
            args = "\n".join([key + " = " + str(val).replace("{","").replace("}","") for key, val in note[3].iteritems()])
            file.write('<note startTime="%d" duration="%d" eventIndex="%d">%s</note>\n' % (note[0], note[1], note[2], cgi.escape(args)))
        file.write('</noteData><v8profile totalTime="0"/></trace>\n')

    def finish(self):
        import fileinput
        self.file.close()
        fi = fileinput.input(self.file_name, inplace=1)
        for line in fi:
            if fi.isfirstline():
                self.write_header()
            print line,
        with open(self.file_name, "a") as file:
            self.write_footer(file)

    @staticmethod
    def join_traces(traces, output):
        import xml.dom.minidom as minidom
        output += ".qtd"
        with open(output, "w") as file:
            print >>file, '<?xml version="1.0" encoding="UTF-8"?>'
            traces = [minidom.parse(trace) for trace in traces] #parse all traces right away
            traceStarts = sorted([int(dom.documentElement.attributes['traceStart'].nodeValue) for dom in traces]) #earlist start time
            traceEnds = sorted([int(dom.documentElement.attributes['traceEnd'].nodeValue) for dom in traces], reverse = True)#latest end time
            print >>file, '<trace version="1.02" traceStart="%d" traceEnd="%d">' % (traceStarts[0], traceEnds[0])
            print >>file, '<eventData totalTime="%d">' % (traceEnds[0] - traceStarts[0])
            event_count = [] #accumulate event count to map indices
            for dom in traces: #first we go by events
                events = dom.getElementsByTagName('eventData')[0].getElementsByTagName('event')
                for event in events: #and correct each event index, adding count of events in previous files
                    index = int(event.attributes['index'].nodeValue) + sum(event_count)
                    event.setAttribute('index', str(index))
                    print >>file, event.toxml()
                event_count.append(len(events)) #for next traces to adjust index start
            print >>file, '</eventData><profilerDataModel>'
            index = 0
            for dom in traces:
                ranges = dom.getElementsByTagName('profilerDataModel')[0].getElementsByTagName('range')
                for range in ranges:
                    eventIndex = int(range.attributes['eventIndex'].nodeValue) + sum(event_count[:index])
                    range.setAttribute('eventIndex', str(eventIndex))
                    print >>file, range.toxml()
                index += 1
            print >>file, '</profilerDataModel><noteData>'
            index = 0
            for dom in traces:
                notes = dom.getElementsByTagName('noteData')[0].getElementsByTagName('note')
                for note in notes:
                    eventIndex = int(note.attributes['eventIndex'].nodeValue) + sum(event_count[:index])
                    note.setAttribute('eventIndex', str(eventIndex))
                    print >>file, note.toxml()
                index += 1
            print >>file, '</noteData><v8profile totalTime="0"/></trace>'
        return output

class FrameDebugger(TaskCombiner):
    def __init__(self, args, tree):
        TaskCombiner.__init__(self, tree)
        sefl.args = args
        self.file = open(self.get_target(), "w+b")
        self.file.write('name, time\n')

    def get_target(self):
        return self.args.output + ".gpa_csv"

    def complete_task(self, type, begin, end):
        start_time = round(begin['time'] / 1000)
        end_time = round(end['time'] / 1000)
        self.file.write('%s, %d\n' % (begin['str'], round((end['time'] - begin['time']) / 1000)))

    def finish(self):
        self.file.close()

    @staticmethod
    def join_traces(traces, output):
        raise NotImplementedError()


###################################
# TODO: add OS events (sched/vsync)
class BestTraceFormat(TaskCombiner):
    """Writer for Best Trace Format.

    Specs for BTF v2.1.3: https://wiki.eclipse.org/images/e/e6/TA_BTF_Specification_2.1.3_Eclipse_Auto_IWG.pdf
    """
    def __init__(self, args, tree):
        """Open the .btf file and write its header."""
        TaskCombiner.__init__(self, tree)
        self.args = args
        self.file = open(self.get_target(), "w+b")
        self.file.write('#version 2.1.3\n')
        self.file.write('#creator GDP-SEA\n')
        self.file.write('#creationDate 2014-02-19T11:39:20Z\n')
        self.file.write('#timeScale ns\n')

    def get_target(self):
        return self.args.output + ".btf"

    def complete_task(self, type, b, e):
        """
        type -- task type : {"task", "frame", "counter"}
        b -- { 'thread_name': '0x6296', 'domain': 'gles.trace.ergs', 'str': 'glPopMatrix', 'time': 1443097648250368731, 'tid': 25238, 'pid': 25238}
        e -- { 'tid': 25238, 'thread_name': '0x6296', 'domain': 'gles.trace.ergs', 'pid': 25238, 'time': 1443097648250548143}
        """
        # <Time>,<Source>,<SourceInstance >,<TargetType>,<Target>,<TargetInstance>,<Event>,<Note>
        if 'str' in b and type=="task":
            self.file.write("%d,%s,0,R,%s,-1,start\n" % (b['time'], b['str'],b['str']))
            self.file.write("%d,%s,0,R,%s,-1,terminate\n" % (e['time'], b['str'],b['str']))

    def finish(self):
        """ Close the .btf file"""
        self.file.close()

    @staticmethod
    def join_traces(traces, output):
        with open(output + ".btf", 'wb') as outfile:
            for file in traces:
                with open(file, 'rb') as infile:
                    for line in infile:
                        outfile.write(line)
        return output + ".btf"

class ETWXML:
    def __init__(self, callback, providers):
        self.callback = callback
        self.providers = providers

    def tag_name(self, tag):
        if tag[0] == '{':
            return tag.split('}')[1]
        return tag

    def iterate_events(self, file):
        import xml.etree.ElementTree as ET
        level = 0
        for event, elem in ET.iterparse(file, events=('start','end')):
            if event == 'start':
                level += 1
                if level == 2:
                    yield elem
            else:
                level -= 1
            elem.clear()

    def as_dict(self, elem):
        return dict((self.tag_name(child.tag), child) for child in elem.getchildren())

    def parse_system(self, system):
        res = {}
        system = self.as_dict(system)
        if not system:
            return res
        provider = system['Provider']
        execution = system['Execution'] if system.has_key('Execution') else None
        res['provider'] = provider.attrib['Name'] if provider.attrib.has_key('Name') else provider.attrib['Guid']
        if execution != None:
            res['pid'] = execution.attrib['ProcessID']
            res['tid'] = execution.attrib['ThreadID']
        if system.has_key('TimeCreated'):
            time_created = system['TimeCreated']
            res['time'] = time_created.attrib['RawTime']
        return res

    def parse_event_data(self, data):
        res = {}
        for child in data.getchildren():
            if 'ComplexData' == self.tag_name(child.tag):
                res[child.attrib['Name']] = self.parse_event_data(child)
            else:
                res[child.attrib['Name']] = child.text.strip() if child.text else ""
        return res

    def parse_rendering_info(self, info):
        res = {}
        info = self.as_dict(info)
        for key, data in info.iteritems():
            res[key] = data.text.strip() if data.text else ""
        return res

    def parse(self, file):
        unhandled_providers = set()
        for elem in self.iterate_events(file):
            children = self.as_dict(elem)
            if not children:
                continue
            system = self.parse_system(children['System'])
            if not system:
                continue
            if system['provider'] in self.providers:
                data = self.parse_event_data(children['EventData']) if children.has_key('EventData') else None
                info = self.parse_rendering_info(children['RenderingInfo']) if children.has_key('RenderingInfo') else None
                self.callback(system, data, info)
            else:
                if system['provider'] not in unhandled_providers:
                    unhandled_providers.add(system['provider'])
        return unhandled_providers

def transform_etw_xml(args):
    tree = default_tree()
    tree['ring_buffer'] = True
    with Callbacks(args, tree) as callbacks:
        if callbacks.is_empty():
            return callbacks.get_result()
        with open(args.input) as file:
            with Progress(os.path.getsize(args.input), 100, "Parsing ETW XML: " + args.input) as progress:
                def on_event(system, data, info):
                    progress.tick(file.tell())
                    if not info or not data:
                        return
                    call_data = {
                        'tid': int(system['tid']), 'pid': int(system['pid']), 'domain': system['provider'],
                        'time': int(data['SyncQPCTime'] if data.has_key('SyncQPCTime') else system['time']),
                        'str': info['Task'] if info.has_key('Task') and info['Task'] else 'Unknown',
                        'args': data,
                    }
                    call_data['thread_name'] = hex(call_data['tid'])

                    opcode = info['Opcode'] if info.has_key('Opcode') else ""
                    if 'Start' in opcode:
                        type = "task_begin"
                    elif 'Stop' in opcode:
                        type = "task_end"
                    else:
                        type = "marker"
                        call_data['data'] = 'task'

                    callbacks.on_event(type, call_data)
                etwxml = ETWXML(on_event, [
                    'Microsoft-Windows-DXGI',
                    'Microsoft-Windows-Direct3D11',
                    'Microsoft-Windows-D3D10Level9',
                    'Microsoft-Windows-Win32k',
                    'Microsoft-Windows-DxgKrnl',
                    'Microsoft-Windows-Dwm-Core',
                    'Microsoft-Windows-Shell-Core'
                ])
                unhandled_providers = etwxml.parse(file)
            print "Unhandled providers:", str(unhandled_providers)


if __name__ == "__main__":
    main()