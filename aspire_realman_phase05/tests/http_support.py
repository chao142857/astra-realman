"""A real TCP loopback ASGI server, used only for CPU/MCP tests."""
from contextlib import contextmanager
import socket
import threading
import time
import uvicorn


@contextmanager
def loopback_server(app):
    sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error',lifespan='on'))
    errors=[]
    def run():
        try:server.run(sockets=[sock])
        except BaseException as error:errors.append(repr(error))
    thread=threading.Thread(target=run,daemon=True);thread.start()
    deadline=time.monotonic()+10
    try:
        while not server.started:
            if errors or not thread.is_alive() or time.monotonic()>deadline:
                raise RuntimeError('LOCAL_SERVER_STARTUP_FAILED:'+str(errors))
            time.sleep(.01)
        yield f'http://127.0.0.1:{port}'
    finally:
        server.should_exit=True;thread.join(timeout=5);sock.close()
        if thread.is_alive():
            server.force_exit=True;thread.join(timeout=2)
            raise RuntimeError('OWN_TEST_SERVER_DID_NOT_CLOSE')
