import glob
import os
import re
import threading

try:
    # Python 3
    from http.server import HTTPServer, SimpleHTTPRequestHandler
except ImportError:
    # Python 2
    from BaseHTTPServer import HTTPServer
    from SimpleHTTPServer import SimpleHTTPRequestHandler


class RepoRequestHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "repo")
        if os.path.isabs(path):
            path = path[1:]
        return os.path.join(root, path)

def _is_repo_step(step):
    regex = re.compile(r"^I use the repository \".+\"$")
    return regex.match(step.name)

def before_all(ctx):
    ctx.http_server = None
    ctx.http_thread = None

def after_all(ctx):
    if ctx.http_server:
        ctx.http_server.shutdown()
    if ctx.http_thread:
        ctx.http_thread.join()
    for repofn in glob.glob("/etc/yum.repos.d/_dnf_functional*.repo"):
        os.remove(repofn)

def before_step(ctx, step):
    if not ctx.http_thread and _is_repo_step(step):
        ctx.http_server = HTTPServer(("127.0.0.1", 0), RepoRequestHandler)
        ctx.http_thread = threading.Thread(target=ctx.http_server.serve_forever)
        ctx.http_thread.daemon = True
        ctx.http_thread.start()
