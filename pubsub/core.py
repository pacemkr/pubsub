import threading
import time
import zmq
from saferef import safeRef

# Create a fowarder in a separate thread with two ends, pub and sub.
# This way we can just 'connect' to this device whenever we need to subscribe to or send a signal.
# see: http://lists.zeromq.org/pipermail/zeromq-dev/2010-July/004411.html
# see: http://lists.zeromq.org/pipermail/zeromq-dev/2010-July/004399.html
class ForwarderDevice(threading.Thread):
    daemon = True
    #in_address = 'inproc://fwdin'
    #out_address = 'inproc://fwdout'
    in_address = 'tcp://127.0.0.1:5555'
    out_address = 'tcp://127.0.0.1:5556'

    def __init__(self, context=None):
        super(ForwarderDevice, self).__init__()
        self.context = context or zmq.Context.instance()

    def run(self):
        insock = self.context.socket(zmq.SUB)
        insock.bind(self.in_address)
        insock.setsockopt(zmq.SUBSCRIBE, '')

        outsock = self.context.socket(zmq.PUB)
        outsock.bind(self.out_address)

        zmq.device(zmq.FORWARDER, insock, outsock)

fwd = ForwarderDevice()
fwd.start()
time.sleep(1)

class Hub():
    _hubs_for_threads = {}

    @staticmethod
    def instance():
        ident = threading.current_thread().ident
        assert ident is not None

        hubs = Hub._hubs_for_threads
        if ident not in hubs:
            hubs[ident] = Hub()

        return hubs[ident]

    def __init__(self, context=None):
        context = context or zmq.Context.instance()

        self._out_socket = context.socket(zmq.PUB)
        self._out_socket.connect(ForwarderDevice.in_address)

        self._in_socket = context.socket(zmq.SUB)
        self._in_socket.connect(ForwarderDevice.out_address)
        self._in_socket.setsockopt(zmq.SUBSCRIBE, '')

        self._receivers = {}

    def send_message(self, topic, data):
        self._out_socket.send_json([topic, data])

    def fileno(self):
        return self._in_socket.FD

    def receive_messages(self):
        try:
            while True:
                topic, data = self._in_socket.recv_json(flags=zmq.NOBLOCK)
                assert isinstance(data, dict)

                if topic not in self._receivers:
                    continue

                for receiver_ref in self._receivers[topic]:
                    receiver_ref()(**data)

        except zmq.ZMQError, ex:
            if not ex.errno == zmq.EAGAIN: raise ex

    def connect_receiver(self, topic, receiver):
        assert callable(receiver)

        if topic not in self._receivers:
            self._receivers[topic] = []

        self._receivers[topic].append(safeRef(receiver, self._receiver_deleted))

    def _receiver_deleted(self, receiver_ref):
        for topic_receivers in self._receivers.itervalues():
            topic_receivers.remove(receiver_ref)

class Message:
    def __init__(self, topic):
        self.topic = topic

    def subscribe(self, receiver):
        hub = Hub.instance()
        hub.connect_receiver(self.topic, receiver)

    def send(self, **kwargs):
        hub = Hub.instance()
        hub.send_message(self.topic, data=kwargs)