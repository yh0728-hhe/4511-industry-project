from pathlib import Path
import socket
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.offline_network import OfflineSocketGuard


class NetworkTests(unittest.TestCase):
    def test_second_guard_install_is_rejected_without_corrupting_restore(self):
        original=socket.socket.connect
        first=OfflineSocketGuard();second=OfflineSocketGuard()
        first.install()
        try:
            with self.assertRaises(RuntimeError):second.install()
            second.restore()
            self.assertIsNot(socket.socket.connect,original)
        finally:first.restore()
        self.assertIs(socket.socket.connect,original)

    def test_external_connections_dns_and_udp_are_blocked(self):
        with OfflineSocketGuard() as guard:
            with socket.socket() as client:
                with self.assertRaises(PermissionError):client.connect(('203.0.113.1',443))
            with self.assertRaises(PermissionError):socket.getaddrinfo('forbidden.invalid',443)
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as client:
                with self.assertRaises(PermissionError):client.sendto(b'dummy',('203.0.113.1',53))
            self.assertEqual(guard.allowed_loopback_connections,0)
            self.assertEqual(guard.blocked_operations,3)

    def test_only_process_owned_listener_loopback_is_allowed(self):
        # Pre-existing listener simulates an unrelated local proxy; never connect to it.
        with socket.socket() as external:
            external.bind(('127.0.0.1',0));external.listen()
            with OfflineSocketGuard() as guard:
                with socket.socket() as client:
                    with self.assertRaises(PermissionError):client.connect(external.getsockname())
                left,right=socket.socketpair()
                try:
                    left.send(b'local IPC')
                    self.assertEqual(right.recv(32),b'local IPC')
                finally:left.close();right.close()
                self.assertGreaterEqual(guard.allowed_loopback_connections,1)


if __name__=='__main__':unittest.main()
