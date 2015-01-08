#!/usr/bin/env python

"""
Simulate open/run/save of an IPython Notebook


Usage:

    python nbbot.py [--url=http://host:port[/base_url]] notebook.ipynb [notebook2.ipynb]
"""

import json
import logging

import requests
# don't need requests logs
logging.getLogger("requests").setLevel(logging.WARNING)

from tornado import gen
from tornado.log import gen_log, enable_pretty_logging
from tornado.options import options
from tornado.ioloop import IOLoop
from tornado.websocket import websocket_connect

from IPython.html.utils import url_path_join
from IPython.kernel.zmq.session import Session
from IPython import nbformat
from IPython.utils.jsonutil import date_default


class NBAPI(object):
    """API wrapper for the relevant bits of the IPython REST API"""
    
    def __init__(self, url='http://127.0.0.1:8888', cookies=None):
        self.url = url
        self.cookies = cookies or {}
    
    def api_request(self, *path, **kwargs):
        """Make an API request"""
        url = url_path_join(self.url, 'api', *path)
        kwargs.setdefault('method', 'GET')
        kwargs.setdefault('cookies', self.cookies)
        kwargs['url'] = url
        gen_log.debug("%s %s", kwargs['method'], url)
        r = requests.request(**kwargs)
        r.raise_for_status()
        if r.text != '':
            return r.json()
    
    def contents(self, path=''):
        return self.api_request('contents', path)
    
    def get_notebook(self, path):
        """Get a notebook"""
        model = self.contents(path)
        return nbformat.from_dict(model['content'])
    
    def _split_path(self, path):
        if '/' in path:
            path, name = path.rsplit('/', 0)
        else:
            path = ''
            name = path
        return path, name
    
    def save_notebook(self, nb, path):
        """Save a notebook"""
        model = {
            'content': nb,
            'type': 'notebook',
            'format': 'json',
        }
        return self.api_request('contents', path, method='PUT',
            data=json.dumps(model),
        )
    
    @gen.coroutine
    def new_kernel(self, session_id, legacy=False):
        """Start a new kernel, and connect a websocket for each channel
        
        Returns Kernel model dict, adding websocket object at each channel name.
        """
        kernel = self.api_request('kernels', method='POST',
            data=json.dumps({
                'name': 'python'
            })
        )
        kernel_id = kernel['id']
        for channel in ('shell', 'iopub', 'stdin'):
            url = url_path_join('ws' + self.url[4:], 'api', 'kernels', kernel_id, channel)
            if not legacy:
                url += '?session_id=%s' % session_id
            kernel[channel] = yield websocket_connect(url)
            if legacy:
                # set session ID with on-first-message:
                kernel[channel].write_message('%s:' % session_id)
        raise gen.Return(kernel)

    def kill_kernel(self, kernel_id):
        """kill a kernel by ID"""
        self.api_request('kernels', kernel_id, method='DELETE')


@gen.coroutine
def execute(cell, kernel, session):
    """Run a single cell, waiting for its output"""
    msg = session.msg('execute_request', content={
        'code': cell.source,
        'user_expressions': [],
        'silent': False,
        'allow_stdin': False,
    })
    
    parent_id = msg['header']['msg_id']
    
    shell = kernel['shell']
    iopub = kernel['iopub']
    gen_log.debug("Executing:\n%s", cell.source)
    shell.write_message(json.dumps(msg, default=date_default))
    reply = yield shell.read_message()
    reply = json.loads(reply)
    gen_log.debug("reply:\n%s", json.dumps(reply['content'], indent=1))
    while True:
        output = yield iopub.read_message()
        output = json.loads(output)
        gen_log.debug("Got output:\n%s", json.dumps(output['content'], indent=1))
        if output['msg_type'] == 'status' \
            and output['content']['execution_state'] == 'idle' \
            and output['parent_header']['msg_id'] == parent_id:
            break


@gen.coroutine
def run_notebook(nb, kernel, session):
    """Run all the cells of a notebook"""
    ncells = sum(cell['cell_type'] == 'code' for cell in nb.cells)
    i = 0
    for cell in nb.cells:
        if cell['cell_type'] == 'code':
            i += 1
            gen_log.info("Executing cell %i/%i", i, ncells)
            yield execute(cell, kernel, session)


@gen.coroutine
def open_run_save(api, path, legacy=False):
    """open a notebook, run it, and save.
    
    Only the original notebook is saved, the output is not recorded.
    """
    nb = api.get_notebook(path)
    session = Session()
    kernel = yield api.new_kernel(session.session, legacy=legacy)
    try:
        yield run_notebook(nb, kernel, session)
    finally:
        api.kill_kernel(kernel['id'])
    gen_log.info("Saving %s/notebooks/%s", api.url, path)
    api.save_notebook(nb, path)

if __name__ == '__main__':
    enable_pretty_logging()
    options.define("url", default="http://127.0.0.1:8888",
        help="The base URL of the notebook server to test"
    )
    options.define("legacy", type=bool, default=False,
        help="Use legacy (2.x) websocket handshake"
    )
    args = options.parse_command_line()
    paths = args or ['Untitled0.ipynb']
    
    api = NBAPI(url=options.url.rstrip('/'))
    loop = IOLoop.current()
    
    for path in paths:
        gen_log.info("Running %s/notebooks/%s", api.url, path)
        loop.run_sync(lambda : open_run_save(api, path, options.legacy))
