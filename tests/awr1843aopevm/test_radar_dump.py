import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock

import radar_dump

HERE = os.path.dirname(os.path.abspath(__file__))
CLEAN = os.path.join(HERE, "data_clean.bin")


class RecordTest(unittest.TestCase):
    def test_output_is_byte_identical_to_port_stream(self):
        with open(CLEAN, "rb") as fh:
            clean = fh.read()
        # chunks of uneven size, with idle periods (None) mixed in
        chunks = [clean[i:i + 1000] for i in range(0, len(clean), 1000)]

        def fake_read_port(fd):
            for i, chunk in enumerate(chunks):
                yield chunk
                yield None
                if i % 3 == 0:
                    yield None

        fd = os.open(os.devnull, os.O_RDONLY)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "rec.bin")
            with mock.patch.object(radar_dump, "open_port", return_value=fd), \
                    mock.patch.object(radar_dump, "read_port", side_effect=fake_read_port), \
                    contextlib.redirect_stderr(io.StringIO()):
                rc = radar_dump.main([out])
            with open(out, "rb") as fh:
                recorded = fh.read()
        self.assertEqual(rc, 0)
        self.assertEqual(recorded, clean)

    def test_existing_output_is_not_overwritten(self):
        fd = os.open(os.devnull, os.O_RDONLY)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "keep.bin")
            with open(out, "wb") as fh:
                fh.write(b"keep me")
            with mock.patch.object(radar_dump, "open_port", return_value=fd), \
                    mock.patch.object(radar_dump, "read_port") as read_port, \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                rc = radar_dump.main([out])
            with open(out, "rb") as fh:
                content = fh.read()
        self.assertEqual(rc, 1)
        self.assertEqual(content, b"keep me")
        self.assertIn("radar_dump:", err.getvalue())
        read_port.assert_not_called()

    def test_port_open_failure_leaves_no_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "rec.bin")
            with mock.patch.object(radar_dump, "open_port", side_effect=OSError("no such port")), \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                rc = radar_dump.main([out])
            exists = os.path.exists(out)
        self.assertEqual(rc, 1)
        self.assertFalse(exists)
        self.assertIn("radar_dump: no such port", err.getvalue())

    def test_ctrl_c_mid_stream_keeps_received_bytes(self):
        chunks = [b"abc" * 100, b"xyz" * 50]

        def fake_read_port(fd):
            for chunk in chunks:
                yield chunk
            yield None
            raise KeyboardInterrupt

        fd = os.open(os.devnull, os.O_RDONLY)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "rec.bin")
            with mock.patch.object(radar_dump, "open_port", return_value=fd), \
                    mock.patch.object(radar_dump, "read_port", side_effect=fake_read_port), \
                    contextlib.redirect_stderr(io.StringIO()):
                rc = radar_dump.main([out])
            with open(out, "rb") as fh:
                recorded = fh.read()
        self.assertEqual(rc, 0)
        self.assertEqual(recorded, b"".join(chunks))


if __name__ == "__main__":
    unittest.main()
