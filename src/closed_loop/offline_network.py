"""Python-socket guard for offline tests that need Windows asyncio IPC.

Only connections to loopback listeners bound by this process after installation
are allowed. External DNS, UDP sends and external connections are blocked. This
is a test guard, not an OS security boundary against arbitrary native code.
"""
import ipaddress
import socket
from threading import Lock
import weakref

_guard_install_lock=Lock()
_installed_guard=None


class OfflineSocketGuard:
    def __init__(self):
        self._original={};self._listeners={};self._lock=Lock()
        self.allowed_loopback_connections=0;self.blocked_operations=0

    def _deny(self):
        self.blocked_operations+=1
        raise PermissionError('External networking forbidden in offline test')

    @staticmethod
    def _loopback(address):
        try:return isinstance(address,tuple) and len(address)>=2 and ipaddress.ip_address(address[0]).is_loopback
        except (TypeError,ValueError):return False

    def install(self):
        global _installed_guard
        with _guard_install_lock:
            if _installed_guard is not None:raise RuntimeError('another offline guard is already installed')
            _installed_guard=self
        if self._original:raise RuntimeError('guard already installed')
        methods=('bind','connect','connect_ex','sendto')
        for name in methods:self._original[('socket',name)]=getattr(socket.socket,name)
        self._original[('module','getaddrinfo')]=socket.getaddrinfo
        def bind(sock,address):
            if not self._loopback(address):return self._deny()
            result=self._original[('socket','bind')](sock,address)
            key=(sock.family,*sock.getsockname()[:2])
            with self._lock:self._listeners[key]=weakref.ref(sock)
            return result
        def permitted(sock,address):
            if not self._loopback(address):return False
            key=(sock.family,*address[:2])
            with self._lock:
                reference=self._listeners.get(key);listener=reference() if reference else None
                okay=listener is not None and listener.fileno()>=0
                if okay:self.allowed_loopback_connections+=1
            return okay
        def connect(sock,address):
            if not permitted(sock,address):return self._deny()
            return self._original[('socket','connect')](sock,address)
        def connect_ex(sock,address):
            if not permitted(sock,address):return self._deny()
            return self._original[('socket','connect_ex')](sock,address)
        def getaddrinfo(host,*args,**kwargs):
            if not self._loopback((host,0)):return self._deny()
            return self._original[('module','getaddrinfo')](host,*args,**kwargs)
        socket.socket.bind=bind;socket.socket.connect=connect;socket.socket.connect_ex=connect_ex
        socket.socket.sendto=lambda *args,**kwargs:self._deny()
        socket.getaddrinfo=getaddrinfo
        return self

    def restore(self):
        global _installed_guard
        with _guard_install_lock:
            if _installed_guard is not self:
                if self._original:raise RuntimeError('guard ownership mismatch')
                return
            for (owner,name),value in self._original.items():
                setattr(socket.socket if owner=='socket' else socket,name,value)
            self._original.clear();_installed_guard=None

    def __enter__(self):return self.install()
    def __exit__(self,*args):self.restore()
