"""KiraluxPort framing: 1024-byte null-padded commands on EP 0x02, replies on EP 0x82."""
import pytest
from hardwarelibrary.communication.usbport import USBPort

from kiralux.device import KiraluxPort, VID, PID, COMMAND_SIZE, EP_COMMAND, EP_RESPONSE


@pytest.fixture
def wire(monkeypatch):
    """USBPort with its USB side replaced by a recorder."""
    class Wire:
        written, reply, opened = [], b"", False
    w = Wire()
    w.written = []
    monkeypatch.setattr(USBPort, "open", lambda self: setattr(w, "opened", True))
    monkeypatch.setattr(USBPort, "endPointForAddress", lambda self, address: ("endpoint", address))
    monkeypatch.setattr(USBPort, "writeData", lambda self, data, endPoint=None: w.written.append((bytes(data), endPoint)) or len(data))
    monkeypatch.setattr(USBPort, "readData", lambda self, length, endPoint=None: bytearray(w.reply.ljust(length, b"\x00")[:length]))
    return w


def test_it_targets_the_kiralux_on_interface_0():
    port = KiraluxPort(serialNumber="18658")
    assert (port.idVendor, port.idProduct, port.serialNumber, port.interfaceNumber) == (VID, PID, "18658", 0)


def test_open_resolves_the_endpoints_and_sets_the_timeout(wire):
    port = KiraluxPort()
    port.open()
    assert wire.opened and port.defaultTimeout == 3000
    assert port.commandEndPoint == ("endpoint", EP_COMMAND)
    assert port.responseEndPoint == ("endpoint", EP_RESPONSE)


@pytest.mark.parametrize("text", ["exp 20000", b"exp 20000"])
def test_a_command_is_null_terminated_and_padded_to_1024_bytes(wire, text):
    port = KiraluxPort()
    port.open()
    port.writeData(text)
    (buffer, endPoint), = wire.written
    assert len(buffer) == COMMAND_SIZE
    assert buffer.startswith(b"exp 20000\x00") and set(buffer[9:]) == {0}
    assert endPoint == ("endpoint", EP_COMMAND)


def test_an_explicit_endpoint_wins(wire):
    port = KiraluxPort()
    port.open()
    port.writeData("stop", endPoint="other")
    assert wire.written[0][1] == "other"


def test_a_reply_is_the_text_up_to_the_first_null(wire):
    port = KiraluxPort()
    port.open()
    wire.reply = b"18658\n\x00garbage after the terminator"
    assert port.readString() == "18658\n"


def test_replies_are_decoded_as_latin1(wire):
    port = KiraluxPort()
    port.open()
    wire.reply = "µm".encode("latin1")
    assert port.readString() == "µm"
